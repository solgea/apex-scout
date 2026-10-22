"""
Apex Scout - History Component
İşlem geçmişi, filtreleme, export.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from io import BytesIO


def render_history(trades: list):
    """İşlem geçmişi tablosu"""
    st.subheader("📜 İşlem Geçmişi")

    if not trades:
        st.info("Henüz işlem yok.")
        return

    # Filtreler
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        side_filter = st.multiselect(
            "Yön", ["buy", "sell"], default=["buy", "sell"], key="hist_side"
        )
    with col2:
        type_filter = st.multiselect(
            "Tür",
            ["Normal", "Take Profit", "Stop Loss", "Trailing Stop"],
            default=["Normal", "Take Profit", "Stop Loss", "Trailing Stop"],
            key="hist_type"
        )
    with col3:
        days = st.selectbox("Son", [1, 3, 7, 30, 90], index=2, key="hist_days")
    with col4:
        if st.button("📥 CSV İndir", use_container_width=True):
            df = pd.DataFrame(trades)
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "CSV Kaydet",
                csv,
                f"apex_scout_trades_{datetime.now().strftime('%Y%m%d')}.csv",
                "text/csv",
                use_container_width=True,
            )

    # Filtrele
    cutoff = datetime.utcnow() - timedelta(days=days)
    filtered = []
    for t in trades:
        if t["side"] not in side_filter:
            continue
        if t["timestamp"] < cutoff:
            continue

        # Tür filtresi
        trade_type = "Normal"
        if t.get("is_take_profit"):
            trade_type = "Take Profit"
        elif t.get("is_stop_loss"):
            trade_type = "Stop Loss"
        elif t.get("is_trailing_stop"):
            trade_type = "Trailing Stop"

        if trade_type not in type_filter:
            continue

        t["trade_type"] = trade_type
        filtered.append(t)

    st.caption(f"Gösterilen: {len(filtered)} / {len(trades)} işlem")

    # Tablo
    df_data = []
    for t in filtered:
        pnl_est = 0  # Basit tahmin
        df_data.append({
            "Zaman": t["timestamp"].strftime("%m/%d %H:%M:%S") if t["timestamp"] else "N/A",
            "Sembol": t["symbol"],
            "Yön": "🟢 AL" if t["side"] == "buy" else "🔴 SAT",
            "Tür": t["trade_type"],
            "Fiyat": f"${t['price']:.6f}",
            "Miktar": f"{t['quantity']:.6f}",
            "Değer": f"${t['price'] * t['quantity']:,.2f}",
            "Komisyon": f"${t['fee']:.4f}",
            "TP Kademe": f"TP{t['tp_tier_index']+1}" if t.get("tp_tier_index") is not None else "-",
        })

    if df_data:
        df = pd.DataFrame(df_data)

        # Renklendirme
        def highlight_type(row):
            if row["Tür"] == "Take Profit":
                return ["background-color: #d4edda"] * len(row)
            elif row["Tür"] == "Stop Loss":
                return ["background-color: #f8d7da"] * len(row)
            elif row["Tür"] == "Trailing Stop":
                return ["background-color: #cce5ff"] * len(row)
            return [""] * len(row)

        styled_df = df.style.apply(highlight_type, axis=1)

        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            height=500,
        )

    # Özet istatistikler
    if filtered:
        st.divider()
        render_trade_summary(filtered)


def render_trade_summary(trades: list):
    """İşlem özeti"""
    st.markdown("### 📊 Özet İstatistikler")

    buys = [t for t in trades if t["side"] == "buy"]
    sells = [t for t in trades if t["side"] == "sell"]

    tp_trades = [t for t in trades if t.get("is_take_profit")]
    sl_trades = [t for t in trades if t.get("is_stop_loss")]
    trail_trades = [t for t in trades if t.get("is_trailing_stop")]

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("Toplam İşlem", len(trades))
    with col2:
        st.metric("Alım", len(buys))
    with col3:
        st.metric("Satım", len(sells))
    with col4:
        st.metric("TP Kapanış", len(tp_trades))
    with col5:
        st.metric("SL Kapanış", len(sl_trades))

    # TP/SL oranı
    if len(tp_trades) + len(sl_trades) > 0:
        tp_ratio = len(tp_trades) / (len(tp_trades) + len(sl_trades)) * 100
        st.metric("TP / (TP+SL) Oranı", f"{tp_ratio:.1f}%")

    # Günlük breakdown
    st.markdown("#### Günlük İşlem Sayısı")
    daily_counts = {}
    for t in trades:
        day = t["timestamp"].strftime("%Y-%m-%d") if t["timestamp"] else "Unknown"
        daily_counts[day] = daily_counts.get(day, 0) + 1

    if daily_counts:
        daily_df = pd.DataFrame(
            [{"Tarih": k, "İşlem": v} for k, v in sorted(daily_counts.items(), reverse=True)]
        )
        st.bar_chart(daily_df.set_index("Tarih"))