"""
Apex Scout - Portfolio Manager
Portföy takibi, bakiye yönetimi, performans metrikleri.
"""

from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

from shared.logger import get_logger
from shared.database import get_session
from shared.models import Position as DBPosition, Trade as DBTrade, SystemMetrics
from config.settings import settings
from config.constants import PositionStatus
from trading.models import PortfolioSnapshot
from trading.position_manager import PositionManager
from trading.okx_client import OKXDemoClient

log = get_logger(__name__)


@dataclass
class PerformanceMetrics:
    """Performans metrikleri"""
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0


class PortfolioManager:
    """
    Portföy yönetimi.
    - Bakiye takibi
    - Performans hesaplama
    - Günlük/haftalık özet
    - Risk exposure
    """

    def __init__(
        self,
        okx_client: OKXDemoClient,
        position_manager: PositionManager,
    ):
        self.okx = okx_client
        self.position_manager = position_manager
        self._initial_balance: Optional[float] = None
        self._peak_balance: float = 0.0
        self._daily_start_balance: Optional[float] = None
        self._daily_start_date: Optional[datetime] = None

    async def initialize(self):
        """Başlangıç bakiyesini al"""
        self._initial_balance = await self.okx.get_available_balance("USDT")
        self._peak_balance = self._initial_balance
        self._daily_start_balance = self._initial_balance
        self._daily_start_date = datetime.utcnow().date()
        log.info(f"[Portfolio] Initialized with balance: ${self._initial_balance:.2f}")

    async def get_snapshot(self) -> PortfolioSnapshot:
        """Anlık portföy görüntüsü"""
        available = await self.okx.get_available_balance("USDT")
        open_positions = self.position_manager.get_open_positions()
        locked = sum(p.entry_value_usd for p in open_positions)
        unrealized = sum(p.unrealized_pnl for p in open_positions)
        realized_24h = self.get_realized_pnl_24h()

        total_value = available + locked + unrealized
        risk_pct = (locked / total_value * 100) if total_value > 0 else 0

        # Peak güncelle
        if total_value > self._peak_balance:
            self._peak_balance = total_value

        # Günlük reset kontrolü
        today = datetime.utcnow().date()
        if self._daily_start_date != today:
            self._daily_start_balance = total_value
            self._daily_start_date = today

        return PortfolioSnapshot(
            total_value_usd=total_value,
            available_balance=available,
            locked_balance=locked,
            unrealized_pnl=unrealized,
            realized_pnl_24h=realized_24h,
            open_positions_count=len(open_positions),
            risk_exposure_pct=risk_pct,
            timestamp=datetime.utcnow(),
        )

    def get_realized_pnl_24h(self) -> float:
        """Son 24 saatteki realized PnL"""
        cutoff = datetime.utcnow() - timedelta(hours=24)
        with get_session() as session:
            trades = session.query(DBTrade).filter(
                DBTrade.timestamp >= cutoff
            ).all()

            pnl = 0.0
            for trade in trades:
                # Trade PnL hesapla (basit: sell - buy)
                # Gerçekte position'dan hesaplanmalı
                pos = session.query(DBPosition).filter(DBPosition.id == trade.position_id).first()
                if pos:
                    if trade.side == "sell" and pos.side == "buy":
                        pnl += (trade.price - pos.entry_price) * trade.quantity
                    elif trade.side == "buy" and pos.side == "sell":
                        pnl += (pos.entry_price - trade.price) * trade.quantity
            return pnl

    def get_performance_metrics(self) -> PerformanceMetrics:
        """Tüm geçmişe dayalı performans metrikleri"""
        with get_session() as session:
            trades = session.query(DBTrade).all()
            positions = session.query(DBPosition).all()

            if not trades:
                return PerformanceMetrics()

            # Trade bazlı PnL hesapla
            trade_pnls = []
            for trade in trades:
                pos = session.query(DBPosition).filter(DBPosition.id == trade.position_id).first()
                if pos:
                    if trade.side == "sell" and pos.side == "buy":
                        pnl = (trade.price - pos.entry_price) * trade.quantity
                    elif trade.side == "buy" and pos.side == "sell":
                        pnl = (pos.entry_price - trade.price) * trade.quantity
                    else:
                        pnl = 0
                    trade_pnls.append(pnl)

            if not trade_pnls:
                return PerformanceMetrics()

            total_trades = len(trade_pnls)
            winning = [p for p in trade_pnls if p > 0]
            losing = [p for p in trade_pnls if p < 0]

            winning_trades = len(winning)
            losing_trades = len(losing)
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

            total_pnl = sum(trade_pnls)
            realized_pnl = sum(p.realized_pnl for p in positions)
            unrealized_pnl = sum(p.unrealized_pnl for p in positions if p.status == PositionStatus.OPEN)

            best_trade = max(trade_pnls) if trade_pnls else 0
            worst_trade = min(trade_pnls) if trade_pnls else 0
            avg_win = sum(winning) / winning_trades if winning_trades > 0 else 0
            avg_loss = sum(losing) / losing_trades if losing_trades > 0 else 0

            gross_profit = sum(winning)
            gross_loss = abs(sum(losing))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

            # Max drawdown
            equity_curve = []
            running = 0
            for pnl in trade_pnls:
                running += pnl
                equity_curve.append(running)

            max_dd = 0
            peak = equity_curve[0] if equity_curve else 0
            for val in equity_curve:
                if val > peak:
                    peak = val
                dd = peak - val
                if dd > max_dd:
                    max_dd = dd

            return PerformanceMetrics(
                total_pnl=total_pnl,
                total_pnl_pct=(total_pnl / self._initial_balance * 100) if self._initial_balance else 0,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                win_rate=win_rate,
                total_trades=total_trades,
                winning_trades=winning_trades,
                losing_trades=losing_trades,
                best_trade=best_trade,
                worst_trade=worst_trade,
                avg_win=avg_win,
                avg_loss=avg_loss,
                profit_factor=profit_factor if profit_factor != float('inf') else 0,
                max_drawdown=max_dd,
            )

    def get_daily_pnl(self) -> float:
        """Günlük PnL"""
        if self._daily_start_balance is None:
            return 0.0
        # Bu basit bir implementasyon, gerçekte snapshot'tan alınmalı
        return 0.0  # TODO: Implement properly

    def get_trade_history(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """İşlem geçmişi"""
        with get_session() as session:
            trades = session.query(DBTrade).order_by(DBTrade.timestamp.desc()).offset(offset).limit(limit).all()

            result = []
            for trade in trades:
                pos = session.query(DBPosition).filter(DBPosition.id == trade.position_id).first()
                token = session.query(DBPosition).filter(DBPosition.id == trade.position_id).first()
                # Token bilgisini al
                token_sym = "N/A"
                if pos and pos.token_id:
                    from shared.models import Token as DBToken
                    tok = session.query(DBToken).filter(DBToken.id == pos.token_id).first()
                    if tok:
                        token_sym = tok.symbol

                result.append({
                    "id": trade.id,
                    "timestamp": trade.timestamp.isoformat(),
                    "symbol": token_sym,
                    "inst_id": trade.inst_id,
                    "side": trade.side,
                    "price": trade.price,
                    "quantity": trade.quantity,
                    "fee": trade.fee,
                    "is_take_profit": trade.is_take_profit,
                    "is_stop_loss": trade.is_stop_loss,
                    "is_trailing_stop": trade.is_trailing_stop,
                    "tp_tier_index": trade.tp_tier_index,
                })
            return result

    def get_open_positions_summary(self) -> List[Dict]:
        """Açık pozisyonlar özeti"""
        positions = self.position_manager.get_open_positions()
        return [
            {
                "id": p.id,
                "inst_id": p.inst_id,
                "side": p.side.value,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
                "quantity": p.quantity,
                "entry_value_usd": p.entry_value_usd,
                "unrealized_pnl": p.unrealized_pnl,
                "unrealized_pnl_pct": p.unrealized_pnl_pct,
                "realized_pnl": p.realized_pnl,
                "stop_loss_price": p.stop_loss_price,
                "trailing_stop_price": p.trailing_stop_price,
                "current_tp_tier": p.current_tp_tier,
                "take_profit_tiers": p.take_profit_tiers,
                "status": p.status,
                "opened_at": p.opened_at.isoformat() if p.opened_at else None,
            }
            for p in positions
        ]

    def save_metrics(self, metrics: Dict):
        """Sistem metriklerini kaydet"""
        try:
            with get_session() as session:
                m = SystemMetrics(**metrics)
                session.add(m)
                session.commit()
        except Exception as e:
            log.error(f"[Portfolio] Metrics save failed: {e}")

    def get_equity_curve(self, hours: int = 24) -> List[Dict]:
        """Eğri verisi (son N saat)"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        with get_session() as session:
            metrics = session.query(SystemMetrics).filter(
                SystemMetrics.timestamp >= cutoff
            ).order_by(SystemMetrics.timestamp.asc()).all()

            return [
                {
                    "timestamp": m.timestamp.isoformat(),
                    "total_value": m.total_portfolio_value,
                    "available": m.available_balance,
                    "risk_pct": m.risk_exposure_pct,
                }
                for m in metrics
            ]