"""
Apex Scout - Order Executor
Emir yürütme, takip, retry mantığı.
"""

import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime

from shared.logger import get_logger, get_trading_logger
from shared.exceptions import OrderExecutionError, TradingError
from config.settings import settings
from config.constants import OrderSide
from trading.okx_client import OKXDemoClient
from trading.models import Order, Trade, OrderType, OrderStatus
from trading.position_manager import PositionManager
from trading.risk_manager import RiskManager

log = get_logger(__name__)
trade_log = get_trading_logger()


class OrderExecutor:
    """
    Emir yürütme motoru.
    - Market emirleri (alım/satım)
    - Emir takibi ve fill bekleme
    - Retry mekanizması
    - Trading audit log
    """

    def __init__(
        self,
        okx_client: OKXDemoClient,
        position_manager: PositionManager,
        risk_manager: RiskManager,
    ):
        self.okx = okx_client
        self.position_manager = position_manager
        self.risk_manager = risk_manager
        self._pending_orders: Dict[str, Order] = {}  # cl_ord_id -> Order
        self._order_semaphore = asyncio.Semaphore(3)  # Max 3 eşzamanlı emir

    async def execute_market_buy(
        self,
        inst_id: str,
        quantity: float,
        cl_ord_id: Optional[str] = None,
    ) -> Order:
        """Market alım emri gönder ve fill bekle"""
        return await self._execute_order(
            inst_id=inst_id,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=quantity,
            cl_ord_id=cl_ord_id,
        )

    async def execute_market_sell(
        self,
        inst_id: str,
        quantity: float,
        cl_ord_id: Optional[str] = None,
    ) -> Order:
        """Market satım emri gönder ve fill bekle"""
        return await self._execute_order(
            inst_id=inst_id,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            size=quantity,
            cl_ord_id=cl_ord_id,
        )

    async def execute_stop_loss_order(
        self,
        inst_id: str,
        quantity: float,
        stop_price: float,
        cl_ord_id: Optional[str] = None,
    ) -> Order:
        """Stop-Loss emri gönder (stop-market)"""
        return await self._execute_order(
            inst_id=inst_id,
            side=OrderSide.SELL,
            order_type=OrderType.STOP_MARKET,
            size=quantity,
            price=stop_price,
            cl_ord_id=cl_ord_id,
        )

    async def _execute_order(
        self,
        inst_id: str,
        side: OrderSide,
        order_type: OrderType,
        size: float,
        price: Optional[float] = None,
        cl_ord_id: Optional[str] = None,
    ) -> Order:
        """İç emir yürütme mantığı"""
        async with self._order_semaphore:
            # Client order ID oluştur
            if not cl_ord_id:
                cl_ord_id = f"apex_{inst_id}_{side.value}_{int(datetime.utcnow().timestamp() * 1000)}"

            # Emir oluştur
            order = Order(
                inst_id=inst_id,
                side=side,
                order_type=order_type,
                size=size,
                price=price,
                okx_cl_ord_id=cl_ord_id,
                status=OrderStatus.PENDING,
            )

            # Trading log
            trade_log.info(
                f"ORDER | {side.value.upper()} | {inst_id} | "
                f"Type: {order_type.value} | Size: {size:.6f} | "
                f"Price: {price if price else 'MARKET'} | CID: {cl_ord_id}"
            )

            try:
                # OKX'e gönder
                submitted_order = await self.okx.place_order(
                    inst_id=inst_id,
                    side=side,
                    size=size,
                    order_type=order_type,
                    price=price,
                    cl_ord_id=cl_ord_id,
                )

                # Başarılı gönderim
                order.okx_order_id = submitted_order.okx_order_id
                order.okx_cl_ord_id = submitted_order.okx_cl_ord_id
                order.status = OrderStatus.SUBMITTED

                # Pending'e ekle
                self._pending_orders[cl_ord_id] = order

                # Fill bekle (market emirleri için)
                if order_type == OrderType.MARKET:
                    filled_order = await self._wait_for_fill(cl_ord_id, inst_id)
                    return filled_order

                return order

            except Exception as e:
                order.status = OrderStatus.FAILED
                trade_log.error(f"ORDER FAILED | {cl_ord_id} | {e}")
                raise OrderExecutionError(f"Order execution failed: {e}", {
                    "inst_id": inst_id,
                    "side": side.value,
                    "size": size,
                    "cl_ord_id": cl_ord_id,
                }) from e

    async def _wait_for_fill(self, cl_ord_id: str, inst_id: str, timeout: float = 30.0) -> Order:
        """Emir fill olana kadar bekle (market emirler için)"""
        order = self._pending_orders.get(cl_ord_id)
        if not order:
            raise OrderExecutionError("Order not found in pending", {"cl_ord_id": cl_ord_id})

        start_time = datetime.utcnow()
        check_interval = 0.5  # 500ms

        while (datetime.utcnow() - start_time).total_seconds() < timeout:
            try:
                # OKX'den emir durumunu sorgula
                updated_order = await self.okx.get_order(inst_id=inst_id, cl_ord_id=cl_ord_id)

                # Local order'ı güncelle
                order.status = updated_order.status
                order.filled_size = updated_order.filled_size
                order.avg_fill_price = updated_order.avg_fill_price
                order.fee = updated_order.fee
                order.okx_order_id = updated_order.okx_order_id

                if updated_order.status == OrderStatus.FILLED:
                    order.filled_at = datetime.utcnow()
                    order.status = OrderStatus.FILLED
                    self._pending_orders.pop(cl_ord_id, None)

                    trade_log.info(
                        f"FILL | {order.side.value.upper()} | {inst_id} | "
                        f"Size: {order.filled_size:.6f} | Avg Price: {order.avg_fill_price:.6f} | "
                        f"Fee: {order.fee:.6f} | OID: {order.okx_order_id}"
                    )
                    return order

                elif updated_order.status in (OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FAILED):
                    order.status = updated_order.status
                    self._pending_orders.pop(cl_ord_id, None)
                    raise OrderExecutionError(f"Order {updated_order.status.value}", {
                        "cl_ord_id": cl_ord_id,
                        "inst_id": inst_id,
                    })

                await asyncio.sleep(check_interval)

            except OrderExecutionError:
                raise
            except Exception as e:
                log.warning(f"[OrderExecutor] Fill check error: {e}")
                await asyncio.sleep(check_interval)

        # Timeout
        order.status = OrderStatus.FAILED
        self._pending_orders.pop(cl_ord_id, None)
        raise OrderExecutionError(f"Order fill timeout after {timeout}s", {
            "cl_ord_id": cl_ord_id,
            "inst_id": inst_id,
        })

    async def cancel_order(self, inst_id: str, cl_ord_id: str = None, ord_id: str = None) -> bool:
        """Emir iptal et"""
        try:
            result = await self.okx.cancel_order(inst_id=inst_id, ord_id=ord_id, cl_ord_id=cl_ord_id)
            if cl_ord_id:
                self._pending_orders.pop(cl_ord_id, None)
            trade_log.info(f"CANCEL | {inst_id} | CID: {cl_ord_id} | OID: {ord_id} | Result: {result}")
            return result
        except Exception as e:
            log.error(f"[OrderExecutor] Cancel failed: {e}")
            return False

    async def get_order_status(self, inst_id: str, cl_ord_id: str = None, ord_id: str = None) -> Order:
        """Emir durumu sorgula"""
        return await self.okx.get_order(inst_id=inst_id, ord_id=ord_id, cl_ord_id=cl_ord_id)

    async def sync_pending_orders(self):
        """Bekleyen emirleri OKX ile senkronize et"""
        to_remove = []
        for cl_ord_id, order in self._pending_orders.items():
            try:
                updated = await self.okx.get_order(inst_id=order.inst_id, cl_ord_id=cl_ord_id)
                order.status = updated.status
                order.filled_size = updated.filled_size
                order.avg_fill_price = updated.avg_fill_price
                order.fee = updated.fee

                if updated.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FAILED):
                    to_remove.append(cl_ord_id)

            except Exception as e:
                log.warning(f"[OrderExecutor] Sync failed for {cl_ord_id}: {e}")

        for cid in to_remove:
            self._pending_orders.pop(cid, None)

    def get_pending_orders(self) -> List[Order]:
        """Bekleyen emirler"""
        return list(self._pending_orders.values())

    def clear_pending(self):
        """Bekleyen emirleri temizle (shutdown时)"""
        self._pending_orders.clear()