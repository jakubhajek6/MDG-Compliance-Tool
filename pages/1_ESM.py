"""
Modul 1 – ESM (Evidence skutečných majitelů / UBO Tool)
Převzatý z existujícího UBO Tool + rozšíření o statutární orgány a AML link.
"""

import os
import re
import sqlite3
import base64
from io import BytesIO
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import streamlit as st
from reportlab.pdfgen import canvas as _canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from importer.ares_vr_client import AresVrClient
from importer.ownership_resolve_online import resolve_tree_online
from importer.graphviz_render import build_graphviz_from_nodelines_bfs

from modules.ares_api import fetch_ares_vr, extract_company_info
from db.database import init_db, log_audit, save_or_snapshot
from modules.auth import require_login
from modules.sidebar import render_sidebar

# ===== PATH pro Graphviz =====
for p in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/opt/local/bin", "/snap/bin"):
    if p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + p

# ===== PAGE CONFIG =====
st.set_page_config(page_title="MDG – ESM", page_icon="🏛️", layout="wide")
require_login()

# ===== THEME =====
PRIMARY = "#2EA39C"
CSS = f"""
<style>
.stButton > button, .stDownloadButton > button {{
  background-color: {PRIMARY} !important;
  color: white !important;
  border: 1px solid {PRIMARY} !important;
}}
div.stProgress > div > div {{ background-color: {PRIMARY} !important; }}
a, a:visited {{ color: {PRIMARY}; }}
.small-muted {{ color: #666; font-size: 0.9rem; }}
.breadcrumb {{ color: #888; font-size: 0.85rem; margin-bottom: 0.5rem; }}
.stat-node {{ background-color: #FFE0B2; border-radius: 8px; padding: 8px; margin: 4px 0; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)
render_sidebar()

# ===== DB =====
init_db()

ares_db_path = os.environ.get("ARES_CACHE_PATH", str(Path("data") / "mdg_compliance.sqlite"))

# Ensure ARES cache table
from importer.ares_vr_client import ensure_ares_cache_schema
ensure_ares_cache_schema(ares_db_path)

# ===== PDF Font =====
PDF_FONT_NAME = "DejaVuSans"
font_path = None
for p in [Path("assets/DejaVuSans.ttf"), Path("DejaVuSans.ttf"), Path("fonts/DejaVuSans.ttf")]:
    if p.exists():
        font_path = p
        break
if font_path:
    try:
        pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, str(font_path)))
    except Exception:
        PDF_FONT_NAME = "Helvetica"
else:
    PDF_FONT_NAME = "Helvetica"

# ===== Logo =====
def load_project_logo():
    for fname in ("assets/logo.png", "logo.png"):
        p = Path(fname)
        if p.exists():
            return p.read_bytes(), "image/png"
    return None, ""

logo_bytes, logo_mime = load_project_logo()

# ===== Helpers (z UBO Tool) =====
INDENT_RE = re.compile(r"^( +)(.*)$")

def _line_depth_text(ln):
    if hasattr(ln, "text"):
        return int(getattr(ln, "depth", 0) or 0), str(getattr(ln, "text", ""))
    if isinstance(ln, dict):
        return int(ln.get("depth", 0) or 0), str(ln.get("text", ""))
    if isinstance(ln, (tuple, list)) and len(ln) >= 2:
        return int(ln[0] or 0), str(ln[1])
    if isinstance(ln, str):
        s = ln.rstrip("\n")
        m = INDENT_RE.match(s)
        if m:
            return len(m.group(1)) // 4, m.group(2).strip()
        return 0, s
    return 0, str(ln)

def _ensure_list(x):
    if x is None: return []
    if isinstance(x, (list, tuple)): return list(x)
    return [x]

def _normalize_resolve_result(res):
    if isinstance(res, tuple):
        lines = res[0] if len(res) >= 1 else []
        warnings = res[1] if len(res) >= 2 else []
        return _ensure_list(lines), _ensure_list(warnings)
    return _ensure_list(res), []

def render_lines(lines):
    items = _ensure_list(lines)
    out = []
    for ln in items:
        depth, text = _line_depth_text(ln)
        indent = "    " * max(0, depth)
        out.append(f"{indent}{text}")
    return out

RE_COMPANY_HEADER = re.compile(r"^(?P<name>.+)\s+\(IČO\s+(?P<ico>\d{7,8})\)\s*$")
ICO_IN_LINE = re.compile(r"\(IČO\s+(?P<ico>\d{7,8})\)")
DASH_SPLIT = re.compile(r"\s+[—–-]\s+")

def extract_companies_from_lines(lines):
    items = _ensure_list(lines)
    found = {}
    for ln in items:
        _, t = _line_depth_text(ln)
        tt = (t or "").strip()
        if not tt: continue
        hm = RE_COMPANY_HEADER.match(tt)
        if hm:
            found[hm.group("ico").zfill(8)] = hm.group("name").strip()
            continue
        im = ICO_IN_LINE.search(tt)
        if im:
            ico = im.group("ico").zfill(8)
            left = tt[:im.start()].strip()
            parts = DASH_SPLIT.split(left, maxsplit=1)
            name = (parts[0] if parts else left).strip()
            found[ico] = name
    return sorted([(name, ico) for ico, name in found.items()], key=lambda x: x[0].lower())

# ===== UBO parsing =====
PCT_RE = re.compile(r"(\d+(?:[.,;]\d+)?)\s*%")
PROCENTA_RE = re.compile(r"(\d+(?:[.,;]\d+)?)\s*PROCENTA", re.IGNORECASE)
FRAC_SLASH_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
FRAC_SEMI_RE = re.compile(r"(\d+)\s*;\s*(\d+)\s*(ZLOMEK|TEXT)?", re.IGNORECASE)
OBCHODNI_PODIL_FRAC_RE = re.compile(r"obchodni[_ ]?podil\s*:\s*(\d+)\s*[/;]\s*(\d+)", re.IGNORECASE)
OBCHODNI_PODIL_PCT_RE = re.compile(r"obchodni[_ ]?podil\s*:\s*(\d+(?:[.,;]\d+)?)\s*(?:%|PROCENTA)", re.IGNORECASE)
HLASOVACI_PRAVA_PCT_RE = re.compile(r"hlasovaci[_ ]?prava\s*:\s*(\d+(?:[.,;]\d+)?)\s*(?:%|PROCENTA)", re.IGNORECASE)
SPLACENO_FIELD_RE = re.compile(r"splaceno\s*:\s*\d+(?:[.,;]\d+)?\s*PROCENTA", re.IGNORECASE)
EFEKTIVNE_RE = re.compile(r"efektivně\s+(\d+(?:[.,;]\d+)?)\s*%", re.IGNORECASE)
RE_FOREIGN_HEADER = re.compile(r"^(?P<name>.+)\s+\(ID\s+(?P<fid>[A-Za-z0-9-]+)\)\s*$")
FOREIGN_IN_LINE = re.compile(r"\(ID\s+(?P<fid>[A-Za-z0-9-]+)\)")

def _to_float(s):
    try: return float(s.replace(",", ".").replace(";", "."))
    except Exception: return None

def parse_pct_from_text(s):
    s = (s or "").strip()
    if not s: return None
    s = SPLACENO_FIELD_RE.sub("", s)
    total = 0.0; found = False
    for m in OBCHODNI_PODIL_FRAC_RE.finditer(s):
        a = _to_float(m.group(1)); b = _to_float(m.group(2))
        if a is not None and b and b != 0: total += (a / b); found = True
    for m in OBCHODNI_PODIL_PCT_RE.finditer(s):
        v = _to_float(m.group(1))
        if v is not None: total += (v / 100.0); found = True
    if found: return max(0.0, min(1.0, total))
    hv_total = 0.0; hv_found = False
    for m in HLASOVACI_PRAVA_PCT_RE.finditer(s):
        v = _to_float(m.group(1))
        if v is not None: hv_total += (v / 100.0); hv_found = True
    if hv_found: return max(0.0, min(1.0, hv_total))
    frac_total = 0.0; frac_found = False
    for m in FRAC_SLASH_RE.finditer(s):
        a = _to_float(m.group(1)); b = _to_float(m.group(2))
        if a is not None and b and b != 0: frac_total += (a / b); frac_found = True
    for m in FRAC_SEMI_RE.finditer(s):
        a = _to_float(m.group(1)); b = _to_float(m.group(2))
        if a is not None and b and b != 0: frac_total += (a / b); frac_found = True
    if frac_found: return max(0.0, min(1.0, frac_total))
    pct_total = 0.0; pct_found = False
    for m in PCT_RE.finditer(s):
        v = _to_float(m.group(1))
        if v is not None: pct_total += (v / 100.0); pct_found = True
    for m in PROCENTA_RE.finditer(s):
        v = _to_float(m.group(1))
        if v is not None: pct_total += (v / 100.0); pct_found = True
    if pct_found: return max(0.0, min(1.0, pct_total))
    return None

def fmt_pct(x):
    if x is None: return "—"
    return f"{(x * 100.0):.2f}%"

def compute_effective_persons(lines):
    persons = {}
    header_stack = []
    pending_next_header_mult = None
    for ln in _ensure_list(lines):
        depth, t = _line_depth_text(ln)
        if not t: continue
        if RE_COMPANY_HEADER.match(t):
            while header_stack and header_stack[-1][0] >= depth: header_stack.pop()
            parent_mult = header_stack[-1][1] if header_stack else 1.0
            this_mult = pending_next_header_mult if pending_next_header_mult is not None else parent_mult
            pending_next_header_mult = None
            header_stack.append((depth, this_mult, "company"))
            continue
        if RE_FOREIGN_HEADER.match(t):
            while header_stack and header_stack[-1][0] >= depth: header_stack.pop()
            parent_mult = header_stack[-1][1] if header_stack else 1.0
            this_mult = pending_next_header_mult if pending_next_header_mult is not None else parent_mult
            pending_next_header_mult = None
            header_stack.append((depth, this_mult, "foreign"))
            continue
        if t.endswith(":"): continue
        parts = DASH_SPLIT.split(t, maxsplit=1)
        name = (parts[0] if parts else t).strip()
        is_company = ICO_IN_LINE.search(t) is not None
        is_foreign = FOREIGN_IN_LINE.search(t) is not None
        expected_parent_header_depth = max(0, depth - 2)
        while header_stack and header_stack[-1][0] > expected_parent_header_depth: header_stack.pop()
        parent_mult = header_stack[-1][1] if header_stack else 1.0
        node_eff = None
        if hasattr(ln, "effective_pct") and getattr(ln, "effective_pct") is not None:
            try: node_eff = float(getattr(ln, "effective_pct")) / 100.0
            except Exception: node_eff = None
        if is_company or is_foreign:
            local_share = None
            if node_eff is not None and parent_mult > 0:
                local_share = node_eff / parent_mult
            else:
                local_share = parse_pct_from_text(t)
                if local_share is None:
                    m = EFEKTIVNE_RE.search(t)
                    if m:
                        eff_pct = _to_float(m.group(1))
                        if eff_pct is not None and parent_mult > 0:
                            local_share = (eff_pct / 100.0) / parent_mult
            pending_next_header_mult = parent_mult * local_share if local_share is not None else None
            continue
        entry = persons.setdefault(name, {"ownership": 0.0, "voting": 0.0, "debug_paths": []})
        local_share = None; eff = None; src = None
        if node_eff is not None:
            eff = node_eff; src = "node_eff"
        else:
            local_share = parse_pct_from_text(t)
            if local_share is not None: eff = parent_mult * local_share; src = "text"
        if eff is not None:
            entry["ownership"] += eff; entry["voting"] += eff
        entry["debug_paths"].append({"parent_mult": parent_mult, "local_share": local_share, "eff": eff, "source": src or "unknown", "text": t})
    for v in persons.values():
        v["ownership"] = max(0.0, min(1.0, v["ownership"]))
        v["voting"] = max(0.0, min(1.0, v["voting"]))
    return persons

# ===== PDF builder =====
def build_pdf(text_lines, graph_png_bytes, logo_bytes, company_links, ubo_lines=None):
    buf = BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    PAGE_W, PAGE_H = A4
    MARGIN = 36
    c.setFont(PDF_FONT_NAME, 10)
    y_top = PAGE_H - MARGIN
    text_x = MARGIN
    if logo_bytes:
        try:
            img = ImageReader(BytesIO(logo_bytes))
            ow, oh = img.getSize()
            tw = 160.0; scale = tw / float(ow); th = oh * scale
            c.drawImage(img, MARGIN, y_top - th, width=tw, height=th, preserveAspectRatio=True, mask='auto')
            text_x = MARGIN + tw + 12
            logo_bottom_y = y_top - th
        except Exception: logo_bottom_y = y_top
    else: logo_bottom_y = y_top
    c.setFont(PDF_FONT_NAME, 14)
    c.drawString(text_x, y_top - 14, "MDG Compliance Tool – ESM")
    c.setFont(PDF_FONT_NAME, 10)
    tz = ZoneInfo("Europe/Prague")
    c.drawString(MARGIN, 18, f"Časové razítko: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}")
    start_y = logo_bottom_y - 12
    c.setFont(PDF_FONT_NAME, 12)
    c.drawString(MARGIN, start_y, "Textový výstup")
    c.setFont(PDF_FONT_NAME, 10)
    text_obj = c.beginText()
    text_obj.setTextOrigin(MARGIN, start_y - 18)
    text_obj.setLeading(14)
    for line in text_lines:
        s = line
        while len(s) > 95:
            cut = s.rfind(" ", 0, 95)
            if cut == -1: cut = 95
            text_obj.textLine(s[:cut]); s = s[cut:].lstrip()
            if text_obj.getY() < 140:
                c.drawText(text_obj); c.showPage(); c.setFont(PDF_FONT_NAME, 10)
                text_obj = c.beginText(); text_obj.setTextOrigin(MARGIN, PAGE_H - MARGIN - 40); text_obj.setLeading(14)
        text_obj.textLine(s)
        if text_obj.getY() < 140:
            c.drawText(text_obj); c.showPage(); c.setFont(PDF_FONT_NAME, 10)
            text_obj = c.beginText(); text_obj.setTextOrigin(MARGIN, PAGE_H - MARGIN - 40); text_obj.setLeading(14)
    c.drawText(text_obj)
    c.showPage()
    c.setFont(PDF_FONT_NAME, 12)
    c.drawString(MARGIN, PAGE_H - MARGIN - 20, "Grafická struktura")
    if graph_png_bytes:
        try:
            img = ImageReader(BytesIO(graph_png_bytes))
            c.drawImage(img, MARGIN, MARGIN, width=PAGE_W - 2*MARGIN, height=PAGE_H - 2*MARGIN - 60, preserveAspectRatio=True, anchor='sw', mask='auto')
        except Exception: c.drawString(MARGIN, PAGE_H - MARGIN - 40, "Graf není k dispozici.")
    else: c.drawString(MARGIN, PAGE_H - MARGIN - 40, "Graf není k dispozici.")
    if company_links:
        c.showPage(); c.setFont(PDF_FONT_NAME, 12)
        c.drawString(MARGIN, PAGE_H - MARGIN - 20, "ODKAZY NA OR")
        c.setFont(PDF_FONT_NAME, 10)
        y_links = PAGE_H - MARGIN - 40
        for name, url in company_links:
            c.drawString(MARGIN, y_links, f"{name} — {url}")
            y_links -= 16
            if y_links < MARGIN + 40: c.showPage(); c.setFont(PDF_FONT_NAME, 10); y_links = PAGE_H - MARGIN - 40
    if ubo_lines:
        c.showPage(); c.setFont(PDF_FONT_NAME, 12)
        c.drawString(MARGIN, PAGE_H - MARGIN - 20, "Skuteční majitelé (vyhodnocení)")
        c.setFont(PDF_FONT_NAME, 10)
        y = PAGE_H - MARGIN - 40
        for line in ubo_lines:
            c.drawString(MARGIN, y, line[:120])
            y -= 14
            if y < MARGIN + 40: c.showPage(); c.setFont(PDF_FONT_NAME, 10); y = PAGE_H - MARGIN - 40
    c.save()
    return buf.getvalue()

# ===== Manuální parser =====
ICO_ONLY_RE = re.compile(r"^\d{7,8}$")
FOREIGN_ID_RE = re.compile(r"^[A-Za-z]{1,6}\d{3,}$")

def progress_ui():
    bar = st.progress(0)
    msg = st.empty()
    def cb(text, p):
        msg.write(text); bar.progress(max(0, min(100, int(p * 100))))
    return cb

def _parse_pairs_mixed(s):
    out = []
    for chunk in (s or "").split(","):
        chunk = chunk.strip()
        if not chunk: continue
        if ":" not in chunk:
            st.error(f"Nesprávný formát: {chunk}"); return None
        left, pct_part = chunk.split(":", 1)
        left = left.strip(); pct_part = pct_part.strip()
        try: pct = float(pct_part.replace(",", ".").replace(";", "."))
        except Exception: st.error(f"Neplatné procento: {pct_part}"); return None
        if pct <= 0: st.error(f"Podíl musí být > 0"); return None
        share = pct / 100.0
        name_opt = None; id_part = left
        m = re.split(r"\s+[—–-]\s+", left, maxsplit=1)
        if len(m) == 2: id_part = m[0].strip(); name_opt = m[1].strip() or None
        digits = re.sub(r"\D+", "", id_part)
        if digits.isdigit() and len(digits) in (7, 8) and id_part.strip().isdigit():
            out.append({"type": "CZ", "id": digits.zfill(8), "name": name_opt, "share": share}); continue
        fid = id_part.strip()
        if FOREIGN_ID_RE.match(fid):
            out.append({"type": "FOREIGN", "id": fid.upper(), "name": name_opt, "share": share}); continue
        person_name = left.strip()
        if name_opt and not FOREIGN_ID_RE.match(id_part): person_name = name_opt
        if not person_name: st.error(f"Neplatné jméno"); return None
        out.append({"type": "PERSON", "name": person_name, "share": share})
    return out

# ===== Session state =====
def ss_default(key, val):
    if key not in st.session_state: st.session_state[key] = val

ss_default("esm_last_result", None)
ss_default("esm_ubo_overrides", {})
ss_default("esm_ubo_cap_overrides", {})
ss_default("esm_manual_persons", {})
ss_default("esm_final_persons", None)
ss_default("esm_manual_company_owners", {})
ss_default("esm_ico_input", "")
ss_default("esm_max_depth", 25)
ss_default("esm_threshold_pct_last", 25.0)
ss_default("esm_block_members_last", [])
ss_default("esm_block_name_last", "Voting Block 1")
ss_default("esm_note_text", "")
ss_default("esm_check_esm", "")
ss_default("esm_check_structure", "")

# ===== HEADER =====
st.markdown('<div class="breadcrumb">Domů / ESM – Evidence skutečných majitelů</div>', unsafe_allow_html=True)

if logo_bytes:
    _b64 = base64.b64encode(logo_bytes).decode("ascii")
    st.markdown(f'<img src="data:image/png;base64,{_b64}" style="width:400px;height:auto;margin-bottom:6px" />', unsafe_allow_html=True)

st.markdown("## ESM – Evidence skutečných majitelů")
st.markdown('<div class="small-muted">Online režim: společníci/akcionáři se načítají z ARES VR API.</div>', unsafe_allow_html=True)
st.markdown("")

# ===== UI Inputs =====
ico = st.text_input("IČO společnosti", value=st.session_state.get("esm_ico_input", ""), placeholder="např. 12345678")
st.session_state["esm_ico_input"] = ico

max_depth = st.slider("Max. hloubka rozkrytí", 1, 60, int(st.session_state.get("esm_max_depth", 25)), 1)
st.session_state["esm_max_depth"] = int(max_depth)

col_btn1, col_btn2, _ = st.columns([1.5, 1.5, 4])
with col_btn1:
    run = st.button("🔎 Rozkrýt strukturu", type="primary")

# ===== Resolve =====
def do_resolve():
    if not ico.strip():
        st.error("Zadejte IČO."); return
    cb = progress_ui(); cb("Start…", 0.01)
    try:
        client = AresVrClient(ares_db_path)
        cb("Načítám z ARES a rozkrývám…", 0.10)
        manual_overrides = st.session_state.get("esm_manual_company_owners") or {}
        res = resolve_tree_online(client=client, root_ico=ico.strip(), max_depth=int(max_depth), manual_overrides=manual_overrides)
        lines, warnings = _normalize_resolve_result(res)
        cb("Načítám statutární orgány…", 0.80)

        # Nové: načtení statutárních orgánů
        statutari = []
        try:
            vr_data = client.get_vr(ico.strip())
            if vr_data and not vr_data.get("_error"):
                info = extract_company_info(vr_data)
                statutari = info.get("statutarni_organ", [])
                # Uložit snapshot
                save_or_snapshot(ico.strip().zfill(8), info)
        except Exception:
            pass

        cb("Hotovo.", 1.0)
        rendered = render_lines(lines)
        g = build_graphviz_from_nodelines_bfs(lines, root_ico=ico.strip(), title=f"Ownership_{ico.strip()}")
        graph_png = None
        try: graph_png = g.pipe(format="png")
        except Exception: graph_png = None
        companies = extract_companies_from_lines(lines)
        st.session_state["esm_last_result"] = {
            "lines": lines, "warnings": warnings, "graphviz": g, "graph_png": graph_png,
            "text_lines": rendered, "companies": companies, "statutari": statutari,
            "ubo_pdf_lines": (st.session_state.get("esm_last_result") or {}).get("ubo_pdf_lines"),
            "unresolved": [w for w in warnings if isinstance(w, dict) and w.get("kind") == "unresolved"],
        }
        log_audit("ESM", "resolve", ico=ico.strip(), details=f"depth={max_depth}")
        st.success("Struktura byla načtena.")
    except Exception as e:
        st.error(f"Chyba při načítání: {e}")

if run: do_resolve()

# ===== Render výsledků =====
lr = st.session_state.get("esm_last_result")
if lr:
    # Textový výstup
    st.subheader("Výsledek – textová struktura")
    st.code("\n".join(lr["text_lines"]), language="text")

    # Graf
    st.subheader("Výsledek – graf")
    try:
        st.graphviz_chart(lr["graphviz"].source)
    except Exception:
        st.warning("Nelze zobrazit graf.")

    # === NOVÉ: Statutární orgány ===
    statutari = lr.get("statutari", [])
    if statutari:
        st.subheader("Statutární orgány")
        st.caption("Jednatelé a členové představenstva načtení z ARES VR.")
        for i, stat in enumerate(statutari):
            col_s1, col_s2, col_s3 = st.columns([3, 2, 2])
            with col_s1:
                icon = "🟠" if stat.get("typ") == "FO" else "🔵"
                st.markdown(f"{icon} **{stat.get('jmeno', 'N/A')}**")
            with col_s2:
                st.markdown(f"Funkce: {stat.get('funkce', 'N/A')}")
            with col_s3:
                # Tlačítko AML kontrola
                if stat.get("typ") == "FO":
                    if st.button(f"🔍 AML kontrola", key=f"aml_stat_{i}"):
                        st.session_state["aml_prefill_name"] = stat.get("jmeno", "")
                        st.session_state["aml_prefill_type"] = "FO"
                        st.switch_page("pages/3_AML.py")

    # Manuální doplnění vlastníků
    st.subheader("Doplnění vlastníků u entit bez dohledaných vlastníků")
    unresolved_list = lr.get("unresolved") or []
    if not unresolved_list:
        st.info("Všechny vlastnické vztahy jsou dohledány.")
    else:
        def _fmt_unres(u):
            nm = u.get("name", "?")
            uid = (u.get("id") or u.get("ico") or "").strip()
            if u.get("ico"): return f"{nm} (IČO {str(u.get('ico')).zfill(8)})"
            return f"{nm} (ID {uid})"
        opts = [_fmt_unres(u) for u in unresolved_list]
        picked = st.selectbox("Entita k doplnění", options=opts, index=0)
        picked_idx = opts.index(picked)
        picked_obj = unresolved_list[picked_idx]
        target_id = (picked_obj.get("id") or picked_obj.get("ico") or "").strip()
        owners_raw = st.text_input("Seznam vlastníků (oddělit čárkou)", placeholder="03999840: 50, Z4159842: 30, Ing. Jan Novák: 20")
        if st.button("➕ Přidat do struktury"):
            parsed = _parse_pairs_mixed(owners_raw)
            if parsed:
                st.session_state["esm_manual_company_owners"][target_id] = parsed
                do_resolve()
                st.rerun()

    # OR links
    st.subheader("Odkazy na obchodní rejstřík")
    companies = lr["companies"]
    if companies:
        for name, ico_val in companies:
            url = f"https://or.justice.cz/ias/ui/rejstrik-$firma?ico={ico_val}&jenPlatne=VSECHNY"
            st.markdown(f"- **{name}** — {url}")

    company_links_now = [(name, f"https://or.justice.cz/ias/ui/rejstrik-$firma?ico={ico_val}&jenPlatne=VSECHNY") for name, ico_val in companies]

    # PDF bez UBO
    pdf_bytes = build_pdf(lr["text_lines"], lr["graph_png"], logo_bytes, company_links_now, ubo_lines=None)
    st.download_button("📄 Export PDF (bez vyhodnocení SM)", data=pdf_bytes,
                       file_name=f"esm_{ico.strip() or 'export'}.pdf", mime="application/pdf", type="primary")

    # ===== SKUTEČNÍ MAJITELÉ =====
    st.subheader("Skuteční majitelé (dle struktury)")
    persons = compute_effective_persons(lr["lines"])

    # Manuální osoby
    st.markdown("**Manuální doplnění osob (např. náhradní SM):**")
    cM1, cM2, cM3, cM4, cM5 = st.columns([3, 2, 2, 2, 2])
    with cM1: manual_name = st.text_input("Jméno osoby", key="esm_man_name")
    with cM2: manual_cap = st.number_input("Podíl na ZK (%)", 0.0, 100.0, 0.0, 0.01, key="esm_man_cap")
    with cM3: manual_vote = st.number_input("Hlasovací práva (%)", 0.0, 100.0, 0.0, 0.01, key="esm_man_vote")
    with cM4: manual_veto = st.checkbox("Právo veta", key="esm_man_veto")
    with cM5:
        if st.button("➕ Přidat osobu"):
            if manual_name.strip():
                st.session_state["esm_manual_persons"][manual_name.strip()] = {
                    "cap": manual_cap / 100.0, "vote": manual_vote / 100.0,
                    "veto": manual_veto, "org_majority": False, "substitute_ubo": False,
                }
                st.rerun()

    overrides_vote = st.session_state["esm_ubo_overrides"]
    overrides_cap = st.session_state["esm_ubo_cap_overrides"]

    with st.form("ubo_form"):
        threshold_pct = st.number_input("Práh pro SM (%)", 0.0, 100.0,
            float(st.session_state.get("esm_threshold_pct_last", 25.0)), 0.01,
            help='Prah je nastaven striktne na "vice nez" (tj. 25.01 % a vice).')
        st.write("**Osoby a efektivní podíly:**")
        edited_voting_pct = {}; edited_cap_pct = {}
        veto_flags = {}; org_majority_flags = {}; substitute_flags = {}
        for idx, (name, info) in enumerate(persons.items()):
            cA, cB, cC, cD = st.columns([3, 2, 2, 2])
            with cA:
                st.markdown(f"**{name}** — ZK: {fmt_pct(info['ownership'])}, HP: {fmt_pct(info['voting'])}")
            with cB:
                edited_cap_pct[name] = st.number_input(f"ZK % ({name})", 0.0, 100.0,
                    float(f"{overrides_cap.get(name, info['ownership'])*100:.2f}"), 0.01, key=f"cap_{idx}")
            with cC:
                edited_voting_pct[name] = st.number_input(f"HP % ({name})", 0.0, 100.0,
                    float(f"{overrides_vote.get(name, info['voting'])*100:.2f}"), 0.01, key=f"vote_{idx}")
            with cD:
                veto_flags[name] = st.checkbox(f"Veto ({name})", key=f"veto_{idx}")
                substitute_flags[name] = st.checkbox(f"Náhradní SM ({name})", key=f"subs_{idx}")

        st.divider()
        all_names = list(set(list(persons.keys()) + list(st.session_state["esm_manual_persons"].keys())))
        block_members = st.multiselect("Jednání ve shodě", all_names, st.session_state.get("esm_block_members_last", []))
        block_name = st.text_input("Název voting blocku", value=st.session_state.get("esm_block_name_last", "Voting Block 1"))
        submitted = st.form_submit_button("Vyhodnotit skutečné majitele")

    if submitted:
        st.session_state["esm_threshold_pct_last"] = float(threshold_pct)
        st.session_state["esm_block_members_last"] = list(block_members)
        st.session_state["esm_block_name_last"] = str(block_name)
        for n, v in edited_voting_pct.items(): overrides_vote[n] = v / 100.0
        for n, v in edited_cap_pct.items(): overrides_cap[n] = v / 100.0
        final_persons = {}
        for n, info in persons.items():
            final_persons[n] = {
                "cap": overrides_cap.get(n, info["ownership"]),
                "vote": overrides_vote.get(n, info["voting"]),
                "veto": veto_flags.get(n, False),
                "org_majority": org_majority_flags.get(n, False) if n in org_majority_flags else False,
                "substitute_ubo": substitute_flags.get(n, False),
            }
        for mn, mi in st.session_state["esm_manual_persons"].items():
            final_persons[mn] = mi
        thr = threshold_pct / 100.0
        ubo = {}; reasons = {}
        def add_reason(n, r): reasons.setdefault(n, []).append(r)
        block_total = sum(final_persons.get(n, {"vote": 0.0})["vote"] for n in block_members) if block_members else 0.0
        for n, vals in final_persons.items():
            cap = vals["cap"]; vote = vals["vote"]; is_ubo = False
            if cap > thr: is_ubo = True; add_reason(n, f"podíl na kapitálu {fmt_pct(cap)} > {threshold_pct:.2f}%")
            if vote > thr: is_ubo = True; add_reason(n, f"hlasovací práva {fmt_pct(vote)} > {threshold_pct:.2f}%")
            if vals.get("veto"): is_ubo = True; add_reason(n, "právo veta")
            if vals.get("substitute_ubo"): is_ubo = True; add_reason(n, "náhradní SM (§ 5 ZESM)")
            if is_ubo: ubo[n] = vals
        if block_members and block_total > thr:
            for n in block_members:
                if n in final_persons:
                    ubo[n] = final_persons[n]
                    add_reason(n, f'voting block "{block_name}" ({fmt_pct(block_total)})')
        st.success("Vyhodnocení dokončeno.")
        ubo_report_lines = []
        if not ubo:
            st.info("Nebyly zjištěny osoby splňující definici SM.")
        else:
            st.markdown("**Skuteční majitelé:**")
            for n, vals in ubo.items():
                rs = "; ".join(reasons.get(n, []))
                line = f"- {n} — ZK: {fmt_pct(vals['cap'])}, HP: {fmt_pct(vals['vote'])} — {rs}"
                st.markdown(line); ubo_report_lines.append(line)
        st.session_state["esm_last_result"]["ubo_pdf_lines"] = ubo_report_lines
        # PDF s UBO
        pdf_ubo = build_pdf(lr["text_lines"], lr["graph_png"], logo_bytes, company_links_now, ubo_lines=ubo_report_lines)
        st.download_button("📄 Export PDF (s vyhodnocením SM)", data=pdf_ubo,
                           file_name=f"esm_ubo_{ico.strip() or 'export'}.pdf", mime="application/pdf", type="primary")
