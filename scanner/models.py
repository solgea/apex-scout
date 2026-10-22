"""
Apex Scout - Scanner Veri Modelleri (Pydantic)
API yanıtlarını parse etmek ve validate etmek için.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from config.constants import TokenSource


class TokenData(BaseModel):
    """Ham token verisi - tüm kaynaklar için ortak model"""

    # Temel kimlik
    address: str = Field(..., description="Token contract/mint address")
    name: str = Field(..., description="Token adı")
    symbol: str = Field(..., description="Token sembolü")

    # Fiyat ve likidite
    price_usd: float = Field(default=0.0, ge=0, description="USD cinsinden fiyat")
    liquidity_usd: float = Field(default=0.0, ge=0, description="Toplam likidite (USD)")
    market_cap: float = Field(default=0.0, ge=0, description="Market cap (USD)")
    volume_24h: float = Field(default=0.0, ge=0, description="24 saatlik hacim (USD)")

    # Token yaşı ve durum
    age_seconds: int = Field(default=0, ge=0, description="Token yaşı (saniye)")
    created_at: datetime | None = Field(default=None, description="Oluşturulma zamanı")

    # Yetki kontrolleri
    mint_authority: str | None = Field(default=None, description="Mint authority address")
    freeze_authority: str | None = Field(default=None, description="Freeze authority address")
    mint_renounced: bool = Field(default=False, description="Mint yetkisi terk edilmiş mi")
    freeze_renounced: bool = Field(default=False, description="Freeze yetkisi terk edilmiş mi")

    # Holder bilgileri
    holder_count: int = Field(default=0, ge=0, description="Holder sayısı")
    top_10_holder_pct: float = Field(default=0.0, ge=0, le=100, description="Top 10 holder yüzdesi")

    # Kaynak
    source: TokenSource = Field(default=TokenSource.DEXSCREENER, description="Veri kaynağı")
    raw_data: dict[str, Any] = Field(default_factory=dict, description="Ham API yanıtı")

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        """Solana address format kontrolü (base58, ~44 karakter)"""
        if not v or len(v) < 32 or len(v) > 50:
            raise ValueError(f"Geçersiz Solana address uzunluğu: {len(v)}")
        return v

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.upper().strip()

    def to_dict(self) -> dict[str, Any]:
        """Dict'e çevir (DB kaydetmek için)"""
        return self.model_dump(exclude={"raw_data"})


class TokenFilterCriteria(BaseModel):
    """Token filtreleme kriterleri"""

    min_liquidity_usd: float = Field(default=5000, ge=0)
    max_age_hours: int = Field(default=2, ge=1)
    min_volume_24h: float = Field(default=1000, ge=0)
    min_holder_count: int = Field(default=10, ge=0)
    max_top_10_holder_pct: float = Field(default=80.0, ge=0, le=100)
    require_mint_renounced: bool = Field(default=False)
    require_freeze_renounced: bool = Field(default=False)
    excluded_symbols: list[str] = Field(default_factory=list)  # Blacklist semboller
    excluded_addresses: list[str] = Field(default_factory=list)  # Blacklist adresler

    def check(self, token: TokenData) -> tuple[bool, list[str]]:
        """
        Token filtrelerden geçer mi?
        Returns: (passed: bool, failed_reasons: List[str])
        """
        reasons = []

        if token.liquidity_usd < self.min_liquidity_usd:
            reasons.append(
                f"Likidite çok düşük: ${token.liquidity_usd:,.0f} < ${self.min_liquidity_usd:,.0f}"
            )

        age_hours = token.age_seconds / 3600
        if age_hours > self.max_age_hours:
            reasons.append(f"Token çok eski: {age_hours:.1f}h > {self.max_age_hours}h")

        if token.volume_24h < self.min_volume_24h:
            # Pump.fun 24h hacim vermez (0 = bilgi yok) -> filtreleme
            from config.constants import TokenSource

            if token.source == TokenSource.PUMPFUN and token.volume_24h == 0:
                pass  # Bilgi yok, atlanır
            else:
                reasons.append(
                    f"Hacim çok düşük: ${token.volume_24h:,.0f} < ${self.min_volume_24h:,.0f}"
                )

        # Holder sayısı kontrolü
        # NOT: holder_count == 0 => "bilgi yok" (DexScreener holder vermez)
        # Bilgi yoksa token elenmez, sadece skorlama etkilenır.
        if token.holder_count > 0 and token.holder_count < self.min_holder_count:
            reasons.append(f"Holder sayısı az: {token.holder_count} < {self.min_holder_count}")

        # Top 10 holder dağılımı - 0 => bilgi yok, kontrol edilmez
        if token.top_10_holder_pct > 0 and token.top_10_holder_pct > self.max_top_10_holder_pct:
            reasons.append(
                f"Top 10 holder çok yoğun: %{token.top_10_holder_pct:.1f} > %{self.max_top_10_holder_pct:.1f}"
            )

        if self.require_mint_renounced and not token.mint_renounced:
            reasons.append("Mint yetkisi terk edilmemiş")

        if self.require_freeze_renounced and not token.freeze_renounced:
            reasons.append("Freeze yetkisi terk edilmemiş")

        if token.symbol in self.excluded_symbols:
            reasons.append(f"Sembol dışlanmış: {token.symbol}")

        if token.address in self.excluded_addresses:
            reasons.append(f"Adres blacklist'te: {token.address[:8]}...")

        return len(reasons) == 0, reasons


# DexScreener özel response modelleri
class DexScreenerPair(BaseModel):
    """DexScreener pair response"""

    chain_id: str
    dex_id: str
    url: str
    pair_address: str
    base_token: dict[str, Any]
    quote_token: dict[str, Any]
    price_usd: str | None = None
    liquidity: dict[str, Any] | None = None
    fdv: float | None = None
    market_cap: float | None = None
    volume: dict[str, Any] | None = None
    price_change: dict[str, Any] | None = None
    txns: dict[str, Any] | None = None
    created_at: int | None = None


class DexScreenerResponse(BaseModel):
    """DexScreener API response"""

    schema_version: str
    pairs: list[DexScreenerPair] = []


# Pump.fun özel response modelleri
class PumpFunToken(BaseModel):
    """Pump.fun token response"""

    mint: str
    name: str
    symbol: str
    description: str
    twitter: str | None = None
    telegram: str | None = None
    website: str | None = None
    creator: str
    created_timestamp: int
    raydium_pool: str | None = None
    complete: bool = False
    virtual_sol_reserves: float = 0
    virtual_token_reserves: float = 0
    real_sol_reserves: float = 0
    real_token_reserves: float = 0
    total_supply: float = 0
    market_cap: float = 0
    reply_count: int = 0
    last_reply: int | None = None
    nsfw: bool = False
    hidden: bool = False


class PumpFunResponse(BaseModel):
    """Pump.fun API response"""

    tokens: list[PumpFunToken] = []
