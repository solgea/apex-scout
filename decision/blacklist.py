"""
Apex Scout - Blacklist Manager
Stop-Loss yiyen token'ları geçici olarak engeller.
"""

from datetime import datetime, timedelta
from typing import List, Optional

from shared.logger import get_logger
from shared.database import get_session
from shared.models import BlacklistEntry
from config.settings import settings

log = get_logger(__name__)


class BlacklistManager:
    """
    Blacklist yönetimi.
    - SL yiyen token'ları belirli süre engeller
    - Cooldown mekanizması
    - Otomatik temizlik
    """

    def __init__(self, default_duration_hours: int = None):
        self.default_duration_hours = default_duration_hours or settings.blacklist_duration_hours

    def add(self, token_address: str, token_symbol: str, reason: str = "STOP_LOSS_HIT", duration_hours: int = None) -> BlacklistEntry:
        """Token'ı blacklist'e ekle"""
        duration = duration_hours or self.default_duration_hours
        expires_at = datetime.utcnow() + timedelta(hours=duration)

        with get_session() as session:
            # Varsa güncelle
            entry = session.query(BlacklistEntry).filter(
                BlacklistEntry.token_address == token_address
            ).first()

            if entry:
                entry.expires_at = expires_at
                entry.reason = reason
                entry.token_symbol = token_symbol
                entry.created_at = datetime.utcnow()
            else:
                entry = BlacklistEntry(
                    token_address=token_address,
                    token_symbol=token_symbol,
                    reason=reason,
                    expires_at=expires_at,
                )
                session.add(entry)

            session.commit()
            log.info(f"[Blacklist] Added: {token_symbol} ({token_address[:8]}...) for {duration}h, reason: {reason}")

            return entry

    def remove(self, token_address: str) -> bool:
        """Token'ı blacklist'ten kaldır"""
        with get_session() as session:
            entry = session.query(BlacklistEntry).filter(
                BlacklistEntry.token_address == token_address
            ).first()

            if entry:
                session.delete(entry)
                session.commit()
                log.info(f"[Blacklist] Removed: {token_address[:8]}...")
                return True
            return False

    def is_blacklisted(self, token_address: str) -> bool:
        """Token blacklist'te mi?"""
        with get_session() as session:
            entry = session.query(BlacklistEntry).filter(
                BlacklistEntry.token_address == token_address,
                BlacklistEntry.expires_at > datetime.utcnow()
            ).first()
            return entry is not None

    def get_remaining_time(self, token_address: str) -> Optional[timedelta]:
        """Kalan süreyi döndür"""
        with get_session() as session:
            entry = session.query(BlacklistEntry).filter(
                BlacklistEntry.token_address == token_address
            ).first()

            if entry and entry.expires_at > datetime.utcnow():
                return entry.expires_at - datetime.utcnow()
            return None

    def get_all_active(self) -> List[dict]:
        """Aktif blacklist entry'leri"""
        now = datetime.utcnow()
        with get_session() as session:
            entries = session.query(BlacklistEntry).filter(
                BlacklistEntry.expires_at > now
            ).order_by(BlacklistEntry.created_at.desc()).all()

            return [
                {
                    "address": e.token_address,
                    "symbol": e.token_symbol,
                    "reason": e.reason,
                    "expires_at": e.expires_at.isoformat(),
                    "remaining_hours": round((e.expires_at - now).total_seconds() / 3600, 1),
                    "created_at": e.created_at.isoformat(),
                }
                for e in entries
            ]

    def cleanup_expired(self) -> int:
        """Süresi dolanları temizle"""
        with get_session() as session:
            now = datetime.utcnow()
            deleted = session.query(BlacklistEntry).filter(
                BlacklistEntry.expires_at <= now
            ).delete()
            session.commit()

            if deleted:
                log.info(f"[Blacklist] Cleaned up {deleted} expired entries")
            return deleted

    def clear_all(self) -> int:
        """Tüm blacklist'i temizle (dikkat!)"""
        with get_session() as session:
            deleted = session.query(BlacklistEntry).delete()
            session.commit()
            log.warning(f"[Blacklist] CLEARED ALL - {deleted} entries removed")
            return deleted