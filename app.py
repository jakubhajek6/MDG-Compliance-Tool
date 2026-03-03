"""
MDG Compliance Tool – hlavní vstupní bod aplikace.
Multipage Streamlit aplikace s login ochranou.
"""

import os
import streamlit as st
from pathlib import Path
from db.database import init_db
from modules.docgen import create_sample_templates

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


# ===== SIDEBAR =====
with st.sidebar:
    # ── Logo ──────────────────────────────────────────────────────────────────
    logo_path = Path("assets/logo.png")
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=True)
    else:
        st.markdown(
            f'<h2 style="color:{PRIMARY}; margin:0;">MDG</h2>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── Navigace ──────────────────────────────────────────────────────────────
    st.page_link("app.py",                 label="🏠 Domů")
    st.page_link("pages/1_ESM.py",         label="📋 ESM – Evidence skutečných majitelů")
    st.page_link("pages/2_Vizualizace.py", label="🔗 Vizualizace vztahů")
    st.page_link("pages/3_AML.py",         label="🔍 AML kontroly")
    st.page_link("pages/4_DataExport.py",  label="📊 Export dat pro MasT a MT")
    st.page_link("pages/5_Smlouvy.py",     label="📝 Návrh smluvní dokumentace")
    st.page_link("pages/6_Monitoring.py",  label="👁️ Monitoring změn v OR")
    st.page_link("pages/7_Riziko.py",      label="⚖️ Riziková klasifikace")

    st.markdown("---")

    # ── Patička sidebaru ──────────────────────────────────────────────────────
    st.markdown(
        '<div class="small-muted">MDG Compliance Tool v1.0</div>',
        unsafe_allow_html=True,
    )
    if st.button("🚪 Odhlásit", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()


# ===== HLAVNÍ STRÁNKA – DASHBOARD =====
st.markdown('<div class="breadcrumb">Domů</div>', unsafe_allow_html=True)
st.markdown("## MDG Compliance Tool")
st.markdown("Vítejte v interním compliance nástroji kanceláře MDG.")

st.markdown("---")

# Rychlý přehled
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown("### 📋 ESM")
    st.markdown("Evidence skutečných majitelů – rozkrytí vlastnické struktury přes ARES.")
    if st.button("Otevřít ESM", key="dash_esm"):
        st.switch_page("pages/1_ESM.py")

with col2:
    st.markdown("### 🔍 AML")
    st.markdown("Automatická AML prověrka – sankční seznamy, PEP, insolvence.")
    if st.button("Otevřít AML", key="dash_aml"):
        st.switch_page("pages/3_AML.py")

with col3:
    st.markdown("### 📊 Data Export")
    st.markdown("Export dat z ARES/OR do formátu pro MasT a Macrtime.")
    if st.button("Otevřít Export", key="dash_export"):
        st.switch_page("pages/4_DataExport.py")

with col4:
    st.markdown("### ⚖️ Riziko")
    st.markdown("Riziková klasifikace klienta dle ZAML §13.")
    if st.button("Otevřít Riziko", key="dash_risk"):
        st.switch_page("pages/7_Riziko.py")

st.markdown("---")

# Notifikace – nezpracované změny
from db.database import get_unprocessed_changes, get_clients
changes = get_unprocessed_changes()
if changes:
    st.warning(f"👁️ **{len(changes)}** nezpracovaných změn v OR – [přejít do Monitoringu](pages/6_Monitoring.py)")

clients = get_clients()
st.info(f"Sledovaných klientů: **{len(clients)}**")
