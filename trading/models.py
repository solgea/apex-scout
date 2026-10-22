"""
Apex Scout - Trading Modelleri (Pydantic)
Emir, pozisyon, trade veri yapıları.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from config.constants import OrderSide


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"


class Order(BaseModel):
    """Emir modeli"""

    id: str | None = None  # Local ID
    okx_order_id: str | None = None  # OKX order ID
    okx_cl_ord_id: str | None = None  # Client order ID

    inst_id: str = Field(..., description="Instrument ID (e.g., BONK-USDT)")
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    size: float = Field(..., gt=0, description="Token miktarı")
    price: float | None = Field(default=None, description="Limit fiyatı (market için None)")

    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    fee: float = 0.0

    # TP/SL bilgisi
    is_take_profit: bool = False
    is_stop_loss: bool = False
    is_trailing_stop: bool = False
    tp_tier_index: int | None = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    filled_at: datetime | None = None

    raw_response: dict[str, Any] = Field(default_factory=dict)


class Trade(BaseModel):
    """Gerçekleşen trade (fill)"""

    id: str | None = None
    position_id: int | None = None
    order_id: str | None = None

    inst_id: str
    side: OrderSide
    price: float
    size: float
    fee: float = 0.0
    fee_ccy: str = "USDT"

    okx_trade_id: str | None = None
    okx_order_id: str | None = None

    is_take_profit: bool = False
    is_stop_loss: bool = False
    is_trailing_stop: bool = False
    tp_tier_index: int | None = None

    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Position(BaseModel):
    """Pozisyon modeli"""

    id: int | None = None  # DB ID
    token_id: int | None = None

    inst_id: str
    okx_pos_id: str | None = None

    side: OrderSide = OrderSide.BUY
    entry_price: float
    quantity: float
    entry_value_usd: float

    # Güncel
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    realized_pnl: float = 0.0

    # Risk yönetimi
    stop_loss_price: float
    take_profit_tiers: list[dict[str, Any]] = Field(
        default_factory=list
    )  # [{"profit_pct": 25, "sell_pct": 40, "triggered": false}]
    current_tp_tier: int = 0
    trailing_stop_price: float | None = None
    trailing_activated: bool = False

    # Durum
    status: str = "OPEN"  # OPEN, PARTIAL, CLOSED, STOPPED_OUT, TRAILING_CLOSED

    opened_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: datetime | None = None
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    def update_price(self, price: float):
        """Güncel fiyatı güncelle ve PnL hesapla"""
        self.current_price = price
        if self.side == OrderSide.BUY:
            self.unrealized_pnl = (price - self.entry_price) * self.quantity
            self.unrealized_pnl_pct = ((price - self.entry_price) / self.entry_price) * 100
        else:
            self.unrealized_pnl = (self.entry_price - price) * self.quantity
            self.unrealized_pnl_pct = ((self.entry_price - price) / self.entry_price) * 100
        self.last_updated = datetime.utcnow()

    def get_remaining_quantity(self) -> float:
        """Kalan miktar (kısmi TP sonrası)"""
        sold = sum(t.get("sell_pct", 0) for t in self.take_profit_tiers if t.get("triggered"))
        return self.quantity * (1 - sold / 100)


class PortfolioSnapshot(BaseModel):
    """Portföy anlık görüntüsü"""

    total_value_usd: float
    available_balance: float
    locked_balance: float
    unrealized_pnl: float
    realized_pnl_24h: float
    open_positions_count: int
    risk_exposure_pct: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
