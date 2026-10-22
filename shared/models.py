"""
Apex Scout - Veritabanı Modelleri (SQLAlchemy 2.0)
Tüm tablolar ve ilişkiler burada tanımlanır.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.constants import DecisionAction, OrderSide, PositionStatus, TokenSource
from shared.database import Base


class Token(Base):
    """Taradığımız token'lar"""

    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(
        String(44), unique=True, index=True, nullable=False
    )  # Solana address
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Temel metrikler
    liquidity_usd: Mapped[float] = mapped_column(Float, default=0.0)
    market_cap: Mapped[float] = mapped_column(Float, default=0.0)
    volume_24h: Mapped[float] = mapped_column(Float, default=0.0)
    price_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # Token bilgileri
    age_seconds: Mapped[int] = mapped_column(Integer, default=0)
    mint_authority: Mapped[str | None] = mapped_column(String(44), nullable=True)
    freeze_authority: Mapped[str | None] = mapped_column(String(44), nullable=True)
    mint_renounced: Mapped[bool] = mapped_column(Boolean, default=False)
    freeze_renounced: Mapped[bool] = mapped_column(Boolean, default=False)
    holder_count: Mapped[int] = mapped_column(Integer, default=0)
    top_10_holder_pct: Mapped[float] = mapped_column(Float, default=0.0)

    # Kaynak ve zaman
    source: Mapped[str] = mapped_column(SQLEnum(TokenSource), default=TokenSource.DEXSCREENER)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # İlişkiler
    decisions: Mapped[list["Decision"]] = relationship(
        "Decision", back_populates="token", cascade="all, delete-orphan"
    )
    positions: Mapped[list["Position"]] = relationship("Position", back_populates="token")

    # İndeksler
    __table_args__ = (
        Index("ix_token_symbol_discovered", "symbol", "discovered_at"),
        Index("ix_token_liquidity_age", "liquidity_usd", "age_seconds"),
    )

    def __repr__(self) -> str:
        return f"<Token {self.symbol} ({self.address[:8]}...)>"


class Decision(Base):
    """Karar motoru çıktıları"""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tokens.id", ondelete="CASCADE"), index=True
    )

    score: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    action: Mapped[str] = mapped_column(
        SQLEnum(DecisionAction), default=DecisionAction.SKIP, index=True
    )
    reasons: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Detaylı nedenler

    # Skor bileşenleri
    score_liquidity: Mapped[float] = mapped_column(Float, default=0.0)
    score_volume: Mapped[float] = mapped_column(Float, default=0.0)
    score_age: Mapped[float] = mapped_column(Float, default=0.0)
    score_mcap: Mapped[float] = mapped_column(Float, default=0.0)
    score_mint_freeze: Mapped[float] = mapped_column(Float, default=0.0)
    score_holder_dist: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # İlişkiler
    token: Mapped["Token"] = relationship("Token", back_populates="decisions")

    def __repr__(self) -> str:
        return f"<Decision {self.token.symbol if self.token else 'N/A'}: {self.action} ({self.score:.1f})>"


class Position(Base):
    """Açık/kapalı pozisyonlar"""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tokens.id", ondelete="SET NULL"), index=True
    )

    # OKX bilgileri
    okx_inst_id: Mapped[str] = mapped_column(String(30), index=True)  # Örn: "BONK-USDT"
    okx_pos_id: Mapped[str | None] = mapped_column(String(50), nullable=True)  # OKX position ID

    # Pozisyon detayları
    side: Mapped[str] = mapped_column(SQLEnum(OrderSide), default=OrderSide.BUY)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)  # Token miktarı
    entry_value_usd: Mapped[float] = mapped_column(
        Float, nullable=False
    )  # USD cinsinden giriş değeri

    # Güncel durum
    current_price: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)

    # Risk yönetimi
    stop_loss_price: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit_tiers: Mapped[list[dict]] = mapped_column(
        JSON, default=list
    )  # [{"profit_pct": 25, "sell_pct": 40, "triggered": false}, ...]
    current_tp_tier: Mapped[int] = mapped_column(Integer, default=0)  # Hangi TP tetiklendi
    trailing_stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trailing_activated: Mapped[bool] = mapped_column(Boolean, default=False)

    # Durum
    status: Mapped[str] = mapped_column(
        SQLEnum(PositionStatus), default=PositionStatus.OPEN, index=True
    )

    # Zaman damgaları
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # İlişkiler
    token: Mapped[Optional["Token"]] = relationship("Token", back_populates="positions")
    trades: Mapped[list["Trade"]] = relationship(
        "Trade", back_populates="position", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        token_sym = self.token.symbol if self.token else "N/A"
        return (
            f"<Position {token_sym} {self.side} {self.status} PnL:{self.unrealized_pnl_pct:.2f}%>"
        )


class Trade(Base):
    """Gerçekleşen işlemler (fill olan emirler)"""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("positions.id", ondelete="CASCADE"), index=True
    )

    # İşlem detayları
    side: Mapped[str] = mapped_column(SQLEnum(OrderSide), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    fee_currency: Mapped[str] = mapped_column(String(10), default="USDT")

    # OKX order ID
    okx_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    okx_trade_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # TP/SL bilgisi
    is_take_profit: Mapped[bool] = mapped_column(Boolean, default=False)
    is_stop_loss: Mapped[bool] = mapped_column(Boolean, default=False)
    is_trailing_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    tp_tier_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # İlişkiler
    position: Mapped["Position"] = relationship("Position", back_populates="trades")

    def __repr__(self) -> str:
        return f"<Trade {self.side} {self.quantity:.4f} @ {self.price:.6f}>"


class SystemMetrics(Base):
    """Sistem metrikleri ve sağlık kontrolü"""

    __tablename__ = "system_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Tarama metrikleri
    scan_count: Mapped[int] = mapped_column(Integer, default=0)
    tokens_found: Mapped[int] = mapped_column(Integer, default=0)
    tokens_filtered: Mapped[int] = mapped_column(Integer, default=0)
    tokens_scored: Mapped[int] = mapped_column(Integer, default=0)

    # Karar metrikleri
    decisions_pass: Mapped[int] = mapped_column(Integer, default=0)
    decisions_watch: Mapped[int] = mapped_column(Integer, default=0)
    decisions_skip: Mapped[int] = mapped_column(Integer, default=0)

    # Trading metrikleri
    trades_executed: Mapped[int] = mapped_column(Integer, default=0)
    trades_failed: Mapped[int] = mapped_column(Integer, default=0)
    positions_opened: Mapped[int] = mapped_column(Integer, default=0)
    positions_closed: Mapped[int] = mapped_column(Integer, default=0)

    # Hata ve performans
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    api_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    scanner_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    decision_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    trading_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)

    # Portföy
    total_portfolio_value: Mapped[float] = mapped_column(Float, default=0.0)
    available_balance: Mapped[float] = mapped_column(Float, default=0.0)
    risk_exposure_pct: Mapped[float] = mapped_column(Float, default=0.0)

    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self) -> str:
        return f"<SystemMetrics scan={self.scan_count} trades={self.trades_executed} errors={self.errors_count}>"


class BlacklistEntry(Base):
    """Blacklist kayıtları (SL yiyen token'lar)"""

    __tablename__ = "blacklist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_address: Mapped[str] = mapped_column(String(44), index=True, nullable=False)
    token_symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(100), default="STOP_LOSS_HIT")
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Blacklist {self.token_symbol} expires={self.expires_at}>"
