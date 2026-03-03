"""
Modul 6 – Monitoring změn v OR
Automatické hlídání změn v OR u sledovaných klientů.
"""

import json
import time
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from modules.ares_api import fetch_ares_vr, fetch_ares_basic, extract_company_info, norm_ico
from db.database import (
    init_db, get_connection, add_client, remove_client, get_clients,
    save_or_snapshot, get_latest_snapshot, save_or_change,
    get_unprocessed_changes, mark_change_processed, log_audit,
)
from modules.auth import require_login
from modules.sidebar import render_sidebar

# ===== PAGE CONFIG =====
st.set_page_config(page_title="MDG – Monitoring", page_icon="👁️", layout="wide")
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
.change-card {{ border-left: 4px solid #dc3545; padding: 8px 12px; margin: 8px 0; background-color: #fff3cd; border-radius: 4px; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)
render_sidebar()

st.markdown('<div class="breadcrumb">Domů / Monitoring změn v OR</div>', unsafe_allow_html=True)
st.markdown("## 👁️ Monitoring změn v OR")
st.markdown("Automatické hlídání změn v obchodním rejstříku u sledovaných klientů.")

st.markdown("---")

# ===== Správa klientů =====
st.subheader("Sledovaní klienti")

tab1, tab2, tab3 = st.tabs(["📋 Seznam klientů", "➕ Přidat klienta", "📥 Import z Excelu"])

with tab1:
    clients = get_clients(active_only=False)
    if clients:
        for client in clients:
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
            with col1:
                st.markdown(f"**{client.get('nazev', 'N/A')}** (IČO: {client['ico']})")
            with col2:
                st.markdown(f"Přidáno: {client.get('added_date', 'N/A')[:10]}")
            with col3:
                active = "✅ Aktivní" if client.get("monitoring_active") else "⏸️ Pozastaveno"
                st.markdown(active)
            with col4:
                if st.button("🗑️", key=f"del_client_{client['ico']}",
                             help="Odebrat klienta ze sledování"):
                    remove_client(client["ico"])
                    st.rerun()
    else:
        st.info("Zatím žádní sledovaní klienti.")

with tab2:
    col_a1, col_a2 = st.columns([2, 1])
    with col_a1:
        new_ico = st.text_input("IČO nového klienta", placeholder="12345678", key="new_client_ico")
    with col_a2:
        new_name = st.text_input("Název (volitelné)", placeholder="Firma s.r.o.", key="new_client_name")

    if st.button("➕ Přidat klienta", type="primary"):
        if not new_ico.strip():
            st.error("Zadejte IČO.")
        else:
            ico_str = norm_ico(new_ico.strip())
            name = new_name.strip()
            if not name:
                # Zkusit načíst z ARES
                with st.spinner("Načítám název z ARES..."):
                    basic = fetch_ares_basic(ico_str)
                    if basic:
                        name = basic.get("obchodniJmeno", "") or ""
            add_client(ico_str, name)
            log_audit("Monitoring", "add_client", ico=ico_str, entity_name=name)
            st.success(f"Klient přidán: {name or ico_str}")
            st.rerun()

with tab3:
    uploaded = st.file_uploader("Excel se sloupcem IČO", type=["xlsx"], key="monitor_import")
    if uploaded:
        try:
            df = pd.read_excel(uploaded)
            ico_col = None
            for col in df.columns:
                if "ič" in str(col).lower() or "ico" in str(col).lower():
                    ico_col = col
                    break
            if not ico_col:
                ico_col = df.columns[0]

            icos = [str(x).strip() for x in df[ico_col].dropna().unique() if str(x).strip()]
            st.info(f"Nalezeno {len(icos)} IČO k importu.")

            if st.button("📥 Importovat všechny"):
                progress = st.progress(0)
                for i, ico_str in enumerate(icos):
                    ico_str = norm_ico(ico_str)
                    add_client(ico_str, "")
                    progress.progress(int((i+1) / len(icos) * 100))
                log_audit("Monitoring", "bulk_import", details=f"{len(icos)} klientů")
                st.success(f"Importováno {len(icos)} klientů.")
                st.rerun()
        except Exception as e:
            st.error(f"Chyba při čtení souboru: {e}")

# ===== Kontrola změn =====
st.markdown("---")
st.subheader("Kontrola změn")


def compare_snapshots(old_data: dict, new_data: dict, ico: str) -> list[dict]:
    """Porovná dva snapshoty a vrátí nalezené změny."""
    changes = []

    # Sídlo
    old_addr = f"{old_data.get('sidlo_ulice', '')} {old_data.get('sidlo_mesto', '')} {old_data.get('sidlo_psc', '')}"
    new_addr = f"{new_data.get('sidlo_ulice', '')} {new_data.get('sidlo_mesto', '')} {new_data.get('sidlo_psc', '')}"
    if old_addr.strip() != new_addr.strip() and old_addr.strip() and new_addr.strip():
        changes.append({"type": "Změna sídla", "old": old_addr.strip(), "new": new_addr.strip()})

    # Statutární orgán
    old_stats = {s.get("jmeno", "") for s in (old_data.get("statutarni_organ") or [])}
    new_stats = {s.get("jmeno", "") for s in (new_data.get("statutarni_organ") or [])}
    removed = old_stats - new_stats
    added = new_stats - old_stats
    if removed:
        changes.append({"type": "Odchod statutára", "old": ", ".join(removed), "new": ""})
    if added:
        changes.append({"type": "Nový statutár", "old": "", "new": ", ".join(added)})

    # Předmět podnikání
    if (old_data.get("predmet_podnikani") or "") != (new_data.get("predmet_podnikani") or ""):
        if old_data.get("predmet_podnikani") and new_data.get("predmet_podnikani"):
            changes.append({
                "type": "Změna předmětu podnikání",
                "old": (old_data.get("predmet_podnikani") or "")[:100],
                "new": (new_data.get("predmet_podnikani") or "")[:100],
            })

    # Základní kapitál
    if (old_data.get("zakladni_kapital") or "") != (new_data.get("zakladni_kapital") or ""):
        if old_data.get("zakladni_kapital") and new_data.get("zakladni_kapital"):
            changes.append({
                "type": "Změna základního kapitálu",
                "old": old_data.get("zakladni_kapital", ""),
                "new": new_data.get("zakladni_kapital", ""),
            })

    # Název
    if (old_data.get("nazev") or "") != (new_data.get("nazev") or ""):
        if old_data.get("nazev") and new_data.get("nazev"):
            changes.append({
                "type": "Změna názvu",
                "old": old_data.get("nazev", ""),
                "new": new_data.get("nazev", ""),
            })

    return changes


if st.button("🔄 Spustit kontrolu všech klientů", type="primary"):
    clients = get_clients()
    if not clients:
        st.warning("Nejsou žádní sledovaní klienti.")
    else:
        progress = st.progress(0)
        status = st.empty()
        total_changes = 0

        for i, client in enumerate(clients):
            ico_str = client["ico"]
            status.text(f"Kontroluji {i+1}/{len(clients)}: {client.get('nazev', ico_str)}")
            progress.progress(int((i / len(clients)) * 100))

            try:
                # Načíst aktuální data
                vr_data = fetch_ares_vr(ico_str)
                basic_data = fetch_ares_basic(ico_str)
                time.sleep(0.7)

                if not vr_data:
                    continue

                new_data = extract_company_info(vr_data, basic_data)

                # Porovnat s posledním snapshotem
                last_snap = get_latest_snapshot(ico_str)
                if last_snap and last_snap.get("data"):
                    old_data = last_snap["data"]
                    changes = compare_snapshots(old_data, new_data, ico_str)
                    for change in changes:
                        save_or_change(ico_str, change["type"], change["old"], change["new"])
                        total_changes += 1

                # Uložit nový snapshot
                save_or_snapshot(ico_str, new_data)

                # Aktualizovat název klienta
                if new_data.get("nazev") and not client.get("nazev"):
                    conn = get_connection()
                    try:
                        conn.execute("UPDATE clients SET nazev = ? WHERE ico = ?",
                                     (new_data["nazev"], ico_str))
                        conn.commit()
                    finally:
                        conn.close()

            except Exception:
                continue

        progress.progress(100)
        status.text("Kontrola dokončena.")
        log_audit("Monitoring", "check_all", details=f"{len(clients)} klientů, {total_changes} změn")

        if total_changes > 0:
            st.warning(f"Nalezeno **{total_changes}** změn!")
        else:
            st.success("Žádné změny nenalezeny.")

# ===== Nezpracované změny =====
st.markdown("---")
st.subheader("Nezpracované změny")

unprocessed = get_unprocessed_changes()
if unprocessed:
    for change in unprocessed:
        st.markdown(
            f'<div class="change-card">'
            f'<strong>{change.get("change_type", "N/A")}</strong> – IČO: {change.get("ico", "N/A")}<br>'
            f'Detekováno: {change.get("detected_date", "N/A")}<br>'
            f'Původní: {change.get("old_value", "—")}<br>'
            f'Nové: {change.get("new_value", "—")}'
            f'</div>',
            unsafe_allow_html=True,
        )
        if st.button(f"✅ Označit jako zpracované", key=f"proc_{change['id']}"):
            mark_change_processed(change["id"])
            log_audit("Monitoring", "mark_processed", details=f"change_id={change['id']}")
            st.rerun()
else:
    st.info("Žádné nezpracované změny.")

# ===== Export změn =====
st.markdown("---")
conn = get_connection()
try:
    all_changes = conn.execute(
        "SELECT * FROM or_changes ORDER BY detected_date DESC LIMIT 200"
    ).fetchall()
finally:
    conn.close()

if all_changes:
    df_changes = pd.DataFrame([dict(r) for r in all_changes])
    st.subheader("Timeline změn")
    st.dataframe(df_changes[["ico", "change_type", "old_value", "new_value", "detected_date", "processed"]],
                 use_container_width=True)

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df_changes.to_excel(w, index=False)
    st.download_button(
        "📥 Export změn (Excel)",
        data=buf.getvalue(),
        file_name=f"or_changes_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
