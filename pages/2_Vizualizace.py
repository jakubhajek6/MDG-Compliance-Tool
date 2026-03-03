"""
Modul 2 – Vizualizace vztahů
Interaktivní rozklikávací mapa vztahů – podklad pro zprávu o vztazích.
"""

import json
import time
import hashlib
from datetime import datetime, timedelta
from io import BytesIO

import pandas as pd
import streamlit as st
from pyvis.network import Network
import streamlit.components.v1 as components

from modules.ares_api import fetch_ares_vr, fetch_ares_basic, extract_company_info, norm_ico
from modules.justice_scraper import search_person_engagements, search_company_persons
from db.database import init_db, get_connection, log_audit
from modules.auth import require_login

# ===== PAGE CONFIG =====
st.set_page_config(page_title="MDG – Vizualizace", page_icon="🔗", layout="wide")
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
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

st.markdown('<div class="breadcrumb">Domů / Vizualizace vztahů</div>', unsafe_allow_html=True)
st.markdown("## 🔗 Vizualizace vztahů")
st.markdown("Interaktivní mapa propojení osob a firem – data z ARES a obchodního rejstříku.")

st.markdown("---")

# ===== Cache helper =====
def _cache_key(entity_type: str, value: str) -> str:
    return hashlib.sha256(f"{entity_type}:{value}".encode()).hexdigest()[:16]


def _get_cached(key: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT data_json, snapshot_date FROM or_snapshots WHERE ico = ? ORDER BY snapshot_date DESC LIMIT 1",
            (f"viz_{key}",)
        ).fetchone()
        if row:
            snap_date = datetime.fromisoformat(dict(row)["snapshot_date"])
            if (datetime.now() - snap_date) < timedelta(hours=24):
                return json.loads(dict(row)["data_json"])
        return None
    except Exception:
        return None
    finally:
        conn.close()


def _set_cached(key: str, data: dict):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO or_snapshots (ico, snapshot_date, data_json) VALUES (?, ?, ?)",
            (f"viz_{key}", datetime.now().isoformat(timespec="seconds"),
             json.dumps(data, ensure_ascii=False))
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ===== Načítání dat =====
def load_company_relations(ico: str, depth: int = 1) -> dict:
    """Načte vztahy pro firmu – statutáři, společníci, propojení."""
    ico = norm_ico(ico)
    relations = {"nodes": [], "edges": [], "loaded_icos": set()}

    def _add_company(ico_val: str, current_depth: int):
        if current_depth > depth or ico_val in relations["loaded_icos"]:
            return
        relations["loaded_icos"].add(ico_val)

        vr_data = fetch_ares_vr(ico_val)
        basic_data = fetch_ares_basic(ico_val)
        time.sleep(0.5)

        if not vr_data:
            return

        info = extract_company_info(vr_data, basic_data)
        nazev = info.get("nazev", ico_val)

        # Přidat uzel firmy
        relations["nodes"].append({
            "id": f"C_{ico_val}",
            "label": nazev,
            "ico": ico_val,
            "type": "company",
            "color": "#1B3A6B",
        })

        # Statutární orgány
        for stat in info.get("statutarni_organ", []):
            person_id = f"S_{hashlib.sha256(stat['jmeno'].encode()).hexdigest()[:8]}"
            relations["nodes"].append({
                "id": person_id,
                "label": stat["jmeno"],
                "type": "statutar",
                "funkce": stat.get("funkce", ""),
                "color": "#E67E22",
            })
            relations["edges"].append({
                "from": person_id,
                "to": f"C_{ico_val}",
                "label": stat.get("funkce", "statutár"),
                "type": "statutar",
                "color": "#E67E22",
            })

        # Společníci
        for sp in info.get("spolecnici", []):
            if sp.get("typ") == "PO" and sp.get("ico"):
                sp_ico = norm_ico(sp["ico"])
                sp_id = f"C_{sp_ico}"
                relations["edges"].append({
                    "from": sp_id,
                    "to": f"C_{ico_val}",
                    "label": "společník",
                    "type": "spolecnik",
                    "color": "#1B3A6B",
                })
                if current_depth < depth:
                    _add_company(sp_ico, current_depth + 1)
            elif sp.get("typ") == "FO":
                person_id = f"P_{hashlib.sha256(sp['jmeno'].encode()).hexdigest()[:8]}"
                relations["nodes"].append({
                    "id": person_id,
                    "label": sp["jmeno"],
                    "type": "person",
                    "color": "#28a745",
                })
                relations["edges"].append({
                    "from": person_id,
                    "to": f"C_{ico_val}",
                    "label": "společník",
                    "type": "spolecnik",
                    "color": "#28a745",
                })

    _add_company(ico, 0)
    return relations


# ===== Vstupy =====
col1, col2 = st.columns([3, 2])
with col1:
    search_input = st.text_input("IČO společnosti nebo jméno osoby", placeholder="12345678 nebo Jan Novák")
with col2:
    depth = st.slider("Hloubka vztahů", 1, 4, 2)

if st.button("🔍 Zobrazit vztahy", type="primary"):
    if not search_input.strip():
        st.error("Zadejte IČO nebo jméno.")
    else:
        with st.spinner("Načítám vztahy z ARES..."):
            # Detekce: IČO vs jméno
            input_clean = search_input.strip()
            if input_clean.isdigit() and len(input_clean) in (7, 8):
                relations = load_company_relations(input_clean, depth=depth)
            else:
                # Hledání osoby – nejdříve přes justice.cz
                st.info(f"Hledám angažmá osoby: {input_clean}")
                engagements = search_person_engagements(input_clean)
                relations = {"nodes": [], "edges": [], "loaded_icos": set()}

                # Přidat osobu jako centrální uzel
                person_id = f"P_{hashlib.sha256(input_clean.encode()).hexdigest()[:8]}"
                relations["nodes"].append({
                    "id": person_id,
                    "label": input_clean,
                    "type": "person",
                    "color": "#28a745",
                })

                for eng in engagements[:20]:
                    company_id = f"C_{eng['ico']}"
                    relations["nodes"].append({
                        "id": company_id,
                        "label": eng.get("nazev", eng["ico"]),
                        "ico": eng["ico"],
                        "type": "company",
                        "color": "#1B3A6B",
                    })
                    relations["edges"].append({
                        "from": person_id,
                        "to": company_id,
                        "label": eng.get("role", "angažmá"),
                        "type": eng.get("role", "angažmá"),
                    })

        log_audit("Vizualizace", "search", details=f"input={input_clean}, depth={depth}")

        if not relations["nodes"]:
            st.warning("Nebyly nalezeny žádné vztahy.")
        else:
            st.success(f"Nalezeno **{len(relations['nodes'])}** entit a **{len(relations['edges'])}** vztahů.")

            # Vytvořit PyVis graf
            net = Network(height="600px", width="100%", directed=True, notebook=False,
                          bgcolor="#ffffff", font_color="#1A1A2E")
            net.barnes_hut(gravity=-3000, central_gravity=0.3, spring_length=150)

            # Deduplikace uzlů
            seen_ids = set()
            for node in relations["nodes"]:
                if node["id"] not in seen_ids:
                    seen_ids.add(node["id"])
                    shape = "box" if node["type"] == "company" else ("diamond" if node["type"] == "statutar" else "ellipse")
                    net.add_node(
                        node["id"],
                        label=node["label"],
                        color=node.get("color", "#1B3A6B"),
                        shape=shape,
                        font={"color": "white" if node["type"] == "company" else "white", "size": 12},
                        title=f"{node['label']}\n({node.get('ico', node['type'])})",
                    )

            for edge in relations["edges"]:
                net.add_edge(
                    edge["from"], edge["to"],
                    label=edge.get("label", ""),
                    color=edge.get("color", "#888"),
                    arrows="to",
                )

            # Render
            html_str = net.generate_html()
            components.html(html_str, height=620, scrolling=True)

            # Export
            st.markdown("---")
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                # Excel export – seznam vztahů
                rows = []
                for edge in relations["edges"]:
                    rows.append({
                        "Od": edge["from"],
                        "Do": edge["to"],
                        "Typ vztahu": edge.get("label", ""),
                        "Typ hrany": edge.get("type", ""),
                    })
                if rows:
                    df = pd.DataFrame(rows)
                    buf = BytesIO()
                    with pd.ExcelWriter(buf, engine="openpyxl") as w:
                        df.to_excel(w, index=False)
                    st.download_button(
                        "📥 Export vztahů (Excel)",
                        data=buf.getvalue(),
                        file_name=f"vztahy_{input_clean}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
