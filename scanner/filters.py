"""
Apex Scout - Token Filtreleme Mantığı
Scanner'dan gelen token'ları config'e göre filtreler.
"""

from datetime import datetime, timedelta

from config.settings import settings
from scanner.models import TokenData, TokenFilterCriteria
from shared.database import get_session
from shared.logger import get_scanner_logger
from shared.models import BlacklistEntry

log = get_scanner_logger()


class TokenFilter:
    """
    Token filtreleme sınıfı.
    Config'den kriterleri alır, blacklist kontrolü yapar.
    """

    def __init__(self, custom_criteria: TokenFilterCriteria | None = None):
        if custom_criteria:
            self.criteria = custom_criteria
        else:
            # Config'den oluştur
            self.criteria = TokenFilterCriteria(
                min_liquidity_usd=settings.min_liquidity_usd,
                max_age_hours=settings.max_token_age_hours,
                min_volume_24h=settings.min_volume_24h,
                min_holder_count=10,
                max_top_10_holder_pct=80.0,
                require_mint_renounced=False,
                require_freeze_renounced=False,
            )
        self._blacklist_cache: set[str] = set()
        self._blacklist_cache_time: datetime | None = None
        self._cache_ttl = timedelta(minutes=5)

    def filter_tokens(self, tokens: list[TokenData]) -> list[TokenData]:
        """
        Token listesini filtrele.
        Returns: Geçen token'lar
        """
        if not tokens:
            return []

        # Blacklist cache'i yenile
        self._refresh_blacklist_cache()

        passed = []
        for token in tokens:
            ok, reasons = self.check_token(token)
            if ok:
                passed.append(token)
            else:
                log.debug(f"[Filter] {token.symbol} ({token.address[:8]}...) filtered: {reasons}")

        log.info(f"[Filter] {len(passed)}/{len(tokens)} tokens passed")
        return passed

    def check_token(self, token: TokenData) -> tuple[bool, list[str]]:
        """
        Tek token'ı kontrol et.
        Returns: (passed, reasons)
        """
        all_reasons = []

        # 1. Temel filtreler
        passed, reasons = self.criteria.check(token)
        all_reasons.extend(reasons)

        # 2. Blacklist kontrolü
        if token.address in self._blacklist_cache:
            all_reasons.append("Token blacklist'te (SL hit)")

        # 3. Sembol blacklist (config'den)
        if token.symbol in self.criteria.excluded_symbols:
            all_reasons.append(f"Sembol dışlanmış: {token.symbol}")

        return len(all_reasons) == 0, all_reasons

    def _refresh_blacklist_cache(self):
        """Blacklist cache'ini DB'den yenile"""
        now = datetime.utcnow()
        if self._blacklist_cache_time and (now - self._blacklist_cache_time) < self._cache_ttl:
            return

        try:
            with get_session() as session:
                # Süresi dolmamış blacklist entry'leri al
                entries = (
                    session.query(BlacklistEntry).filter(BlacklistEntry.expires_at > now).all()
                )

                self._blacklist_cache = {e.token_address for e in entries}
                self._blacklist_cache_time = now
                log.debug(
                    f"[Filter] Blacklist cache refreshed: {len(self._blacklist_cache)} entries"
                )
        except Exception as e:
            log.warning(f"[Filter] Blacklist cache refresh failed: {e}")

    def add_to_blacklist(self, token_address: str, token_symbol: str, duration_hours: int = None):
        """Token'ı blacklist'e ekle (DB'ye yaz)"""
        duration = duration_hours or settings.blacklist_duration_hours
        expires_at = datetime.utcnow() + timedelta(hours=duration)

        try:
            with get_session() as session:
                # Varsa güncelle, yoksa ekle
                entry = (
                    session.query(BlacklistEntry)
                    .filter(BlacklistEntry.token_address == token_address)
                    .first()
                )

                if entry:
                    entry.expires_at = expires_at
                    entry.reason = "STOP_LOSS_HIT"
                    entry.token_symbol = token_symbol
                else:
                    entry = BlacklistEntry(
                        token_address=token_address,
                        token_symbol=token_symbol,
                        reason="STOP_LOSS_HIT",
                        expires_at=expires_at,
                    )
                    session.add(entry)

                session.commit()
                self._blacklist_cache.add(token_address)
                log.info(
                    f"[Filter] Added to blacklist: {token_symbol} ({token_address[:8]}...) for {duration}h"
                )

        except Exception as e:
            log.error(f"[Filter] Blacklist add failed: {e}")

    def is_blacklisted(self, token_address: str) -> bool:
        """Token blacklist'te mi?"""
        self._refresh_blacklist_cache()
        return token_address in self._blacklist_cache

    def get_blacklist(self) -> list[dict]:
        """Aktif blacklist'i döndür"""
        self._refresh_blacklist_cache()
        now = datetime.utcnow()

        with get_session() as session:
            entries = (
                session.query(BlacklistEntry)
                .filter(BlacklistEntry.expires_at > now)
                .order_by(BlacklistEntry.created_at.desc())
                .all()
            )

            return [
                {
                    "address": e.token_address,
                    "symbol": e.token_symbol,
                    "reason": e.reason,
                    "expires_at": e.expires_at.isoformat(),
                    "remaining_hours": round((e.expires_at - now).total_seconds() / 3600, 1),
                }
                for e in entries
            ]

    def clear_expired_blacklist(self):
        """Süresi dolan blacklist entry'lerini temizle"""
        try:
            with get_session() as session:
                now = datetime.utcnow()
                deleted = (
                    session.query(BlacklistEntry).filter(BlacklistEntry.expires_at <= now).delete()
                )
                session.commit()
                if deleted:
                    log.info(f"[Filter] Cleared {deleted} expired blacklist entries")
        except Exception as e:
            log.error(f"[Filter] Blacklist cleanup failed: {e}")
