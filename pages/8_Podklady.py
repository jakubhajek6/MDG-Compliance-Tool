"""
Modul 8 – Stažení podkladů ESM
Stahování OR výpisů (server-side) a generování ESM odkazů pro prohlížeč.
"""

import time
from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from db.database import (
    get_clients,
    get_podklady_history,
    init_db,
    log_audit,
    save_podklady_run,
    update_podklady_status,
    upsert_client_subjekt_id,
)
from modules.auth import require_login
from modules.podklady import (
    bulk_download_js,
    bulk_open_esm_js,
    download_or_pdf,
    esm_grafika_url,
    esm_vypis_url,
    lookup_subjekt_id,
    make_filename,
)
from modules.sidebar import render_sidebar

# ===== PAGE CONFIG =====
st.set_page_config(
    page_title="MDG – Stažení podkladů ESM",
    page_icon="📄",
    layout="wide",
)

init_db()
require_login()

PRIMARY = "#2EA39C"
CSS = f"""
<style>
.stButton > button, .stDownloadButton > button {{
  background-color: {PRIMARY} !important; color: white !important;
  border: 1px solid {PRIMARY} !important;
}}
div.stProgress > div > div {{ background-color: {PRIMARY} !important; }}
a, a:visited {{ color: {PRIMARY}; }}
.breadcrumb {{ color: #888; font-size: 0.85rem; margin-bottom: 0.5rem; }}
.status-ok   {{ color: #2EA39C; font-weight: bold; }}
.status-err  {{ color: #e53935; font-weight: bold; }}
.status-wait {{ color: #888; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)
render_sidebar()

# ===== HEADER =====
st.markdown('<div class="breadcrumb">Domů / Stažení podkladů ESM</div>', unsafe_allow_html=True)
st.markdown("## 📄 Stažení podkladů ESM")
st.markdown(
    "Stahování OR výpisů automaticky + generování ESM odkazů pro váš prohlížeč "
    "(ESM vyžaduje platnou session z bankovní identity)."
)
st.markdown("---")

# ===== HELPER FUNCTIONS =====

def _status_icon(status: str) -> str:
    """Převede status string na emoji ikonku."""
    return {"ok": "✅", "error": "❌", "pending": "🕐"}.get(status, "🕐")




# ===========================================================================
# ZÁLOŽKY
# ===========================================================================
tab_single, tab_bulk, tab_history = st.tabs([
    "🏢 Jedno IČO",
    "📋 Hromadné zpracování",
    "📅 Historie",
])

# ===========================================================================
# TAB 1 – Jedno IČO
# ===========================================================================
with tab_single:
    st.subheader("Stažení podkladů pro jednu společnost")
    st.caption(
        "Zadejte IČO a název společnosti. subjektId se dohledá automaticky."
    )

    col_ico, col_nazev = st.columns(2)
    with col_ico:
        ico_single = st.text_input("IČO", placeholder="03999840", key="single_ico")
    with col_nazev:
        nazev_single = st.text_input(
            "Název společnosti (pro pojmenování souborů)",
            placeholder="MatiDal s.r.o.",
            key="single_nazev",
        )

    if st.button("📥 Stáhnout všechny podklady (OR + ESM)", key="btn_all_single", type="primary"):
        ico = ico_single.strip()
        nazev = nazev_single.strip()

        if not ico:
            st.error("Zadejte IČO.")
        else:
            # ── 1. subjektId: zkusíme nejprve DB (uložené z minula), pak justice.cz ──
            clients_list = get_clients(active_only=False)
            sid = next(
                (c.get("subjekt_id") or "" for c in clients_list if c["ico"] == ico),
                "",
            )
            if not sid:
                with st.spinner("Hledám subjektId v justice.cz…"):
                    sid = lookup_subjekt_id(ico) or ""
                if sid:
                    upsert_client_subjekt_id(ico, sid)
                else:
                    st.error(
                        "subjektId nebylo nalezeno v justice.cz. "
                        "Zkontrolujte IČO nebo přidejte subjekt ručně přes záložku Hromadné zpracování."
                    )

            if sid:
                # ── 2. Stažení OR PDF ze serveru ──────────────────────────
                with st.spinner("Stahuji OR výpis…"):
                    pdf_bytes, or_msg = download_or_pdf(sid)

                fn_base = nazev or ico

                # ── 3. Uložení záznamu a statusů ──────────────────────────
                run_id = save_podklady_run(ico, sid, nazev)
                st.session_state["single_run_id"] = run_id
                update_podklady_status(run_id, "or_status", "ok" if pdf_bytes else "error")
                update_podklady_status(run_id, "esm_status", "ok")
                update_podklady_status(run_id, "esm_grafika_status", "ok")
                log_audit("Podklady", "all_download", ico=ico, entity_name=nazev,
                          details=f"sid={sid} or={'ok' if pdf_bytes else or_msg}")

                # ── 4. JS: OR jako base64 data-URI + ESM fetch/window.open ─
                js_parts: list[str] = []
                if pdf_bytes:
                    js_parts.append(bulk_download_js(
                        [{"data": pdf_bytes, "filename": make_filename(fn_base, "or")}]
                    ))
                js_parts.append(bulk_open_esm_js([
                    {"url": esm_vypis_url(sid),   "filename": make_filename(fn_base, "esm")},
                    {"url": esm_grafika_url(sid),  "filename": make_filename(fn_base, "esm_grafika")},
                ]))
                components.html("\n".join(js_parts), height=0)

                if pdf_bytes:
                    st.success(
                        f"✅ Spuštěno stahování 3 souborů: "
                        f"**{make_filename(fn_base, 'or')}**, ESM výpis, ESM grafika."
                    )
                else:
                    st.warning(
                        f"⚠️ OR výpis se nepodařilo stáhnout ({or_msg}). "
                        "ESM záložky byly otevřeny."
                    )

    # Opt-out: uživatel může opravit ESM stav pokud se soubor nestáhl
    if st.session_state.get("single_run_id"):
        with st.expander("⚠️ Něco selhalo? Opravit stav záznamu", expanded=False):
            st.caption("Použijte pouze pokud se některý soubor skutečně nestáhl.")
            col_s1, col_s2, col_s3 = st.columns(3)
            with col_s1:
                fix_or = st.checkbox("OR výpis ❌", key="fix_or_single")
            with col_s2:
                fix_esm = st.checkbox("ESM výpis ❌", key="fix_esm_single")
            with col_s3:
                fix_graf = st.checkbox("ESM grafika ❌", key="fix_graf_single")
            if st.button("💾 Uložit opravu", key="btn_fix_single"):
                run_id = st.session_state["single_run_id"]
                if fix_or:
                    update_podklady_status(run_id, "or_status", "error")
                if fix_esm:
                    update_podklady_status(run_id, "esm_status", "error")
                if fix_graf:
                    update_podklady_status(run_id, "esm_grafika_status", "error")
                log_audit("Podklady", "status_corrected", ico=ico_single.strip(),
                          details=f"or={fix_or} esm={fix_esm} grafika={fix_graf}")
                st.success("Stav opraven.")

# ===========================================================================
# TAB 2 – Hromadné zpracování
# ===========================================================================
with tab_bulk:
    st.subheader("Hromadné zpracování více společností")

    source_mode = st.radio(
        "Zdroj dat",
        ["📋 Načíst ze seznamu klientů", "📤 Nahrát Excel (A=IČO, B=subjektId)"],
        horizontal=True,
        key="bulk_source",
    )

    bulk_rows: list[dict] = []  # {"ico": str, "subjekt_id": str, "nazev": str}

    if source_mode.startswith("📋"):
        clients = get_clients(active_only=True)
        if not clients:
            st.info("Žádní aktivní klienti. Přidejte klienty v modulu ESM.")
        else:
            df_clients = pd.DataFrame(clients)[["ico", "nazev", "subjekt_id"]].fillna("")
            df_clients.columns = ["IČO", "Název", "subjektId"]
            st.dataframe(df_clients, use_container_width=True, hide_index=True)
            bulk_rows = [
                {"ico": c["ico"], "subjekt_id": c.get("subjekt_id") or "", "nazev": c.get("nazev") or ""}
                for c in clients
            ]
    else:
        uploaded = st.file_uploader(
            "Excel – řádek 1 záhlaví, sloupec A = IČO, sloupec B = subjektId (smí být prázdné)",
            type=["xlsx", "xls"],
            key="bulk_upload",
        )
        if uploaded:
            try:
                df_up = pd.read_excel(uploaded, header=0, dtype=str)
                # Normalizace: pracujeme vždy s prvními dvěma sloupci
                df_up = df_up.iloc[:, :3].copy()
                df_up.columns = (list(df_up.columns[:3]) + [])[:3]
                # Sloupce: 0=IČO, 1=subjektId, případně 3=Název
                has_nazev = df_up.shape[1] >= 3
                for _, row in df_up.iterrows():
                    ico_val = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
                    sid_val = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""
                    if sid_val.lower() in ("nan", "none", ""):
                        sid_val = ""
                    nazev_val = str(row.iloc[2]).strip() if (has_nazev and pd.notna(row.iloc[2])) else ""
                    if ico_val:
                        bulk_rows.append({"ico": ico_val, "subjekt_id": sid_val, "nazev": nazev_val})
                st.success(f"Načteno {len(bulk_rows)} řádků.")
                st.dataframe(
                    pd.DataFrame(bulk_rows).rename(columns={"ico": "IČO", "subjekt_id": "subjektId", "nazev": "Název"}),
                    use_container_width=True, hide_index=True,
                )
            except Exception as exc:
                st.error(f"Chyba při čtení souboru: {exc}")

    if not bulk_rows:
        st.stop()

    # ── Spuštění zpracování ────────────────────────────────────────────────
    if st.button("▶️ Spustit zpracování", key="btn_bulk_run", type="primary"):
        results: list[dict] = []  # {"ico", "nazev", "subjekt_id", "run_id", "or_status", "or_entry"}
        progress = st.progress(0, text="Inicializace…")
        status_box = st.status("Probíhá zpracování…", expanded=True)

        with status_box:
            for idx, row in enumerate(bulk_rows):
                ico = row["ico"]
                subjekt_id = row["subjekt_id"]
                nazev = row["nazev"]
                progress.progress((idx) / len(bulk_rows), text=f"Zpracovávám {ico}…")

                # Auto-lookup chybějícího subjektId
                if not subjekt_id:
                    st.write(f"🔍 Hledám subjektId pro IČO {ico}…")
                    subjekt_id = lookup_subjekt_id(ico) or ""
                    if subjekt_id:
                        upsert_client_subjekt_id(ico, subjekt_id)
                        st.write(f"  ✅ Nalezeno: {subjekt_id}")
                    else:
                        st.write(f"  ❌ Nenalezeno – přeskočeno")

                if not subjekt_id:
                    results.append({
                        "ico": ico, "nazev": nazev, "subjekt_id": "",
                        "run_id": None, "or_status": "error", "or_entry": None,
                    })
                    continue

                # Stažení OR PDF
                st.write(f"📥 Stahuji OR výpis pro {nazev or ico} (subjektId={subjekt_id})…")
                run_id = save_podklady_run(ico, subjekt_id, nazev)
                pdf_bytes, msg = download_or_pdf(subjekt_id)
                or_status = "ok" if pdf_bytes else "error"
                update_podklady_status(run_id, "or_status", or_status)
                log_audit("Podklady", "or_download", ico=ico, entity_name=nazev,
                          details=f"bulk subjektId={subjekt_id} status={or_status} {msg}")

                or_entry = None
                if pdf_bytes:
                    fname = make_filename(nazev or ico, "or")
                    or_entry = {"data": pdf_bytes, "filename": fname}
                    st.write(f"  ✅ OR stažen ({len(pdf_bytes)//1024} KB)")
                else:
                    st.write(f"  ❌ OR selhalo: {msg}")

                results.append({
                    "ico": ico, "nazev": nazev, "subjekt_id": subjekt_id,
                    "run_id": run_id, "or_status": or_status, "or_entry": or_entry,
                })

        progress.progress(1.0, text="Hotovo!")
        st.session_state["bulk_results"] = results

    # ── Výsledky po zpracování ────────────────────────────────────────────
    results = st.session_state.get("bulk_results", [])
    if not results:
        st.stop()

    st.markdown("---")
    st.markdown("### Výsledky zpracování")

    ok_pdfs = [r["or_entry"] for r in results if r["or_entry"]]
    fail_count = sum(1 for r in results if r["or_status"] == "error")

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Celkem", len(results))
    col_b.metric("OR staženo ✅", len(ok_pdfs))
    col_c.metric("Chyby ❌", fail_count)

    # Tabulka stavů
    df_results = pd.DataFrame([
        {
            "IČO": r["ico"],
            "Název": r["nazev"],
            "subjektId": r["subjekt_id"],
            "OR": _status_icon(r["or_status"]),
            "ESM výpis": "🕐",
            "ESM grafika": "🕐",
        }
        for r in results
    ])
    st.dataframe(df_results, use_container_width=True, hide_index=True)

    # ── Hromadné stažení OR PDF ────────────────────────────────────────────
    if ok_pdfs:
        st.markdown("#### 📥 Stažení OR PDF")
        st.caption(
            f"Kliknutím na tlačítko níže se automaticky spustí stažení všech "
            f"{len(ok_pdfs)} OR PDF souborů ve vašem prohlížeči."
        )
        if st.button("📥 Stáhnout všechny OR PDF", key="btn_bulk_or_dl"):
            js_html = bulk_download_js(ok_pdfs)
            components.html(js_html, height=0)

    # ── Retry neúspěšných ─────────────────────────────────────────────────
    error_rows = [r for r in results if r["or_status"] == "error" and r["subjekt_id"]]
    if error_rows:
        st.markdown("#### 🔄 Opakovat neúspěšná stažení")
        st.caption(f"{len(error_rows)} záznam(ů) se nepodařilo stáhnout.")
        if st.button("🔄 Opakovat neúspěšné", key="btn_retry"):
            retry_progress = st.progress(0, text="Opakuji…")
            for idx, rr in enumerate(error_rows):
                retry_progress.progress((idx + 1) / len(error_rows),
                                         text=f"Opakuji {rr['ico']}…")
                pdf_bytes, msg = download_or_pdf(rr["subjekt_id"])
                new_status = "ok" if pdf_bytes else "error"
                if rr["run_id"]:
                    update_podklady_status(rr["run_id"], "or_status", new_status)
                log_audit("Podklady", "or_retry", ico=rr["ico"],
                          details=f"status={new_status} {msg}")
                # Aktualizujeme results in-place
                for r_item in results:
                    if r_item["ico"] == rr["ico"]:
                        r_item["or_status"] = new_status
                        if pdf_bytes:
                            fname = make_filename(rr["nazev"] or rr["ico"], "or")
                            r_item["or_entry"] = {"data": pdf_bytes, "filename": fname}
            st.session_state["bulk_results"] = results
            st.rerun()

    # ── Hromadné otevření ESM odkazů ────────────────────────────────────────
    st.markdown("#### 🔗 ESM dokumenty")
    st.caption(
        "Tlačítko otevře všechny ESM výpisy a grafické struktury najednou v nových záložkách "
        "a automaticky označí stav jako ✅. Prohlížeč musí mít aktivní ESM session (bankovní identita)."
    )

    esm_items = [r for r in results if r["subjekt_id"]]
    if esm_items:
        if st.button(
            f"📥 Stahovat ESM podklady ({len(esm_items)} klientů)",
            key="btn_esm_bulk_open",
            type="primary",
        ):
            # Sestavíme seznam items s URL + názvem souboru – výpis + grafika
            all_esm_items: list[dict] = []
            for r in esm_items:
                fn_base = r["nazev"] or r["ico"]
                all_esm_items.append(
                    {"url": esm_vypis_url(r["subjekt_id"]), "filename": make_filename(fn_base, "esm")}
                )
                all_esm_items.append(
                    {"url": esm_grafika_url(r["subjekt_id"]), "filename": make_filename(fn_base, "esm_grafika")}
                )
            # Injektujeme JS – fetch+blob pro pojmenování, window.open jako fallback
            components.html(bulk_open_esm_js(all_esm_items), height=0)

            # Auto-mark ok pro všechny záznamy s platným subjektId
            for r in esm_items:
                if r["run_id"]:
                    update_podklady_status(r["run_id"], "esm_status", "ok")
                    update_podklady_status(r["run_id"], "esm_grafika_status", "ok")
            log_audit("Podklady", "esm_bulk_auto_triggered",
                      details=f"otevřeno={len(all_urls)} záložek klientů={len(esm_items)}")
            st.success(
                f"✅ Otevřeno {len(all_urls)} ESM záložek pro {len(esm_items)} klientů – "
                "stažení proběhlo automaticky."
            )

        # Opt-out: per-company oprava pokud výjimečně něco selhalo
        with st.expander("⚠️ Něco selhalo? Opravit stav pro jednotlivé klienty", expanded=False):
            st.caption("Zaškrtněte pouze klienty/dokumenty, u nichž se stažení skutečně nezdařilo.")
            failed: dict[str, dict] = {}
            for r in esm_items:
                label = f"{r['nazev'] or r['ico']} ({r['ico']})"
                c1, c2 = st.columns(2)
                with c1:
                    fail_v = st.checkbox(f"Výpis ❌  {label}", key=f"fail_v_{r['ico']}")
                with c2:
                    fail_g = st.checkbox(f"Grafika ❌  {label}", key=f"fail_g_{r['ico']}")
                failed[r["ico"]] = {"vypis": fail_v, "grafika": fail_g}
            if st.button("💾 Uložit opravené stavy", key="btn_esm_bulk_fix"):
                for r in esm_items:
                    if r["run_id"] and r["ico"] in failed:
                        if failed[r["ico"]]["vypis"]:
                            update_podklady_status(r["run_id"], "esm_status", "error")
                        if failed[r["ico"]]["grafika"]:
                            update_podklady_status(r["run_id"], "esm_grafika_status", "error")
                log_audit("Podklady", "esm_bulk_status_corrected",
                          details=f"opraveno_klientů={len(esm_items)}")
                st.success("Opravené stavy uloženy.")
    else:
        st.info("Žádní klienti s dostupným subjektId pro ESM stažení.")

# ===========================================================================
# TAB 3 – Historie
# ===========================================================================
with tab_history:
    st.subheader("Historie stažení podkladů")

    clients_for_filter = get_clients(active_only=False)
    filter_options = ["Všichni"] + [
        f"{c['ico']} – {c['nazev']}" for c in clients_for_filter
    ]
    filter_sel = st.selectbox("Filtrovat dle klienta", filter_options, key="hist_filter")
    filter_ico = "" if filter_sel == "Všichni" else filter_sel.split(" – ")[0].strip()

    history = get_podklady_history(ico=filter_ico, limit=100)
    if not history:
        st.info("Žádné záznamy. Spusťte zpracování podkladů.")
    else:
        df_hist = pd.DataFrame(history)
        # Převod stavů na ikonky
        for col in ["or_status", "esm_status", "esm_grafika_status"]:
            if col in df_hist.columns:
                df_hist[col] = df_hist[col].map(_status_icon)
        rename_map = {
            "run_date": "Datum",
            "ico": "IČO",
            "nazev": "Název",
            "subjekt_id": "subjektId",
            "or_status": "OR",
            "esm_status": "ESM výpis",
            "esm_grafika_status": "ESM grafika",
            "notes": "Poznámky",
        }
        df_hist = df_hist.rename(columns=rename_map)
        # Vybereme jen sloupce, které existují
        display_cols = [c for c in rename_map.values() if c in df_hist.columns]
        st.dataframe(df_hist[display_cols], use_container_width=True, hide_index=True)
        st.caption(f"Zobrazeno {len(df_hist)} záznamů.")
