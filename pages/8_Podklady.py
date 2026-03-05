"""
Modul 8 – Stažení podkladů ESM
Stahování OR výpisů (server-side) a generování ESM odkazů pro prohlížeč.
"""

import time
from datetime import date, datetime

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
    create_renamed_zip,
    download_or_pdf,
    esm_grafika_url,
    esm_vypis_url,
    lookup_subjekt_id,
    make_filename,
    match_esm_uploads,
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
                    {"url": esm_vypis_url(sid),   "filename": make_filename(fn_base, "esm"),
                     "type": "vypis"},
                    {"url": esm_grafika_url(sid),  "filename": make_filename(fn_base, "esm_grafika"),
                     "type": "grafika"},
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
                                                    "filename": make_filename(fn_r, "esm"),
                                                    "type": "vypis"})
                            update_podklady_status(run_id, "esm_status", "ok")
                        if fix_graf and sid_r:
                            esm_retry_items.append({"url": esm_grafika_url(sid_r),
                                                    "filename": make_filename(fn_r, "esm_grafika"),
                                                    "type": "grafika"})
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

    # ── Přejmenování stažených ESM souborů ────────────────────────────────
    st.markdown("---")
    st.markdown("### 📁 Přejmenovat stažené ESM soubory")
    st.caption(
        "ESM soubory se z esm.justice.cz stahují s názvem od serveru "
        "(bezpečnostní omezení prohlížeče). Nahrajte je sem – aplikace je "
        "automaticky přiřadí, přejmenuje a nabídne ke stažení jako ZIP."
    )
    esm_uploads_single = st.file_uploader(
        "Stažené ESM soubory", accept_multiple_files=True, key="esm_rename_single",
    )
    if esm_uploads_single:
        fn_base_s = nazev_single.strip() or ico_single.strip()
        if not fn_base_s:
            st.warning("Vyplňte IČO nebo název společnosti výše – použije se pro názvy souborů.")
        else:
            # Pro jedno IČO: company_order má jediný prvek
            sid_for_match = ""
            clients_match = get_clients(active_only=False)
            sid_for_match = next(
                (c.get("subjekt_id") or "" for c in clients_match
                 if c["ico"] == ico_single.strip()), ""
            )
            company_order_single = [{
                "nazev": nazev_single.strip(), "ico": ico_single.strip(),
                "subjekt_id": sid_for_match,
            }]
            matches = match_esm_uploads(
                [uf.name for uf in esm_uploads_single], company_order_single,
            )
            renamed_files: list[dict] = []
            all_options = ["ESM výpis", "ESM grafická struktura"]
            for i, (uf, m) in enumerate(zip(esm_uploads_single, matches)):
                col_orig, col_new = st.columns([2, 2])
                with col_orig:
                    st.text(f"📄 {uf.name}")
                if m["matched"]:
                    # Auto-matched
                    with col_new:
                        st.markdown(f"✅ → **{m['new_filename']}**")
                    renamed_files.append({"data": uf.read(), "filename": m["new_filename"]})
                else:
                    # Nerozpoznaný soubor – název neodpovídá vzoru výpisu ani grafiky.
                    # Nejčastěji jde o login stránku staženou při vypršené ESM session.
                    with col_new:
                        st.warning(
                            f"⚠️ **{uf.name}** nebyl rozpoznán. "
                            "Pokud jde o login stránku místo ESM souboru, stáhněte ho znovu. "
                            "Jinak přiřaďte ručně:"
                        )
                        sel = st.selectbox(
                            "Typ", all_options, key=f"esm_type_s_{i}",
                            label_visibility="collapsed",
                        )
                    dt = "esm_grafika" if "grafick" in sel else "esm"
                    new_name = make_filename(fn_base_s, dt)
                    st.caption(f"→ **{new_name}** (ruční přiřazení – obsah neověřen)")
                    renamed_files.append({"data": uf.read(), "filename": new_name})

            if renamed_files:
                zip_bytes = create_renamed_zip(renamed_files)
                today_str = date.today().strftime("%d.%m.%Y")
                st.download_button(
                    f"📥 Stáhnout přejmenované ({len(renamed_files)} souborů, ZIP)",
                    data=zip_bytes,
                    file_name=f"ESM_podklady_{fn_base_s}_{today_str}.zip",
                    mime="application/zip",
                    key="dl_esm_renamed_single",
                )

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
                                      "filename": make_filename(fn_base, "esm"),
                                      "type": "vypis"})
                all_esm_items.append({"url": esm_grafika_url(r["subjekt_id"]),
                                      "filename": make_filename(fn_base, "esm_grafika"),
                                      "type": "grafika"})
            js_parts_bulk.append(bulk_open_esm_js(all_esm_items))
            # Uložíme pořadí firem pro rename workflow
            st.session_state["esm_company_order"] = [
                {"nazev": r["nazev"], "ico": r["ico"], "subjekt_id": r["subjekt_id"]}
                for r in esm_items
            ]
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

    # ── Přejmenování stažených ESM souborů (hromadné) ─────────────────────
    company_order_bulk = st.session_state.get("esm_company_order", [])
    if company_order_bulk:
        st.markdown("---")
        st.markdown("### 📁 Přejmenovat stažené ESM soubory")
        st.caption(
            "ESM soubory se z esm.justice.cz stahují s názvem od serveru. "
            "Nahrajte je všechny sem – aplikace je automaticky přiřadí "
            "podle subjektId (výpisy) a pořadí stahování (grafiky), přejmenuje "
            "a nabídne jako ZIP."
        )
        expected_count = len(company_order_bulk) * 2
        st.info(f"Očekáváno **{expected_count}** souborů ({len(company_order_bulk)} klientů × 2).")
        esm_uploads_bulk = st.file_uploader(
            "Stažené ESM soubory", accept_multiple_files=True, key="esm_rename_bulk",
        )
        if esm_uploads_bulk:
            matches_b = match_esm_uploads(
                [uf.name for uf in esm_uploads_bulk], company_order_bulk,
            )
            # Sestavíme options pro ruční přiřazení nerozpoznaných souborů
            all_options_b: list[str] = []
            for c in company_order_bulk:
                label = c["nazev"] or c["ico"]
                all_options_b.append(f"{label} – ESM výpis")
                all_options_b.append(f"{label} – ESM grafická struktura")

            renamed_bulk: list[dict] = []
            matched_count = sum(1 for m in matches_b if m["matched"])
            unmatched_count = len(matches_b) - matched_count
            if matched_count:
                st.success(f"✅ Automaticky přiřazeno: {matched_count} souborů")
            if unmatched_count:
                st.warning(f"⚠️ {unmatched_count} souborů nebylo rozpoznáno – přiřaďte ručně níže.")

            # Detekce chybějících souborů: porovnáme nahrané vs. očekávané
            if len(esm_uploads_bulk) < expected_count:
                # Zjistíme, které (company_idx, doc_type) páry jsou pokryté nahraným souborem
                covered: set[tuple[int, str]] = set()
                for m in matches_b:
                    if m["matched"] and m["company_idx"] is not None:
                        covered.add((m["company_idx"], m["doc_type"]))
                missing_labels: list[str] = []
                for ci, c in enumerate(company_order_bulk):
                    label = c["nazev"] or c["ico"]
                    if (ci, "esm") not in covered:
                        missing_labels.append(f"**{label}** – ESM výpis")
                    if (ci, "esm_grafika") not in covered:
                        missing_labels.append(f"**{label}** – ESM grafická struktura")
                if missing_labels:
                    missing_md = "\n".join(f"- {x}" for x in missing_labels)
                    st.error(
                        f"Nahráno {len(esm_uploads_bulk)} ze {expected_count} souborů. "
                        f"Pravděpodobně chybí:\n{missing_md}"
                    )

            for i, (uf, m) in enumerate(zip(esm_uploads_bulk, matches_b)):
                col_orig_b, col_new_b = st.columns([2, 3])
                with col_orig_b:
                    st.text(f"📄 {uf.name}")
                if m["matched"]:
                    with col_new_b:
                        st.markdown(f"✅ → **{m['new_filename']}**")
                    renamed_bulk.append({"data": uf.read(), "filename": m["new_filename"]})
                else:
                    # Nerozpoznaný soubor – název neodpovídá ani výpisu, ani grafice.
                    # NEJČASTĚJŠÍ PŘÍČINA: vypršela ESM session → browser stáhl login
                    # stránku místo PDF. Soubor bude mít špatný obsah i po přejmenování.
                    with col_new_b:
                        st.warning(
                            f"⚠️ Soubor **{uf.name}** nebyl rozpoznán "
                            f"(neobsahuje `vypis-{{číslo}}` ani `grafickaStruktura`). "
                            "Pravděpodobně jde o login stránku místo ESM souboru – "
                            "zkontrolujte, zda máte platnou ESM session, a soubor stáhněte znovu. "
                            "Pokud víte co soubor je, přiřaďte ručně:"
                        )
                        sel_b = st.selectbox(
                            "Přiřadit k", all_options_b, key=f"esm_assign_b_{i}",
                            label_visibility="collapsed",
                        )
                    # Rozpoznáme výběr → doc_type + firma
                    sel_idx = all_options_b.index(sel_b)
                    c_idx = sel_idx // 2
                    is_grafika_sel = sel_idx % 2 == 1
                    c_sel = company_order_bulk[c_idx]
                    dt_sel = "esm_grafika" if is_grafika_sel else "esm"
                    new_name_b = make_filename(c_sel["nazev"] or c_sel["ico"], dt_sel)
                    st.caption(f"→ **{new_name_b}** (ruční přiřazení – obsah neověřen)")
                    renamed_bulk.append({"data": uf.read(), "filename": new_name_b})

            if renamed_bulk:
                zip_bytes_bulk = create_renamed_zip(renamed_bulk)
                today_str = date.today().strftime("%d.%m.%Y")
                st.download_button(
                    f"📥 Stáhnout přejmenované ({len(renamed_bulk)} souborů, ZIP)",
                    data=zip_bytes_bulk,
                    file_name=f"ESM_podklady_hromadne_{today_str}.zip",
                    mime="application/zip",
                    key="dl_esm_renamed_bulk",
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
