"""
Apex Scout - DexScreener Scanner
DexScreener API'den Solana yeni token'ları tarar.
API: https://api.dexscreener.com/token-profiles/latest/v1
     https://api.dexscreener.com/tokens/v1/solana/{address}
"""

import asyncio
import aiohttp
from typing import List, Optional
from datetime import datetime, timezone

from shared.logger import get_scanner_logger
from shared.exceptions import DexScreenerError
from shared.utils import safe_float, utc_now
from config.settings import settings
from scanner.base import BaseScanner
from scanner.models import TokenData, TokenFilterCriteria, DexScreenerResponse, DexScreenerPair
from config.constants import TokenSource

log = get_scanner_logger()


class DexScreenerScanner(BaseScanner):
    """DexScreener API scanner"""

    def __init__(self, filter_criteria: Optional[TokenFilterCriteria] = None):
        super().__init__(filter_criteria, source_name="dexscreener")
        self.base_url = settings.dexscreener_base_url
        self.session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(10)  # Eşzamanlı istek limiti

    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "ApexScout/1.0"},
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Session lazy initialization"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "ApexScout/1.0"},
            )
        return self.session

    async def fetch_new_tokens(self) -> List[TokenData]:
        """
        DexScreener'dan en yeni token profillerini çek.
        Endpoint: /token-profiles/latest/v1
        Sonra her token için detay çek: /tokens/v1/solana/{address}
        """
        session = await self._get_session()

        # 1. En yeni profilleri al
        url = f"{self.base_url}/token-profiles/latest/v1"
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise DexScreenerError(f"HTTP {resp.status}: {await resp.text()}")
                profiles = await resp.json()
        except aiohttp.ClientError as e:
            raise DexScreenerError(f"Request failed: {e}") from e

        if not profiles:
            log.debug("[DexScreener] No new profiles found")
            return []

        # Sadece Solana chain'lerini filtrele
        solana_profiles = [p for p in profiles if p.get("chainId") == "solana"]
        log.debug(f"[DexScreener] {len(solana_profiles)} Solana profiles from {len(profiles)} total")

        # 2. Her token için detaylı veri çek (paralel)
        tokens = []
        semaphore = asyncio.Semaphore(5)  # Detay çekerken daha konservatif

        async def fetch_detail(profile: dict) -> Optional[TokenData]:
            address = profile.get("tokenAddress")
            if not address:
                return None

            async with semaphore:
                return await self._fetch_token_detail(session, address, profile)

        tasks = [fetch_detail(p) for p in solana_profiles[:50]]  # Max 50 token per scan
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, TokenData):
                tokens.append(result)
            elif isinstance(result, Exception):
                log.warning(f"[DexScreener] Detail fetch error: {result}")

        return tokens

    async def _fetch_token_detail(
        self,
        session: aiohttp.ClientSession,
        address: str,
        profile: dict
    ) -> Optional[TokenData]:
        """Token detayını çek ve TokenData'ya çevir"""
        url = f"{self.base_url}/tokens/v1/solana/{address}"

        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    log.debug(f"[DexScreener] Detail HTTP {resp.status} for {address[:8]}")
                    return None
                data = await resp.json()
        except Exception as e:
            log.warning(f"[DexScreener] Detail request error for {address[:8]}: {e}")
            return None

        if not data or not isinstance(data, list) or len(data) == 0:
            return None

        # İlk pair'i al (genellikle en likit olan)
        pair = data[0]

        # Veriyi parse et
        return self._parse_pair_to_token(pair, profile)

    def _parse_pair_to_token(self, pair: dict, profile: dict) -> Optional[TokenData]:
        """DexScreener pair verisini TokenData'ya çevir"""
        try:
            base_token = pair.get("baseToken", {})
            quote_token = pair.get("quoteToken", {})

            # Solana token base token olmalı (quote genellikle SOL/USDC)
            address = base_token.get("address")
            if not address:
                return None

            # Likidite
            liquidity = pair.get("liquidity", {})
            liquidity_usd = safe_float(liquidity.get("usd"), 0.0)

            # Hacim
            volume = pair.get("volume", {})
            volume_24h = safe_float(volume.get("h24"), 0.0)

            # Fiyat
            price_usd = safe_float(pair.get("priceUsd"), 0.0)

            # Market cap / FDV
            market_cap = safe_float(pair.get("marketCap") or pair.get("fdv"), 0.0)

            # Yaş
            created_at = pair.get("pairCreatedAt")
            age_seconds = 0
            if created_at:
                created_dt = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)
                age_seconds = int((utc_now() - created_dt).total_seconds())

            # Token bilgileri
            token = TokenData(
                address=address,
                name=base_token.get("name", "Unknown"),
                symbol=base_token.get("symbol", "UNK"),
                price_usd=price_usd,
                liquidity_usd=liquidity_usd,
                market_cap=market_cap,
                volume_24h=volume_24h,
                age_seconds=age_seconds,
                mint_authority=None,  # DexScreener bu bilgiyi vermez
                freeze_authority=None,
                mint_renounced=False,
                freeze_renounced=False,
                holder_count=0,
                top_10_holder_pct=0.0,
                source=TokenSource.DEXSCREENER,
                raw_data={**pair, "profile": profile},
            )

            return token

        except Exception as e:
            log.warning(f"[DexScreener] Parse error: {e}")
            return None

    async def fetch_token_details(self, address: str) -> Optional[TokenData]:
        """Tek bir token'ın detayını çek"""
        session = await self._get_session()
        url = f"{self.base_url}/tokens/v1/solana/{address}"

        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except Exception as e:
            log.warning(f"[DexScreener] fetch_token_details error: {e}")
            return None

        if not data or not isinstance(data, list):
            return None

        return self._parse_pair_to_token(data[0], {})

    async def close(self):
        """Session'ı kapat"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None