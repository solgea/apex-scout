"""
Apex Scout - Loguru Logger Konfigürasyonu
Merkezi loglama, dosya rotasyonu, formatlama.
"""

import sys
from pathlib import Path

from loguru import logger

from config.settings import settings


def _safe_console_sink(message: str):
    """
    Windows konsolunda emoji/unicode karakterler hata verir (cp1254).
    Güvenli şekilde yaz, desteklenmeyen karakterleri '?' ile değiştir.
    """
    try:
        sys.stdout.write(message)
        sys.stdout.flush()
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        safe = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
        sys.stdout.write(safe)
        sys.stdout.flush()


def setup_logger() -> None:
    """
    Loguru logger'ını yapılandırır.
    - Konsola: Renkli, formatlı (Windows için encoding-safe)
    - Dosyaya: Rotasyonlu, retentionlı
    """
    # Varsayılan handler'ı kaldır
    logger.remove()

    # Log dizini
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Konsol handler - renkli ve okunabilir (encoding-safe)
    logger.add(
        _safe_console_sink,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # Dosya handler - genel loglar (rotation + retention)
    logger.add(
        log_dir / "apex_scout.log",
        level=settings.log_level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation=settings.log_rotation,
        retention=settings.log_retention,
        compression="zip",
        backtrace=True,
        diagnose=True,
        enqueue=True,  # Thread-safe
    )

    # Hata logları ayrı dosya
    logger.add(
        log_dir / "errors.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}\n{exception}",
        rotation=settings.log_rotation,
        retention=settings.log_retention,
        compression="zip",
        backtrace=True,
        diagnose=True,
        enqueue=True,
    )

    # Trading işlemleri ayrı log (audit trail)
    logger.add(
        log_dir / "trading.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
        rotation=settings.log_rotation,
        retention=settings.log_retention,
        compression="zip",
        filter=lambda record: "TRADING" in record["extra"],
        enqueue=True,
    )

    # Scanner logları
    logger.add(
        log_dir / "scanner.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
        rotation=settings.log_rotation,
        retention=settings.log_retention,
        compression="zip",
        filter=lambda record: record["extra"].get("module") == "scanner",
        enqueue=True,
    )

    logger.info("Apex Scout logger initialized")


def get_logger(name: str = None):
    """
    Modül için logger instance'ı döner.
    Kullanım:
        log = get_logger(__name__)
        log.info("Mesaj")
        log.bind(module="scanner").debug("Scanner debug")
    """
    if name:
        return logger.bind(name=name)
    return logger


# Trading logger helper
def get_trading_logger():
    """Trading audit log için özel logger"""
    return logger.bind(TRADING=True)


# Scanner logger helper
def get_scanner_logger():
    """Scanner modülü için özel logger"""
    return logger.bind(module="scanner")


# Decision logger helper
def get_decision_logger():
    """Decision modülü için özel logger"""
    return logger.bind(module="decision")


# Başlangıçta logger'ı kur
setup_logger()
