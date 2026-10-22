"""
Apex Scout - Position Manager
Pozisyon yaşam döngüsü: açma, güncelleme, kapatma, DB senkronizasyonu.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from decimal import Decimal, ROUND_DOWN

from shared.logger import get_logger
from shared.database import get_session
from shared.models import Position as DBPosition, Trade as DBTrade, Token as DBToken
from shared.exceptions import PositionNotFoundError, TradingError
from config.constants import OrderSide, PositionStatus
from trading.models import Position, Order, Trade, OrderSide as ModelOrderSide
from trading.risk_manager import RiskManager

log = get_logger(__name__)


class PositionManager:
    """
    Pozisyon yönetimi.
    - Memory'de hızlı erişim
    - DB'ye kalıcı kayıt
    - OKX ile senkronizasyon
    """

    def __init__(self, risk_manager: RiskManager):
        self.risk_manager = risk_manager
        self._positions: Dict[int, Position] = {}  # db_id -> Position
        self._positions_by_inst: Dict[str, Position] = {}  # inst_id -> Position
        self._next_id = 1

    # ============ CREATE ============

    def create_position(
        self,
        token_id: Optional[int],
        inst_id: str,
        side: OrderSide,
        entry_price: float,
        quantity: float,
        stop_loss_price: float,
        take_profit_tiers: List[Dict],
        okx_order_id: Optional[str] = None,
    ) -> Position:
        """Yeni pozisyon oluştur (memory + DB)"""
        entry_value = entry_price * quantity

        # Memory model
        position = Position(
            id=self._next_id,
            token_id=token_id,
            inst_id=inst_id,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            entry_value_usd=entry_value,
            stop_loss_price=stop_loss_price,
            take_profit_tiers=take_profit_tiers,
            status=PositionStatus.OPEN,
            okx_order_id=okx_order_id,
        )

        # DB model
        db_position = DBPosition(
            token_id=token_id,
            okx_inst_id=inst_id,
            okx_pos_id=okx_order_id,
            side=side.value,
            entry_price=entry_price,
            quantity=quantity,
            entry_value_usd=entry_value,
            current_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_tiers=take_profit_tiers,
            current_tp_tier=0,
            status=PositionStatus.OPEN,
        )

        with get_session() as session:
            session.add(db_position)
            session.flush()
            position.id = db_position.id
            self._next_id = max(self._next_id, db_position.id + 1)

        # Cache'e ekle
        self._positions[position.id] = position
        self._positions_by_inst[inst_id] = position

        log.info(f"[Position] Created: {inst_id} {side.value} {quantity:.6f} @ {entry_price:.6f} (ID: {position.id})")
        return position

    # ============ READ ============

    def get_position(self, position_id: int) -> Optional[Position]:
        """ID ile pozisyon getir (memory cache)"""
        return self._positions.get(position_id)

    def get_position_by_inst(self, inst_id: str) -> Optional[Position]:
        """Instrument ID ile pozisyon getir"""
        return self._positions_by_inst.get(inst_id)

    def get_all_positions(self) -> List[Position]:
        """Tüm pozisyonlar"""
        return list(self._positions.values())

    def get_open_positions(self) -> List[Position]:
        """Açık pozisyonlar"""
        return [p for p in self._positions.values() if p.status == PositionStatus.OPEN]

    def get_positions_by_status(self, status: str) -> List[Position]:
        """Duruma göre pozisyonlar"""
        return [p for p in self._positions.values() if p.status == status]

    # ============ UPDATE ============

    def update_price(self, position_id: int, current_price: float) -> Optional[Position]:
        """Pozisyon fiyatını güncelle"""
        position = self._positions.get(position_id)
        if not position:
            return None

        position.update_price(current_price)
        self._sync_to_db(position)
        return position

    def update_prices_batch(self, prices: Dict[str, float]):
        """Birden fazla pozisyon fiyatını güncelle"""
        for inst_id, price in prices.items():
            position = self._positions_by_inst.get(inst_id)
            if position and position.status == PositionStatus.OPEN:
                position.update_price(price)
                self._sync_to_db(position)

    def apply_tp_fill(self, position_id: int, tp_tier_index: int, fill_price: float, fill_qty: float) -> bool:
        """TP fill uygula"""
        position = self._positions.get(position_id)
        if not position:
            return False

        self.risk_manager.update_position_after_tp(position, tp_tier_index, fill_price, fill_qty)
        self._sync_to_db(position)
        self._record_trade(position, ModelOrderSide.SELL if position.side == ModelOrderSide.BUY else ModelOrderSide.BUY,
                          fill_price, fill_qty, is_take_profit=True, tp_tier_index=tp_tier_index)
        return True

    def apply_sl_fill(self, position_id: int, fill_price: float, fill_qty: float) -> bool:
        """SL fill uygula"""
        position = self._positions.get(position_id)
        if not position:
            return False

        self.risk_manager.update_position_after_sl(position, fill_price, fill_qty)
        self._sync_to_db(position)
        self._record_trade(position, ModelOrderSide.SELL if position.side == ModelOrderSide.BUY else ModelOrderSide.BUY,
                          fill_price, fill_qty, is_stop_loss=True)
        return True

    def apply_trailing_fill(self, position_id: int, fill_price: float, fill_qty: float) -> bool:
        """Trailing fill uygula"""
        position = self._positions.get(position_id)
        if not position:
            return False

        self.risk_manager.update_position_after_trailing(position, fill_price, fill_qty)
        self._sync_to_db(position)
        self._record_trade(position, ModelOrderSide.SELL if position.side == ModelOrderSide.BUY else ModelOrderSide.BUY,
                          fill_price, fill_qty, is_trailing_stop=True)
        return True

    def close_position(self, position_id: int, close_price: float, reason: str = "MANUAL") -> bool:
        """Pozisyonu manuel kapat"""
        position = self._positions.get(position_id)
        if not position:
            return False

        # Kalan miktarı hesapla
        remaining_qty = position.get_remaining_quantity()
        if remaining_qty <= 0:
            return False

        pnl = (close_price - position.entry_price) * remaining_qty if position.side == OrderSide.BUY \
            else (position.entry_price - close_price) * remaining_qty

        position.quantity = 0
        position.realized_pnl += pnl
        position.status = PositionStatus.CLOSED
        position.closed_at = datetime.utcnow()
        position.current_price = close_price

        self._sync_to_db(position)
        self._record_trade(position, ModelOrderSide.SELL if position.side == ModelOrderSide.BUY else ModelOrderSide.BUY,
                          close_price, remaining_qty)
        return True

    # ============ SYNC ============

    def _sync_to_db(self, position: Position):
        """Memory position -> DB"""
        try:
            with get_session() as session:
                db_pos = session.query(DBPosition).filter(DBPosition.id == position.id).first()
                if db_pos:
                    db_pos.current_price = position.current_price
                    db_pos.unrealized_pnl = position.unrealized_pnl
                    db_pos.unrealized_pnl_pct = position.unrealized_pnl_pct
                    db_pos.realized_pnl = position.realized_pnl
                    db_pos.take_profit_tiers = position.take_profit_tiers
                    db_pos.current_tp_tier = position.current_tp_tier
                    db_pos.trailing_stop_price = position.trailing_stop_price
                    db_pos.trailing_activated = position.trailing_activated
                    db_pos.status = position.status
                    db_pos.closed_at = position.closed_at
                    db_pos.last_updated = datetime.utcnow()
                    session.commit()
        except Exception as e:
            log.error(f"[Position] DB sync failed for {position.id}: {e}")

    def _record_trade(
        self,
        position: Position,
        side: ModelOrderSide,
        price: float,
        quantity: float,
        is_take_profit: bool = False,
        is_stop_loss: bool = False,
        is_trailing_stop: bool = False,
        tp_tier_index: Optional[int] = None,
    ):
        """Trade kaydet"""
        try:
            with get_session() as session:
                trade = DBTrade(
                    position_id=position.id,
                    side=side.value,
                    price=price,
                    quantity=quantity,
                    fee=0.0,  # OKX'ten fill sonrası güncellenecek
                    is_take_profit=is_take_profit,
                    is_stop_loss=is_stop_loss,
                    is_trailing_stop=is_trailing_stop,
                    tp_tier_index=tp_tier_index,
                )
                session.add(trade)
                session.commit()
        except Exception as e:
            log.error(f"[Position] Trade record failed: {e}")

    # ============ LOAD FROM DB ============

    def load_from_db(self) -> int:
        """Başlangıçta DB'den açık pozisyonları yükle"""
        with get_session() as session:
            db_positions = session.query(DBPosition).filter(
                DBPosition.status.in_([PositionStatus.OPEN, PositionStatus.PARTIAL])
            ).all()

            count = 0
            for db_pos in db_positions:
                position = Position(
                    id=db_pos.id,
                    token_id=db_pos.token_id,
                    inst_id=db_pos.okx_inst_id,
                    okx_pos_id=db_pos.okx_pos_id,
                    side=OrderSide(db_pos.side),
                    entry_price=db_pos.entry_price,
                    quantity=db_pos.quantity,
                    entry_value_usd=db_pos.entry_value_usd,
                    current_price=db_pos.current_price,
                    unrealized_pnl=db_pos.unrealized_pnl,
                    unrealized_pnl_pct=db_pos.unrealized_pnl_pct,
                    realized_pnl=db_pos.realized_pnl,
                    stop_loss_price=db_pos.stop_loss_price,
                    take_profit_tiers=db_pos.take_profit_tiers or [],
                    current_tp_tier=db_pos.current_tp_tier,
                    trailing_stop_price=db_pos.trailing_stop_price,
                    trailing_activated=db_pos.trailing_activated,
                    status=db_pos.status,
                    opened_at=db_pos.opened_at,
                    closed_at=db_pos.closed_at,
                )
                self._positions[position.id] = position
                self._positions_by_inst[position.inst_id] = position
                self._next_id = max(self._next_id, position.id + 1)
                count += 1

            log.info(f"[Position] Loaded {count} open positions from DB")
            return count

    # ============ UTILITIES ============

    def get_total_exposure(self) -> float:
        """Toplam açık pozisyon değeri"""
        return sum(p.entry_value_usd for p in self.get_open_positions())

    def get_total_unrealized_pnl(self) -> float:
        """Toplam unrealized PnL"""
        return sum(p.unrealized_pnl for p in self.get_open_positions())

    def get_total_realized_pnl(self) -> float:
        """Toplam realized PnL (tüm pozisyonlar)"""
        return sum(p.realized_pnl for p in self._positions.values())

    def get_position_count(self) -> int:
        return len(self._positions)

    def get_open_position_count(self) -> int:
        return len(self.get_open_positions())

    def remove_from_cache(self, position_id: int):
        """Cache'den sil (DB'de kalır)"""
        position = self._positions.pop(position_id, None)
        if position:
            self._positions_by_inst.pop(position.inst_id, None)