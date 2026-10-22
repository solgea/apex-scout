"""
Apex Scout - Performance Component
Performans özeti, equity curve, metrikler.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta


def render_performance(trades: list, positions: list, metrics: list):
    """Performans paneli"""
    st.subheader("📈 Performans Özeti")

    if not trades and not positions:
        st.info("Performans verisi için işlem veya pozisyon gerekli.")
        return

    # Hesaplamalar
    open_pos = [p for p in positions if p["status"] == "OPEN"]
    all_pos = positions

    total_realized = sum(p["realized_pnl"] for p in all_pos)
    total_unrealized = sum(p["unrealized_pnl"] for p in open_pos)
    total_pnl = total_realized + total_unrealized

    # Trade bazlı PnL
    trade_pnls = []
    for t in trades:
        # Basit: sell - buy için
        pass  # TODO: Proper PnL calculation from position

    # Win/Loss
    tp_count = len([t for t in trades if t.get("is_take_profit")])
    sl_count = len([t for t in trades if t.get("is_stop_loss")])
    trail_count = len([t for t in trades if t.get("is_trailing_stop")])
    total_closed = tp_count + sl_count + trail_count
    win_rate = (tp_count + trail_count) / total_closed * 100 if total_closed > 0 else 0

    # Metrikler satırı
    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        st.metric(
            "Toplam PnL",
            f"${total_pnl:,.2f}",
            delta=f"${total_unrealized:+,.2f}" if total_unrealized != 0 else None,
            delta_color="normal" if total_pnl >= 0 else "inverse",
        )
    with col2:
        st.metric(
            "Gerçekleşen",
            f"${total_realized:,.2f}",
            delta_color="normal" if total_realized >= 0 else "inverse",
        )
    with col3:
        st.metric(
            "Açık",
            f"${total_unrealized:,.2f}",
            delta_color="normal" if total_unrealized >= 0 else "inverse",
        )
    with col4:
        st.metric("Win Rate", f"{win_rate:.1f}%")
    with col5:
        st.metric("Kazanma", tp_count + trail_count)
    with col6:
        st.metric("Kaybetme", sl_count)

    st.divider()

    # Equity Curve (metriklerden)
    if metrics:
        st.markdown("### 📊 Portföy Değeri Zaman Serisi")
        render_equity_chart(metrics)

    # Trade dağılımı
    if trades:
        st.markdown("### 🎯 İşlem Dağılımı")
        col1, col2 = st.columns(2)

        with col1:
            # TP/SL/Trailing pasta
            labels = ["Take Profit", "Stop Loss", "Trailing Stop", "Diğer"]
            values = [tp_count, sl_count, trail_count, len(trades) - total_closed]
            fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.4)])
            fig.update_layout(title="Kapanış Türleri", height=300)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            # Günlük PnL (basit)
            st.markdown("**Günlük İşlem Sayısı**")
            daily = {}
            for t in trades:
                day = t["timestamp"].strftime("%m/%d") if t["timestamp"] else "N/A"
                daily[day] = daily.get(day, 0) + 1

            if daily:
                daily_df = pd.DataFrame([{"Gün": k, "İşlem": v} for k, v in daily.items()])
                st.bar_chart(daily_df.set_index("Gün"))

    # En iyi / en kötü (position'dan)
    st.markdown("### 🏆 En İyi / En Kötü Pozisyonlar")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**🟢 En Karlı (Açık)**")
        best_open = sorted(open_pos, key=lambda x: x["unrealized_pnl_pct"], reverse=True)[:5]
        if best_open:
            for i, p in enumerate(best_open, 1):
                st.write(
                    f"{i}. {p['symbol']}: ${p['unrealized_pnl']:+,.2f} ({p['unrealized_pnl_pct']:+.2f}%)"
                )
        else:
            st.write("Açık pozisyon yok")

    with col2:
        st.markdown("**🔴 En Zararlı (Açık)**")
        worst_open = sorted(open_pos, key=lambda x: x["unrealized_pnl_pct"])[:5]
        if worst_open:
            for i, p in enumerate(worst_open, 1):
                st.write(
                    f"{i}. {p['symbol']}: ${p['unrealized_pnl']:+,.2f} ({p['unrealized_pnl_pct']:+.2f}%)"
                )
        else:
            st.write("Açık pozisyon yok")

    # Kapalı pozisyonlardan en iyi/kötü
    closed = [p for p in all_pos if p["status"] != "OPEN"]
    if closed:
        st.markdown("### 📋 Kapalı Pozisyon Performansı")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**🟢 En Karlı (Kapalı)**")
            best_closed = sorted(closed, key=lambda x: x["realized_pnl"], reverse=True)[:5]
            for i, p in enumerate(best_closed, 1):
                st.write(f"{i}. {p['symbol']}: ${p['realized_pnl']:+,.2f}")

        with col2:
            st.markdown("**🔴 En Zararlı (Kapalı)**")
            worst_closed = sorted(closed, key=lambda x: x["realized_pnl"])[:5]
            for i, p in enumerate(worst_closed, 1):
                st.write(f"{i}. {p['symbol']}: ${p['realized_pnl']:+,.2f}")

    # Risk metrikleri
    st.divider()
    st.markdown("### ⚠️ Risk Metrikleri")
    render_risk_metrics(positions)


def render_equity_chart(metrics: list):
    """Equity curve grafiği"""
    if not metrics:
        return

    # Metrics'i zaman sırasına göre sırala (eski -> yeni)
    sorted_metrics = sorted(metrics, key=lambda x: x["timestamp"])

    timestamps = [m["timestamp"] for m in sorted_metrics]
    values = [m["total_portfolio_value"] for m in sorted_metrics]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=values,
            mode="lines",
            name="Portföy Değeri",
            line=dict(color="#1f77b4", width=2),
            fill="tozeroy",
            fillcolor="rgba(31, 119, 180, 0.1)",
        )
    )

    fig.update_layout(
        title="Portföy Değeri (USDT)",
        xaxis_title="Zaman",
        yaxis_title="Değer (USDT)",
        height=350,
        hovermode="x unified",
        template="plotly_white",
    )

    st.plotly_chart(fig, use_container_width=True)


def render_risk_metrics(positions: list):
    """Risk metrikleri"""
    open_pos = [p for p in positions if p["status"] == "OPEN"]

    if not open_pos:
        st.info("Açık pozisyon yok, risk metrikleri hesaplanamıyor.")
        return

    total_exposure = sum(p["entry_value_usd"] for p in open_pos)
    max_single = max(p["entry_value_usd"] for p in open_pos)
    avg_sl_dist = sum(
        (
            ((p["current_price"] - p["stop_loss_price"]) / p["current_price"] * 100)
            if p["side"] == "buy"
            else ((p["stop_loss_price"] - p["current_price"]) / p["current_price"] * 100)
        )
        for p in open_pos
    ) / len(open_pos)

    trailing_active = sum(1 for p in open_pos if p.get("trailing_activated"))
    tp_triggered_total = sum(p.get("current_tp_tier", 0) for p in open_pos)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Toplam Risk", f"${total_exposure:,.2f}")
    with col2:
        st.metric("En Büyük Pozisyon", f"${max_single:,.2f}")
    with col3:
        st.metric("Ort. SL Mesafesi", f"{avg_sl_dist:.1f}%")
    with col4:
        st.metric("Trailing Aktif", f"{trailing_active}/{len(open_pos)}")

    # Pozisyon bazlı risk detayı
    st.markdown("#### Pozisyon Bazlı Risk")
    risk_data = []
    for p in open_pos:
        sl_dist = (
            ((p["current_price"] - p["stop_loss_price"]) / p["current_price"] * 100)
            if p["side"] == "buy"
            else ((p["stop_loss_price"] - p["current_price"]) / p["current_price"] * 100)
        )
        risk_data.append(
            {
                "Sembol": p["symbol"],
                "Değer": f"${p['entry_value_usd']:,.2f}",
                "SL Mesafesi": f"{sl_dist:.1f}%",
                "TP Kademe": p["current_tp_tier"],
                "Trailing": "✅" if p.get("trailing_activated") else "❌",
            }
        )

    st.dataframe(pd.DataFrame(risk_data), use_container_width=True, hide_index=True)
