"""
Apex Scout - Base Scanner Abstract Class
Tüm scanner'lar için ortak arayüz.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from scanner.models import TokenData, TokenFilterCriteria
from shared.exceptions import ScannerError
from shared.logger import get_scanner_logger

log = get_scanner_logger()


class BaseScanner(ABC):
    """Tüm scanner'lar için base class"""

    def __init__(
        self,
        filter_criteria: TokenFilterCriteria | None = None,
        source_name: str = "base",
    ):
        self.filter_criteria = filter_criteria
        self.source_name = source_name
        self.last_scan_time: datetime | None = None
        self.scan_count = 0
        self.error_count = 0

    @abstractmethod
    async def fetch_new_tokens(self) -> list[TokenData]:
        """
        Yeni token'ları çek.
        Her kaynak kendi implementasyonunu yapar.
        """
        pass

    @abstractmethod
    async def fetch_token_details(self, address: str) -> TokenData | None:
        """
        Belirli bir token'ın detaylı bilgisini çek.
        """
        pass

    async def scan(self) -> list[TokenData]:
        """
        Tam tarama döngüsü: fetch -> filter -> return.
        """
        start_time = datetime.utcnow()
        log.info(f"[{self.source_name}] Starting scan...")

        try:
            # 1. Token'ları çek
            raw_tokens = await self.fetch_new_tokens()
            log.info(f"[{self.source_name}] Fetched {len(raw_tokens)} raw tokens")

            # 2. Filtrele
            filtered_tokens = []
            for token in raw_tokens:
                if self.filter_criteria:
                    passed, reasons = self.filter_criteria.check(token)
                    if passed:
                        filtered_tokens.append(token)
                    else:
                        log.debug(f"[{self.source_name}] Filtered out {token.symbol}: {reasons}")
                else:
                    filtered_tokens.append(token)

            # 3. İstatistikleri güncelle
            self.last_scan_time = datetime.utcnow()
            self.scan_count += 1

            elapsed = (self.last_scan_time - start_time).total_seconds()
            log.info(
                f"[{self.source_name}] Scan complete: "
                f"{len(filtered_tokens)}/{len(raw_tokens)} passed in {elapsed:.2f}s"
            )

            return filtered_tokens

        except Exception as e:
            self.error_count += 1
            log.error(f"[{self.source_name}] Scan error: {e}")
            raise ScannerError(f"{self.source_name} scan failed", {"error": str(e)}) from e

    def get_stats(self) -> dict:
        """Scanner istatistikleri"""
        return {
            "source": self.source_name,
            "scan_count": self.scan_count,
            "error_count": self.error_count,
            "last_scan": self.last_scan_time.isoformat() if self.last_scan_time else None,
        }
