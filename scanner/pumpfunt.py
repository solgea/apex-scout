"""
Apex Scout - Pump.fun Scanner
Pump.fun API ve WebSocket'den yeni token'ları tarar.
API: https://frontend-api.pump.fun
WebSocket: wss://pumpportal.fun/api/data
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import aiohttp
import websockets

from config.constants import TokenSource
from config.settings import settings
from scanner.base import BaseScanner
from scanner.models import TokenData, TokenFilterCriteria
from shared.logger import get_scanner_logger
from shared.utils import safe_float, utc_now

log = get_scanner_logger()


class PumpFunScanner(BaseScanner):
    """Pump.fun API + WebSocket scanner"""

    # Browser-like User-Agent (API 403/530 döndürüyor default UA ile)
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, filter_criteria: TokenFilterCriteria | None = None):
        super().__init__(filter_criteria, source_name="pumpfunt")
        self.base_url = getattr(settings, "pumpfun_base_url", "https://frontend-api-v3.pump.fun")
        self.ws_url = "wss://pumpportal.fun/api/data"
        self.session: aiohttp.ClientSession | None = None
        self.ws: Any | None = None
        self._ws_task: asyncio.Task | None = None
        self._new_token_callback: Callable[[TokenData], Awaitable[None]] | None = None
        self._ws_connected = False
        self._received_tokens: list[TokenData] = []
        self._max_buffer = 100

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": self.USER_AGENT, "Accept": "application/json"},
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop_websocket()
        if self.session:
            await self.session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": self.USER_AGENT, "Accept": "application/json"},
            )
        return self.session

    async def fetch_new_tokens(self) -> list[TokenData]:
        """
        REST API ile yeni token'ları çek.
        Endpoint: /coins/latest (veya benzeri)
        Not: Pump.fun public API değişebilir, fallback olarak WebSocket kullanılır.
        """
        # Önce REST API dene
        rest_tokens = await self._fetch_via_rest()

        # WebSocket buffer'ından da al
        ws_tokens = self._drain_ws_buffer()

        # Birleştir ve deduplicate (address bazında)
        all_tokens = rest_tokens + ws_tokens
        seen = set()
        unique = []
        for t in all_tokens:
            if t.address not in seen:
                seen.add(t.address)
                unique.append(t)

        return unique

    async def _fetch_via_rest(self) -> list[TokenData]:
        """REST API ile token çek"""
        session = await self._get_session()
        tokens = []

        # Pump.fun API endpoint'leri değişebilir, yaygın olanları dene
        endpoints = [
            # v3 API - en yeni token'lar (browser UA gerekir)
            "/coins?offset=0&limit=50&sort=created_timestamp&order=desc&includeNsfw=true",
            "/coins/latest",
            "/coins?offset=0&limit=50&sort=created_timestamp&order=desc",
        ]

        for endpoint in endpoints:
            try:
                url = f"{self.base_url}{endpoint}"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tokens = self._parse_rest_response(data)
                        if tokens:
                            log.debug(f"[PumpFun] REST {endpoint}: {len(tokens)} tokens")
                            break
                    else:
                        log.debug(f"[PumpFun] REST {endpoint} HTTP {resp.status}")
            except Exception as e:
                log.debug(f"[PumpFun] REST {endpoint} error: {e}")

        return tokens

    def _parse_rest_response(self, data: dict) -> list[TokenData]:
        """REST response'u parse et"""
        tokens = []

        # Farklı response formatlarını handle et
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            if "coins" in data:
                items = data["coins"]
            elif "tokens" in data:
                items = data["tokens"]
            elif "data" in data:
                items = data["data"]

        for item in items[:50]:  # Max 50
            try:
                token = self._parse_pumpfunt_token(item)
                if token:
                    tokens.append(token)
            except Exception as e:
                log.warning(f"[PumpFun] Parse error: {e}")

        return tokens

    def _parse_pumpfunt_token(self, item: dict) -> TokenData | None:
        """Pump.fun token verisini TokenData'ya çevir"""
        try:
            mint = item.get("mint") or item.get("address")
            if not mint:
                return None

            # Likidite hesapla (SOL reserves * SOL price)
            # Pump.fun bonding curve: virtual_sol_reserves * virtual_token_reserves = k
            # DİKKAT: reserves LAMPORT cinsinden gelir (1 SOL = 1e9 lamport)
            virtual_sol = safe_float(item.get("virtual_sol_reserves"), 0) / 1e9
            real_sol = safe_float(item.get("real_sol_reserves"), 0) / 1e9

            # Yaklaşık likidite (SOL cinsinden * SOL fiyatı)
            sol_price_usd = 150.0  # Sabit varsayım, gerçekte OKX'ten alınmalı
            liquidity_usd = (virtual_sol + real_sol) * sol_price_usd

            # Market cap
            total_supply_raw = safe_float(item.get("total_supply"), 1_000_000_000_000_000)
            # Pump.fun tokenları 6 decimals kullanır -> gerçek token sayısı
            total_supply_tokens = total_supply_raw / 1e6

            market_cap = safe_float(item.get("market_cap"), 0)
            if market_cap == 0 and liquidity_usd > 0:
                # Bonding curve market cap tahmini
                market_cap = liquidity_usd * 2  # Rough estimate

            # Token başına fiyat (USD)
            price_usd = market_cap / total_supply_tokens if total_supply_tokens > 0 else 0.0

            # Yaş
            created_ts = item.get("created_timestamp") or item.get("created_at")
            age_seconds = 0
            if created_ts:
                if created_ts > 1e12:  # milliseconds
                    created_ts = created_ts / 1000
                created_dt = datetime.fromtimestamp(created_ts, tz=timezone.utc)
                age_seconds = int((utc_now() - created_dt).total_seconds())

            # Mint/Freeze authority - Pump.fun'da genellikle renounced
            # Gerçek kontrol için Solana RPC gerekir, burada varsayılan
            mint_renounced = item.get("mint_renounced", True)
            freeze_renounced = item.get("freeze_renounced", True)

            token = TokenData(
                address=mint,
                name=item.get("name", "Unknown"),
                symbol=item.get("symbol", "UNK"),
                price_usd=price_usd,
                liquidity_usd=liquidity_usd,
                market_cap=market_cap,
                volume_24h=0.0,  # Pump.fun genelde 24h vol vermez
                age_seconds=age_seconds,
                mint_authority=None,
                freeze_authority=None,
                mint_renounced=mint_renounced,
                freeze_renounced=freeze_renounced,
                holder_count=item.get("holder_count", 0),
                top_10_holder_pct=item.get("top_10_holder_pct", 0.0),
                source=TokenSource.PUMPFUN,
                raw_data=item,
            )

            return token

        except Exception as e:
            log.warning(f"[PumpFun] Token parse error: {e}")
            return None

    # ============ WEBSOCKET ============

    async def start_websocket(self, callback: Callable[[TokenData], Awaitable[None]] | None = None):
        """WebSocket bağlantısını başlat ve yeni token'ları dinle"""
        self._new_token_callback = callback
        self._ws_task = asyncio.create_task(self._ws_loop())
        log.info("[PumpFun] WebSocket started")

    async def stop_websocket(self):
        """WebSocket'i durdur"""
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self.ws:
            await self.ws.close()
        self._ws_connected = False
        log.info("[PumpFun] WebSocket stopped")

    async def _ws_loop(self):
        """WebSocket döngüsü - yeniden bağlanma ile"""
        while True:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    self.ws = ws
                    self._ws_connected = True
                    log.info("[PumpFun] WebSocket connected")

                    # Subscribe to new tokens
                    await ws.send(json.dumps({"method": "subscribeNewToken"}))

                    async for message in ws:
                        await self._handle_ws_message(message)

            except websockets.exceptions.ConnectionClosed:
                log.warning("[PumpFun] WebSocket closed, reconnecting...")
            except Exception as e:
                log.error(f"[PumpFun] WebSocket error: {e}")

            self._ws_connected = False
            await asyncio.sleep(5)  # Reconnect delay

    async def _handle_ws_message(self, message: str):
        """WebSocket mesajını işle"""
        try:
            data = json.loads(message)

            # Yeni token mesajı formatı
            if data.get("type") == "newToken" or "mint" in data:
                token = self._parse_pumpfunt_token(data)
                if token:
                    self._received_tokens.append(token)
                    if len(self._received_tokens) > self._max_buffer:
                        self._received_tokens.pop(0)

                    if self._new_token_callback:
                        await self._new_token_callback(token)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            log.warning(f"[PumpFun] WS message error: {e}")

    def _drain_ws_buffer(self) -> list[TokenData]:
        """WebSocket buffer'ını boşalt ve token'ları döndür"""
        tokens = self._received_tokens.copy()
        self._received_tokens.clear()
        return tokens

    async def fetch_token_details(self, address: str) -> TokenData | None:
        """Tek token detayı (REST)"""
        session = await self._get_session()

        endpoints = [
            f"/coins/{address}",
            f"/tokens/{address}",
        ]

        for endpoint in endpoints:
            try:
                url = f"{self.base_url}{endpoint}"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return self._parse_pumpfunt_token(data)
            except Exception:
                continue

        return None

    async def close(self):
        await self.stop_websocket()
        if self.session and not self.session.closed:
            await self.session.close()
