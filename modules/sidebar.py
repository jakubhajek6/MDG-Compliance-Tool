"""
MDG Compliance Tool – shared sidebar component.

All pages must call render_sidebar() immediately after require_login() so the
navigation and branding look identical regardless of which page is active.

Why a dedicated module and not inline code in each page:
  Streamlit pages in pages/ are independent Python scripts. The sidebar built
  inside app.py is only visible when app.py is the active page. Every other page
  is a fresh script execution and must render the sidebar itself. Having a single
  function here avoids copy-paste drift and makes future changes (e.g. adding a
  new page) a one-line edit in one file.
"""

from pathlib import Path

import streamlit as st

# Brand colour – kept in sync with app.py and .streamlit/config.toml
PRIMARY = "#2EA39C"


def render_sidebar() -> None:
    """Render the branded navigation sidebar and hide the auto-generated page list.

    Streamlit automatically builds a plain sidebar nav from the files in pages/.
    That auto-nav shows abbreviated names and cannot be styled, so we suppress it
    with CSS and replace it entirely with st.page_link() calls that we control.

    Must be called after require_login() (so unauthenticated users never see the
    navigation) and after st.set_page_config() (which must be the very first call).
    """

    # Suppress Streamlit's auto-generated page list in the sidebar.
    # This CSS is injected on every page that calls this function, ensuring the
    # auto-nav stays hidden regardless of which page is currently active.
    st.markdown(
        "<style>[data-testid='stSidebarNav'] { display: none !important; }</style>",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        # ── Logo ──────────────────────────────────────────────────────────────
        logo_path = Path("assets/logo.png")
        if logo_path.exists():
            st.image(str(logo_path), use_container_width=True)
        else:
            st.markdown(
                f'<h2 style="color:{PRIMARY}; margin:0 0 0.25rem 0;">MDG</h2>',
                unsafe_allow_html=True,
            )

        st.markdown("---")

        # ── Navigation ────────────────────────────────────────────────────────
        # st.page_link() automatically highlights the currently active page,
        # so no manual "active" state management is needed.
        st.page_link("app.py",                 label="🏠 Domů")
        st.page_link("pages/1_ESM.py",         label="📋 ESM – Evidence skutečných majitelů")
        st.page_link("pages/2_Vizualizace.py", label="🔗 Vizualizace vztahů")
        st.page_link("pages/3_AML.py",         label="🔍 AML kontroly")
        st.page_link("pages/4_DataExport.py",  label="📊 Export dat pro MasT a MT")
        st.page_link("pages/5_Smlouvy.py",     label="📝 Návrh smluvní dokumentace")
        st.page_link("pages/6_Monitoring.py",  label="👁️ Monitoring změn v OR")
        st.page_link("pages/7_Riziko.py",      label="⚖️ Riziková klasifikace")

        st.markdown("---")

        # ── Footer ────────────────────────────────────────────────────────────
        st.markdown(
            '<div style="color:#555; font-size:0.85rem; margin-bottom:0.5rem;">'
            "MDG Compliance Tool v1.0</div>",
            unsafe_allow_html=True,
        )
        if st.button("🚪 Odhlásit", use_container_width=True):
            st.session_state["authenticated"] = False
            st.rerun()
