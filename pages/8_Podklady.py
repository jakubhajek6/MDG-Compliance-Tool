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
        with st.expander("⚠️ Něco selhalo? Zopakovat nebo opravit stav", expanded=False):
            st.caption("Zaškrtněte co se nestáhlo a klikněte na Opakovat – nebo jen označte jako chybu.")
            col_s1, col_s2, col_s3 = st.columns(3)
            with col_s1:
                fix_or   = st.checkbox("OR výpis ❌",    key="fix_or_single")
            with col_s2:
                fix_esm  = st.checkbox("ESM výpis ❌",   key="fix_esm_single")
            with col_s3:
                fix_graf = st.checkbox("ESM grafika ❌", key="fix_graf_single")

            if fix_or or fix_esm or fix_graf:
                col_retry, col_mark = st.columns(2)
                with col_retry:
                    if st.button("🔄 Opakovat vybrané", key="btn_retry_single", type="primary"):
                        run_id = st.session_state["single_run_id"]
                        ico_r = ico_single.strip()
                        nazev_r = nazev_single.strip()
                        # Dohledáme sid z DB
                        clients_r = get_clients(active_only=False)
                        sid_r = next(
                            (c.get("subjekt_id") or "" for c in clients_r if c["ico"] == ico_r), ""
                        )
                        fn_r = nazev_r or ico_r
                        js_retry: list[str] = []
                        if fix_or and sid_r:
                            with st.spinner("Stahuji OR výpis znovu…"):
                                pdf_r, msg_r = download_or_pdf(sid_r)
                            if pdf_r:
                                update_podklady_status(run_id, "or_status", "ok")
                                js_retry.append(bulk_download_js(
                                    [{"data": pdf_r, "filename": make_filename(fn_r, "or")}]
                                ))
                            else:
                                st.error(f"OR stažení selhalo znovu: {msg_r}")
                        esm_retry_items: list[dict] = []
                        if fix_esm and sid_r:
                            esm_retry_items.append({"url": esm_vypis_url(sid_r),
                                                    "filename": make_filename(fn_r, "esm")})
                            update_podklady_status(run_id, "esm_status", "ok")
                        if fix_graf and sid_r:
                            esm_retry_items.append({"url": esm_grafika_url(sid_r),
                                                    "filename": make_filename(fn_r, "esm_grafika")})
                            update_podklady_status(run_id, "esm_grafika_status", "ok")
                        if esm_retry_items:
                            js_retry.append(bulk_open_esm_js(esm_retry_items))
                        if js_retry:
                            components.html("\n".join(js_retry), height=0)
                            st.success("✅ Opakované stahování spuštěno.")
                with col_mark:
                    if st.button("💾 Jen označit jako chybu", key="btn_fix_single"):
                        run_id = st.session_state["single_run_id"]
                        if fix_or:
                            update_podklady_status(run_id, "or_status", "error")
                        if fix_esm:
                            update_podklady_status(run_id, "esm_status", "error")
                        if fix_graf:
                            update_podklady_status(run_id, "esm_grafika_status", "error")
                        log_audit("Podklady", "status_corrected", ico=ico_single.strip(),
                                  details=f"or={fix_or} esm={fix_esm} grafika={fix_graf}")
                        st.success("Stav označen jako chyba.")

# ===========================================================================
# TAB 2 – Hromadné zpracování
# ===========================================================================
with tab_bulk:
    st.subheader("Hromadné zpracování více společností")

    source_mode = st.radio(
        "Zdroj dat",
        ["📋 Načíst ze seznamu klientů", "📤 Nahrát Excel"],
        horizontal=True,
        key="bulk_source",
    )

    bulk_rows: list[dict] = []  # {"ico": str, "nazev": str}

    if source_mode.startswith("📋"):
        clients = get_clients(active_only=True)
        if not clients:
            st.info("Žádní aktivní klienti. Přidejte klienty v modulu ESM.")
        else:
            bulk_rows = [{"ico": c["ico"], "nazev": c.get("nazev") or ""} for c in clients]
            st.dataframe(
                pd.DataFrame(bulk_rows).rename(columns={"ico": "IČO", "nazev": "Název"}),
                use_container_width=True, hide_index=True,
            )
    else:
        st.caption("Excel: sloupec **A = Název**, sloupec **B = IČO**. Řádek 1 je záhlaví. subjektId se dohledá automaticky.")
        uploaded = st.file_uploader(
            "Excel soubor (.xlsx / .xls)",
            type=["xlsx", "xls"],
            key="bulk_upload",
        )
        if uploaded:
            try:
                df_up = pd.read_excel(uploaded, header=0, dtype=str).iloc[:, :2]
                for _, row in df_up.iterrows():
                    nazev_val = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
                    ico_val   = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""
                    if ico_val.lower() not in ("", "nan", "none") and ico_val:
                        bulk_rows.append({"ico": ico_val, "nazev": nazev_val})
                st.success(f"Načteno {len(bulk_rows)} řádků.")
                st.dataframe(
                    pd.DataFrame(bulk_rows).rename(columns={"ico": "IČO", "nazev": "Název"}),
                    use_container_width=True, hide_index=True,
                )
            except Exception as exc:
                st.error(f"Chyba při čtení souboru: {exc}")

    if not bulk_rows:
        st.stop()

    # ── Spuštění zpracování ────────────────────────────────────────────────
    if st.button("▶️ Spustit zpracování", key="btn_bulk_run", type="primary"):
        results: list[dict] = []
        progress = st.progress(0, text="Inicializace…")
        status_box = st.status("Probíhá zpracování…", expanded=True)

        # Načteme DB klienty jednou pro celé zpracování
        db_clients = get_clients(active_only=False)
        sid_cache: dict[str, str] = {
            c["ico"]: (c.get("subjekt_id") or "") for c in db_clients
        }

        with status_box:
            for idx, row in enumerate(bulk_rows):
                ico   = row["ico"]
                nazev = row["nazev"]
                progress.progress(idx / len(bulk_rows), text=f"Zpracovávám {nazev or ico}…")

                # Dohledání subjektId: DB cache → justice.cz
                subjekt_id = sid_cache.get(ico, "")
                if not subjekt_id:
                    st.write(f"🔍 Hledám subjektId pro {nazev or ico}…")
                    subjekt_id = lookup_subjekt_id(ico) or ""
                    if subjekt_id:
                        upsert_client_subjekt_id(ico, subjekt_id)
                        sid_cache[ico] = subjekt_id
                        st.write(f"  ✅ Nalezeno: {subjekt_id}")
                    else:
                        st.write(f"  ❌ subjektId nenalezeno pro {nazev or ico}")
                        results.append({
                            "ico": ico, "nazev": nazev, "subjekt_id": "",
                            "run_id": None, "or_status": "error", "or_entry": None,
                            "or_msg": "subjektId nenalezeno",
                        })
                        continue

                # Stažení OR PDF
                st.write(f"📥 Stahuji OR výpis pro {nazev or ico}…")
                run_id = save_podklady_run(ico, subjekt_id, nazev)
                pdf_bytes, msg = download_or_pdf(subjekt_id)
                or_status = "ok" if pdf_bytes else "error"
                update_podklady_status(run_id, "or_status", or_status)
                log_audit("Podklady", "or_download", ico=ico, entity_name=nazev,
                          details=f"bulk sid={subjekt_id} status={or_status} {msg}")

                or_entry = None
                if pdf_bytes:
                    or_entry = {"data": pdf_bytes, "filename": make_filename(nazev or ico, "or")}
                    st.write(f"  ✅ OR stažen ({len(pdf_bytes)//1024} KB)")
                else:
                    st.write(f"  ❌ OR selhalo: {msg}")

                results.append({
                    "ico": ico, "nazev": nazev, "subjekt_id": subjekt_id,
                    "run_id": run_id, "or_status": or_status, "or_entry": or_entry,
                    "or_msg": msg,
                })

        progress.progress(1.0, text="Hotovo!")
        st.session_state["bulk_results"] = results

    # ── Výsledky ──────────────────────────────────────────────────────────
    results = st.session_state.get("bulk_results", [])
    if not results:
        st.stop()

    st.markdown("---")
    st.markdown("### Výsledky zpracování")

    ok_count   = sum(1 for r in results if r["or_status"] == "ok")
    fail_count = sum(1 for r in results if r["or_status"] == "error")
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Celkem", len(results))
    col_b.metric("OR staženo ✅", ok_count)
    col_c.metric("Chyby ❌", fail_count)

    df_results = pd.DataFrame([
        {
            "IČO":    r["ico"],
            "Název":  r["nazev"],
            "OR":     _status_icon(r["or_status"]),
            "Poznámka": r.get("or_msg", "") if r["or_status"] == "error" else "",
        }
        for r in results
    ])
    st.dataframe(df_results, use_container_width=True, hide_index=True)

    # ── Retry jednotlivých chyb ───────────────────────────────────────────
    error_rows = [r for r in results if r["or_status"] == "error"]
    if error_rows:
        st.markdown("#### 🔄 Opakovat neúspěšná stažení")
        for rr in error_rows:
            label = f"{rr['nazev'] or rr['ico']} ({rr['ico']})"
            col_lbl, col_btn = st.columns([5, 1])
            col_lbl.markdown(f"❌ **{label}** – `{rr.get('or_msg', '')}`")
            if col_btn.button("🔄 Retry", key=f"retry_{rr['ico']}"):
                # Pokud chybí subjektId, zkusíme znovu
                if not rr["subjekt_id"]:
                    rr["subjekt_id"] = lookup_subjekt_id(rr["ico"]) or ""
                    if rr["subjekt_id"]:
                        upsert_client_subjekt_id(rr["ico"], rr["subjekt_id"])
                if rr["subjekt_id"]:
                    pdf_bytes, msg = download_or_pdf(rr["subjekt_id"])
                    new_status = "ok" if pdf_bytes else "error"
                    for r_item in results:
                        if r_item["ico"] == rr["ico"]:
                            r_item["or_status"] = new_status
                            r_item["or_msg"]    = msg
                            if pdf_bytes:
                                r_item["or_entry"] = {
                                    "data": pdf_bytes,
                                    "filename": make_filename(rr["nazev"] or rr["ico"], "or"),
                                }
                            if rr.get("run_id"):
                                update_podklady_status(rr["run_id"], "or_status", new_status)
                    log_audit("Podklady", "or_retry", ico=rr["ico"],
                              details=f"status={new_status} {msg}")
                    st.session_state["bulk_results"] = results
                    st.rerun()
                else:
                    st.error(f"subjektId pro {rr['ico']} stále nenalezeno – zkontrolujte IČO.")

    # ── Hlavní tlačítko stažení ───────────────────────────────────────────
    ok_pdfs   = [r["or_entry"] for r in results if r["or_entry"]]
    esm_items = [r for r in results if r["subjekt_id"]]

    st.markdown("---")
    if fail_count:
        st.warning(
            f"{fail_count} záznamů má chybu OR. Stažení ESM proběhne pro všechny s dohledaným subjektId. "
            "Chybné OR výpisy můžete opakovat výše."
        )

    if st.button(
        f"📥 Stáhnout všechny podklady ({ok_count} OR + {len(esm_items)} × ESM)",
        key="btn_bulk_dl_all",
        type="primary",
    ):
        js_parts_bulk: list[str] = []
        if ok_pdfs:
            js_parts_bulk.append(bulk_download_js(ok_pdfs))
        if esm_items:
            all_esm_items: list[dict] = []
            for r in esm_items:
                fn_base = r["nazev"] or r["ico"]
                all_esm_items.append({"url": esm_vypis_url(r["subjekt_id"]),
                                      "filename": make_filename(fn_base, "esm")})
                all_esm_items.append({"url": esm_grafika_url(r["subjekt_id"]),
                                      "filename": make_filename(fn_base, "esm_grafika")})
            js_parts_bulk.append(bulk_open_esm_js(all_esm_items))
            for r in esm_items:
                if r["run_id"]:
                    update_podklady_status(r["run_id"], "esm_status", "ok")
                    update_podklady_status(r["run_id"], "esm_grafika_status", "ok")
        if js_parts_bulk:
            components.html("\n".join(js_parts_bulk), height=0)
        log_audit("Podklady", "bulk_all_download",
                  details=f"or={len(ok_pdfs)} esm_klientů={len(esm_items)}")
        st.success(
            f"✅ Spuštěno: {len(ok_pdfs)} OR PDF + {len(esm_items) * 2} ESM záložek."
        )

# ===========================================================================
# TAB 3 – Historie
# ===========================================================================
with tab_history:
    st.subheader("Historie stažení podkladů")

    col_hist_filter, col_hist_refresh = st.columns([4, 1])
    with col_hist_filter:
        clients_for_filter = get_clients(active_only=False)
        filter_options = ["Všichni"] + [
            f"{c['ico']} – {c['nazev']}" for c in clients_for_filter
        ]
        filter_sel = st.selectbox("Filtrovat dle klienta", filter_options, key="hist_filter")
    with col_hist_refresh:
        st.markdown("<div style='margin-top:1.8rem'></div>", unsafe_allow_html=True)
        if st.button("🔄 Obnovit", key="btn_hist_refresh"):
            st.rerun()

    filter_ico = "" if filter_sel == "Všichni" else filter_sel.split(" – ")[0].strip()

    try:
        history = get_podklady_history(ico=filter_ico, limit=100)
    except Exception as exc:
        st.error(f"Chyba při načítání historie: {exc}")
        history = []

    if not history:
        st.info("Žádné záznamy. Spusťte zpracování podkladů – záznamy se zobrazí zde.")
    else:
        df_hist = pd.DataFrame(history)
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
        display_cols = [c for c in rename_map.values() if c in df_hist.columns]
        st.dataframe(df_hist[display_cols], use_container_width=True, hide_index=True)
        st.caption(f"Zobrazeno {len(df_hist)} záznamů.")
