#!/usr/bin/env python3
"""
Apex Scout - Solana Token Scanner & Trading System
Entry point for the trading bot.

Usage:
    python main.py              # Run the bot (scanner + trading)
    python main.py --dashboard  # Run only dashboard
    python main.py --help       # Show help
"""

import asyncio
import argparse
import sys
import os
from pathlib import Path

# Proje kök dizinini path'e ekle
sys.path.insert(0, str(Path(__file__).parent))

from shared.logger import setup_logger, get_logger
from config.settings import settings
from orchestrator.main import Orchestrator
from orchestrator.health import HealthMonitor
from orchestrator.recovery import RecoveryManager
from dashboard.app import run_dashboard

# Logger'ı başlat
setup_logger()
log = get_logger(__name__)


async def run_bot():
    """Bot ana döngüsünü çalıştır"""
    log.info("=" * 60)
    log.info("🎯 APEX SCOUT - Starting Bot Mode")
    log.info("=" * 60)
    log.info(f"Mode: {'DEMO' if settings.okx_demo_trading else 'LIVE ⚠️'}")
    log.info(f"Scan Interval: {settings.scan_interval_seconds}s")
    log.info(f"Min Liquidity: ${settings.min_liquidity_usd:,.0f}")
    log.info(f"Max Token Age: {settings.max_token_age_hours}h")
    log.info(f"Min Score to Trade: {settings.min_score_to_trade}")
    log.info(f"Max Open Positions: {settings.max_open_positions}")
    log.info(f"Max Portfolio Risk: {settings.max_portfolio_risk_pct}%")
    log.info("=" * 60)

    # Bileşenleri oluştur
    orchestrator = Orchestrator()
    health_monitor = HealthMonitor()
    recovery = RecoveryManager()

    # Health monitor callback'lerini kaydet
    async def health_alert(status):
        log.warning(f"[HEALTH ALERT] System unhealthy: {status.issues}")

    health_monitor.add_alert_callback(health_alert)

    # Recovery callback'leri
    async def get_recovery_state():
        """Orchestrator durumundan RecoveryState üret"""
        from orchestrator.recovery import RecoveryState
        status = orchestrator.get_status()
        return RecoveryState(
            orchestrator_stats=status.get("stats", {}),
            open_positions=status.get("positions", {}),
            metadata={"system_status": status.get("running", False)},
        )

    async def restore_recovery_state(state):
        log.info(f"[Recovery] Restoring state from {state.last_save}")

    recovery.set_callbacks(get_recovery_state, restore_recovery_state)

    # Health monitor API check'lerini kaydet
    health_monitor.register_api_check("okx", lambda: orchestrator._okx_client)

    async def get_portfolio():
        return await orchestrator._portfolio.get_snapshot()

    health_monitor.register_position_risk_check(get_portfolio)

    try:
        # Orchestrator kendi initialize()'ını run() içinde çağırır
        # (çift initialization'ı önlemek için burada çağırmıyoruz)
        await health_monitor.start()
        await recovery.start()

        # Bot'u çalıştır
        await orchestrator.run()

    except KeyboardInterrupt:
        log.info("Keyboard interrupt received")
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Temizlik
        log.info("Shutting down...")
        await recovery.stop()
        await health_monitor.stop()
        log.info("Shutdown complete")


def run_dashboard_mode():
    """Dashboard modunu çalıştır (Streamlit)"""
    log.info("=" * 60)
    log.info("🎯 APEX SCOUT - Starting Dashboard Mode")
    log.info("=" * 60)

    # Streamlit'i subprocess olarak çalıştır
    import subprocess
    dashboard_path = Path(__file__).parent / "dashboard" / "app.py"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parent)

    try:
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", str(dashboard_path),
            "--server.port", str(settings.dashboard_port),
            "--server.address", settings.dashboard_host,
            "--server.headless", "true",
        ], env=env, check=True)
    except subprocess.CalledProcessError as e:
        log.error(f"Dashboard failed: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        log.info("Dashboard stopped")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Apex Scout - Solana Token Scanner & Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    # Run trading bot
  python main.py --dashboard        # Run dashboard only
  python main.py --init-db          # Initialize database only
  python main.py --test-config      # Test configuration
        """
    )

    parser.add_argument(
        "--dashboard", "-d",
        action="store_true",
        help="Run Streamlit dashboard only"
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Initialize database tables and exit"
    )
    parser.add_argument(
        "--test-config",
        action="store_true",
        help="Validate configuration and exit"
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version="Apex Scout 1.0.0"
    )

    args = parser.parse_args()

    # Config test
    if args.test_config:
        log.info("Testing configuration...")
        try:
            # Settings zaten load oldu, validasyon yapıldı
            log.info("✅ Configuration valid!")
            log.info(f"   OKX Demo Trading: {settings.okx_demo_trading}")
            log.info(f"   DB URL: {settings.db_url}")
            log.info(f"   Scan Interval: {settings.scan_interval_seconds}s")
            log.info(f"   Min Score: {settings.min_score_to_trade}")
            log.info(f"   Max Positions: {settings.max_open_positions}")
            log.info(f"   Risk Limit: {settings.max_portfolio_risk_pct}%")
            sys.exit(0)
        except Exception as e:
            log.error(f"❌ Configuration invalid: {e}")
            sys.exit(1)

    # DB init
    if args.init_db:
        log.info("Initializing database...")
        from shared.database import init_db
        init_db()
        log.info("✅ Database initialized!")
        sys.exit(0)

    # Dashboard mode
    if args.dashboard:
        run_dashboard_mode()
        return

    # Normal bot mode
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        log.info("Bot stopped by user")
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()