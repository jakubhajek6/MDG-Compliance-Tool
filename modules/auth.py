"""
MDG Compliance Tool – authentication guard.

Each page must call require_login() as its first action after st.set_page_config().
Because Streamlit multipage pages are independent Python scripts, the auth check
in app.py does NOT protect them – each page must enforce it independently.
"""

import streamlit as st


def require_login() -> None:
    """Stop rendering the page if the user is not authenticated.

    Streamlit stores session state across all pages, so the ``authenticated``
    flag set in app.py is available here.  If the flag is missing or False the
    user sees a short error message with a link back to the login page, and
    st.stop() prevents any further content from being rendered.

    Must be called AFTER st.set_page_config() (which itself must be the very
    first Streamlit call in the script).
    """
    if not st.session_state.get("authenticated"):
        st.error("Pro přístup k této stránce se musíte nejprve přihlásit.")
        st.page_link("app.py", label="Přejít na přihlášení →")
        st.stop()
