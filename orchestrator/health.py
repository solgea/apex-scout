"""
Apex Scout - Health Monitor
Sistem sağlık kontrolü, metrik toplama, alerting.
"""

import asyncio
import psutil
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field

from shared.logger import get_logger
from shared.database import get_session
from shared.models import SystemMetrics
from config.settings import settings

log = get_logger(__name__)


@dataclass
class HealthStatus:
    """Sağlık durumu"""
    healthy: bool = True
    checks: Dict[str, bool] = field(default_factory=dict)
    messages: Dict[str, str] = field(default_factory=dict)
    last_check: Optional[datetime] = None
    issues: list = field(default_factory=list)


class HealthMonitor:
    """
    Sistem sağlık izleme.
    - API bağlantıları
    - Veritabanı
    - Disk/CPU/Memory
    - Hata oranları
    - Pozisyon riskleri
    """

    def __init__(self):
        self._checks: Dict[str, Callable[[], Awaitable[tuple[bool, str]]]] = {}
        self._alert_callbacks: list[Callable[[HealthStatus], Awaitable[None]]] = []
        self._last_status = HealthStatus()
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False

        # Varsayılan check'leri ekle
        self._register_default_checks()

    def _register_default_checks(self):
        """Varsayılan sağlık kontrolleri"""
        self.add_check("database", self._check_database)
        self.add_check("disk_space", self._check_disk_space)
        self.add_check("memory", self._check_memory)
        self.add_check("cpu", self._check_cpu)
        self.add_check("error_rate", self._check_error_rate)

    def add_check(self, name: str, check_func: Callable[[], Awaitable[tuple[bool, str]]]):
        """Sağlık kontrolü ekle"""
        self._checks[name] = check_func
        log.debug(f"[Health] Added check: {name}")

    def add_alert_callback(self, callback: Callable[[HealthStatus], Awaitable[None]]):
        """Alert callback ekle"""
        self._alert_callbacks.append(callback)

    async def start(self, interval: int = None):
        """Monitoring başlat"""
        interval = interval or settings.heartbeat_interval
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval))
        log.info(f"[Health] Monitoring started (interval: {interval}s)")

    async def stop(self):
        """Monitoring durdur"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        log.info("[Health] Monitoring stopped")

    async def _monitor_loop(self, interval: int):
        """Ana monitoring döngüsü"""
        while self._running:
            try:
                await self.run_checks()
            except Exception as e:
                log.error(f"[Health] Monitor loop error: {e}")
            await asyncio.sleep(interval)

    async def run_checks(self) -> HealthStatus:
        """Tüm check'leri çalıştır"""
        status = HealthStatus()
        status.last_check = datetime.utcnow()

        for name, check_func in self._checks.items():
            try:
                healthy, message = await check_func()
                status.checks[name] = healthy
                status.messages[name] = message
                if not healthy:
                    status.healthy = False
                    status.issues.append(f"{name}: {message}")
            except Exception as e:
                status.checks[name] = False
                status.messages[name] = f"Check failed: {e}"
                status.healthy = False
                status.issues.append(f"{name}: Check exception - {e}")

        self._last_status = status

        # Alert callback'lerini çağır
        if not status.healthy:
            for callback in self._alert_callbacks:
                try:
                    await callback(status)
                except Exception as e:
                    log.error(f"[Health] Alert callback failed: {e}")

        return status

    def get_status(self) -> HealthStatus:
        """Son durum"""
        return self._last_status

    def is_healthy(self) -> bool:
        """Sistem sağlıklı mı?"""
        return self._last_status.healthy

    # ============ DEFAULT CHECKS ============

    async def _check_database(self) -> tuple[bool, str]:
        """Veritabanı bağlantısı"""
        try:
            with get_session() as session:
                session.execute("SELECT 1")
            return True, "Database connection OK"
        except Exception as e:
            return False, f"Database connection failed: {e}"

    async def _check_disk_space(self) -> tuple[bool, str]:
        """Disk alanı"""
        try:
            disk = psutil.disk_usage(".")
            free_gb = disk.free / (1024**3)
            total_gb = disk.total / (1024**3)
            pct_used = (disk.used / disk.total) * 100

            if pct_used > 90:
                return False, f"Disk usage critical: {pct_used:.1f}% ({free_gb:.1f}GB free of {total_gb:.1f}GB)"
            elif pct_used > 80:
                return True, f"Disk usage warning: {pct_used:.1f}% ({free_gb:.1f}GB free)"
            return True, f"Disk OK: {pct_used:.1f}% used ({free_gb:.1f}GB free)"
        except Exception as e:
            return False, f"Disk check failed: {e}"

    async def _check_memory(self) -> tuple[bool, str]:
        """Memory kullanımı"""
        try:
            mem = psutil.virtual_memory()
            pct_used = mem.percent

            if pct_used > 90:
                return False, f"Memory critical: {pct_used:.1f}% used"
            elif pct_used > 80:
                return True, f"Memory warning: {pct_used:.1f}% used"
            return True, f"Memory OK: {pct_used:.1f}% used"
        except Exception as e:
            return False, f"Memory check failed: {e}"

    async def _check_cpu(self) -> tuple[bool, str]:
        """CPU kullanımı"""
        try:
            pct = psutil.cpu_percent(interval=1)
            if pct > 90:
                return False, f"CPU critical: {pct:.1f}%"
            elif pct > 80:
                return True, f"CPU warning: {pct:.1f}%"
            return True, f"CPU OK: {pct:.1f}%"
        except Exception as e:
            return False, f"CPU check failed: {e}"

    async def _check_error_rate(self) -> tuple[bool, str]:
        """Son hatalar oranı"""
        try:
            with get_session() as session:
                cutoff = datetime.utcnow() - timedelta(minutes=10)
                recent = session.query(SystemMetrics).filter(
                    SystemMetrics.timestamp >= cutoff
                ).order_by(SystemMetrics.timestamp.desc()).limit(10).all()

                if not recent:
                    return True, "No recent metrics"

                total_errors = sum(m.errors_count for m in recent)
                total_scans = sum(m.scan_count for m in recent)

                if total_scans == 0:
                    return True, "No scans in recent period"

                error_rate = (total_errors / total_scans) * 100 if total_scans > 0 else 0

                if error_rate > 50:
                    return False, f"Error rate critical: {error_rate:.1f}% ({total_errors}/{total_scans})"
                elif error_rate > 20:
                    return True, f"Error rate warning: {error_rate:.1f}%"
                return True, f"Error rate OK: {error_rate:.1f}%"
        except Exception as e:
            return False, f"Error rate check failed: {e}"

    # ============ CUSTOM CHECKS (to be added by orchestrator) ============

    def register_api_check(self, name: str, client_getter: Callable[[], Any]):
        """API sağlık kontrolü kaydet (OKX vb.)"""
        async def check():
            try:
                client = client_getter()
                if hasattr(client, 'health_check'):
                    healthy = await client.health_check()
                    return healthy, f"{name} API {'OK' if healthy else 'FAILED'}"
                return True, f"{name} API check not implemented"
            except Exception as e:
                return False, f"{name} API check failed: {e}"

        self.add_check(name, check)

    def register_position_risk_check(self, portfolio_getter: Callable[[], Awaitable[Any]]):
        """Portföy risk kontrolü"""
        async def check():
            try:
                portfolio = await portfolio_getter()
                risk_pct = portfolio.risk_exposure_pct
                max_risk = settings.max_portfolio_risk_pct

                if risk_pct > max_risk:
                    return False, f"Portfolio risk exceeded: {risk_pct:.1f}% > {max_risk}%"
                elif risk_pct > max_risk * 0.8:
                    return True, f"Portfolio risk high: {risk_pct:.1f}%"
                return True, f"Portfolio risk OK: {risk_pct:.1f}%"
            except Exception as e:
                return False, f"Position risk check failed: {e}"

        self.add_check("position_risk", check)