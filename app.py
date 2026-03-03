"""
MDG Compliance Tool – hlavní vstupní bod aplikace.
Multipage Streamlit aplikace s login ochranou.
"""

import os
import streamlit as st
from pathlib import Path
from db.database import init_db
from modules.docgen import create_sample_templates
from modules.sidebar import render_sidebar

# ===== PAGE CONFIG =====
st.set_page_config(
    page_title="MDG Compliance Tool",
    page_icon="favicon.png" if Path("favicon.png").exists() else "🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===== Inicializace DB a šablon =====
init_db()
create_sample_templates()

# ===== CSS THEME =====
# Brand colour: RGB 46 / 163 / 156
PRIMARY = "#2EA39C"
PRIMARY_DARK = "#24857f"   # ~15 % darker, used for hover states

CSS = f"""
<style>
/* ── Always hide Streamlit's auto-generated sidebar page list.
       We build the sidebar manually below so the auto-list is a duplicate. ── */
[data-testid="stSidebarNav"] {{ display: none !important; }}

/* ── Buttons ── */
.stButton > button, .stDownloadButton > button {{
    background-color: {PRIMARY} !important;
    color: white !important;
    border: 1px solid {PRIMARY} !important;
    border-radius: 6px !important;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
    background-color: {PRIMARY_DARK} !important;
}}

/* ── Sliders ── */
[data-testid="stSlider"] > div > div > div > div {{
    background-color: {PRIMARY} !important;
}}

/* ── Radio & checkbox accent ── */
input[type="radio"]:checked + label::before,
input[type="checkbox"]:checked + label::before {{
    background-color: {PRIMARY} !important;
    border-color: {PRIMARY} !important;
}}

/* ── Progress bar ── */
div.stProgress > div > div {{
    background-color: {PRIMARY} !important;
}}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {{
    background-color: #F4FBFB;
    border-right: 2px solid {PRIMARY};
}}
section[data-testid="stSidebar"] .stMarkdown h1 {{
    color: {PRIMARY};
    font-size: 1.3rem;
}}
/* Active page link highlight in sidebar */
[data-testid="stSidebarNav"] a[aria-current="page"],
section[data-testid="stSidebar"] a[aria-current="page"] {{
    color: {PRIMARY} !important;
    font-weight: bold;
}}

/* ── Status colours ── */
.status-green  {{ color: #28a745; font-weight: bold; }}
.status-yellow {{ color: #e6a817; font-weight: bold; }}
.status-red    {{ color: #dc3545; font-weight: bold; }}

/* ── Misc helpers ── */
.small-muted {{ color: #555; font-size: 0.88rem; }}
.breadcrumb  {{ color: #888; font-size: 0.85rem; margin-bottom: 0.5rem; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ===== AUTENTIZACE =====
def check_password() -> bool:
    """Jednoduchá session-based autentizace."""
    if st.session_state.get("authenticated"):
        return True

    # Heslo z environment variable nebo secrets
    correct_password = os.environ.get("MDG_PASSWORD", "")
    if not correct_password:
        try:
            correct_password = st.secrets.get("password", "mdg2024")
        except Exception:
            correct_password = "mdg2024"

    st.markdown("## 🔐 MDG Compliance Tool")
    st.markdown("Přihlaste se pro přístup k aplikaci.")
    password = st.text_input("Heslo", type="password", key="login_password")
    if st.button("Přihlásit", type="primary"):
        if password == correct_password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Nesprávné heslo.")
    return False


if not check_password():
    st.stop()

render_sidebar()

# ===== DASHBOARD =====
import pandas as pd
from db.database import get_unprocessed_changes, get_clients, get_aml_checks
from datetime import date

st.markdown('<div class="breadcrumb">Domů</div>', unsafe_allow_html=True)
st.markdown("## 📊 Přehled stavu")
st.markdown("---")

# ── Načtení dat ────────────────────────────────────────────────────────────────
client_list = get_clients()
or_changes  = get_unprocessed_changes()
aml_all     = get_aml_checks(limit=500)

# Counts for KPIs
aml_red   = [c for c in aml_all if str(c.get("result_status", "")).upper() in ("RED", "ČERVENÁ", "POZOR")]
aml_today = [c for c in aml_all if c.get("check_date", "").startswith(str(date.today()))]

# ── KPI metriky ────────────────────────────────────────────────────────────────
kpi1, kpi2, kpi3, kpi4 = st.columns(4)

with kpi1:
    st.metric("Sledovaní klienti", len(client_list))
with kpi2:
    st.metric("⚠️ Nezpracované změny OR" if or_changes else "Nezpracované změny OR", len(or_changes))
with kpi3:
    st.metric("AML kontroly dnes", len(aml_today))
with kpi4:
    st.metric("🚨 Rizikové výsledky" if aml_red else "Rizikové výsledky", len(aml_red))

st.markdown("---")

col_left, col_right = st.columns(2)

# ── Nezpracované změny OR ──────────────────────────────────────────────────────
with col_left:
    st.subheader("👁️ Nezpracované změny v OR")
    if not or_changes:
        st.success("Všechny změny zpracovány.")
    else:
        df_changes = pd.DataFrame(or_changes[:10])[["ico", "detected_date", "change_type", "old_value", "new_value"]]
        df_changes.columns = ["IČO", "Datum", "Typ změny", "Původní hodnota", "Nová hodnota"]
        st.dataframe(df_changes, use_container_width=True, hide_index=True)
        if st.button("→ Přejít do Monitoringu", key="dash_to_monitoring"):
            st.switch_page("pages/6_Monitoring.py")

# ── Poslední AML kontroly ──────────────────────────────────────────────────────
with col_right:
    st.subheader("🔍 Posledních 5 AML kontrol")
    if not aml_all:
        st.info("Zatím nebyly provedeny žádné AML kontroly.")
    else:
        df_aml = pd.DataFrame(aml_all[:5])[["entity_name", "ico", "check_date", "result_status"]]
        df_aml.columns = ["Entita", "IČO", "Datum kontroly", "Výsledek"]
        st.dataframe(df_aml, use_container_width=True, hide_index=True)
        if st.button("→ Přejít do AML", key="dash_to_aml"):
            st.switch_page("pages/3_AML.py")

