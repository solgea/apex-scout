"""
Apex Scout - Positions Component
Açık pozisyonlar, PnL, TP/SL seviyeleri.
"""

from datetime import datetime

import pandas as pd
import streamlit as st


def render_positions(positions: list):
    """Pozisyon tablosunu render et"""
    st.subheader("📊 Açık Pozisyonlar")

    open_positions = [p for p in positions if p["status"] == "OPEN"]
    closed_positions = [p for p in positions if p["status"] != "OPEN"]

    if not open_positions and not closed_positions:
        st.info("Açık pozisyon yok. PASS kararları alındığında pozisyon açılır.")
        return

    # Açık pozisyonlar
    if open_positions:
        st.markdown(f"### 🟢 Açık Pozisyonlar ({len(open_positions)})")

        df_data = []
        for p in open_positions:
            # PnL rengi
            pnl_pct = p["unrealized_pnl_pct"]
            pnl_color = "🟢" if pnl_pct >= 0 else "🔴"

            # TP durumu
            tp_info = ""
            tiers = p.get("take_profit_tiers", [])
            for i, tier in enumerate(tiers):
                status = "✅" if tier.get("triggered") else "⏳"
                tp_info += (
                    f"{status} TP{i+1}: +{tier['profit_pct']:.0f}% ({tier['sell_pct']:.0f}%)  "
                )

            # Trailing durumu
            trailing_info = ""
            if p.get("trailing_activated") and p.get("trailing_stop_price"):
                trailing_info = f"📉 Trailing: ${p['trailing_stop_price']:.6f}"

            df_data.append(
                {
                    "Sembol": p["symbol"],
                    "Yön": p["side"],
                    "Giriş": f"${p['entry_price']:.6f}",
                    "Güncel": f"${p['current_price']:.6f}",
                    "Miktar": f"{p['quantity']:.4f}",
                    "Değer": f"${p['entry_value_usd']:,.2f}",
                    f"{pnl_color} PnL": f"${p['unrealized_pnl']:+,.2f} ({pnl_pct:+.2f}%)",
                    "Realized": f"${p['realized_pnl']:+,.2f}",
                    "SL": f"${p['stop_loss_price']:.6f}",
                    "TP Kademeleri": tp_info.strip(),
                    "Trailing": trailing_info,
                    "Durum": p["status"],
                    "Açılış": p["opened_at"].strftime("%H:%M:%S") if p["opened_at"] else "N/A",
                }
            )

        df = pd.DataFrame(df_data)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

        # Pozisyon detayı
        st.divider()
        selected_symbol = st.selectbox(
            "Detay için pozisyon seçin:",
            [p["symbol"] for p in open_positions],
            key="pos_detail_select",
        )
        selected = next(p for p in open_positions if p["symbol"] == selected_symbol)

        with st.expander(f"📋 {selected['symbol']} Pozisyon Detayı", expanded=True):
            render_position_detail(selected)

    # Kapalı pozisyonlar (son 20)
    if closed_positions:
        with st.expander(f"🔴 Kapalı Pozisyonlar ({len(closed_positions)})", expanded=False):
            recent_closed = sorted(
                closed_positions, key=lambda x: x["closed_at"] or datetime.min, reverse=True
            )[:20]

            df_data = []
            for p in recent_closed:
                total_pnl = p["realized_pnl"] + p["unrealized_pnl"]
                pnl_color = "🟢" if total_pnl >= 0 else "🔴"
                close_reason = p["status"]

                df_data.append(
                    {
                        "Sembol": p["symbol"],
                        "Yön": p["side"],
                        "Giriş": f"${p['entry_price']:.6f}",
                        "Kapanış": f"${p['current_price']:.6f}",
                        f"{pnl_color} Net PnL": f"${total_pnl:+,.2f}",
                        "Neden": close_reason,
                        "Açılış": (
                            p["opened_at"].strftime("%m/%d %H:%M") if p["opened_at"] else "N/A"
                        ),
                        "Kapanış Zamanı": (
                            p["closed_at"].strftime("%m/%d %H:%M") if p["closed_at"] else "N/A"
                        ),
                    }
                )

            df = pd.DataFrame(df_data)
            st.dataframe(df, use_container_width=True, hide_index=True)


def render_position_detail(p: dict):
    """Pozisyon detay modal"""
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Temel Bilgiler**")
        st.write(f"📊 Sembol: {p['symbol']}")
        st.write(f"📈 Yön: {p['side']}")
        st.write(f"💰 Giriş Fiyatı: ${p['entry_price']:.6f}")
        st.write(f"📍 Güncel Fiyat: ${p['current_price']:.6f}")
        st.write(f"📦 Miktar: {p['quantity']:.6f}")
        st.write(f"💵 Pozisyon Değeri: ${p['entry_value_usd']:,.2f}")

    with col2:
        st.markdown("**Kar/Zarar**")
        pnl_color = "green" if p["unrealized_pnl"] >= 0 else "red"
        st.markdown(
            f"<span style='color:{pnl_color}'>📊 Unrealized: ${p['unrealized_pnl']:+,.2f} ({p['unrealized_pnl_pct']:+.2f}%)</span>",
            unsafe_allow_html=True,
        )
        st.write(f"✅ Realized: ${p['realized_pnl']:+,.2f}")
        st.write(f"📉 Toplam: ${p['unrealized_pnl'] + p['realized_pnl']:+,.2f}")

    with col3:
        st.markdown("**Risk Yönetimi**")
        st.write(f"🛑 Stop-Loss: ${p['stop_loss_price']:.6f}")
        sl_dist = (
            ((p["current_price"] - p["stop_loss_price"]) / p["current_price"] * 100)
            if p["side"] == "buy"
            else ((p["stop_loss_price"] - p["current_price"]) / p["current_price"] * 100)
        )
        st.write(f"   SL Mesafesi: {sl_dist:.1f}%")

        if p.get("trailing_stop_price"):
            st.write(f"📉 Trailing Stop: ${p['trailing_stop_price']:.6f}")
            trail_dist = (
                ((p["current_price"] - p["trailing_stop_price"]) / p["current_price"] * 100)
                if p["side"] == "buy"
                else ((p["trailing_stop_price"] - p["current_price"]) / p["current_price"] * 100)
            )
            st.write(f"   Trailing Mesafesi: {trail_dist:.1f}%")
            st.write(f"   Aktif: {'Evet' if p['trailing_activated'] else 'Hayır'}")

    # TP Kademeleri
    st.markdown("**🎯 Take-Profit Kademeleri**")
    tiers = p.get("take_profit_tiers", [])
    if tiers:
        tp_df = []
        for i, tier in enumerate(tiers):
            triggered = tier.get("triggered", False)
            tp_df.append(
                {
                    "Kademe": f"TP{i+1}",
                    "Hedef": f"+{tier['profit_pct']:.0f}%",
                    "Satılacak": f"%{tier['sell_pct']:.0f}",
                    "Durum": "✅ Tetiklendi" if triggered else "⏳ Bekliyor",
                    "Tetikleme Fiyatı": (
                        f"${p['entry_price'] * (1 + tier['profit_pct']/100):.6f}"
                        if p["side"] == "buy"
                        else f"${p['entry_price'] * (1 - tier['profit_pct']/100):.6f}"
                    ),
                }
            )
        st.dataframe(pd.DataFrame(tp_df), hide_index=True, use_container_width=True)
    else:
        st.write("TP kademesi tanımlı değil.")
