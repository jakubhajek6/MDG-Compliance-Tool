"""
Modul 5 – Návrh smluvní dokumentace
Automatické předvyplnění Word šablon daty klienta z OR/ARES.
"""

import zipfile
from datetime import datetime
from io import BytesIO

import streamlit as st

from modules.ares_api import fetch_ares_vr, fetch_ares_basic, extract_company_info, norm_ico
from modules.docgen import (
    get_available_templates, build_placeholders, fill_template,
    generate_all_documents, create_sample_templates,
)
from db.database import init_db, log_audit
from modules.auth import require_login

# ===== PAGE CONFIG =====
st.set_page_config(page_title="MDG – Smlouvy", page_icon="📝", layout="wide")
init_db()
require_login()
create_sample_templates()

PRIMARY = "#2EA39C"
CSS = f"""
<style>
.stButton > button, .stDownloadButton > button {{
  background-color: {PRIMARY} !important; color: white !important; border: 1px solid {PRIMARY} !important;
}}
div.stProgress > div > div {{ background-color: {PRIMARY} !important; }}
.breadcrumb {{ color: #888; font-size: 0.85rem; margin-bottom: 0.5rem; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

st.markdown('<div class="breadcrumb">Domů / Návrh smluvní dokumentace</div>', unsafe_allow_html=True)
st.markdown("## 📝 Návrh smluvní dokumentace")
st.markdown("Automatické předvyplnění Word šablon daty klienta z ARES/OR.")

st.markdown("---")

# ===== Vstupy =====
ico_input = st.text_input("IČO klienta", placeholder="12345678")

if st.button("📥 Načíst data klienta", type="primary"):
    if not ico_input.strip():
        st.error("Zadejte IČO.")
    else:
        with st.spinner("Načítám data z ARES..."):
            ico_str = norm_ico(ico_input.strip())
            vr_data = fetch_ares_vr(ico_str)
            basic_data = fetch_ares_basic(ico_str)

        if not vr_data and not basic_data:
            st.error(f"IČO {ico_str} nebylo nalezeno v ARES.")
        else:
            info = extract_company_info(vr_data or {}, basic_data)
            if not info.get("nazev") and basic_data:
                info["nazev"] = basic_data.get("obchodniJmeno", "") or ""
            if not info.get("ico"):
                info["ico"] = ico_str

            st.session_state["smlouvy_company_info"] = info
            st.success(f"Data načtena: **{info.get('nazev', 'N/A')}**")
            log_audit("Smlouvy", "fetch", ico=ico_str, entity_name=info.get("nazev", ""))

# ===== Zobrazení dat a generování =====
company_info = st.session_state.get("smlouvy_company_info")
if company_info:
    st.markdown("---")
    st.subheader("Data klienta")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Název:** {company_info.get('nazev', '')}")
        st.markdown(f"**IČO:** {company_info.get('ico', '')}")
        st.markdown(f"**DIČ:** {company_info.get('dic', '')}")
        st.markdown(f"**Právní forma:** {company_info.get('pravni_forma', '')}")
    with col2:
        st.markdown(f"**Sídlo:** {company_info.get('sidlo_ulice', '')}, {company_info.get('sidlo_mesto', '')} {company_info.get('sidlo_psc', '')}")
        st.markdown(f"**Datová schránka:** {company_info.get('datova_schranka', '')}")
        # Jednatel
        for s in (company_info.get("statutarni_organ") or []):
            if s.get("typ") == "FO":
                st.markdown(f"**Jednatel:** {s.get('jmeno', '')} ({s.get('funkce', '')})")
                break

    # Placeholdery
    placeholders = build_placeholders(company_info)

    with st.expander("Zobrazit/upravit placeholdery"):
        edited_placeholders = {}
        for key, val in placeholders.items():
            edited_placeholders[key] = st.text_input(key, value=val, key=f"ph_{key}")
        placeholders = edited_placeholders

    st.markdown("---")
    st.subheader("Dostupné šablony")

    templates = get_available_templates()
    if not templates:
        st.warning("Žádné šablony nenalezeny ve složce `data/templates/`.")
    else:
        selected_templates = []
        for tmpl in templates:
            name_display = tmpl["name"].replace("_", " ")
            if st.checkbox(f"📄 {name_display}", value=True, key=f"tmpl_{tmpl['name']}"):
                selected_templates.append(tmpl)

        if selected_templates:
            st.markdown("---")

            # Generování jednotlivých dokumentů
            st.subheader("Generování dokumentů")

            for tmpl in selected_templates:
                try:
                    doc_bytes = fill_template(tmpl["path"], placeholders)
                    st.download_button(
                        f"📥 {tmpl['name'].replace('_', ' ')}.docx",
                        data=doc_bytes,
                        file_name=f"{tmpl['name']}_{company_info.get('ico', 'export')}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"dl_{tmpl['name']}",
                    )
                except Exception as e:
                    st.error(f"Chyba při generování {tmpl['name']}: {e}")

            # ZIP export
            st.markdown("---")
            if st.button("📦 Stáhnout vše jako ZIP", type="primary"):
                template_names = [t["name"] for t in selected_templates]
                zip_bytes = generate_all_documents(company_info, template_names)
                log_audit("Smlouvy", "generate", ico=company_info.get("ico", ""),
                          details=f"templates={','.join(template_names)}")
                st.download_button(
                    "📥 Stáhnout ZIP",
                    data=zip_bytes,
                    file_name=f"smlouvy_{company_info.get('ico', 'export')}_{datetime.now().strftime('%Y%m%d')}.zip",
                    mime="application/zip",
                    key="dl_zip",
                )
