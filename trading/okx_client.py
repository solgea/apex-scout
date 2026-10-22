"""
Apex Scout - OKX Demo Client
Sadece DEMO trading destekler. Gerçek hesap engellenir.
OKX API v5: https://www.okx.com/docs-v5/
"""

import time
import hmac
import hashlib
import base64
import json
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from shared.logger import get_logger
from shared.exceptions import (
    OKXAPIError, OKXAuthError, OKXRateLimitError,
    OrderExecutionError, InsufficientBalanceError
)
from shared.utils import generate_signature, utc_now_iso
from config.settings import settings
from config.constants import OKX_DEMO_HEADER, OKX_DEMO_VALUE, OKX_INST_ID_SUFFIX
from trading.models import Order, Trade, OrderSide, OrderType, OrderStatus, PortfolioSnapshot

log = get_logger(__name__)


class OKXDemoClient:
    """
    OKX Demo Trading Client.
    ZORUNLU: x-simulated-trading: 1 header gönderir.
    Gerçek hesap kullanımı engellenir.
    """

    def __init__(self):
        # Demo trading zorunluluğu config'te validate edilmiş olmalı
        if not settings.okx_demo_trading:
            raise ValueError("OKX_DEMO_TRADING=true olmalı! Sadece demo hesap desteklenir.")

        self.api_key = settings.okx_api_key
        self.secret = settings.okx_api_secret
        self.passphrase = settings.okx_passphrase
        self.base_url = settings.okx_base_url.rstrip("/")

        self.session: Optional[aiohttp.ClientSession] = None
        self._rate_limit_remaining = 100
        self._rate_limit_reset = 0

        # Demo mode header - HER ZAMAN GÖNDERİLMELİ
        self.demo_header = {OKX_DEMO_HEADER: OKX_DEMO_VALUE}

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "ApexScout/1.0"},
        )
        # Zaman senkronizasyonu kontrolü
        await self._check_time_sync()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "ApexScout/1.0"},
            )
        return self.session

    async def _check_time_sync(self) -> bool:
        """OKX sunucu zamanıyla lokal zaman farkını kontrol et"""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/api/v5/public/time", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == "0" and data.get("data"):
                        server_time_ms = int(data["data"][0]["ts"])
                        local_time_ms = int(time.time() * 1000)
                        diff_ms = abs(local_time_ms - server_time_ms)
                        if diff_ms > 30000:  # 30 saniye tolerans
                            log.warning(f"Time sync issue: local vs server diff = {diff_ms}ms")
                            return False
                        log.debug(f"Time sync OK: diff = {diff_ms}ms")
                        return True
        except Exception as e:
            log.warning(f"Time sync check failed: {e}")
        return True  # Fail-open

    def _get_headers(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        """OKX imzalı header'ları oluştur"""
        timestamp = utc_now_iso()
        signature = generate_signature(timestamp, method, request_path, body, self.secret)

        return {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            **self.demo_header,  # ZORUNLU: Demo trading header
        }

    @staticmethod
    def _build_signed_path(endpoint: str, params: Dict = None) -> str:
        """
        İmzalama için request path oluştur.
        ÖNEMLİ: Query string imzaya DAHİL EDİLMELİ (OKX kuralı).
        Örn: /api/v5/account/balance?ccy=USDT
        """
        if not params:
            return endpoint

        # Sıralı query string (deterministik imza için)
        query = "&".join(
            f"{k}={v}" for k, v in sorted(params.items()) if v is not None
        )
        return f"{endpoint}?{query}" if query else endpoint

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Dict = None,
        data: Dict = None,
        auth: bool = True
    ) -> Dict:
        """HTTP isteği gönder - Her retry'de fresh timestamp + query string imzası ile"""
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"
        body = json.dumps(data) if data else ""

        # İMZALANACAK PATH: query string dahil
        signed_path = self._build_signed_path(endpoint, params)

        max_retries = settings.max_retries
        base_delay = settings.retry_backoff_base

        for attempt in range(max_retries + 1):
            # Her denemede FRESH timestamp ve signature üret
            headers = (
                self._get_headers(method, signed_path, body)
                if auth else {"Content-Type": "application/json"}
            )

            try:
                async with session.request(method, url, params=params, data=body, headers=headers) as resp:
                    response_text = await resp.text()

                    # Rate limit header'larını kontrol et
                    self._rate_limit_remaining = int(resp.headers.get("x-ratelimit-remaining", "100"))
                    self._rate_limit_reset = int(resp.headers.get("x-ratelimit-reset", "0"))

                    if resp.status == 429:
                        raise OKXRateLimitError("Rate limit exceeded")

                    try:
                        result = json.loads(response_text)
                    except json.JSONDecodeError:
                        result = {"code": "500", "msg": f"Invalid JSON: {response_text}"}

                    # OKX hata kodları
                    if resp.status != 200 or result.get("code") != "0":
                        error_msg = result.get("msg", f"HTTP {resp.status}")
                        error_code = result.get("code", "unknown")

                        # Timestamp hataları - retry için özel durum
                        if error_code in ("50112", "50113"):
                            log.warning(f"Timestamp error [{error_code}]: {error_msg}, retrying with fresh timestamp... (attempt {attempt + 1}/{max_retries + 1})")
                            if attempt < max_retries:
                                delay = min(base_delay * (2 ** attempt), 60.0)
                                await asyncio.sleep(delay)
                                continue
                            raise OKXRateLimitError(f"Timestamp error after retries: {error_msg}")

                        if error_code in ("58000", "58001", "58002", "58003"):
                            raise OKXAuthError(f"Auth error: {error_msg}")
                        elif error_code == "58101":
                            raise InsufficientBalanceError(f"Insufficient balance: {error_msg}")
                        else:
                            raise OKXAPIError(f"OKX API error [{error_code}]: {error_msg}")

                    return result

            except OKXAPIError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < max_retries:
                    delay = min(base_delay * (2 ** attempt), 60.0)
                    log.warning(f"Request error (attempt {attempt + 1}/{max_retries + 1}): {e}, retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    continue
                log.error(f"OKX request failed after {max_retries + 1} attempts: {method} {endpoint} - {e}")
                raise OKXAPIError(f"Request failed after retries: {e}") from e
            except Exception as e:
                log.error(f"OKX request failed: {method} {endpoint} - {e}")
                raise OKXAPIError(f"Request failed: {e}") from e

        # Buraya asla gelmemeli ama type checker için
        raise OKXAPIError("Max retries exceeded")

    # ============ ACCOUNT / BALANCE ============

    async def get_account_balance(self, ccy: str = "USDT") -> Dict:
        """Hesap bakiyesi (Demo)"""
        result = await self._request("GET", "/api/v5/account/balance", params={"ccy": ccy})
        return result["data"][0] if result["data"] else {}

    async def get_available_balance(self, ccy: str = "USDT") -> float:
        """Kullanılabilir bakiye (USDT)"""
        bal = await self.get_account_balance(ccy)
        details = bal.get("details", [])
        for d in details:
            if d.get("ccy") == ccy:
                return float(d.get("availBal", "0"))
        return float(bal.get("availBal", "0"))

    # ============ MARKET DATA ============

    async def get_ticker(self, inst_id: str) -> Dict:
        """Anlık ticker"""
        result = await self._request("GET", "/api/v5/market/ticker", params={"instId": inst_id})
        return result["data"][0] if result["data"] else {}

    async def get_price(self, inst_id: str) -> float:
        """Anlık fiyat"""
        ticker = await self.get_ticker(inst_id)
        return float(ticker.get("last", "0"))

    async def get_candles(self, inst_id: str, bar: str = "1m", limit: int = 100) -> List[List]:
        """Mum verileri (OHLCV)"""
        result = await self._request("GET", "/api/v5/market/candles", params={
            "instId": inst_id,
            "bar": bar,
            "limit": str(limit),
        })
        return result["data"]  # [ts, o, h, l, c, vol, ...]

    # ============ TRADING ============

    async def place_order(
        self,
        inst_id: str,
        side: OrderSide,
        size: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        cl_ord_id: Optional[str] = None,
    ) -> Order:
        """Emir gönder (Demo)"""
        # Parametreleri hazırla
        data = {
            "instId": inst_id,
            "tdMode": "cash",  # Spot trading
            "side": side.value,
            "ordType": order_type.value,
            "sz": str(size),
        }

        if order_type != OrderType.MARKET and price is not None:
            data["px"] = str(price)

        if cl_ord_id:
            data["clOrdId"] = cl_ord_id

        result = await self._request("POST", "/api/v5/trade/order", data=data)

        if result["data"]:
            order_data = result["data"][0]
            return Order(
                okx_order_id=order_data.get("ordId"),
                okx_cl_ord_id=order_data.get("clOrdId"),
                inst_id=inst_id,
                side=side,
                order_type=order_type,
                size=size,
                price=price,
                status=OrderStatus.SUBMITTED,
                raw_response=order_data,
            )

        raise OrderExecutionError("Order placement failed", {"result": result})

    async def cancel_order(self, inst_id: str, ord_id: str = None, cl_ord_id: str = None) -> bool:
        """Emir iptal"""
        data = {"instId": inst_id}
        if ord_id:
            data["ordId"] = ord_id
        if cl_ord_id:
            data["clOrdId"] = cl_ord_id

        result = await self._request("POST", "/api/v5/trade/cancel-order", data=data)
        return result["data"][0].get("sCode") == "0" if result["data"] else False

    async def get_order(self, inst_id: str, ord_id: str = None, cl_ord_id: str = None) -> Order:
        """Emir detayı"""
        params = {"instId": inst_id}
        if ord_id:
            params["ordId"] = ord_id
        if cl_ord_id:
            params["clOrdId"] = cl_ord_id

        result = await self._request("GET", "/api/v5/trade/order", params=params)

        if result["data"]:
            d = result["data"][0]
            return Order(
                okx_order_id=d.get("ordId"),
                okx_cl_ord_id=d.get("clOrdId"),
                inst_id=inst_id,
                side=OrderSide(d.get("side", "buy")),
                order_type=OrderType(d.get("ordType", "market")),
                size=float(d.get("sz", "0")),
                price=float(d.get("px", "0")) if d.get("px") else None,
                status=self._map_order_status(d.get("state")),
                filled_size=float(d.get("accFillSz", "0")),
                avg_fill_price=float(d.get("avgPx", "0")) if d.get("avgPx") else 0.0,
                fee=float(d.get("fee", "0")),
                raw_response=d,
            )

        raise OrderExecutionError("Order not found", {"inst_id": inst_id, "ord_id": ord_id})

    def _map_order_status(self, state: str) -> OrderStatus:
        """OKX state -> OrderStatus"""
        mapping = {
            "live": OrderStatus.SUBMITTED,
            "partially_filled": OrderStatus.PARTIAL,
            "filled": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "failed": OrderStatus.REJECTED,
        }
        return mapping.get(state, OrderStatus.PENDING)

    async def get_fills(self, inst_id: str = None, ord_id: str = None, after: str = None) -> List[Trade]:
        """Trade geçmişi (fills)"""
        params = {}
        if inst_id:
            params["instId"] = inst_id
        if ord_id:
            params["ordId"] = ord_id
        if after:
            params["after"] = after

        result = await self._request("GET", "/api/v5/trade/fills", params=params)

        trades = []
        for d in result["data"]:
            trades.append(Trade(
                inst_id=d.get("instId", ""),
                side=OrderSide(d.get("side", "buy")),
                price=float(d.get("fillPx", "0")),
                size=float(d.get("fillSz", "0")),
                fee=float(d.get("fee", "0")),
                fee_ccy=d.get("feeCcy", "USDT"),
                okx_trade_id=d.get("tradeId"),
                okx_order_id=d.get("ordId"),
                timestamp=datetime.fromtimestamp(int(d.get("ts", "0")) / 1000) if d.get("ts") else datetime.utcnow(),
            ))
        return trades

    # ============ POSITIONS (Spot için position yok, balance kullan) ============

    async def get_positions(self, inst_type: str = "SPOT") -> List[Dict]:
        """Pozisyonlar (Spot için boş döner, futures için çalışır)"""
        result = await self._request("GET", "/api/v5/account/positions", params={"instType": inst_type})
        return result["data"]

    # ============ INSTRUMENTS ============

    async def get_instruments(self, inst_type: str = "SPOT", inst_id: str = None) -> List[Dict]:
        """Instrument listesi"""
        params = {"instType": inst_type}
        if inst_id:
            params["instId"] = inst_id
        result = await self._request("GET", "/api/v5/public/instruments", params=params)
        return result["data"]

    def format_inst_id(self, symbol: str) -> str:
        """Symbol'den OKX instrument ID oluştur"""
        symbol = symbol.upper().strip()
        if symbol.endswith("USDT"):
            return symbol
        if symbol.endswith("USDC"):
            return symbol
        return f"{symbol}{OKX_INST_ID_SUFFIX}"

    async def close(self):
        """Session kapat"""
        if self.session and not self.session.closed:
            await self.session.close()

    # ============ HEALTH CHECK ============

    async def health_check(self) -> bool:
        """API sağlık kontrolü"""
        try:
            await self._request("GET", "/api/v5/public/time", auth=False)
            return True
        except Exception:
            return False