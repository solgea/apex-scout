"""
Apex Scout - Recovery Manager
Hata kurtarma, state persistence, crash recovery.
"""

import asyncio
import json
import pickle
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Callable, Awaitable
from pathlib import Path
from dataclasses import dataclass, field, asdict

from shared.logger import get_logger
from shared.database import get_session
from shared.models import Position as DBPosition, Token, Decision
from config.constants import PositionStatus
from config.settings import settings

log = get_logger(__name__)


@dataclass
class RecoveryState:
    """Kurtarma durumu"""
    last_save: datetime = field(default_factory=datetime.utcnow)
    orchestrator_stats: Dict = field(default_factory=dict)
    open_positions: list = field(default_factory=list)
    pending_decisions: list = field(default_factory=list)
    scanner_state: Dict = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)


class RecoveryManager:
    """
    Hata kurtarma ve state persistence.
    - Periyodik state kaydetme
    - Crash sonrası recovery
    - Checkpoint yönetimi
    """

    def __init__(self, state_dir: str = "data/recovery"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self.state_dir / "recovery_state.json"
        self._backup_dir = self.state_dir / "backups"
        self._backup_dir.mkdir(exist_ok=True)

        self._save_interval = 60  # saniye
        self._save_task: Optional[asyncio.Task] = None
        self._running = False

        # Callbacks
        self._get_state_callback: Optional[Callable[[], Awaitable[RecoveryState]]] = None
        self._restore_callback: Optional[Callable[[RecoveryState], Awaitable[None]]] = None

    def set_callbacks(
        self,
        get_state: Callable[[], Awaitable[RecoveryState]],
        restore_state: Callable[[RecoveryState], Awaitable[None]],
    ):
        """State getter/setter callback'leri"""
        self._get_state_callback = get_state
        self._restore_callback = restore_state

    async def start(self):
        """Auto-save başlat"""
        self._running = True
        self._save_task = asyncio.create_task(self._auto_save_loop())
        log.info(f"[Recovery] Auto-save started (interval: {self._save_interval}s)")

        # Mevcut state varsa restore et
        await self.try_recover()

    async def stop(self):
        """Durdur ve son state'i kaydet"""
        self._running = False
        if self._save_task:
            self._save_task.cancel()
            try:
                await self._save_task
            except asyncio.CancelledError:
                pass
        # Final save
        await self.save_state()
        log.info("[Recovery] Stopped and final state saved")

    async def _auto_save_loop(self):
        """Periyodik kaydetme döngüsü"""
        while self._running:
            await asyncio.sleep(self._save_interval)
            if self._running:
                await self.save_state()

    async def save_state(self):
        """Mevcut state'i kaydet"""
        if not self._get_state_callback:
            return

        try:
            state = await self._get_state_callback()
            state.last_save = datetime.utcnow()

            # JSON serializable hale getir
            data = self._serialize_state(state)

            # Atomic write (temp dosya + rename)
            temp_file = self._state_file.with_suffix(".tmp")
            with open(temp_file, "w") as f:
                json.dump(data, f, indent=2, default=str)
            temp_file.replace(self._state_file)

            # Backup da al (her 10 kaydetmede bir)
            if hasattr(self, '_save_count'):
                self._save_count += 1
            else:
                self._save_count = 1

            if self._save_count % 10 == 0:
                backup_file = self._backup_dir / f"state_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
                with open(backup_file, "w") as f:
                    json.dump(data, f, indent=2, default=str)
                # Eski backup'ları temizle (son 20)
                self._cleanup_backups()

            log.debug(f"[Recovery] State saved: {self._state_file}")

        except Exception as e:
            log.error(f"[Recovery] Save failed: {e}")

    async def try_recover(self) -> bool:
        """State'i geri yüklemeye çalış"""
        if not self._state_file.exists():
            log.info("[Recovery] No previous state found, starting fresh")
            return False

        if not self._restore_callback:
            log.warning("[Recovery] No restore callback, skipping recovery")
            return False

        try:
            with open(self._state_file, "r") as f:
                data = json.load(f)

            state = self._deserialize_state(data)

            # State'in çok eski olmadığını kontrol et (max 1 saat)
            age = datetime.utcnow() - state.last_save
            if age > timedelta(hours=1):
                log.warning(f"[Recovery] State too old ({age}), starting fresh")
                return False

            log.info(f"[Recovery] Recovering state from {state.last_save}")
            await self._restore_callback(state)

            # Açık pozisyonları DB'den de doğrula
            await self._validate_positions(state)

            log.info("[Recovery] State recovered successfully")
            return True

        except Exception as e:
            log.error(f"[Recovery] Recovery failed: {e}")
            return False

    async def _validate_positions(self, state: RecoveryState):
        """Açık pozisyonları DB ile doğrula"""
        try:
            with get_session() as session:
                db_positions = session.query(DBPosition).filter(
                    DBPosition.status.in_([PositionStatus.OPEN, PositionStatus.PARTIAL])
                ).all()

                log.info(f"[Recovery] Found {len(db_positions)} open positions in DB")

                for db_pos in db_positions:
                    log.debug(f"  - {db_pos.okx_inst_id}: {db_pos.status} PnL={db_pos.unrealized_pnl:.2f}")

        except Exception as e:
            log.error(f"[Recovery] Position validation failed: {e}")

    def _serialize_state(self, state: RecoveryState) -> Dict:
        """State'i JSON serializable dict'e çevir"""
        return {
            "last_save": state.last_save.isoformat(),
            "orchestrator_stats": state.orchestrator_stats,
            "open_positions": state.open_positions,
            "pending_decisions": state.pending_decisions,
            "scanner_state": state.scanner_state,
            "metadata": state.metadata,
        }

    def _deserialize_state(self, data: Dict) -> RecoveryState:
        """Dict'ten RecoveryState oluştur"""
        return RecoveryState(
            last_save=datetime.fromisoformat(data["last_save"]),
            orchestrator_stats=data.get("orchestrator_stats", {}),
            open_positions=data.get("open_positions", []),
            pending_decisions=data.get("pending_decisions", []),
            scanner_state=data.get("scanner_state", {}),
            metadata=data.get("metadata", {}),
        )

    def _cleanup_backups(self):
        """Eski backup'ları temizle"""
        try:
            backups = sorted(self._backup_dir.glob("state_*.json"))
            if len(backups) > 20:
                for old in backups[:-20]:
                    old.unlink()
        except Exception as e:
            log.warning(f"[Recovery] Backup cleanup failed: {e}")

    # ============ MANUAL OPERATIONS ============

    async def force_save(self):
        """Manuel kaydet"""
        await self.save_state()

    async def force_recover(self) -> bool:
        """Manuel recovery"""
        return await self.try_recover()

    def list_backups(self) -> list:
        """Backup'ları listele"""
        backups = sorted(self._backup_dir.glob("state_*.json"), reverse=True)
        return [
            {
                "file": b.name,
                "size": b.stat().st_size,
                "modified": datetime.fromtimestamp(b.stat().st_mtime).isoformat(),
            }
            for b in backups
        ]

    def get_latest_backup(self) -> Optional[Path]:
        """En son backup"""
        backups = sorted(self._backup_dir.glob("state_*.json"), reverse=True)
        return backups[0] if backups else None

    async def restore_from_backup(self, backup_name: str) -> bool:
        """Belirli bir backup'tan restore et"""
        backup_file = self._backup_dir / backup_name
        if not backup_file.exists():
            log.error(f"[Recovery] Backup not found: {backup_name}")
            return False

        try:
            with open(backup_file, "r") as f:
                data = json.load(f)

            state = self._deserialize_state(data)

            if self._restore_callback:
                await self._restore_callback(state)
                log.info(f"[Recovery] Restored from backup: {backup_name}")
                return True

        except Exception as e:
            log.error(f"[Recovery] Backup restore failed: {e}")

        return False