"""
Modul 4 – Výčet dat z OR pro MasT a MT
Export standardizovaných dat z ARES/OR do Excelu.
"""

import time
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from modules.ares_api import fetch_ares_basic, fetch_ares_vr, extract_company_info, norm_ico
from db.database import init_db, log_audit, save_or_snapshot
from modules.auth import require_login

# ===== PAGE CONFIG =====
st.set_page_config(page_title="MDG – Export dat", page_icon="📊", layout="wide")

init_db()
require_login()

PRIMARY = "#1B3A6B"
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

# ===== HEADER =====
st.markdown('<div class="breadcrumb">Domů / Export dat pro MasT a MT</div>', unsafe_allow_html=True)
st.markdown("## 📊 Export dat z OR pro MasT a MT")
st.markdown("Načtení dat z ARES a obchodního rejstříku, export do 2 formátů Excelu.")

st.markdown("---")

# ===== Režim: jedno IČO vs. hromadné =====
mode = st.radio("Režim zpracování", ["Jedno IČO", "Hromadné zpracování (Excel)"], horizontal=True)


def fetch_company_data(ico_str: str) -> dict:
    """Načte kompletní data pro jedno IČO."""
    ico_str = norm_ico(ico_str)
    vr_data = fetch_ares_vr(ico_str)
    basic_data = fetch_ares_basic(ico_str)
    if not vr_data and not basic_data:
        return {"ico": ico_str, "_error": f"Nenalezeno v ARES: {ico_str}"}
    info = extract_company_info(vr_data or {}, basic_data)
    if not info.get("nazev") and basic_data:
        info["nazev"] = basic_data.get("obchodniJmeno", "") or ""
    if not info.get("ico"):
        info["ico"] = ico_str
    return info


def build_mast_df(data_list: list[dict]) -> pd.DataFrame:
    """Sestaví DataFrame pro MasT export."""
    rows = []
    for d in data_list:
        if d.get("_error"):
            continue
        # Statutář - první
        stat_jmeno = ""
        stat_funkce = ""
        for s in (d.get("statutarni_organ") or []):
            stat_jmeno = s.get("jmeno", "")
            stat_funkce = s.get("funkce", "")
            break
        rows.append({
            "IČO": d.get("ico", ""),
            "DIČ": d.get("dic", ""),
            "Název": d.get("nazev", ""),
            "Právní forma": d.get("pravni_forma", ""),
            "Sídlo – ulice": d.get("sidlo_ulice", ""),
            "Sídlo – město": d.get("sidlo_mesto", ""),
            "Sídlo – PSČ": d.get("sidlo_psc", ""),
            "Sídlo – stát": d.get("sidlo_stat", ""),
            "Datum vzniku": d.get("datum_vzniku", ""),
            "Statutář – jméno": stat_jmeno,
            "Statutář – funkce": stat_funkce,
            "Datová schránka": d.get("datova_schranka", ""),
            "Datum exportu": datetime.now().strftime("%d.%m.%Y"),
        })
    return pd.DataFrame(rows)


def build_mt_df(data_list: list[dict]) -> pd.DataFrame:
    """Sestaví DataFrame pro MT (Macrtime) export."""
    rows = []
    for d in data_list:
        if d.get("_error"):
            continue
        rows.append({
            "IČO": d.get("ico", ""),
            "Název": d.get("nazev", ""),
            "Sídlo – ulice": d.get("sidlo_ulice", ""),
            "Město": d.get("sidlo_mesto", ""),
            "PSČ": d.get("sidlo_psc", ""),
            "Stát": d.get("sidlo_stat", "Česká republika"),
            "DIČ": d.get("dic", ""),
            "Datová schránka": d.get("datova_schranka", ""),
            "Právní forma": d.get("pravni_forma", ""),
            "Datum exportu": datetime.now().strftime("%d.%m.%Y"),
        })
    return pd.DataFrame(rows)


def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    """Převede DataFrame na Excel bytes."""
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Data")
    return buf.getvalue()


if mode == "Jedno IČO":
    ico_input = st.text_input("IČO společnosti", placeholder="12345678")

    if st.button("📥 Načíst data", type="primary"):
        if not ico_input.strip():
            st.error("Zadejte IČO.")
        else:
            with st.spinner("Načítám data z ARES..."):
                data = fetch_company_data(ico_input.strip())

            if data.get("_error"):
                st.error(f"Chyba: {data['_error']}")
            else:
                # Uložit snapshot
                save_or_snapshot(data["ico"], data)
                log_audit("DataExport", "fetch", ico=data["ico"], entity_name=data.get("nazev", ""))

                st.success(f"Data načtena: **{data.get('nazev', 'N/A')}**")

                # Preview
                st.subheader("Náhled dat")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Název:** {data.get('nazev', '')}")
                    st.markdown(f"**IČO:** {data.get('ico', '')}")
                    st.markdown(f"**DIČ:** {data.get('dic', '')}")
                    st.markdown(f"**Právní forma:** {data.get('pravni_forma', '')}")
                    st.markdown(f"**Datum vzniku:** {data.get('datum_vzniku', '')}")
                with col2:
                    st.markdown(f"**Sídlo:** {data.get('sidlo_ulice', '')}, {data.get('sidlo_mesto', '')} {data.get('sidlo_psc', '')}")
                    st.markdown(f"**Datová schránka:** {data.get('datova_schranka', '')}")
                    st.markdown(f"**Základní kapitál:** {data.get('zakladni_kapital', '')}")
                    st.markdown(f"**Předmět podnikání:** {data.get('predmet_podnikani', '')[:100]}")

                # Statutární orgán
                if data.get("statutarni_organ"):
                    st.markdown("**Statutární orgán:**")
                    for s in data["statutarni_organ"]:
                        st.markdown(f"- {s.get('jmeno', '')} – {s.get('funkce', '')}")

                st.markdown("---")

                # Export
                data_list = [data]
                mast_df = build_mast_df(data_list)
                mt_df = build_mt_df(data_list)

                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    st.download_button(
                        "📥 Stáhnout MasT Excel",
                        data=df_to_excel_bytes(mast_df),
                        file_name=f"MasT_{data['ico']}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary",
                    )
                with col_e2:
                    st.download_button(
                        "📥 Stáhnout MT Excel",
                        data=df_to_excel_bytes(mt_df),
                        file_name=f"MT_{data['ico']}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary",
                    )

else:
    # Hromadné zpracování
    st.markdown("Nahrajte Excel soubor se sloupcem **IČO**.")
    uploaded_file = st.file_uploader("Excel soubor (.xlsx)", type=["xlsx"])

    if uploaded_file:
        try:
            df_input = pd.read_excel(uploaded_file)
        except Exception as e:
            st.error(f"Chyba při čtení souboru: {e}")
            df_input = None

        if df_input is not None:
            # Najít sloupec s IČO
            ico_col = None
            for col in df_input.columns:
                if "ič" in str(col).lower() or "ico" in str(col).lower():
                    ico_col = col
                    break
            if not ico_col:
                ico_col = df_input.columns[0]
                st.warning(f"Sloupec IČO nenalezen, používám první sloupec: {ico_col}")

            icos = [str(x).strip() for x in df_input[ico_col].dropna().unique() if str(x).strip()]
            st.info(f"Nalezeno **{len(icos)}** unikátních IČO ke zpracování.")

            if st.button("🚀 Spustit hromadné zpracování", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()

                data_list = []
                errors = []

                for i, ico_str in enumerate(icos):
                    status_text.text(f"Zpracovávám {i+1}/{len(icos)}: IČO {ico_str}")
                    progress_bar.progress(int((i / len(icos)) * 100))

                    try:
                        data = fetch_company_data(ico_str)
                        if data.get("_error"):
                            errors.append({"ico": ico_str, "error": data["_error"]})
                        else:
                            data_list.append(data)
                            save_or_snapshot(data["ico"], data)
                        time.sleep(0.7)  # rate limiting
                    except Exception as e:
                        errors.append({"ico": ico_str, "error": str(e)})

                progress_bar.progress(100)
                status_text.text("Hotovo!")
                log_audit("DataExport", "bulk_fetch", details=f"{len(data_list)} OK, {len(errors)} chyb")

                st.success(f"Zpracováno: **{len(data_list)}** úspěšně, **{len(errors)}** chyb")

                if errors:
                    st.subheader("Chybná / nenalezená IČO")
                    for e in errors:
                        st.warning(f"IČO {e['ico']}: {e['error']}")

                if data_list:
                    # Preview
                    st.subheader("Náhled dat")
                    mast_df = build_mast_df(data_list)
                    mt_df = build_mt_df(data_list)

                    st.dataframe(mast_df, use_container_width=True)

                    # Export
                    st.markdown("---")
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        st.download_button(
                            "📥 Stáhnout MasT Excel",
                            data=df_to_excel_bytes(mast_df),
                            file_name=f"MasT_bulk_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            type="primary",
                        )
                    with col_e2:
                        st.download_button(
                            "📥 Stáhnout MT Excel",
                            data=df_to_excel_bytes(mt_df),
                            file_name=f"MT_bulk_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            type="primary",
                        )
