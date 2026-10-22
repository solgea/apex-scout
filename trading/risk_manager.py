"""
Apex Scout - Risk Manager
Kademeli TP, Trailing SL, Stop-Loss, Pozisyon limitleri, Portföy risk limiti.
"""

from typing import List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from shared.logger import get_logger
from shared.exceptions import (
    RiskError,
    MaxPositionsExceededError,
    MaxRiskExceededError,
    PositionSizeError,
)
from config.settings import settings
from config.constants import OrderSide, PositionStatus
from trading.models import Position, Order, OrderSide as ModelOrderSide, OrderType, OrderStatus

log = get_logger(__name__)


@dataclass
class TPTier:
    """Take-Profit katmanı"""

    profit_pct: float  # Hedef kâr %
    sell_pct: float  # Bu kademede satılacak %
    triggered: bool = False


@dataclass
class RiskCheckResult:
    """Risk kontrol sonucu"""

    allowed: bool
    reason: str = ""
    max_size_usd: float = 0.0


class RiskManager:
    """
    Risk yönetimi merkezi.
    - Kademeli Take-Profit
    - Trailing Stop-Loss
    - Hard Stop-Loss
    - Max açık pozisyon
    - Max portföy riski
    - Pozisyon boyutu
    """

    def __init__(self):
        self.max_open_positions = settings.max_open_positions
        self.max_portfolio_risk_pct = settings.max_portfolio_risk_pct
        self.position_size_pct = settings.position_size_pct
        self.stop_loss_pct = settings.stop_loss_pct
        self.trailing_stop_pct = settings.trailing_stop_pct
        self.take_profit_tiers = settings.get_take_profit_tiers()

    # ============ POSITION SIZING ============

    def calculate_position_size(
        self, available_balance: float, entry_price: float
    ) -> Tuple[float, float]:
        """
        Pozisyon boyutunu hesapla.
        Returns: (quantity, position_value_usd)
        """
        if available_balance <= 0:
            raise PositionSizeError("Available balance must be positive")

        # Config'deki yüzdeye göre
        position_value = available_balance * (self.position_size_pct / 100)

        # Minimum kontrol (örn $10)
        min_position = 10.0
        if position_value < min_position:
            position_value = min(min_position, available_balance)

        quantity = position_value / entry_price if entry_price > 0 else 0

        return quantity, position_value

    def check_position_size(
        self, position_value_usd: float, available_balance: float
    ) -> RiskCheckResult:
        """Pozisyon boyutu risk kontrolü"""
        max_allowed = available_balance * (self.position_size_pct / 100) * 1.1  # %10 tolerans

        if position_value_usd > max_allowed:
            return RiskCheckResult(
                allowed=False,
                reason=f"Position size ${position_value_usd:.2f} exceeds limit ${max_allowed:.2f}",
                max_size_usd=max_allowed,
            )

        return RiskCheckResult(allowed=True, max_size_usd=max_allowed)

    # ============ PORTFOLIO RISK ============

    def check_portfolio_risk(
        self,
        current_positions: List[Position],
        new_position_value: float,
        total_portfolio_value: float,
    ) -> RiskCheckResult:
        """
        Portföy risk kontrolü.
        Açık pozisyonların toplam değeri + yeni pozisyon ≤ max_portfolio_risk_pct
        """
        if total_portfolio_value <= 0:
            return RiskCheckResult(allowed=False, reason="Invalid portfolio value")

        current_exposure = sum(p.entry_value_usd for p in current_positions if p.status == "OPEN")
        new_exposure = current_exposure + new_position_value
        exposure_pct = (new_exposure / total_portfolio_value) * 100

        if exposure_pct > self.max_portfolio_risk_pct:
            return RiskCheckResult(
                allowed=False,
                reason=f"Portfolio risk would be {exposure_pct:.1f}% > {self.max_portfolio_risk_pct}%",
                max_size_usd=total_portfolio_value * (self.max_portfolio_risk_pct / 100)
                - current_exposure,
            )

        return RiskCheckResult(
            allowed=True,
            max_size_usd=total_portfolio_value * (self.max_portfolio_risk_pct / 100)
            - current_exposure,
        )

    def check_max_positions(self, current_positions: List[Position]) -> RiskCheckResult:
        """Maksimum pozisyon sayısı kontrolü"""
        open_count = sum(1 for p in current_positions if p.status == "OPEN")

        if open_count >= self.max_open_positions:
            return RiskCheckResult(
                allowed=False,
                reason=f"Max open positions reached: {open_count}/{self.max_open_positions}",
            )

        return RiskCheckResult(allowed=True)

    # ============ STOP LOSS / TAKE PROFIT ============

    def create_stop_loss_price(self, entry_price: float, side: OrderSide) -> float:
        """Stop-Loss fiyatı hesapla"""
        if side == OrderSide.BUY:
            return entry_price * (1 - self.stop_loss_pct / 100)
        else:
            return entry_price * (1 + self.stop_loss_pct / 100)

    def create_take_profit_tiers(self, entry_price: float, side: OrderSide) -> List[TPTier]:
        """TP katmanlarını oluştur"""
        tiers = []
        for tp in self.take_profit_tiers:
            if side == OrderSide.BUY:
                trigger_price = entry_price * (1 + tp["profit_pct"] / 100)
            else:
                trigger_price = entry_price * (1 - tp["profit_pct"] / 100)

            tiers.append(
                TPTier(
                    profit_pct=tp["profit_pct"],
                    sell_pct=tp["sell_pct"],
                    triggered=False,
                )
            )
        return tiers

    def get_tp_trigger_prices(self, entry_price: float, side: OrderSide) -> List[float]:
        """TP tetikleme fiyatları"""
        prices = []
        for tp in self.take_profit_tiers:
            if side == OrderSide.BUY:
                prices.append(entry_price * (1 + tp["profit_pct"] / 100))
            else:
                prices.append(entry_price * (1 - tp["profit_pct"] / 100))
        return prices

    # ============ POSITION MONITORING ============

    def check_exit_conditions(
        self,
        position: Position,
        current_price: float,
    ) -> Tuple[Optional[str], Optional[float], Optional[int]]:
        """
        Pozisyon için çıkış koşullarını kontrol et.
        Returns: (action, price, tp_tier_index)
        action: "STOP_LOSS", "TAKE_PROFIT", "TRAILING_STOP", or None
        """
        # 1. Hard Stop-Loss
        if self._check_stop_loss(position, current_price):
            return "STOP_LOSS", position.stop_loss_price, None

        # 2. Take-Profit tiers
        tp_action = self._check_take_profit(position, current_price)
        if tp_action:
            return tp_action

        # 3. Trailing Stop
        trailing_action = self._check_trailing_stop(position, current_price)
        if trailing_action:
            return trailing_action

        return None, None, None

    def _check_stop_loss(self, position: Position, current_price: float) -> bool:
        """Stop-Loss kontrolü"""
        if position.side == OrderSide.BUY:
            return current_price <= position.stop_loss_price
        else:
            return current_price >= position.stop_loss_price

    def _check_take_profit(
        self, position: Position, current_price: float
    ) -> Optional[Tuple[str, float, int]]:
        """Take-Profit katmanları kontrolü"""
        for i, tier in enumerate(position.take_profit_tiers):
            if tier.get("triggered"):
                continue

            profit_pct = tier["profit_pct"]
            trigger_price = (
                position.entry_price * (1 + profit_pct / 100)
                if position.side == OrderSide.BUY
                else position.entry_price * (1 - profit_pct / 100)
            )

            if position.side == OrderSide.BUY:
                triggered = current_price >= trigger_price
            else:
                triggered = current_price <= trigger_price

            if triggered:
                return "TAKE_PROFIT", trigger_price, i

        return None

    def _check_trailing_stop(
        self, position: Position, current_price: float
    ) -> Optional[Tuple[str, float, int]]:
        """Trailing Stop kontrolü"""
        # Trailing sadece ilk TP sonrası aktif olur
        if not position.trailing_activated:
            # İlk TP tetiklendi mi?
            first_tp_triggered = any(t.get("triggered") for t in position.take_profit_tiers)
            if first_tp_triggered:
                # Trailing'i en yüksek/alçak fiyattan başlat
                if position.side == OrderSide.BUY:
                    position.trailing_stop_price = current_price * (
                        1 - self.trailing_stop_pct / 100
                    )
                else:
                    position.trailing_stop_price = current_price * (
                        1 + self.trailing_stop_pct / 100
                    )
                position.trailing_activated = True
                log.info(
                    f"[Risk] Trailing activated for {position.inst_id} at {position.trailing_stop_price:.6f}"
                )
                return None  # Bu tick'te tetikleme yok

        # Trailing aktifse kontrol et
        if position.trailing_stop_price is not None:
            if position.side == OrderSide.BUY:
                # Fiyat yükseldiyse trailing'i yukarı çek
                new_trailing = current_price * (1 - self.trailing_stop_pct / 100)
                if new_trailing > position.trailing_stop_price:
                    position.trailing_stop_price = new_trailing

                # Fiyat trailing'in altına düştüyse
                if current_price <= position.trailing_stop_price:
                    return "TRAILING_STOP", position.trailing_stop_price, None
            else:
                # Short için simetrik
                new_trailing = current_price * (1 + self.trailing_stop_pct / 100)
                if new_trailing < position.trailing_stop_price:
                    position.trailing_stop_price = new_trailing

                if current_price >= position.trailing_stop_price:
                    return "TRAILING_STOP", position.trailing_stop_price, None

        return None

    def update_position_after_tp(
        self, position: Position, tp_tier_index: int, fill_price: float, fill_qty: float
    ):
        """TP fill sonrası pozisyonu güncelle"""
        if tp_tier_index < len(position.take_profit_tiers):
            position.take_profit_tiers[tp_tier_index]["triggered"] = True
            position.take_profit_tiers[tp_tier_index]["filled_price"] = fill_price
            position.take_profit_tiers[tp_tier_index]["filled_qty"] = fill_qty
            position.take_profit_tiers[tp_tier_index]["filled_at"] = datetime.utcnow().isoformat()

        position.current_tp_tier = tp_tier_index + 1
        position.quantity -= fill_qty
        position.realized_pnl += (
            (fill_price - position.entry_price) * fill_qty
            if position.side == OrderSide.BUY
            else (position.entry_price - fill_price) * fill_qty
        )

        # Kalan miktar 0 ise pozisyon kapandı
        if position.quantity <= 0.000001:
            position.status = PositionStatus.CLOSED
        else:
            position.status = PositionStatus.PARTIAL

    def update_position_after_sl(self, position: Position, fill_price: float, fill_qty: float):
        """SL fill sonrası pozisyonu güncelle"""
        position.quantity -= fill_qty
        position.realized_pnl += (
            (fill_price - position.entry_price) * fill_qty
            if position.side == OrderSide.BUY
            else (position.entry_price - fill_price) * fill_qty
        )
        position.status = PositionStatus.STOPPED_OUT

    def update_position_after_trailing(
        self, position: Position, fill_price: float, fill_qty: float
    ):
        """Trailing fill sonrası pozisyonu güncelle"""
        position.quantity -= fill_qty
        position.realized_pnl += (
            (fill_price - position.entry_price) * fill_qty
            if position.side == OrderSide.BUY
            else (position.entry_price - fill_price) * fill_qty
        )
        position.status = PositionStatus.TRAILING_CLOSED

    # ============ ORDER CREATION HELPERS ============

    def create_tp_order(
        self,
        position: Position,
        tp_tier_index: int,
        quantity: float,
    ) -> Order:
        """TP emri oluştur"""
        tier = position.take_profit_tiers[tp_tier_index]
        side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY

        return Order(
            inst_id=position.inst_id,
            side=side,
            order_type=OrderType.MARKET,
            size=quantity,
            is_take_profit=True,
            tp_tier_index=tp_tier_index,
        )

    def create_sl_order(self, position: Position, quantity: float) -> Order:
        """Stop-Loss emri oluştur (market - okx stop order kullan)"""
        side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY

        return Order(
            inst_id=position.inst_id,
            side=side,
            order_type=OrderType.STOP_MARKET,
            size=quantity,
            price=position.stop_loss_price,
            is_stop_loss=True,
        )

    def create_trailing_order(self, position: Position, quantity: float) -> Order:
        """Trailing Stop emri oluştur"""
        side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY

        return Order(
            inst_id=position.inst_id,
            side=side,
            order_type=OrderType.STOP_MARKET,
            size=quantity,
            price=position.trailing_stop_price,
            is_trailing_stop=True,
        )

    def get_risk_summary(self, positions: List[Position], portfolio_value: float) -> dict:
        """Risk özeti"""
        open_positions = [p for p in positions if p.status == "OPEN"]
        total_exposure = sum(p.entry_value_usd for p in open_positions)
        exposure_pct = (total_exposure / portfolio_value * 100) if portfolio_value > 0 else 0

        return {
            "open_positions": len(open_positions),
            "max_positions": self.max_open_positions,
            "total_exposure_usd": total_exposure,
            "portfolio_value_usd": portfolio_value,
            "exposure_pct": round(exposure_pct, 2),
            "max_exposure_pct": self.max_portfolio_risk_pct,
            "position_size_pct": self.position_size_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "trailing_stop_pct": self.trailing_stop_pct,
            "take_profit_tiers": self.take_profit_tiers,
        }
