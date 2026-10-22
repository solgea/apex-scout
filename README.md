# 🎯 Apex Scout

**Solana Token Scanner + Jev-style Decision Engine + OKX Demo Trading + Real-time Dashboard**

Modüler, dayanıklı ve tam yapılandırılabilir bir Solana token tarama ve otomatik trading sistemi.

## 🚀 Özellikler

### 🔍 Scanner Bot
- **DexScreener** ve **Pump.fun** üzerinden yeni Solana token'larını tarar
- Filtreler: Likidite ≥ $5,000, Yaş ≤ 2 saat, Hacim ≥ $1,000
- Token detayları: isim, sembol, contract, likidite, market cap, hacim, yaş, mint/freeze durumu

### 🧠 Decision Layer (Jev-style)
- Token'ları **0-100 arası skorlar**
- 6 kriter ağırlıklı hesaplama:
  - Likidite Derinliği (25%)
  - 24h Hacim/Likidite Oranı (20%)
  - Token Yaşı (15%)
  - Market Cap Sweet Spot (15%)
  - Mint/Freeze Authority (10%)
  - Holder Dağılımı (15%)
- Karar: **PASS** (≥70) / **WATCH** (50-69) / **SKIP** (<50)

### 💰 OKX Demo Trading (Gelişmiş)
- **Sadece Demo Hesap** - Gerçek hesap engellenir
- Spot alım-satım (Market emirleri)
- **Kademeli Take-Profit**: +25%→%40, +45%→%40, +70%→%100
- **Trailing Stop**: İlk TP sonrası aktif, %10 izler
- **Stop-Loss**: Sabit %15
- **Risk Limitleri**: Max 4 pozisyon, Portföy max %35 risk, İşlem başı %10

### 📊 Dashboard (Streamlit)
- **Token Tarama**: Canlı token listesi, skorlar, filtreler
- **Pozisyonlar**: Giriş, güncel PnL, TP kademeleri, Trailing seviyesi
- **İşlem Geçmişi**: Filtrelenebilir, CSV export
- **Performans**: Win rate, PnL, Equity curve, En iyi/kötü trade
- **Sistem Durumu**: API health, hata oranları, risk metrikleri, Blacklist
- **Kontrol Paneli**: Başlat/Duraklat/Acil Kapat, ayar override

### 🛡️ Orchestrator & Resilience
- Dayanıklı ana döngü (Tarama → Karar → İşlem → Takip)
- Retry + Exponential backoff + Circuit breaker
- Graceful shutdown (SIGTERM/SIGINT)
- State persistence & Crash recovery
- Health monitoring (API, DB, Disk, CPU, Memory, Error rate)

## 📁 Proje Yapısı

```
apex-scout/
├── config/
│   ├── settings.py          # Pydantic Settings (.env + validation)
│   └── constants.py         # Enum'lar, sabitler
├── scanner/
│   ├── dexscreener.py       # DexScreener API client
│   ├── pumpfunt.py          # Pump.fun API + WebSocket
│   ├── filters.py           # Token filtreleme + Blacklist
│   └── models.py            # Pydantic data models
├── decision/
│   ├── engine.py            # Jev-style scoring engine
│   ├── criteria.py          # Skorlama kriterleri
│   ├── blacklist.py         # SL cooldown yönetimi
│   └── models.py            # Decision result models
├── trading/
│   ├── okx_client.py        # OKX Demo API wrapper
│   ├── risk_manager.py      # TP/SL/Trailing + risk limits
│   ├── position_manager.py  # Pozisyon yaşam döngüsü
│   ├── order_executor.py    # Emir yürütme + fill tracking
│   ├── portfolio.py         # Portföy + performans metrikleri
│   └── models.py            # Trading data models
├── dashboard/
│   ├── app.py               # Streamlit main app
│   └── components/          # UI bileşenleri
├── orchestrator/
│   ├── main.py              # Ana koordinatör
│   ├── scheduler.py         # Zamanlanmış görevler
│   ├── health.py            # Health monitoring
│   └── recovery.py          # Crash recovery
├── shared/
│   ├── database.py          # SQLAlchemy 2.0 + SQLite
│   ├── models.py            # DB models (Token, Decision, Position, Trade)
│   ├── exceptions.py        # Custom exceptions
│   ├── logger.py            # Loguru config
│   └── utils.py             # Helper functions
├── tests/                   # Unit tests
├── data/                    # SQLite DB, recovery states
├── logs/                    # Rotating log files
├── main.py                  # Entry point
├── requirements.txt
├── .env.example
└── pyproject.toml
```

## ⚙️ Kurulum

### 1. Gereksinimler
- Python 3.10+
- OKX Demo Hesabı ([okx.com → Demo Trading](https://www.okx.com))

### 2. Kurulum
```bash
# Repo klonla
git clone <repo-url> apex-scout
cd apex-scout

# Virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Bağımlılıklar
pip install -r requirements.txt

# Konfigürasyon
cp .env.example .env
# .env dosyasını düzenle (OKX Demo credentials zorunlu)
```

### 3. .env Konfigürasyonu (Örnek)
```env
# OKX DEMO ONLY - ZORUNLU
OKX_API_KEY=your_demo_key
OKX_API_SECRET=your_demo_secret
OKX_PASSPHRASE=your_demo_passphrase
OKX_DEMO_TRADING=true

# Scanner
SCAN_INTERVAL_SECONDS=60
MIN_LIQUIDITY_USD=5000
MAX_TOKEN_AGE_HOURS=2

# Decision
MIN_SCORE_TO_TRADE=70

# Risk
MAX_OPEN_POSITIONS=4
MAX_PORTFOLIO_RISK_PCT=35
POSITION_SIZE_PCT=10
STOP_LOSS_PCT=15
TRAILING_STOP_PCT=10
```

### 4. Veritabanı
```bash
python main.py --init-db
```

## 🐳 Docker Compose (Önerilen)

Bot + Dashboard tek komutla ayağa kalkar. Ortak volume üzerinden **aynı SQLite DB'yi** paylaşırlar (WAL modu ile eşzamanlı erişim).

```bash
# 1. .env dosyasını hazırla (OKX Demo credentials)
cp .env.example .env
notepad .env

# 2. Build + Başlat
docker compose up -d --build

# 3. Dashboard
# http://localhost:8501

# 4. Logları izle
docker compose logs -f bot
docker compose logs -f dashboard

# 5. Durdur
docker compose down

# 6. Verilerle birlikte tamamen temizle
docker compose down -v
```

### Servisler

| Servis | Açıklama | Port |
|--------|----------|------|
| `bot` | Scanner + Decision + Trading | - |
| `dashboard` | Streamlit arayüz | 8501 |

### Volume'lar

| Volume | İçerik |
|--------|--------|
| `apex_scout_data` | SQLite DB + recovery state (kalıcı) |
| `apex_scout_logs` | Log dosyaları (rotasyonlu) |

### Testleri Container'da Çalıştırma
```bash
docker compose run --rm tests
```

### Docker Komutları
```bash
docker compose ps                  # Durum
docker compose restart bot         # Bot'u yeniden başlat
docker compose logs -f --tail=100 bot
docker compose exec bot python main.py --test-config
docker compose down -v && docker compose up -d --build   # Sıfırdan kur
```

---

## 🏃 Çalıştırma (Manuel / Lokal)

### Bot Modu (Tarama + Trading)
```bash
python main.py
```
- Sürekli tarar, karar verir, işlem açar, pozisyonları takip eder
- `Ctrl+C` ile graceful shutdown

### Dashboard Modu (Arayüz)
```bash
python main.py --dashboard
# veya
streamlit run dashboard/app.py
```
- Tarayıcıda açılır: `http://localhost:8501`
- Canlı veri, filtreler, grafikler, kontroller

### Yapılandırma Testi
```bash
python main.py --test-config
```

## 📸 Dashboard Ekran Görüntüleri

| Sekme | Açıklama |
|-------|----------|
| 🔍 Token Tarama | Canlı token listesi, skorlar, PASS/WATCH/SKIP, detaylar |
| 📊 Pozisyonlar | Açık pozisyonlar, PnL, TP kademeleri, Trailing SL |
| 📜 İşlem Geçmişi | Tüm trade'ler, TP/SL/Trailing ayrımı, CSV export |
| 📈 Performans | Win rate, Equity curve, Günlük PnL, En iyi/kötü |
| ⚙️ Sistem Durumu | API health, Metrikler, Hatalar, Blacklist |
| 🚫 Blacklist | SL yiyen token'lar, kalan cooldown süresi |

## 🔧 Gelişmiş Konfigürasyon

### Take-Profit Kademeleri (`.env`)
```env
# JSON formatında dizi
TAKE_PROFIT_TIERS=[{"profit_pct": 25, "sell_pct": 40}, {"profit_pct": 45, "sell_pct": 40}, {"profit_pct": 70, "sell_pct": 100}]
```

### Skor Ağırlıkları (Toplam 1.0 olmalı)
```env
SCORING_WEIGHTS_LIQUIDITY=0.25
SCORING_WEIGHTS_VOLUME=0.20
SCORING_WEIGHTS_AGE=0.15
SCORING_WEIGHTS_MCAP=0.15
SCORING_WEIGHTS_MINT_FREEZE=0.10
SCORING_WEIGHTS_HOLDER_DIST=0.15
```

## 🛡️ Güvenlik

| Kural | Açıklama |
|-------|----------|
| ✅ Demo Only | `OKX_DEMO_TRADING=true` zorunlu, aksi takdirde başlatmaz |
| ✅ No Private Keys | Sadece API key/secret/passphrase (demo sub-account) |
| ✅ Read-only Dashboard | UI'dan trading yapılamaz, sadece izleme |
| ✅ Config Validation | Pydantic ile startup'ta tüm parametreler doğrulanır |
| ✅ Rate Limiting | API limitlerine saygı, config'den ayarlanabilir |

## 🧪 Testler

```bash
# Tüm testler
pytest tests/ -v

# Coverage
pytest tests/ --cov=scanner --cov=decision --cov=trading --cov=orchestrator
```

## 📈 Performans ve Monitoring

- **Logs**: `logs/apex_scout.log` (rotating, 10MB, 7 gün)
- **Trading Audit**: `logs/trading.log` (sadece işlemler)
- **Metrics DB**: `data/apex_scout.db` (SystemMetrics tablosu)
- **Health Checks**: Her 30 saniyede (API, DB, Disk, CPU, Memory, Error rate)

## 🤝 Katkıda Bulunma

1. Fork yapın
2. Feature branch: `git checkout -b feature/yeni-ozellik`
3. Commit: `git commit -m "feat: yeni özellik"`
4. Push: `git push origin feature/yeni-ozellik`
5. Pull Request açın

## 📄 Lisans

MIT License - Detaylar için `LICENSE` dosyasına bakın.

## ⚠️ Disclaimer

> **Bu yazılım sadece eğitim ve araştırma amaçlıdır.**
> **OKX Demo hesap ile test edilmiştir. Gerçek para ile kullanım yasaktır.**
> **Kripto para yatırımı yüksek risk içerir. Kendi araştırmanızı yapın (DYOR).**

---

**Apex Scout** - Built with ❤️ for algorithmic trading enthusiasts.