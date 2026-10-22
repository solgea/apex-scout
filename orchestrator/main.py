"""
Apex Scout - Main Orchestrator
Tüm döngüyü yönetir: Tarama -> Karar -> İşlem -> Pozisyon Takibi
"""

import asyncio
import signal
from dataclasses import dataclass, field
from datetime import datetime

from config.constants import DecisionAction, OrderSide, PositionStatus
from config.settings import settings
from decision.blacklist import BlacklistManager
from decision.engine import DecisionEngine
from scanner.dexscreener import DexScreenerScanner
from scanner.filters import TokenFilter
from scanner.models import TokenData, TokenFilterCriteria
from scanner.pumpfunt import PumpFunScanner
from shared.database import get_session, init_db
from shared.logger import get_logger
from shared.models import Decision, SystemMetrics, Token
from decision.models import DecisionResult
from trading.okx_client import OKXDemoClient
from trading.order_executor import OrderExecutor
from trading.portfolio import PortfolioManager
from trading.position_manager import PositionManager
from trading.risk_manager import RiskManager

log = get_logger(__name__)


@dataclass
class OrchestratorStats:
    """Orchestrator istatistikleri"""

    cycles_completed: int = 0
    cycles_failed: int = 0
    tokens_scanned: int = 0
    tokens_filtered: int = 0
    decisions_pass: int = 0
    decisions_watch: int = 0
    decisions_skip: int = 0
    trades_executed: int = 0
    errors: int = 0
    last_cycle_time: datetime | None = None
    last_cycle_duration_ms: float = 0.0
    start_time: datetime = field(default_factory=datetime.utcnow)


class Orchestrator:
    """
    Ana orkestratör.
    - Periyodik tarama döngüsü
    - Hata toleranslı (retry, circuit breaker)
    - Graceful shutdown
    - Durum kaydetme
    """

    def __init__(self):
        self.stats = OrchestratorStats()
        self._running = False
        self._paused = False
        self._shutdown_event = asyncio.Event()
        self._main_task: asyncio.Task | None = None

        # Bileşenler (lazy init)
        self._dex_scanner: DexScreenerScanner | None = None
        self._pump_scanner: PumpFunScanner | None = None
        self._token_filter: TokenFilter | None = None
        self._decision_engine: DecisionEngine | None = None
        self._blacklist: BlacklistManager | None = None
        self._okx_client: OKXDemoClient | None = None
        self._position_manager: PositionManager | None = None
        self._risk_manager: RiskManager | None = None
        self._order_executor: OrderExecutor | None = None
        self._portfolio: PortfolioManager | None = None

        # Metrik delta takibi (per-cycle değerler için)
        self._last_metrics_saved = {
            "tokens_scanned": 0,
            "tokens_filtered": 0,
            "decisions_pass": 0,
            "decisions_watch": 0,
            "decisions_skip": 0,
            "trades_executed": 0,
            "errors": 0,
        }

        # Sinyal handler
        self._setup_signals()

    def _setup_signals(self):
        """Sinyal handler'ları kur"""
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._signal_handler)
        except NotImplementedError:
            # Windows'ta signal handler farklı çalışabilir
            pass

    def _signal_handler(self):
        """Shutdown sinyali alındığında"""
        log.info("Shutdown signal received, initiating graceful shutdown...")
        self._shutdown_event.set()

    # ============ INITIALIZATION ============

    async def initialize(self):
        """Tüm bileşenleri başlat"""
        log.info("Initializing Apex Scout components...")

        # DB
        init_db()

        # Scanner
        filter_criteria = TokenFilterCriteria(
            min_liquidity_usd=settings.min_liquidity_usd,
            max_age_hours=settings.max_token_age_hours,
            min_volume_24h=settings.min_volume_24h,
        )
        self._token_filter = TokenFilter(filter_criteria)
        self._dex_scanner = DexScreenerScanner(filter_criteria)
        self._pump_scanner = PumpFunScanner(filter_criteria)

        # Decision
        self._decision_engine = DecisionEngine()
        self._blacklist = BlacklistManager()

        # Trading
        self._okx_client = OKXDemoClient()
        await self._okx_client.__aenter__()

        self._risk_manager = RiskManager()
        self._position_manager = PositionManager(self._risk_manager)
        self._order_executor = OrderExecutor(
            self._okx_client, self._position_manager, self._risk_manager
        )
        self._portfolio = PortfolioManager(self._okx_client, self._position_manager)

        # DB'den açık pozisyonları yükle
        self._position_manager.load_from_db()

        # Portföy başlat
        await self._portfolio.initialize()

        # OKX instrument listesini yükle (hangi token'lar trade edilebilir)
        await self._okx_client.refresh_instruments()

        # Pump.fun WebSocket başlat (opsiyonel)
        # await self._pump_scanner.start_websocket(self._on_new_pumpfunt_token)

        log.info("All components initialized successfully")

    async def cleanup(self):
        """Temizlik"""
        log.info("Cleaning up...")

        if self._okx_client:
            await self._okx_client.close()

        if self._pump_scanner:
            await self._pump_scanner.close()

        if self._dex_scanner:
            await self._dex_scanner.close()

        log.info("Cleanup complete")

    # ============ MAIN LOOP ============

    async def run(self):
        """Ana döngüyü başlat"""
        if self._running:
            log.warning("Orchestrator already running")
            return

        await self.initialize()
        self._running = True
        self._shutdown_event.clear()

        log.info("Starting Apex Scout main loop...")
        self._main_task = asyncio.create_task(self._main_loop())

        try:
            await self._main_task
        except asyncio.CancelledError:
            log.info("Main loop cancelled")
        except Exception as e:
            log.error(f"Main loop error: {e}")
            self.stats.cycles_failed += 1
            self.stats.errors += 1
        finally:
            self._running = False
            await self.cleanup()

    async def _main_loop(self):
        """Ana tarama döngüsü"""
        while not self._shutdown_event.is_set():
            cycle_start = datetime.utcnow()

            try:
                if not self._paused:
                    await self._run_cycle()
                else:
                    log.debug("Orchestrator paused, skipping cycle")
                    await asyncio.sleep(5)

            except Exception as e:
                self.stats.cycles_failed += 1
                self.stats.errors += 1
                log.error(f"Cycle error: {e}", exc_info=True)
                # Hata durumunda kısa bekle
                await asyncio.sleep(10)

            # İstatistikleri güncelle
            cycle_end = datetime.utcnow()
            self.stats.last_cycle_time = cycle_end
            self.stats.last_cycle_duration_ms = (cycle_end - cycle_start).total_seconds() * 1000

            # Bekleme süresi (interval - cycle_duration)
            elapsed = self.stats.last_cycle_duration_ms / 1000
            sleep_time = max(1, settings.scan_interval_seconds - elapsed)

            if not self._shutdown_event.is_set():
                await asyncio.sleep(sleep_time)

    async def _run_cycle(self):
        """Tek bir tarama döngüsü"""
        cycle_start = datetime.utcnow()
        log.info("=" * 50)
        log.info("Starting new scan cycle")

        # 1. SCAN - Token'ları tara
        tokens = await self._scan_tokens()
        self.stats.tokens_scanned += len(tokens)
        log.info(f"Scan complete: {len(tokens)} tokens after filtering")

        if not tokens:
            log.info("No tokens passed filters, skipping decision/trading")
            await self._monitor_positions()
            return

        # 2. DECISION - Token'ları skorla
        decisions = await self._evaluate_decisions(tokens)
        pass_tokens = [d for d in decisions if d.action == DecisionAction.PASS]
        watch_tokens = [d for d in decisions if d.action == DecisionAction.WATCH]

        self.stats.decisions_pass += len(pass_tokens)
        self.stats.decisions_watch += len(watch_tokens)
        self.stats.decisions_skip += len([d for d in decisions if d.action == DecisionAction.SKIP])

        log.info(
            f"Decisions: PASS={len(pass_tokens)}, WATCH={len(watch_tokens)}, SKIP={self.stats.decisions_skip}"
        )

        # 3. TRADE - PASS token'ları için işlem aç
        if pass_tokens:
            trades = await self._execute_trades(pass_tokens)
            self.stats.trades_executed += trades
            log.info(f"Executed {trades} new trades")

        # 4. MONITOR - Pozisyonları takip et (TP/SL/Trailing)
        await self._monitor_positions()

        # 5. PERSIST - Metrikleri kaydet
        await self._save_metrics()

        self.stats.cycles_completed += 1

        cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
        log.info(f"Cycle complete in {cycle_duration:.2f}s")

    # ============ SCAN ============

    async def _scan_tokens(self) -> list[Token]:
        """Her iki kaynaktan token tara ve birleştir"""
        all_tokens = []

        # DexScreener
        try:
            dex_tokens = await self._dex_scanner.scan()
            all_tokens.extend(dex_tokens)
            log.debug(f"DexScreener: {len(dex_tokens)} tokens")
        except Exception as e:
            log.error(f"DexScreener scan error: {e}")
            self.stats.errors += 1

        # Pump.fun
        try:
            pump_tokens = await self._pump_scanner.scan()
            all_tokens.extend(pump_tokens)
            log.debug(f"Pump.fun: {len(pump_tokens)} tokens")
        except Exception as e:
            log.error(f"Pump.fun scan error: {e}")
            self.stats.errors += 1

        # Deduplicate (address bazında)
        seen = set()
        unique_tokens = []
        for token in all_tokens:
            if token.address not in seen:
                seen.add(token.address)
                unique_tokens.append(token)

        # Filtrele
        filtered = self._token_filter.filter_tokens(unique_tokens)
        self.stats.tokens_filtered = len(filtered)

        return filtered  # type: ignore[return-value]

    # ============ DECISION ============

    async def _evaluate_decisions(self, tokens: list[TokenData]) -> list[DecisionResult]:
        """Token'ları değerlendir"""
        results = self._decision_engine.evaluate_batch(tokens)

        # Sonuçları DB'ye kaydet
        with get_session() as session:
            for result in results.results:
                # Token'ı kaydet/güncelle
                db_token = (
                    session.query(Token).filter(Token.address == result.token.address).first()
                )
                if not db_token:
                    db_token = Token(
                        address=result.token.address,
                        name=result.token.name,
                        symbol=result.token.symbol,
                        liquidity_usd=result.token.liquidity_usd,
                        market_cap=result.token.market_cap,
                        volume_24h=result.token.volume_24h,
                        price_usd=result.token.price_usd,
                        age_seconds=result.token.age_seconds,
                        mint_authority=result.token.mint_authority,
                        freeze_authority=result.token.freeze_authority,
                        mint_renounced=result.token.mint_renounced,
                        freeze_renounced=result.token.freeze_renounced,
                        holder_count=result.token.holder_count,
                        top_10_holder_pct=result.token.top_10_holder_pct,
                        source=result.token.source,
                    )
                    session.add(db_token)
                    session.flush()
                else:
                    # Güncelle
                    db_token.liquidity_usd = result.token.liquidity_usd
                    db_token.market_cap = result.token.market_cap
                    db_token.volume_24h = result.token.volume_24h
                    db_token.price_usd = result.token.price_usd
                    db_token.last_updated = datetime.utcnow()

                # Kararı kaydet
                decision = Decision(
                    token_id=db_token.id,
                    score=result.score,
                    action=result.action.value,
                    reasons=result.reasons,
                    score_liquidity=result.breakdown.liquidity,
                    score_volume=result.breakdown.volume,
                    score_age=result.breakdown.age,
                    score_mcap=result.breakdown.mcap,
                    score_mint_freeze=result.breakdown.mint_freeze,
                    score_holder_dist=result.breakdown.holder_dist,
                )
                session.add(decision)

            session.commit()

        return results.results

    # ============ TRADE ============

    async def _execute_trades(self, pass_decisions: list) -> int:
        """PASS kararları için işlem aç"""
        executed = 0

        for decision in pass_decisions:
            try:
                # Risk kontrolleri
                open_positions = self._position_manager.get_open_positions()
                portfolio_snapshot = await self._portfolio.get_snapshot()

                # Max pozisyon kontrolü
                risk_check = self._risk_manager.check_max_positions(open_positions)
                if not risk_check.allowed:
                    log.warning(f"Max positions reached, skipping {decision.token.symbol}")
                    continue

                # Portföy risk kontrolü
                token = decision.token

                # OKX'te listelenmiş mi kontrol et (listelenmemişse işlem yapılamaz)
                inst_id = await self._okx_client.find_instrument(token.symbol)
                if not inst_id:
                    log.debug(f"[Trade] {token.symbol} not listed on OKX, skipping")
                    continue

                # Fiyat al
                try:
                    current_price = await self._okx_client.get_price(inst_id)
                    if current_price <= 0:
                        log.warning(f"Invalid price for {inst_id}, skipping")
                        continue
                except Exception as e:
                    log.warning(f"Price fetch failed for {inst_id}: {e}")
                    continue

                # Pozisyon boyutu hesapla
                quantity, position_value = self._risk_manager.calculate_position_size(
                    portfolio_snapshot.available_balance,
                    current_price,
                )

                # Portföy risk kontrolü
                risk_check = self._risk_manager.check_portfolio_risk(
                    open_positions,
                    position_value,
                    portfolio_snapshot.total_value_usd,
                )
                if not risk_check.allowed:
                    log.warning(
                        f"Portfolio risk limit, skipping {token.symbol}: {risk_check.reason}"
                    )
                    continue

                # Pozisyon boyutu kontrolü
                risk_check = self._risk_manager.check_position_size(
                    position_value, portfolio_snapshot.available_balance
                )
                if not risk_check.allowed:
                    log.warning(
                        f"Position size limit, skipping {token.symbol}: {risk_check.reason}"
                    )
                    continue

                # SL/TP hesapla
                sl_price = self._risk_manager.create_stop_loss_price(current_price, OrderSide.BUY)
                tp_tiers = self._risk_manager.create_take_profit_tiers(current_price, OrderSide.BUY)

                # TP tiers'ları dict formatına çevir
                tp_tiers_dict = [
                    {"profit_pct": t.profit_pct, "sell_pct": t.sell_pct, "triggered": False}
                    for t in tp_tiers
                ]

                # Market buy emri gönder
                order = await self._order_executor.execute_market_buy(
                    inst_id=inst_id,
                    quantity=quantity,
                )

                if order.status.value == "FILLED":
                    # Pozisyon oluştur
                    fill_price = order.avg_fill_price
                    fill_qty = order.filled_size

                    # SL/TP fiyatlarını fill price'a göre yeniden hesapla
                    sl_price = self._risk_manager.create_stop_loss_price(fill_price, OrderSide.BUY)
                    tp_tiers = self._risk_manager.create_take_profit_tiers(
                        fill_price, OrderSide.BUY
                    )
                    tp_tiers_dict = [
                        {"profit_pct": t.profit_pct, "sell_pct": t.sell_pct, "triggered": False}
                        for t in tp_tiers
                    ]

                    self._position_manager.create_position(
                        token_id=decision.token.id if hasattr(decision.token, "id") else None,
                        inst_id=inst_id,
                        side=OrderSide.BUY,
                        entry_price=fill_price,
                        quantity=fill_qty,
                        stop_loss_price=sl_price,
                        take_profit_tiers=tp_tiers_dict,
                        okx_order_id=order.okx_order_id,
                    )

                    # Stop-Loss emri de gönder (opsiyonel - OKX stop order)
                    # await self._order_executor.execute_stop_loss_order(inst_id, fill_qty, sl_price)

                    executed += 1
                    log.info(f"Position opened: {token.symbol} {fill_qty:.6f} @ {fill_price:.6f}")
                else:
                    log.warning(f"Order not filled for {token.symbol}: {order.status}")

            except Exception as e:
                log.error(f"Trade execution failed for {decision.token.symbol}: {e}")
                self.stats.errors += 1

        return executed

    # ============ MONITOR ============

    async def _monitor_positions(self):
        """Açık pozisyonları takip et: TP/SL/Trailing kontrolü"""
        open_positions = self._position_manager.get_open_positions()
        if not open_positions:
            return

        # Güncel fiyatları topla
        inst_ids = [p.inst_id for p in open_positions]
        prices = {}

        for inst_id in inst_ids:
            try:
                price = await self._okx_client.get_price(inst_id)
                prices[inst_id] = price
            except Exception as e:
                log.warning(f"Price fetch failed for {inst_id}: {e}")

        # Fiyatları güncelle
        self._position_manager.update_prices_batch(prices)

        # Her pozisyon için çıkış koşullarını kontrol et
        for position in open_positions:
            current_price = prices.get(position.inst_id)
            if current_price is None:
                continue

            # Risk manager'dan çıkış koşullarını kontrol et
            action, trigger_price, tp_tier = self._risk_manager.check_exit_conditions(
                position, current_price
            )

            if action == "STOP_LOSS":
                await self._handle_stop_loss(position, trigger_price)
            elif action == "TAKE_PROFIT":
                await self._handle_take_profit(position, tp_tier, trigger_price)
            elif action == "TRAILING_STOP":
                await self._handle_trailing_stop(position, trigger_price)

        # Pending emirleri senkronize et
        await self._order_executor.sync_pending_orders()

    async def _handle_stop_loss(self, position, trigger_price: float):
        """Stop-Loss tetiklendi"""
        log.warning(f"STOP LOSS triggered for {position.inst_id} at {trigger_price:.6f}")

        # Market sat emri
        remaining_qty = position.get_remaining_quantity()
        if remaining_qty > 0:
            order = await self._order_executor.execute_market_sell(
                inst_id=position.inst_id,
                quantity=remaining_qty,
            )

            if order.status.value == "FILLED":
                self._position_manager.apply_sl_fill(
                    position.id,
                    order.avg_fill_price,
                    order.filled_size,
                )

                # Blacklist'e ekle
                if position.token_id:
                    from shared.database import get_session
                    from shared.models import Token as DBToken

                    with get_session() as session:
                        token = (
                            session.query(DBToken).filter(DBToken.id == position.token_id).first()
                        )
                        if token:
                            self._blacklist.add(token.address, token.symbol, "STOP_LOSS_HIT")

                log.info(f"Stop-Loss executed for {position.inst_id}")

    async def _handle_take_profit(self, position, tp_tier_index: int, trigger_price: float):
        """Take-Profit tetiklendi"""
        tier = position.take_profit_tiers[tp_tier_index]
        sell_pct = tier["sell_pct"]
        sell_qty = position.quantity * (sell_pct / 100)

        log.info(
            f"TAKE PROFIT TP{tp_tier_index+1} triggered for {position.inst_id} at {trigger_price:.6f}, selling {sell_pct}%"
        )

        order = await self._order_executor.execute_market_sell(
            inst_id=position.inst_id,
            quantity=sell_qty,
        )

        if order.status.value == "FILLED":
            self._position_manager.apply_tp_fill(
                position.id,
                tp_tier_index,
                order.avg_fill_price,
                order.filled_size,
            )
            log.info(f"Take-Profit TP{tp_tier_index+1} executed for {position.inst_id}")

    async def _handle_trailing_stop(self, position, trigger_price: float):
        """Trailing Stop tetiklendi"""
        log.warning(f"TRAILING STOP triggered for {position.inst_id} at {trigger_price:.6f}")

        remaining_qty = position.get_remaining_quantity()
        if remaining_qty > 0:
            order = await self._order_executor.execute_market_sell(
                inst_id=position.inst_id,
                quantity=remaining_qty,
            )

            if order.status.value == "FILLED":
                self._position_manager.apply_trailing_fill(
                    position.id,
                    order.avg_fill_price,
                    order.filled_size,
                )
                log.info(f"Trailing Stop executed for {position.inst_id}")

    # ============ METRICS ============

    async def _save_metrics(self):
        """
        Sistem metriklerini kaydet.
        NOT: Her satır PER-CYCLE değerleri tutar (delta), kümülatif değil.
        Böylece dashboard'da zaman serisi doğru grafiklenir.
        """
        try:
            portfolio = await self._portfolio.get_snapshot()
            open_positions = self._position_manager.get_open_positions()

            # Önceki kayıttan farkı al (per-cycle delta)
            prev = self._last_metrics_saved
            delta_tokens = max(0, self.stats.tokens_scanned - prev["tokens_scanned"])
            delta_filtered = max(0, self.stats.tokens_filtered - prev["tokens_filtered"])
            delta_pass = max(0, self.stats.decisions_pass - prev["decisions_pass"])
            delta_watch = max(0, self.stats.decisions_watch - prev["decisions_watch"])
            delta_skip = max(0, self.stats.decisions_skip - prev["decisions_skip"])
            delta_trades = max(0, self.stats.trades_executed - prev["trades_executed"])
            delta_errors = max(0, self.stats.errors - prev["errors"])

            # Kümülatif sayaçları güncelle
            self._last_metrics_saved = {
                "tokens_scanned": self.stats.tokens_scanned,
                "tokens_filtered": self.stats.tokens_filtered,
                "decisions_pass": self.stats.decisions_pass,
                "decisions_watch": self.stats.decisions_watch,
                "decisions_skip": self.stats.decisions_skip,
                "trades_executed": self.stats.trades_executed,
                "errors": self.stats.errors,
            }

            metrics = SystemMetrics(
                scan_count=1,
                tokens_found=delta_tokens,
                tokens_filtered=delta_filtered,
                tokens_scored=delta_pass + delta_watch + delta_skip,
                decisions_pass=delta_pass,
                decisions_watch=delta_watch,
                decisions_skip=delta_skip,
                trades_executed=delta_trades,
                trades_failed=0,
                positions_opened=len(
                    [p for p in open_positions if p.status == PositionStatus.OPEN]
                ),
                positions_closed=0,
                errors_count=delta_errors,
                api_latency_ms=0,  # TODO: measure
                scanner_latency_ms=0,
                decision_latency_ms=0,
                trading_latency_ms=0,
                total_portfolio_value=portfolio.total_value_usd,
                available_balance=portfolio.available_balance,
                risk_exposure_pct=portfolio.risk_exposure_pct,
            )

            with get_session() as session:
                session.add(metrics)
                session.commit()

        except Exception as e:
            log.error(f"Metrics save failed: {e}")

    # ============ CONTROL ============

    def pause(self):
        """Döngüyü duraklat"""
        self._paused = True
        log.info("Orchestrator paused")

    def resume(self):
        """Döngüyü devam ettir"""
        self._paused = False
        log.info("Orchestrator resumed")

    def stop(self):
        """Döngüyü durdur"""
        self._shutdown_event.set()
        log.info("Orchestrator stop requested")

    def get_status(self) -> dict:
        """Durum bilgisi"""
        return {
            "running": self._running,
            "paused": self._paused,
            "stats": {
                "cycles_completed": self.stats.cycles_completed,
                "cycles_failed": self.stats.cycles_failed,
                "tokens_scanned": self.stats.tokens_scanned,
                "tokens_filtered": self.stats.tokens_filtered,
                "decisions_pass": self.stats.decisions_pass,
                "decisions_watch": self.stats.decisions_watch,
                "decisions_skip": self.stats.decisions_skip,
                "trades_executed": self.stats.trades_executed,
                "errors": self.stats.errors,
                "last_cycle_time": (
                    self.stats.last_cycle_time.isoformat() if self.stats.last_cycle_time else None
                ),
                "last_cycle_duration_ms": self.stats.last_cycle_duration_ms,
                "uptime_seconds": (datetime.utcnow() - self.stats.start_time).total_seconds(),
            },
            "positions": {
                "open": (
                    self._position_manager.get_open_position_count()
                    if self._position_manager
                    else 0
                ),
                "total": (
                    self._position_manager.get_position_count() if self._position_manager else 0
                ),
            },
        }
