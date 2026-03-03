"""
Modul 7 – Riziková klasifikace klienta (ZAML)
Automatický výpočet rizikového skóre dle zákona č. 253/2008 Sb. §13.
"""

import json
from datetime import datetime
from io import BytesIO

import streamlit as st
import plotly.graph_objects as go

from modules.ares_api import fetch_ares_vr, fetch_ares_basic, extract_company_info, norm_ico
from modules.risk_scoring import calculate_risk_score
from modules.aml_checks import run_aml_check
from db.database import (
    init_db, save_risk_score, get_latest_risk_score, log_audit,
    get_clients, add_client,
)
from modules.auth import require_login

# ===== PAGE CONFIG =====
st.set_page_config(page_title="MDG – Riziková klasifikace", page_icon="⚖️", layout="wide")
init_db()
require_login()

PRIMARY = "#2EA39C"
CSS = f"""
<style>
.stButton > button, .stDownloadButton > button {{
  background-color: {PRIMARY} !important; color: white !important; border: 1px solid {PRIMARY} !important;
}}
div.stProgress > div > div {{ background-color: {PRIMARY} !important; }}
.breadcrumb {{ color: #888; font-size: 0.85rem; margin-bottom: 0.5rem; }}
.risk-low {{ background-color: #d4edda; border-radius: 8px; padding: 16px; margin: 8px 0; }}
.risk-medium {{ background-color: #fff3cd; border-radius: 8px; padding: 16px; margin: 8px 0; }}
.risk-high {{ background-color: #f8d7da; border-radius: 8px; padding: 16px; margin: 8px 0; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

st.markdown('<div class="breadcrumb">Domů / Riziková klasifikace</div>', unsafe_allow_html=True)
st.markdown("## ⚖️ Riziková klasifikace klienta (ZAML)")
st.markdown("Automatický výpočet rizikového skóre dle zákona č. 253/2008 Sb. §13.")

st.markdown("---")

# ===== Vstupy =====
col1, col2, col3 = st.columns([2, 2, 2])
with col1:
    ico_input = st.text_input("IČO společnosti", placeholder="12345678")
with col2:
    client_since = st.date_input("Klient od", value=None, help="Datum navázání obchodního vztahu")
with col3:
    ownership_depth = st.number_input("Hloubka vlastnické struktury", 0, 10, 1,
                                      help="Kolik úrovní vlastníků má společnost")

use_existing_aml = st.checkbox("Použít výsledky poslední AML kontroly (pokud existují)", value=True)

if st.button("📊 Vypočítat rizikové skóre", type="primary"):
    if not ico_input.strip():
        st.error("Zadejte IČO.")
    else:
        ico_str = norm_ico(ico_input.strip())

        with st.spinner("Načítám data z ARES..."):
            vr_data = fetch_ares_vr(ico_str)
            basic_data = fetch_ares_basic(ico_str)

        if not vr_data and not basic_data:
            st.error(f"IČO {ico_str} nebylo nalezeno v ARES.")
        else:
            company_info = extract_company_info(vr_data or {}, basic_data)
            if not company_info.get("nazev") and basic_data:
                company_info["nazev"] = basic_data.get("obchodniJmeno", "") or ""

            # AML výsledky
            aml_results = None
            if use_existing_aml and st.session_state.get("last_aml_results"):
                aml_results = st.session_state["last_aml_results"]
                st.info("Používám existující výsledky AML kontroly.")
            else:
                with st.spinner("Provádím AML kontrolu..."):
                    aml_results = run_aml_check(
                        name=company_info.get("nazev", ""),
                        ico=ico_str,
                        entity_type="PO",
                    )
                    # Také kontrola statutárů
                    for stat in (company_info.get("statutarni_organ") or [])[:3]:
                        if stat.get("typ") == "FO":
                            stat_aml = run_aml_check(
                                name=stat["jmeno"],
                                entity_type="FO",
                            )
                            # Merge výsledky
                            if stat_aml.get("total_hits", 0) > 0:
                                for check in stat_aml.get("checks", []):
                                    aml_results["checks"].append(check)
                                    aml_results["total_hits"] += check.get("hits", 0)

            # Datum klienta
            client_since_str = None
            if client_since:
                client_since_str = client_since.isoformat()

            # Výpočet
            risk = calculate_risk_score(
                ico=ico_str,
                company_info=company_info,
                aml_results=aml_results,
                client_since=client_since_str,
                ownership_depth=ownership_depth,
            )

            # Uložit
            save_risk_score(ico_str, risk["total_score"], risk["category"],
                            {"factors": risk["factors"], "recommendations": risk["recommendations"]})
            add_client(ico_str, company_info.get("nazev", ""))
            log_audit("Riziko", "calculate", ico=ico_str,
                      entity_name=company_info.get("nazev", ""),
                      details=f"score={risk['total_score']}, category={risk['category']}")

            st.session_state["last_risk_result"] = risk
            st.session_state["last_risk_company"] = company_info

# ===== Zobrazení výsledku =====
risk = st.session_state.get("last_risk_result")
company_info = st.session_state.get("last_risk_company")

if risk and company_info:
    st.markdown("---")
    st.subheader(f"Výsledek: {company_info.get('nazev', 'N/A')}")

    # Gauge chart
    col_g, col_d = st.columns([1, 1])
    with col_g:
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=risk["total_score"],
            title={"text": "Rizikové skóre", "font": {"size": 20}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 2},
                "bar": {"color": risk["color"]},
                "steps": [
                    {"range": [0, 30], "color": "#d4edda"},
                    {"range": [30, 60], "color": "#fff3cd"},
                    {"range": [60, 100], "color": "#f8d7da"},
                ],
                "threshold": {
                    "line": {"color": "black", "width": 4},
                    "thickness": 0.75,
                    "value": risk["total_score"],
                },
            },
        ))
        fig.update_layout(height=350, margin=dict(l=20, r=20, t=50, b=20))
        st.plotly_chart(fig, use_container_width=True)

    with col_d:
        # Kategorie
        cat = risk["category"]
        if cat == "Nízké":
            st.markdown(f'<div class="risk-low"><h3>🟢 Riziko: {cat}</h3>'
                        f'<p>Skóre: {risk["total_score"]}/100</p>'
                        f'<p>Frekvence přezkumu: {risk["review_frequency"]}</p></div>',
                        unsafe_allow_html=True)
        elif cat == "Střední":
            st.markdown(f'<div class="risk-medium"><h3>🟡 Riziko: {cat}</h3>'
                        f'<p>Skóre: {risk["total_score"]}/100</p>'
                        f'<p>Frekvence přezkumu: {risk["review_frequency"]}</p></div>',
                        unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="risk-high"><h3>🔴 Riziko: {cat}</h3>'
                        f'<p>Skóre: {risk["total_score"]}/100</p>'
                        f'<p>Frekvence přezkumu: {risk["review_frequency"]}</p></div>',
                        unsafe_allow_html=True)

        st.markdown(f"**Datum hodnocení:** {risk.get('score_date', '')}")

    # Faktory
    st.markdown("---")
    st.subheader("Rizikové faktory")

    if risk["factors"]:
        for f in risk["factors"]:
            st.markdown(
                f"- **{f['factor']}** — hodnota: {f['value']} — skóre: **{f['score']} b.**"
            )
    else:
        st.info("Žádné rizikové faktory nebyly identifikovány.")

    # Doporučení
    st.markdown("---")
    st.subheader("Doporučení opatření")

    for rec in risk.get("recommendations", []):
        if "POZOR" in rec:
            st.error(rec)
        else:
            st.markdown(f"- {rec}")

    # Export
    st.markdown("---")
    st.download_button(
        "📥 Stáhnout rizikové hodnocení (JSON)",
        data=json.dumps({
            "company": company_info,
            "risk": risk,
        }, ensure_ascii=False, indent=2),
        file_name=f"risk_{company_info.get('ico', 'export')}_{datetime.now().strftime('%Y%m%d')}.json",
        mime="application/json",
    )

# ===== Historie hodnocení =====
st.markdown("---")
st.subheader("Poslední hodnocení klientů")

clients = get_clients()
if clients:
    for client in clients[:20]:
        score = get_latest_risk_score(client["ico"])
        if score:
            cat = score.get("category", "N/A")
            icon = "🟢" if cat == "Nízké" else ("🟡" if cat == "Střední" else "🔴")
            st.markdown(
                f"{icon} **{client.get('nazev', client['ico'])}** – "
                f"Skóre: {score.get('total_score', 'N/A')}/100 – "
                f"Kategorie: {cat} – "
                f"Datum: {score.get('score_date', 'N/A')[:10]}"
            )
        else:
            st.markdown(f"⬜ **{client.get('nazev', client['ico'])}** – dosud nehodnoceno")
else:
    st.info("Zatím žádní klienti s rizikovým hodnocením.")
