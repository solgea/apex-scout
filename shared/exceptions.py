"""
Apex Scout - Özel Exception Sınıfları
Hata türlerini ayırarak yakalama ve yönetimi kolaylaştırır.
"""


class ApexScoutError(Exception):
    """Tüm Apex Scout hatalarının base sınıfı"""

    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self):
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class ConfigError(ApexScoutError):
    """Yapılandırma hataları"""

    pass


class ScannerError(ApexScoutError):
    """Scanner modülü hataları"""

    pass


class DexScreenerError(ScannerError):
    """DexScreener API hataları"""

    pass


class PumpFunError(ScannerError):
    """Pump.fun API hataları"""

    pass


class DecisionError(ApexScoutError):
    """Karar motoru hataları"""

    pass


class TradingError(ApexScoutError):
    """Trading modülü hataları"""

    pass


class OKXAPIError(TradingError):
    """OKX API hataları"""

    pass


class OKXAuthError(OKXAPIError):
    """OKX kimlik doğrulama hataları"""

    pass


class OKXRateLimitError(OKXAPIError):
    """OKX rate limit hataları"""

    pass


class OrderExecutionError(TradingError):
    """Emir yürütme hataları"""

    pass


class InsufficientBalanceError(TradingError):
    """Yetersiz bakiye hataları"""

    pass


class PositionNotFoundError(TradingError):
    """Pozisyon bulunamadı hataları"""

    pass


class RiskError(ApexScoutError):
    """Risk yönetimi ihlalleri"""

    pass


class MaxPositionsExceededError(RiskError):
    """Maksimum pozisyon sayısı aşıldı"""

    pass


class MaxRiskExceededError(RiskError):
    """Maksimum risk limiti aşıldı"""

    pass


class PositionSizeError(RiskError):
    """Pozisyon boyutu hatası"""

    pass


class BlacklistError(RiskError):
    """Blacklist ile ilgili hatalar"""

    pass


class DashboardError(ApexScoutError):
    """Dashboard hataları"""

    pass


class DatabaseError(ApexScoutError):
    """Veritabanı hataları"""

    pass


class OrchestratorError(ApexScoutError):
    """Orkestratör hataları"""

    pass


class ShutdownSignal(Exception):
    """Graceful shutdown sinyali (exception değil, control flow)"""

    pass
