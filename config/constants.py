"""
Apex Scout - Sabitler ve Enumlar
Sistem genelinde kullanılan sabit değerler.
"""

from enum import Enum


class DecisionAction(str, Enum):
    """Karar motoru çıktı aksiyonları"""
    PASS = "PASS"       # İşlem yap, yüksek skor
    WATCH = "WATCH"     # İzle, orta skor
    SKIP = "SKIP"       # Atla, düşük skor


class PositionStatus(str, Enum):
    """Pozisyon durumları"""
    OPEN = "OPEN"                   # Açık pozisyon
    PARTIAL = "PARTIAL"             # Kısmen kapatıldı (TP tetiklendi)
    CLOSED = "CLOSED"               # Tamamen kapatıldı
    STOPPED_OUT = "STOPPED_OUT"     # Stop-Loss ile kapatıldı
    TRAILING_CLOSED = "TRAILING_CLOSED"  # Trailing stop ile kapatıldı


class OrderSide(str, Enum):
    """Emir yönleri"""
    BUY = "buy"
    SELL = "sell"


class TokenSource(str, Enum):
    """Token kaynağı"""
    DEXSCREENER = "dexscreener"
    PUMPFUN = "pumpfun"


class Timeframe(str, Enum):
    """Zaman dilimleri"""
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


# OKX Demo trading header - ZORUNLU
OKX_DEMO_HEADER = "x-simulated-trading"
OKX_DEMO_VALUE = "1"

# Desteklenen Solana token'lar için OKX instrument ID formatı
# Örnek: "SOL-USDT", "BONK-USDT"
OKX_INST_ID_SUFFIX = "-USDT"

# Varsayılan sayfalama
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100