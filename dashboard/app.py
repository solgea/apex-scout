"""
Apex Scout - Main Dashboard Application
Streamlit tabanlı canlı trading paneli.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import time
import asyncio
from typing import List, Dict, Any

from shared.logger import get_logger
from shared.database import get_session, init_db
from shared.models import Token, Decision, Position, Trade, SystemMetrics, BlacklistEntry
from config.settings import settings
from config.constants import DecisionAction, PositionStatus
from dashboard.components.sidebar import render_sidebar
from dashboard.components.token_table import render_token_table
from dashboard.components.positions import render_positions
from dashboard.components.history import render_history
from dashboard.components.performance import render_performance
from dashboard.components.system_status import render_system_status

log = get_logger(__name__)

# Sayfa konfigürasyonu
st.set_page_config(
    page_title="Apex Scout",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1f77b4;
        text-align: center;
        padding: 1rem 0;
        border-bottom: 2px solid #1f77b4;
        margin-bottom: 1rem;
    }
    .metric-card {
        background: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .status-running { color: #28a745; font-weight: bold; }
    .status-stopped { color: #dc3545; font-weight: bold; }
    .status-paused { color: #ffc107; font-weight: bold; }
    .positive { color: #28a745; }
    .negative { color: #dc3545; }
    .neutral { color: #6c757d; }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """Session state başlat"""
    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = datetime.utcnow()
    if "auto_refresh" not in st.session_state:
        st.session_state.auto_refresh = True
    if "refresh_interval" not in st.session_state:
        st.session_state.refresh_interval = settings.dashboard_refresh_seconds
    if "system_status" not in st.session_state:
        st.session_state.system_status = "UNKNOWN"
    if "scan_stats" not in st.session_state:
        st.session_state.scan_stats = {}


@st.cache_data(ttl=5)
def get_tokens(limit: int = 100) -> List[Dict]:
    """Token verilerini getir (cached)"""
    with get_session() as session:
        tokens = session.query(Token).order_by(Token.discovered_at.desc()).limit(limit).all()
        result = []
        for t in tokens:
            # Son karar
            decision = session.query(Decision).filter(Decision.token_id == t.id).order_by(Decision.created_at.desc()).first()
            result.append({
                "id": t.id,
                "symbol": t.symbol,
                "name": t.name,
                "address": t.address[:12] + "...",
                "full_address": t.address,
                "price_usd": t.price_usd,
                "liquidity_usd": t.liquidity_usd,
                "market_cap": t.market_cap,
                "volume_24h": t.volume_24h,
                "age_hours": round(t.age_seconds / 3600, 2),
                "holder_count": t.holder_count,
                "top_10_pct": t.top_10_holder_pct,
                "mint_renounced": t.mint_renounced,
                "freeze_renounced": t.freeze_renounced,
                "source": t.source.value,
                "discovered_at": t.discovered_at,
                "decision_score": decision.score if decision else 0,
                "decision_action": decision.action.value if decision else "PENDING",
                "decision_reasons": decision.reasons if decision else [],
            })
        return result


@st.cache_data(ttl=5)
def get_positions() -> List[Dict]:
    """Pozisyon verilerini getir (cached)"""
    with get_session() as session:
        positions = session.query(Position).order_by(Position.opened_at.desc()).all()
        result = []
        for p in positions:
            token = session.query(Token).filter(Token.id == p.token_id).first() if p.token_id else None
            result.append({
                "id": p.id,
                "inst_id": p.okx_inst_id,
                "symbol": token.symbol if token else p.okx_inst_id.replace("-USDT", ""),
                "side": p.side,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
                "quantity": p.quantity,
                "entry_value_usd": p.entry_value_usd,
                "unrealized_pnl": p.unrealized_pnl,
                "unrealized_pnl_pct": p.unrealized_pnl_pct,
                "realized_pnl": p.realized_pnl,
                "stop_loss_price": p.stop_loss_price,
                "trailing_stop_price": p.trailing_stop_price,
                "current_tp_tier": p.current_tp_tier,
                "take_profit_tiers": p.take_profit_tiers or [],
                "status": p.status,
                "opened_at": p.opened_at,
                "closed_at": p.closed_at,
            })
        return result


@st.cache_data(ttl=5)
def get_trades(limit: int = 200) -> List[Dict]:
    """İşlem geçmişini getir (cached)"""
    with get_session() as session:
        trades = session.query(Trade).order_by(Trade.timestamp.desc()).limit(limit).all()
        result = []
        for trade in trades:
            pos = session.query(Position).filter(Position.id == trade.position_id).first()
            token = session.query(Token).filter(Token.id == pos.token_id).first() if pos and pos.token_id else None
            result.append({
                "id": trade.id,
                "timestamp": trade.timestamp,
                "symbol": token.symbol if token else "N/A",
                "inst_id": trade.inst_id,
                "side": trade.side,
                "price": trade.price,
                "quantity": trade.quantity,
                "fee": trade.fee,
                "is_take_profit": trade.is_take_profit,
                "is_stop_loss": trade.is_stop_loss,
                "is_trailing_stop": trade.is_trailing_stop,
                "tp_tier_index": trade.tp_tier_index,
            })
        return result


@st.cache_data(ttl=5)
def get_metrics(limit: int = 100) -> List[Dict]:
    """Sistem metrikleri"""
    with get_session() as session:
        metrics = session.query(SystemMetrics).order_by(SystemMetrics.timestamp.desc()).limit(limit).all()
        return [
            {
                "timestamp": m.timestamp,
                "scan_count": m.scan_count,
                "tokens_found": m.tokens_found,
                "decisions_pass": m.decisions_pass,
                "decisions_watch": m.decisions_watch,
                "decisions_skip": m.decisions_skip,
                "trades_executed": m.trades_executed,
                "errors_count": m.errors_count,
                "api_latency_ms": m.api_latency_ms,
                "total_portfolio_value": m.total_portfolio_value,
                "risk_exposure_pct": m.risk_exposure_pct,
            }
            for m in metrics
        ]


@st.cache_data(ttl=5)
def get_blacklist() -> List[Dict]:
    """Blacklist"""
    with get_session() as session:
        entries = session.query(BlacklistEntry).filter(
            BlacklistEntry.expires_at > datetime.utcnow()
        ).order_by(BlacklistEntry.created_at.desc()).all()
        return [
            {
                "symbol": e.token_symbol,
                "address": e.token_address[:12] + "...",
                "reason": e.reason,
                "expires_at": e.expires_at,
                "remaining_hours": round((e.expires_at - datetime.utcnow()).total_seconds() / 3600, 1),
            }
            for e in entries
        ]


def render_header():
    """Ana başlık"""
    st.markdown('<div class="main-header">🎯 Apex Scout</div>', unsafe_allow_html=True)

    # Üst bar: sistem durumu ve kontroller
    col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 2])

    with col1:
        status = st.session_state.get("system_status", "UNKNOWN")
        status_class = {
            "RUNNING": "status-running",
            "PAUSED": "status-paused",
            "STOPPED": "status-stopped",
        }.get(status, "status-stopped")
        st.markdown(f"**Sistem:** <span class='{status_class}'>{status}</span>", unsafe_allow_html=True)

    with col2:
        last_refresh = st.session_state.get("last_refresh", datetime.utcnow())
        st.markdown(f"**Son Güncelleme:** {last_refresh.strftime('%H:%M:%S')}")

    with col3:
        auto = st.session_state.get("auto_refresh", True)
        st.markdown(f"**Oto Yenileme:** {'✅ Açık' if auto else '❌ Kapalı'}")

    with col4:
        open_pos = len([p for p in get_positions() if p["status"] == "OPEN"])
        st.markdown(f"**Açık Pozisyon:** {open_pos}/{settings.max_open_positions}")

    with col5:
        if st.button("🔄 Yenile", use_container_width=True):
            st.cache_data.clear()
            st.session_state.last_refresh = datetime.utcnow()
            st.rerun()


def render_metrics_row():
    """Özet metrikler satırı"""
    positions = get_positions()
    trades = get_trades(1000)

    open_pos = [p for p in positions if p["status"] == "OPEN"]
    closed_pos = [p for p in positions if p["status"] != "OPEN"]

    total_unrealized = sum(p["unrealized_pnl"] for p in open_pos)
    total_realized = sum(p["realized_pnl"] for p in positions)

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        st.metric("Toplam Değer", f"${total_realized + total_unrealized:,.2f}",
                  delta=f"{total_unrealized:+,.2f}" if total_unrealized != 0 else None)

    with col2:
        st.metric("Gerçekleşen K/Z", f"${total_realized:,.2f}",
                  delta_color="normal" if total_realized >= 0 else "inverse")

    with col3:
        st.metric("Açık K/Z", f"${total_unrealized:,.2f}",
                  delta_color="normal" if total_unrealized >= 0 else "inverse")

    with col4:
        win_trades = len([t for t in trades if (t.get("is_take_profit") or t.get("is_trailing_stop"))])
        total_trades = len([t for t in trades if t.get("is_take_profit") or t.get("is_stop_loss") or t.get("is_trailing_stop")])
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
        st.metric("Win Rate", f"{win_rate:.1f}%")

    with col5:
        st.metric("Toplam İşlem", total_trades)

    with col6:
        best = max([t["price"] * t["quantity"] for t in trades], default=0)
        st.metric("En İyi Trade", f"${best:,.2f}")


def render_main_tabs():
    """Ana sekmeler"""
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "🔍 Token Tarama",
        "📊 Pozisyonlar",
        "📜 İşlem Geçmişi",
        "📈 Performans",
        "⚙️ Sistem Durumu",
        "🚫 Blacklist",
    ])

    with tab1:
        render_token_table(get_tokens())

    with tab2:
        render_positions(get_positions())

    with tab3:
        render_history(get_trades())

    with tab4:
        render_performance(get_trades(), get_positions(), get_metrics())

    with tab5:
        render_system_status(get_metrics(), get_blacklist())

    with tab6:
        render_blacklist_tab(get_blacklist())


def render_blacklist_tab(blacklist: List[Dict]):
    """Blacklist sekmesi"""
    st.subheader("🚫 Blacklist (Stop-Loss Yiyen Token'lar)")

    if not blacklist:
        st.info("Blacklist boş. Stop-Loss yiyen token'lar burada listelenir.")
        return

    df = pd.DataFrame(blacklist)
    st.dataframe(
        df,
        column_config={
            "symbol": "Sembol",
            "address": "Adres",
            "reason": "Neden",
            "expires_at": st.column_config.DatetimeColumn("Bitiş", format="DD.MM.YYYY HH:mm"),
            "remaining_hours": st.column_config.NumberColumn("Kalan (saat)", format="%.1f"),
        },
        use_container_width=True,
        hide_index=True,
    )


def run_dashboard():
    """Dashboard entry point"""
    init_session_state()
    init_db()  # DB tablolarını oluştur

    # Sidebar
    render_sidebar()

    # Ana içerik
    render_header()
    render_metrics_row()
    st.divider()
    render_main_tabs()

    # Auto refresh
    if st.session_state.get("auto_refresh", True):
        time.sleep(st.session_state.get("refresh_interval", 10))
        st.rerun()


if __name__ == "__main__":
    run_dashboard()