"""
Apex Scout - Task Scheduler
Zamanlanmış görevler: periyodik temizlik, raporlama, bakım.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from shared.logger import get_logger

log = get_logger(__name__)


@dataclass
class ScheduledTask:
    """Zamanlanmış görev"""

    name: str
    coro_func: Callable[[], Awaitable[None]]
    interval_seconds: float
    last_run: datetime | None = None
    next_run: datetime | None = None
    enabled: bool = True
    run_count: int = 0
    error_count: int = 0


class TaskScheduler:
    """
    Basit async task scheduler.
    Periyodik görevleri çalıştırır.
    """

    def __init__(self):
        self._tasks: list[ScheduledTask] = []
        self._running = False
        self._scheduler_task: asyncio.Task | None = None

    def add_task(
        self,
        name: str,
        coro_func: Callable[[], Awaitable[None]],
        interval_seconds: float,
        enabled: bool = True,
    ):
        """Görev ekle"""
        now = datetime.utcnow()
        task = ScheduledTask(
            name=name,
            coro_func=coro_func,
            interval_seconds=interval_seconds,
            next_run=now,
            enabled=enabled,
        )
        self._tasks.append(task)
        log.info(f"[Scheduler] Added task: {name} every {interval_seconds}s")

    def remove_task(self, name: str) -> bool:
        """Görev sil"""
        for i, task in enumerate(self._tasks):
            if task.name == name:
                self._tasks.pop(i)
                log.info(f"[Scheduler] Removed task: {name}")
                return True
        return False

    def enable_task(self, name: str) -> bool:
        """Görevi etkinleştir"""
        for task in self._tasks:
            if task.name == name:
                task.enabled = True
                return True
        return False

    def disable_task(self, name: str) -> bool:
        """Görevi devre dışı bırak"""
        for task in self._tasks:
            if task.name == name:
                task.enabled = False
                return True
        return False

    async def start(self):
        """Scheduler'ı başlat"""
        if self._running:
            return

        self._running = True
        self._scheduler_task = asyncio.create_task(self._run_loop())
        log.info("[Scheduler] Started")

    async def stop(self):
        """Scheduler'ı durdur"""
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        log.info("[Scheduler] Stopped")

    async def _run_loop(self):
        """Ana scheduler döngüsü"""
        while self._running:
            now = datetime.utcnow()

            for task in self._tasks:
                if not task.enabled:
                    continue

                if task.next_run and now >= task.next_run:
                    await self._run_task(task, now)

            # 1 saniye bekle
            await asyncio.sleep(1)

    async def _run_task(self, task: ScheduledTask, now: datetime):
        """Tek görevi çalıştır"""
        try:
            log.debug(f"[Scheduler] Running task: {task.name}")
            await task.coro_func()
            task.last_run = now
            task.next_run = now + timedelta(seconds=task.interval_seconds)
            task.run_count += 1
            log.debug(f"[Scheduler] Task completed: {task.name}")
        except Exception as e:
            task.error_count += 1
            task.next_run = now + timedelta(seconds=task.interval_seconds)
            log.error(f"[Scheduler] Task {task.name} failed: {e}")

    def get_tasks_status(self) -> list[dict]:
        """Tüm görevlerin durumu"""
        now = datetime.utcnow()
        return [
            {
                "name": task.name,
                "enabled": task.enabled,
                "interval_seconds": task.interval_seconds,
                "last_run": task.last_run.isoformat() if task.last_run else None,
                "next_run": task.next_run.isoformat() if task.next_run else None,
                "run_count": task.run_count,
                "error_count": task.error_count,
                "due_in_seconds": (task.next_run - now).total_seconds() if task.next_run else None,
            }
            for task in self._tasks
        ]

    async def run_task_now(self, name: str) -> bool:
        """Görevi hemen çalıştır"""
        for task in self._tasks:
            if task.name == name:
                await self._run_task(task, datetime.utcnow())
                return True
        return False
