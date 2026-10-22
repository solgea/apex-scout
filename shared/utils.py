"""
Apex Scout - Yardımcı Fonksiyonlar
Ortak kullanılan utility fonksiyonları.
"""

import time
import hashlib
import hmac
import base64
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Callable, TypeVar
from functools import wraps
from decimal import Decimal, ROUND_DOWN

from config.settings import settings
from shared.logger import get_logger

log = get_logger(__name__)

T = TypeVar("T")


def utc_now() -> datetime:
    """UTC timezone-aware now"""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """
    UTC timestamp in OKX ISO8601 format: "2026-10-22T13:52:23.054Z"

    OKX API sadece bu formatı kabul eder (Unix timestamp reddedilir).
    Önemli: UTC olmalı, local time + Z çalışmaz.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def timestamp_ms() -> int:
    """Current timestamp in milliseconds"""
    return int(time.time() * 1000)


def timestamp_seconds() -> int:
    """Current timestamp in seconds"""
    return int(time.time())


def format_number(value: float, decimals: int = 4) -> str:
    """Sayıyı formatla (binlik ayraçlı)"""
    if value >= 1e9:
        return f"{value / 1e9:.{decimals}f}B"
    elif value >= 1e6:
        return f"{value / 1e6:.{decimals}f}M"
    elif value >= 1e3:
        return f"{value / 1e3:.{decimals}f}K"
    else:
        return f"{value:.{decimals}f}"


def format_pct(value: float, decimals: int = 2, show_sign: bool = True) -> str:
    """Yüzde formatla"""
    sign = "+" if show_sign and value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def format_usd(value: float, decimals: int = 2) -> str:
    """USD formatla"""
    return f"${value:,.{decimals}f}"


def round_down(value: float, decimals: int) -> float:
    """Aşağı yuvarla (truncate)"""
    d = Decimal(str(value))
    quantize_str = "0." + "0" * decimals
    return float(d.quantize(Decimal(quantize_str), rounding=ROUND_DOWN))


def calculate_pnl_pct(entry: float, current: float, side: str = "buy") -> float:
    """PnL yüzdesini hesapla"""
    if entry == 0:
        return 0.0
    if side.lower() == "buy":
        return ((current - entry) / entry) * 100
    else:  # sell/short
        return ((entry - current) / entry) * 100


def calculate_quantity(entry_price: float, position_value_usd: float, decimals: int = 4) -> float:
    """Pozisyon değeri ve giriş fiyatından miktar hesapla"""
    if entry_price <= 0:
        return 0.0
    return round_down(position_value_usd / entry_price, decimals)


def generate_signature(timestamp: str, method: str, request_path: str, body: str, secret: str) -> str:
    """
    OKX API imzası oluşturur (HMAC SHA256 + Base64)
    OKX dokümantasyonuna göre: timestamp + method + requestPath + body
    """
    message = timestamp + method.upper() + request_path + body
    mac = hmac.new(secret.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


def retry_with_backoff(
    max_retries: int = None,
    base_delay: float = None,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,),
    logger=None,
):
    """
    Exponential backoff ile retry decorator.
    Kullanım:
        @retry_with_backoff(max_retries=3, base_delay=2.0)
        async def my_func(): ...
    """
    max_retries = max_retries or settings.max_retries
    base_delay = base_delay or settings.retry_backoff_base

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        if logger:
                            logger.warning(
                                f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                                f"after {delay:.1f}s: {e}"
                            )
                        time.sleep(delay)
                    else:
                        if logger:
                            logger.error(f"All retries exhausted for {func.__name__}: {e}")
            raise last_exception

        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            import asyncio
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        if logger:
                            logger.warning(
                                f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                                f"after {delay:.1f}s: {e}"
                            )
                        await asyncio.sleep(delay)
                    else:
                        if logger:
                            logger.error(f"All retries exhausted for {func.__name__}: {e}")
            raise last_exception

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


class CircuitBreaker:
    """
    Circuit Breaker pattern implementation.
    Belirli hata sayısından sonra kısa süreliğine çağrıları engeller.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type = Exception,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half-open

    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Sync çağrı için circuit breaker"""
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
                log.info(f"Circuit breaker half-open for {func.__name__}")
            else:
                raise self.expected_exception(f"Circuit breaker open for {func.__name__}")

        try:
            result = func(*args, **kwargs)
            self.on_success()
            return result
        except self.expected_exception as e:
            self.on_failure()
            raise

    async def acall(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Async çağrı için circuit breaker"""
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
                log.info(f"Circuit breaker half-open for {func.__name__}")
            else:
                raise self.expected_exception(f"Circuit breaker open for {func.__name__}")

        try:
            result = await func(*args, **kwargs)
            self.on_success()
            return result
        except self.expected_exception as e:
            self.on_failure()
            raise

    def on_success(self):
        """Başarılı çağrı sonrası"""
        self.failure_count = 0
        self.state = "closed"

    def on_failure(self):
        """Başarısız çağrı sonrası"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            log.warning(f"Circuit breaker opened after {self.failure_count} failures")

    def reset(self):
        """Manuel reset"""
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"


def is_token_blacklisted(token_address: str) -> bool:
    """Token blacklist'te mi kontrol et (DB'siz basit versiyon)"""
    # Gerçek implementasyon DB'den kontrol eder
    # Bu basit bir placeholder
    return False


def parse_okx_inst_id(symbol: str) -> str:
    """Token symbol'ünden OKX instrument ID oluştur"""
    symbol = symbol.upper().strip()
    if symbol.endswith("USDT"):
        return symbol
    return f"{symbol}-USDT"


def extract_symbol_from_inst_id(inst_id: str) -> str:
    """OKX instrument ID'den symbol çıkar"""
    return inst_id.replace("-USDT", "").replace("USDT", "")


def safe_float(value: Any, default: float = 0.0) -> float:
    """Güvenli float dönüşümü"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Güvenli int dönüşümü"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def chunks(lst: List[Any], n: int) -> List[List[Any]]:
    """Listeyi n'li parçalara böl"""
    return [lst[i:i + n] for i in range(0, len(lst), n)]


def get_time_ago_str(seconds: int) -> str:
    """Saniyeyi okunabilir süreye çevir"""
    if seconds < 60:
        return f"{seconds}s ago"
    elif seconds < 3600:
        return f"{seconds // 60}m ago"
    elif seconds < 86400:
        return f"{seconds // 3600}h ago"
    else:
        return f"{seconds // 86400}d ago"