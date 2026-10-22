"""
Apex Scout - System Status Component
Sistem durumu, loglar, sağlık kontrolü.
"""

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def render_system_status(metrics: list, blacklist: list):
    """Sistem durumu paneli"""
    st.subheader("⚙️ Sistem Durumu ve Sağlık")

    if not metrics:
        st.info("Henüz sistem metriği yok. Bot çalışmaya başladığında veriler gelecek.")
        return

    # En son metrik
    latest = metrics[0] if metrics else {}

    # Genel durum kartları
    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        st.metric("Tarama Sayısı", latest.get("scan_count", 0))
    with col2:
        st.metric("Bulunan Token", latest.get("tokens_found", 0))
    with col3:
        pass_count = latest.get("decisions_pass", 0)
        st.metric("PASS", pass_count)
    with col4:
        watch_count = latest.get("decisions_watch", 0)
        st.metric("WATCH", watch_count)
    with col5:
        skip_count = latest.get("decisions_skip", 0)
        st.metric("SKIP", skip_count)
    with col6:
        st.metric("İşlem Sayısı", latest.get("trades_executed", 0))

    # Hata ve gecikme
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        errors = latest.get("errors_count", 0)
        st.metric("Hatalar", errors, delta_color="inverse" if errors > 0 else "normal")
    with col2:
        latency = latest.get("api_latency_ms", 0)
        st.metric("API Gecikme", f"{latency:.0f}ms")
    with col3:
        portfolio_val = latest.get("total_portfolio_value", 0)
        st.metric("Portföy Değeri", f"${portfolio_val:,.2f}")
    with col4:
        risk_pct = latest.get("risk_exposure_pct", 0)
        st.metric("Risk Pozisyonu", f"{risk_pct:.1f}%")

    st.divider()

    # Zaman serisi grafikler
    if len(metrics) > 1:
        st.markdown("### 📈 Sistem Metrikleri Zaman Serisi")
        render_metrics_charts(metrics)

    # Son hatalar / loglar
    st.markdown("### 📋 Son Sistem Olayları")
    render_recent_events(metrics)

    # Blacklist özeti
    if blacklist:
        st.markdown("### 🚫 Aktif Blacklist")
        df = pd.DataFrame(blacklist)
        st.dataframe(
            df,
            column_config={
                "symbol": "Sembol",
                "address": "Adres",
                "reason": "Neden",
                "expires_at": st.column_config.DatetimeColumn("Bitiş", format="DD.MM HH:mm"),
                "remaining_hours": st.column_config.NumberColumn("Kalan (saat)", format="%.1f"),
            },
            use_container_width=True,
            hide_index=True,
        )


def render_metrics_charts(metrics: list):
    """Metrik grafikleri"""
    # Zaman sıralı (eski -> yeni)
    sorted_metrics = sorted(metrics, key=lambda x: x["timestamp"])[-100:]  # Son 100

    timestamps = [m["timestamp"] for m in sorted_metrics]

    # 1. Tarama ve karar grafiği
    fig1 = go.Figure()
    fig1.add_trace(
        go.Scatter(
            x=timestamps,
            y=[m["tokens_found"] for m in sorted_metrics],
            name="Bulunan",
            mode="lines",
        )
    )
    fig1.add_trace(
        go.Scatter(
            x=timestamps, y=[m["decisions_pass"] for m in sorted_metrics], name="PASS", mode="lines"
        )
    )
    fig1.add_trace(
        go.Scatter(
            x=timestamps,
            y=[m["decisions_watch"] for m in sorted_metrics],
            name="WATCH",
            mode="lines",
        )
    )
    fig1.add_trace(
        go.Scatter(
            x=timestamps, y=[m["decisions_skip"] for m in sorted_metrics], name="SKIP", mode="lines"
        )
    )
    fig1.update_layout(title="Tarama ve Kararlar", height=300, template="plotly_white")
    st.plotly_chart(fig1, use_container_width=True)

    # 2. İşlem ve hata grafiği
    fig2 = go.Figure()
    fig2.add_trace(
        go.Scatter(
            x=timestamps,
            y=[m["trades_executed"] for m in sorted_metrics],
            name="İşlemler",
            mode="lines",
            line={"color": "green"},
        )
    )
    fig2.add_trace(
        go.Scatter(
            x=timestamps,
            y=[m["errors_count"] for m in sorted_metrics],
            name="Hatalar",
            mode="lines",
            line={"color": "red"},
        )
    )
    fig2.update_layout(title="İşlemler ve Hatalar", height=300, template="plotly_white")
    st.plotly_chart(fig2, use_container_width=True)

    # 3. Portföy ve risk
    fig3 = go.Figure()
    fig3.add_trace(
        go.Scatter(
            x=timestamps,
            y=[m["total_portfolio_value"] for m in sorted_metrics],
            name="Portföy ($)",
            mode="lines",
            yaxis="y",
        )
    )
    fig3.add_trace(
        go.Scatter(
            x=timestamps,
            y=[m["risk_exposure_pct"] for m in sorted_metrics],
            name="Risk (%)",
            mode="lines",
            yaxis="y2",
            line={"color": "orange"},
        )
    )
    fig3.update_layout(
        title="Portföy Değeri ve Risk",
        height=300,
        template="plotly_white",
        yaxis={"title": "Değer (USDT)", "side": "left"},
        yaxis2={"title": "Risk (%)", "side": "right", "overlaying": "y"},
    )
    st.plotly_chart(fig3, use_container_width=True)


def render_recent_events(metrics: list):
    """Son olaylar"""
    # Metrics'lerden olay türet
    events = []

    for m in metrics[:20]:  # Son 20
        ts = m["timestamp"]
        if m["scan_count"] > 0:
            events.append(
                {
                    "Zaman": ts.strftime("%H:%M:%S") if isinstance(ts, datetime) else str(ts)[:8],
                    "Tür": "Tarama",
                    "Detay": f"{m['tokens_found']} token, {m['decisions_pass']} PASS, {m['decisions_watch']} WATCH, {m['decisions_skip']} SKIP",
                }
            )
        if m["trades_executed"] > 0:
            events.append(
                {
                    "Zaman": ts.strftime("%H:%M:%S") if isinstance(ts, datetime) else str(ts)[:8],
                    "Tür": "İşlem",
                    "Detay": f"{m['trades_executed']} işlem gerçekleşti",
                }
            )
        if m["errors_count"] > 0:
            events.append(
                {
                    "Zaman": ts.strftime("%H:%M:%S") if isinstance(ts, datetime) else str(ts)[:8],
                    "Tür": "⚠️ Hata",
                    "Detay": f"{m['errors_count']} hata oluştu",
                }
            )

    if events:
        df = pd.DataFrame(events)

        def highlight_event(row):
            if "Hata" in row["Tür"]:
                return ["background-color: #f8d7da"] * len(row)
            elif "İşlem" in row["Tür"]:
                return ["background-color: #d4edda"] * len(row)
            return [""] * len(row)

        styled = df.style.apply(highlight_event, axis=1)
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.info("Henüz sistem olayı kaydedilmemiş.")
