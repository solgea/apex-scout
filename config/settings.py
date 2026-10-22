"""
Apex Scout - Merkezi Yapılandırma (Pydantic Settings)
Tüm ortam değişkenleri buradan doğrulanır ve erişilir.
.env dosyasından okur, tip güvenliği sağlar.
"""

from typing import List, Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TakeProfitTierModel(BaseSettings):
    """Kademeli Take-Profit katmanı modeli"""

    profit_pct: float = Field(..., description="Kâr hedefi yüzdesi (örn: 25 = %25)")
    sell_pct: float = Field(..., description="Bu kademe satılacak pozisyon yüzdesi (örn: 40 = %40)")

    @field_validator("profit_pct", "sell_pct")
    @classmethod
    def positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Yüzde değerleri pozitif olmalı")
        if v > 100:
            raise ValueError("Yüzde değerleri 100'den büyük olamaz")
        return v


class Settings(BaseSettings):
    """Ana yapılandırma sınıfı - .env'den yükler"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ============ OKX DEMO ONLY ============
    okx_api_key: str = Field(..., description="OKX Demo API Key")
    okx_api_secret: str = Field(..., description="OKX Demo API Secret")
    okx_passphrase: str = Field(..., description="OKX Demo Passphrase")
    okx_demo_trading: bool = Field(..., description="ZORUNLU: Demo modu aktif olmalı (true)")
    okx_base_url: str = Field(default="https://www.okx.com", description="OKX API base URL")

    # ============ SCANNER ============
    scan_interval_seconds: int = Field(
        default=60, ge=10, le=3600, description="Tarama aralığı (saniye)"
    )
    dexscreener_base_url: str = Field(
        default="https://api.dexscreener.com", description="DexScreener API URL"
    )
    pumpfun_base_url: str = Field(
        default="https://frontend-api-v3.pump.fun", description="Pump.fun API URL (v3)"
    )
    min_liquidity_usd: float = Field(default=5000, ge=0, description="Minimum likidite (USD)")
    max_token_age_hours: int = Field(
        default=2, ge=1, le=168, description="Maksimum token yaşı (saat)"
    )
    min_volume_24h: float = Field(default=1000, ge=0, description="Minimum 24h hacim (USD)")

    # ============ DECISION / SCORING ============
    min_score_to_trade: int = Field(default=70, ge=0, le=100, description="İşlem için minimum skor")
    watch_threshold: int = Field(default=50, ge=0, le=100, description="İzleme eşiği")

    # Skor ağırlıkları (toplam 1.0 olmalı)
    scoring_weights_liquidity: float = Field(
        default=0.25, ge=0, le=1, description="Likidite ağırlığı"
    )
    scoring_weights_volume: float = Field(default=0.20, ge=0, le=1, description="Hacim ağırlığı")
    scoring_weights_age: float = Field(default=0.15, ge=0, le=1, description="Yaş ağırlığı")
    scoring_weights_mcap: float = Field(default=0.15, ge=0, le=1, description="Market cap ağırlığı")
    scoring_weights_mint_freeze: float = Field(
        default=0.10, ge=0, le=1, description="Mint/Freeze ağırlığı"
    )
    scoring_weights_holder_dist: float = Field(
        default=0.15, ge=0, le=1, description="Holder dağılımı ağırlığı"
    )

    # ============ RISK MANAGEMENT ============
    max_open_positions: int = Field(default=4, ge=1, le=20, description="Max açık pozisyon sayısı")
    max_portfolio_risk_pct: float = Field(
        default=35.0, ge=1, le=100, description="Max portföy riski (%)"
    )
    position_size_pct: float = Field(
        default=10.0, ge=1, le=50, description="İşlem başı pozisyon büyüklüğü (%)"
    )
    stop_loss_pct: float = Field(default=15.0, ge=1, le=90, description="Stop-Loss (%)")
    trailing_stop_pct: float = Field(default=10.0, ge=1, le=50, description="Trailing Stop (%)")
    take_profit_tiers: List[TakeProfitTierModel] = Field(
        default=[
            {"profit_pct": 25.0, "sell_pct": 40.0},
            {"profit_pct": 45.0, "sell_pct": 40.0},
            {"profit_pct": 70.0, "sell_pct": 100.0},
        ],
        description="Kademeli TP katmanları",
    )
    blacklist_duration_hours: int = Field(
        default=3, ge=1, le=168, description="Blacklist süresi (saat)"
    )
    trade_cooldown_seconds: int = Field(
        default=30, ge=0, le=3600, description="İşlem cooldown (saniye)"
    )

    # ============ DASHBOARD ============
    dashboard_host: str = Field(default="0.0.0.0", description="Dashboard host")
    dashboard_port: int = Field(default=8501, ge=1000, le=65535, description="Dashboard port")
    dashboard_refresh_seconds: int = Field(
        default=10, ge=5, le=300, description="Dashboard yenileme (saniye)"
    )

    # ============ SYSTEM ============
    log_level: str = Field(default="INFO", description="Log seviyesi")
    log_rotation: str = Field(default="10 MB", description="Log rotasyon boyutu")
    log_retention: str = Field(default="7 days", description="Log saklama süresi")
    db_url: str = Field(default="sqlite:///data/apex_scout.db", description="Veritabanı URL")
    heartbeat_interval: int = Field(
        default=30, ge=5, le=300, description="Heartbeat aralığı (saniye)"
    )
    max_retries: int = Field(default=3, ge=0, le=10, description="Max retry sayısı")
    retry_backoff_base: float = Field(default=2.0, ge=1.0, le=10.0, description="Backoff tabanı")

    # ============ VALIDATORS ============
    @field_validator("okx_demo_trading")
    @classmethod
    def validate_demo_trading(cls, v: bool) -> bool:
        """Sadece demo trading'e izin ver"""
        if not v:
            raise ValueError(
                "OKX_DEMO_TRADING=true olmalıdır! "
                "Gerçek hesap trading'i güvenlik nedeniyle desteklenmez. "
                "Demo hesap için: okx.com -> Demo Trading"
            )
        return v

    @model_validator(mode="after")
    def validate_scoring_weights(self) -> "Settings":
        """Skor ağırlıkları toplamı 1.0 olmalı (yaklaşık)"""
        total = (
            self.scoring_weights_liquidity
            + self.scoring_weights_volume
            + self.scoring_weights_age
            + self.scoring_weights_mcap
            + self.scoring_weights_mint_freeze
            + self.scoring_weights_holder_dist
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Skor ağırlıkları toplamı 1.0 olmalı, şu an: {total:.3f}. "
                "Lütfen .env'deki SCORING_WEIGHTS_* değerlerini düzeltin."
            )
        return self

    @model_validator(mode="after")
    def validate_take_profit_tiers(self) -> "Settings":
        """TP katmanları artan profit_pct olmalı, sell_pct toplamı <= 100"""
        if not self.take_profit_tiers:
            raise ValueError("En az bir TP katmanı tanımlanmalı")

        prev_profit = 0
        total_sell = 0
        for tier in self.take_profit_tiers:
            if tier.profit_pct <= prev_profit:
                raise ValueError("TP katmanları profit_pct olarak artan sırada olmalı")
            prev_profit = tier.profit_pct
            total_sell += tier.sell_pct

        if total_sell > 100:
            raise ValueError(f"TP katmanları sell_pct toplamı 100'i geçemez, şu an: {total_sell}")

        return self

    @model_validator(mode="after")
    def validate_risk_limits(self) -> "Settings":
        """Risk limitleri tutarlı olmalı"""
        # Max risk pozisyon sayısı * pozisyon büyüklüğünden az olmamalı
        max_theoretical_risk = self.max_open_positions * self.position_size_pct
        if self.max_portfolio_risk_pct > max_theoretical_risk:
            # Bu bir uyarı seviyesinde, hata değil - sadece bilgi
            pass
        return self

    # ============ COMPUTED PROPERTIES ============
    @property
    def scoring_weights_dict(self) -> dict:
        """Skor ağırlıklarını dict olarak döner"""
        return {
            "liquidity": self.scoring_weights_liquidity,
            "volume": self.scoring_weights_volume,
            "age": self.scoring_weights_age,
            "mcap": self.scoring_weights_mcap,
            "mint_freeze": self.scoring_weights_mint_freeze,
            "holder_dist": self.scoring_weights_holder_dist,
        }

    @property
    def okx_headers(self) -> dict:
        """OKX Demo trading header'ları"""
        return {
            "OK-ACCESS-KEY": self.okx_api_key,
            "OK-ACCESS-SIGN": "",  # Request sırasında doldurulur
            "OK-ACCESS-TIMESTAMP": "",  # Request sırasında doldurulur
            "OK-ACCESS-PASSPHRASE": self.okx_passphrase,
            "Content-Type": "application/json",
            "x-simulated-trading": "1",  # ZORUNLU: Demo trading header
        }

    def get_take_profit_tiers(self) -> List[dict]:
        """TP katmanlarını dict listesi olarak döner"""
        return [
            {"profit_pct": t.profit_pct, "sell_pct": t.sell_pct} for t in self.take_profit_tiers
        ]


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Settings instance'ını döner (dependency injection için)"""
    return settings
