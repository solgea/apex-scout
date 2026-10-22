"""
Apex Scout - Sidebar Component
Kontrol paneli ve ayarlar.
"""

import streamlit as st

from config.constants import PositionStatus
from config.settings import settings
from shared.database import get_session
from shared.models import Position as DBPosition


def render_sidebar():
    """Sol kenar çubuğu"""
    with st.sidebar:
        st.markdown("## ⚙️ Kontrol Paneli")

        # Sistem kontrolü
        st.markdown("### 🎮 Sistem")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ Başlat", use_container_width=True, type="primary"):
                st.session_state.system_status = "RUNNING"
                st.success("Sistem başlatıldı!")
        with col2:
            if st.button("⏸️ Duraklat", use_container_width=True):
                st.session_state.system_status = "PAUSED"
                st.warning("Sistem duraklatıldı!")

        if st.button("🛑 Acil Kapat (Tüm Pozisyonlar)", use_container_width=True, type="secondary"):
            st.session_state.system_status = "STOPPED"
            st.error("Acil kapat tetiklendi! Tüm pozisyonlar kapatılıyor...")

        st.divider()

        # Tarama ayarları
        st.markdown("### 🔍 Tarama Ayarları")
        st.session_state.scan_interval = st.slider(
            "Tarama Aralığı (saniye)",
            min_value=10,
            max_value=300,
            value=settings.scan_interval_seconds,
            step=10,
            help="Yeni token tarama sıklığı",
        )

        st.session_state.min_liquidity = st.number_input(
            "Min Likidite ($)",
            min_value=100,
            max_value=100000,
            value=int(settings.min_liquidity_usd),
            step=500,
        )

        st.session_state.max_age = st.slider(
            "Max Token Yaşı (saat)",
            min_value=1,
            max_value=24,
            value=settings.max_token_age_hours,
        )

        st.divider()

        # Risk ayarları
        st.markdown("### ⚠️ Risk Yönetimi")
        st.session_state.max_positions = st.slider(
            "Max Açık Pozisyon",
            min_value=1,
            max_value=20,
            value=settings.max_open_positions,
        )

        st.session_state.max_risk = st.slider(
            "Max Portföy Riski (%)",
            min_value=5,
            max_value=100,
            value=int(settings.max_portfolio_risk_pct),
        )

        st.session_state.position_size = st.slider(
            "Pozisyon Büyüklüğü (%)",
            min_value=1,
            max_value=50,
            value=int(settings.position_size_pct),
        )

        st.session_state.stop_loss = st.slider(
            "Stop-Loss (%)",
            min_value=5,
            max_value=50,
            value=int(settings.stop_loss_pct),
        )

        st.session_state.trailing_stop = st.slider(
            "Trailing Stop (%)",
            min_value=1,
            max_value=30,
            value=int(settings.trailing_stop_pct),
        )

        st.divider()

        # Dashboard ayarları
        st.markdown("### 📊 Dashboard")
        st.session_state.auto_refresh = st.checkbox(
            "Otomatik Yenileme", value=st.session_state.get("auto_refresh", True)
        )

        st.session_state.refresh_interval = st.slider(
            "Yenileme Aralığı (sn)",
            min_value=5,
            max_value=60,
            value=st.session_state.get("refresh_interval", 10),
        )

        st.divider()

        # Bilgi
        st.markdown("### ℹ️ Bilgi")
        st.markdown(f"""
        **Versiyon:** 1.0.0
        **Mod:** {'DEMO' if settings.okx_demo_trading else 'LIVE ⚠️'}
        **DB:** {settings.db_url}
        **Log:** logs/apex_scout.log
        """)

        # Pozisyon özeti
        with get_session() as session:
            open_count = (
                session.query(DBPosition).filter(DBPosition.status == PositionStatus.OPEN).count()
            )
            st.metric("Açık Pozisyon", f"{open_count}/{settings.max_open_positions}")

        st.divider()
        st.caption("Apex Scout v1.0 | Solana Token Scanner & Trading Bot")
