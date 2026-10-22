# AGENT.md — ScareByte Otomasyon Geçişi (Faz A+B)

> Bu dosya, OpenCode ajanının bu oturumda yaptığı işlemlerin özetidir. Aynı yetkilerle (workspace r/w, shell, git, gh, python, schtasks) diğer projelerde benzer görevler için referans olarak kullanılabilir.

---

## 🎯 Hedef

**ScareByte YouTube Shorts pipeline**'ını:
- **Faz A:** Üretimi GitHub Actions'a taşı (saatlik, Discord alarmı çalışır)
- **Faz B:** Paneli Tailscale ile her yerden erişilebilir yap, Actions tetikleme butonu ekle
- **Faz C:** (Bekliyor) fal bakiyesi yüklendikten sonra ilk gerçek Short

---

## 🔧 Yapılan Değişiklikler (Özet)

### 1. State dosyalarını `state/` klasörüne taşı (git-tracked)
```python
# src/scarebyte/publish/ledger.py
DEFAULT_LEDGER_PATH = Path("state/ledger.json")

# src/scarebyte/schedule.py
DEFAULT_SCHEDULE_PATH = Path("state/releases.json")

# src/scarebyte/dashboard/settings.py
DEFAULT_SETTINGS_PATH = Path("state/settings.json")

# src/scarebyte/notify.py
DEFAULT_STATE_PATH = Path("state/notify_state.json")
```
→ Runner `state/` checkout eder, commit+push yapar. `media/` sadece çalışma dosyaları (gitignore).

### 2. Font auto-detection (Linux runner için)
```python
# src/scarebyte/render.py
FONT_CANDIDATES = (
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
)
def resolve_font(): ...
```
→ `SCAREBYTE_FONT` env ile override edilebilir.

### 3. GitHub Actions Workflow (`.github/workflows/production.yml`)
```yaml
on:
  schedule: - cron: "0 * * * *"      # saatlik
  workflow_dispatch:                 # panelden tetikleme
    inputs:
      dry_run: boolean (default: true)

jobs:
  produce:
    runs-on: ubuntu-latest
    permissions: contents: write
    steps:
      - checkout (persist-credentials)
      - python 3.12 + ffmpeg + fonts-dejavu-core
      - pip install -e .
      - scarebyte schedule produce --provider fal --maintain
      - scarebyte doctor --json > state/health.json
      - git commit & push state/
```
**Secrets:** `FAL_KEY`, `NVIDIA_API_KEY`, `YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN`, `SCAREBYTE_WEBHOOK_URL`

### 4. Panel → Actions tetikleme endpoint'i
```python
# src/scarebyte/dashboard/api.py
def trigger_actions_produce(self, payload):
    # .env'den GITHUB_PAT okur
    # gh api --method POST /repos/.../dispatches --input -
    # JSON: {"ref": "main", "inputs": {"dry_run": true}}
```

### 5. Frontend butonu + i18n
```html
<!-- src/scarebyte/dashboard/static/index.html -->
<button id="produce-actions">Actions ile üret</button>
<label><input type="checkbox" id="dry-run" checked> Dry run</label>
```

### 6. Tailscale auto-detect (Dashboard + Install script)
```python
# src/scarebyte/dashboard/server.py
def _default_host():
    try: result = subprocess.run(["C:\\Program Files\\Tailscale\\tailscale.exe", "ip", "-4"], ...)
    return ip or "127.0.0.1"
DEFAULT_HOST = _default_host()
```

```powershell
# scripts/windows/install_task.ps1
$ts = Get-Command "C:\Program Files\Tailscale\tailscale.exe"
$ip = & $ts ip -4
$DashboardHost = $ip  # http://100.65.193.122:8760
```

### 5. Yerel Production task kaldırıldı
```powershell
schtasks /Delete /TN "ScareByte Production" /F
# Dashboard task kaldi (5 dk auto-restart)
```

---

## 📋 Komut Şablonları (Diğer Projelerde Kullanım İçin)

### GitHub Actions Workflow Oluştur
```bash
mkdir -p .github/workflows
cat > .github/workflows/production.yml <<'EOF'
name: Scheduled Production
on:
  schedule: [{cron: "0 * * * *"}]
  workflow_dispatch:
    inputs:
      dry_run: {type: boolean, default: true}
concurrency:
  group: production
  cancel-in-progress: false
permissions: {contents: write}
jobs:
  run:
    runs-on: ubuntu-latest
    env:
      SECRET1: ${{ secrets.SECRET1 }}
    steps:
      - uses: actions/checkout@v4
        with: {persist-credentials: true, fetch-depth: 0}
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -e .
      - run: your-cli produce --maintain
      - run: your-cli doctor --json > state/health.json
      - run: |
          git config user.name "bot"
          git config user.email "bot@users.noreply.github.com"
          git add state/
          if ! git diff --cached --quiet; then
            git commit -m "ci: update state"
            git pull --rebase
            git push
          fi
EOF
```

### Secrets Ayarlama
```bash
gh secret set SECRET1 --body "value"
gh secret set SECRET2 --body "value"
# Listeleme: gh secret list
```

### Panelden Workflow Tetikleme (Python)
```python
import subprocess, json, os

def trigger_workflow(repo, workflow, dry_run=True):
    pat = os.getenv("GITHUB_PAT")
    body = json.dumps({"ref": "main", "inputs": {"dry_run": dry_run}})
    subprocess.run([
        "gh", "api", "--method", "POST",
        f"/repos/{repo}/actions/workflows/{workflow}/dispatches",
        "--input", "-"
    ], input=body, text=True, env={**os.environ, "GH_TOKEN": pat}, check=True)
```

### Scheduled Task Kaydet (PowerShell)
```powershell
$action = New-ScheduledTaskAction -Execute "python.exe" `
    -Argument "-m your.cli dashboard --port 8760" `
    -WorkingDirectory "C:\path\to\repo"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName "Your Dashboard" -Action $action -Trigger $trigger `
    -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
        -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15)) `
    -Principal (New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited) `
    -Force
```

### Tailscale IP Alma
```powershell
$ts = Get-Command "C:\Program Files\Tailscale\tailscale.exe" -EA SilentlyContinue
if ($ts) { $ip = & $ts ip -4 }
# veya Python:
subprocess.run(["C:\\Program Files\\Tailscale\\tailscale.exe", "ip", "-4"], capture_output=True).stdout.strip()
```

---

## ✅ Test & Doğrulama Listesi

| Adım | Komut | Beklenen |
|---|---|---|
| Workflow tetikle (dry) | `gh workflow run production.yml -f dry_run=true` | `completed success` |
| Workflow tetikle (gerçek) | `gh workflow run production.yml -f dry_run=false` | `completed success` |
| Panel erişim (lokal) | `curl http://127.0.0.1:8760/api/overview` | JSON döner |
| Panel erişim (Tailscale) | `curl http://100.65.193.122:8760/api/overview` | JSON döner |
| Actions tetikle (panelden) | `curl -X POST http://.../api/produce-via-actions -d '{"dry_run":true}'` | `{"status":"PASS"}` |
| Scheduled task çalışıyor mu | `schtasks /Query /TN "ScareByte Dashboard"` | `Running` / `Ready` |
| Secrets ayarlandı mı | `gh secret list` | 7 secret listelenir |
| Testler geçiyor mu | `python -m pytest tests -q` | `310 passed` |

---

## ⚠️ Sık Karşılaşılan Sorunlar & Çözümler

| Sorun | Çözüm |
|---|---|
| `python -m scarebyte` bulunamıyor | `pip install -e .` (sistem + user Python'ına) |
| `GITHUB_PAT not set in environment` | `.env`'de `GITHUB_PAT=gho_...` + `load_env_file(".env")` çağrısı |
| `gh api --input -` parse hatası | JSON stdin ile gönder: `echo '{"ref":"main"}' | gh api --method POST ... --input -` |
| Scheduled task `python.exe` bulamaz | Sistem Python'ına `pip install -e .` veya `WorkingDirectory` kontrol |
| Port 8760 erişilemiyor (mobil) | `netsh advfirewall firewall add rule name="Dashboard" dir=in action=allow protocol=TCP localport=8760` (Admin) |
| `gh workflow run` 422 hatası | `dry_run` boolean string değil, `--input -` ile JSON gönder |
| Pycache stale import | `find . -name __pycache__ -exec rm -rf {} + ; find . -name *.pyc -delete` |

---

## 🔐 Yetki Özeti (Agent İçin)

```
WORKSPACE: C:\Users\trycahce\Desktop\Proje\scarebyte-prompt-engine
├── READ/WRITE: Tüm dosyalar (src/, tests/, scripts/, .github/, state/, config/)
├── SHELL: PowerShell (git, gh, python, pip, curl, schtasks, taskkill, netstat, winget)
├── GIT: commit, push, pull --rebase, branch, tag
├── GH CLI: secret set/list, workflow run/list/watch, api, auth token
├── PYTHON: pytest, pip install -e ., -m scarebyte.cli
├── TASKS: schtasks /Create|Run|Delete|Query, Start-ScheduledTask
├── PROCESS: taskkill, Get-Process, Stop-Process
├── NETWORK: curl, netstat, netsh (admin gerektirir)
└── PACKAGE: winget install (user onayıyla)
```

---

## 📌 Sonraki Adımlar (Faz C — Bakiye Yüklendikten Sonra)

1. `fal.ai/dashboard/billing` → bakiye yükle
2. Panel → **"Actions ile üret"** (Dry run **KAPALI**) → İlk gerçek Short
3. 24 saat izle: `state/health.json`, Discord alarmı, ilk `publishAt` zamanında yayın

---

*Oluşturulma: 2026-10-22 | OpenCode Agent | ScareByte v0.4.0*