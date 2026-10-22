"""
Apex Scout - Token Table Component
Canlı token listesi ve skorları.
"""

import streamlit as st
import pandas as pd
from config.constants import DecisionAction


def render_token_table(tokens: list):
    """Token tablosunu render et"""
    st.subheader("🔍 Tarılan Token'lar")

    if not tokens:
        st.info("Henüz token bulunamadı. Tarama bekleyin veya ayarları kontrol edin.")
        return

    # Filtreler
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        action_filter = st.multiselect(
            "Aksiyon",
            options=[a.value for a in DecisionAction],
            default=[DecisionAction.PASS.value, DecisionAction.WATCH.value],
        )
    with col2:
        source_filter = st.multiselect(
            "Kaynak",
            options=["dexscreener", "pumpfunt"],
            default=["dexscreener", "pumpfunt"],
        )
    with col3:
        min_score = st.slider("Min Skor", 0, 100, 0)
    with col4:
        sort_by = st.selectbox("Sırala", ["Skor (Azalan)", "Skor (Artan)", "Likidite", "Yaş", "Hacim"])

    # Filtrele
    filtered = [
        t for t in tokens
        if t["decision_action"] in action_filter
        and t["source"] in source_filter
        and t["decision_score"] >= min_score
    ]

    # Sırala
    if sort_by == "Skor (Azalan)":
        filtered.sort(key=lambda x: x["decision_score"], reverse=True)
    elif sort_by == "Skor (Artan)":
        filtered.sort(key=lambda x: x["decision_score"])
    elif sort_by == "Likidite":
        filtered.sort(key=lambda x: x["liquidity_usd"], reverse=True)
    elif sort_by == "Yaş":
        filtered.sort(key=lambda x: x["age_hours"])
    elif sort_by == "Hacim":
        filtered.sort(key=lambda x: x["volume_24h"], reverse=True)

    st.caption(f"Gösterilen: {len(filtered)} / {len(tokens)} token")

    # Tablo verisi hazırla
    df_data = []
    for t in filtered:
        # Akksiyon badge
        action = t["decision_action"]
        if action == DecisionAction.PASS.value:
            action_display = "✅ PASS"
        elif action == DecisionAction.WATCH.value:
            action_display = "👁️ WATCH"
        else:
            action_display = "⏭️ SKIP"

        # Mint/Freeze durumu
        mint_status = "✅" if t["mint_renounced"] else "❌"
        freeze_status = "✅" if t["freeze_renounced"] else "❌"

        df_data.append({
            "Aksiyon": action_display,
            "Skor": f"{t['decision_score']:.1f}",
            "Sembol": t["symbol"],
            "İsim": t["name"][:20] + "..." if len(t["name"]) > 20 else t["name"],
            "Adres": t["address"],
            "Fiyat": f"${t['price_usd']:.8f}" if t['price_usd'] > 0 else "N/A",
            "Likidite": f"${t['liquidity_usd']:,.0f}",
            "Market Cap": f"${t['market_cap']:,.0f}",
            "24h Hacim": f"${t['volume_24h']:,.0f}",
            "Yaş (saat)": f"{t['age_hours']:.2f}",
            "Holder": t["holder_count"],
            "Top10%": f"{t['top_10_pct']:.1f}%",
            "Mint": mint_status,
            "Freeze": freeze_status,
            "Kaynak": t["source"].upper(),
            "Bulunma": t["discovered_at"].strftime("%H:%M:%S") if t["discovered_at"] else "N/A",
        })

    if df_data:
        df = pd.DataFrame(df_data)

        # Renklendirme
        def highlight_action(row):
            if "PASS" in row["Aksiyon"]:
                return ["background-color: #d4edda"] * len(row)
            elif "WATCH" in row["Aksiyon"]:
                return ["background-color: #fff3cd"] * len(row)
            else:
                return ["background-color: #f8d7da"] * len(row)

        styled_df = df.style.apply(highlight_action, axis=1)

        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Aksiyon": st.column_config.TextColumn(width="small"),
                "Skor": st.column_config.NumberColumn(format="%.1f", width="small"),
                "Sembol": st.column_config.TextColumn(width="small"),
                "İsim": st.column_config.TextColumn(width="medium"),
                "Adres": st.column_config.TextColumn(width="small"),
                "Fiyat": st.column_config.TextColumn(width="small"),
                "Likidite": st.column_config.TextColumn(width="small"),
                "Market Cap": st.column_config.TextColumn(width="small"),
                "24h Hacim": st.column_config.TextColumn(width="small"),
                "Yaş (saat)": st.column_config.TextColumn(width="small"),
                "Holder": st.column_config.NumberColumn(width="small"),
                "Top10%": st.column_config.TextColumn(width="small"),
                "Mint": st.column_config.TextColumn(width="small"),
                "Freeze": st.column_config.TextColumn(width="small"),
                "Kaynak": st.column_config.TextColumn(width="small"),
                "Bulunma": st.column_config.TextColumn(width="small"),
            },
        )

    # Detay görüntüleme
    if filtered:
        st.divider()
        selected_symbol = st.selectbox("Detay için token seçin:", [t["symbol"] for t in filtered])
        selected = next(t for t in filtered if t["symbol"] == selected_symbol)

        with st.expander(f"📋 {selected['symbol']} Detayları", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Skor", f"{selected['decision_score']:.1f}")
                st.metric("Aksiyon", selected["decision_action"])
                st.metric("Likidite", f"${selected['liquidity_usd']:,.0f}")
                st.metric("Market Cap", f"${selected['market_cap']:,.0f}")
                st.metric("24h Hacim", f"${selected['volume_24h']:,.0f}")
            with col2:
                st.metric("Yaş", f"{selected['age_hours']:.2f} saat")
                st.metric("Holder", selected["holder_count"])
                st.metric("Top 10%", f"{selected['top_10_pct']:.1f}%")
                st.metric("Mint Renounced", "Evet" if selected["mint_renounced"] else "Hayır")
                st.metric("Freeze Renounced", "Evet" if selected["freeze_renounced"] else "Hayır")

            if selected["decision_reasons"]:
                st.markdown("**Karar Nedenleri:**")
                for reason in selected["decision_reasons"]:
                    st.write(f"• {reason}")