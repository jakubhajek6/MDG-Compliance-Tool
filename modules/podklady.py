"""
MDG Compliance Tool – modul Podklady ESM.

Obsahuje veškerou business logiku pro stahování podkladů z obchodního rejstříku
a generování odkazů pro evidenci skutečných majitelů (ESM).

Architektonická volba – OR server-side, ESM browser-link:
  OR výpisy jsou na veřejném endpointu or.justice.cz; lze je stáhnout
  přímo server-side přes requests a předat uživateli jako bytes.
  ESM výpisy vyžadují přihlášení bankovní identitou, které je vázáno na
  browser session uživatele – nelze přenést na server. Proto ESM předáváme
  jako plain URL, které uživatel otevírá ve svém prohlížeči, kde má session.
  (Viz docs/decisions/2026-03-05-podklady-esm-browser-links.md)
"""

import base64
import io
import re
import time
import zipfile
from datetime import date
from typing import Literal

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# URL konstanty
# ---------------------------------------------------------------------------

_OR_SEARCH_URL = (
    "https://or.justice.cz/ias/ui/rejstrik-$firma"
    "?ico={ico}&jenPlatne=VSECHNY"
)
_OR_PDF_URL = (
    "https://or.justice.cz/ias/ui/print-pdf"
    "?subjektId={subjekt_id}&typVypisu=PLATNY&full=false"
)
_ESM_VYPIS_URL = (
    "https://esm.justice.cz/ias/issm/print-pdf"
    "?subjektId={subjekt_id}&typVypisu=UPLNY_SM&full=false"
)
_ESM_GRAFIKA_URL = (
    "https://esm.justice.cz/ias/issm/wicket/bookmarkable/"
    "cz.inqool.issm.isvr.ias.misc.internet.pages.vypisy.PrintSvgPage"
    "?subjektId={subjekt_id}&typVypisu=UPLNY_SM&full=false&nocache={nocache}"
)

# Minimální akceptovatelná velikost PDF v bajtech (ochrana před HTML chybovou stránkou)
_MIN_PDF_BYTES = 5_000

# Maximální počet pokusů při stahování OR PDF
_OR_MAX_RETRIES = 3
# Prodleva mezi pokusy v sekundách
_OR_RETRY_DELAY = 2.0

# ---------------------------------------------------------------------------
# Lookup subjektId z IČO
# ---------------------------------------------------------------------------

def lookup_subjekt_id(ico: str, timeout: int = 20) -> str | None:
    """Vyhledá justice.cz interní subjektId pro dané IČO.

    Scrapuje OR search stránku a extrahuje subjektId z první nalezené URL.
    Vrátí řetězec (např. ``'898776'``) nebo ``None`` pokud subjekt nebyl
    nalezen nebo došlo k chybě.

    Args:
        ico:     IČO subjektu (8 číslic, funkce neprovádí normalizaci).
        timeout: Timeout HTTP požadavku v sekundách.
    """
    url = _OR_SEARCH_URL.format(ico=ico)
    try:
        r = requests.get(url, timeout=timeout, headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "MDG-Compliance-Tool/1.0",
        })
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "lxml")
        # OR výsledky obsahují href ve tvaru:
        # /ias/ui/rejstrik-firma.vysledky?subjektId=898776&typ=PLATNY
        for a in soup.find_all("a", href=True):
            m = re.search(r"subjektId=(\d+)", a["href"])
            if m:
                return m.group(1)
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Stahování OR PDF (server-side)
# ---------------------------------------------------------------------------

def download_or_pdf(
    subjekt_id: str, timeout: int = 30, max_retries: int = _OR_MAX_RETRIES
) -> tuple[bytes | None, str]:
    """Stáhne PDF výpisu z obchodního rejstříku ze serveru or.justice.cz.

    Endpoint je veřejný a nevyžaduje autentizaci.

    Implementuje retry logiku: při 5xx chybách nebo síťovém výpadku zkusí
    stažení až ``max_retries``-krát s prodlevou ``_OR_RETRY_DELAY`` sekund.

    Validace PDF:
      - Kontroluje HTTP status (musí být 200).
      - Kontroluje Content-Type (musí obsahovat "pdf").
      - Kontroluje skutečné PDF magic bytes ``%PDF`` na začátku obsahu –
        or.justice.cz občas vrátí HTTP 200 + Content-Type: application/pdf
        i pro HTML chybové stránky, takže Content-Type sám nestačí.
      - Minimální velikost souboru (_MIN_PDF_BYTES) jako poslední záchrana.

    Args:
        subjekt_id:  justice.cz interní ID subjektu.
        timeout:     Timeout jednoho HTTP požadavku v sekundách.
        max_retries: Maximální počet pokusů celkem (včetně prvního).

    Returns:
        Dvojice ``(bytes, "ok")`` při úspěchu, nebo ``(None, popis_chyby)``
        při selhání všech pokusů.
    """
    url = _OR_PDF_URL.format(subjekt_id=subjekt_id)
    last_error = "neznámá chyba"

    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, timeout=timeout, headers={
                "Accept": "application/pdf,*/*",
                "User-Agent": "MDG-Compliance-Tool/1.0",
            })

            # Transientní serverová chyba – zkusíme znovu
            if r.status_code >= 500:
                last_error = f"HTTP {r.status_code} (pokus {attempt}/{max_retries})"
                if attempt < max_retries:
                    time.sleep(_OR_RETRY_DELAY)
                    continue
                return None, last_error

            if r.status_code != 200:
                # 4xx a jiné – retry nepomůže
                return None, f"HTTP {r.status_code}"

            # Content-Type kontrola
            ct = r.headers.get("Content-Type", "")
            if "pdf" not in ct.lower():
                last_error = f"Neočekávaný Content-Type: {ct!r} (pokus {attempt}/{max_retries})"
                if attempt < max_retries:
                    time.sleep(_OR_RETRY_DELAY)
                    continue
                return None, last_error

            # Magic bytes: PDF vždy začíná %PDF (0x25 0x50 0x44 0x46)
            # or.justice.cz někdy vrátí HTTP 200 + Content-Type: application/pdf
            # i pro HTML chybové stránky – tohle je jediná spolehlivá detekce.
            if not r.content.startswith(b"%PDF"):
                last_error = (
                    f"Stažený soubor není PDF (magic bytes chybí) – "
                    f"pravděpodobně dočasná chyba serveru (pokus {attempt}/{max_retries})"
                )
                if attempt < max_retries:
                    time.sleep(_OR_RETRY_DELAY)
                    continue
                return None, last_error

            if len(r.content) < _MIN_PDF_BYTES:
                last_error = f"Soubor příliš malý ({len(r.content)} B) (pokus {attempt}/{max_retries})"
                if attempt < max_retries:
                    time.sleep(_OR_RETRY_DELAY)
                    continue
                return None, last_error

            # Vše prošlo – vrátíme obsah
            return r.content, "ok"

        except requests.Timeout:
            last_error = f"Timeout při stahování (pokus {attempt}/{max_retries})"
            if attempt < max_retries:
                time.sleep(_OR_RETRY_DELAY)
        except requests.RequestException as exc:
            last_error = f"Chyba sítě: {exc} (pokus {attempt}/{max_retries})"
            if attempt < max_retries:
                time.sleep(_OR_RETRY_DELAY)

    return None, last_error


# ---------------------------------------------------------------------------
# ESM URL generátory (browser-side)
# ---------------------------------------------------------------------------

def esm_vypis_url(subjekt_id: str) -> str:
    """Vrátí URL pro ESM výpis (otevírá se v prohlížeči uživatele)."""
    return _ESM_VYPIS_URL.format(subjekt_id=subjekt_id)


def esm_grafika_url(subjekt_id: str) -> str:
    """Vrátí URL pro ESM grafickou strukturu (otevírá se v prohlížeči uživatele).

    Přidává ``nocache`` parametr (aktuální milisekundový timestamp) aby se
    předešlo kešování a vždy se načetla aktuální verze dokumentu.
    """
    return _ESM_GRAFIKA_URL.format(
        subjekt_id=subjekt_id,
        nocache=int(time.time() * 1000),
    )


# ---------------------------------------------------------------------------
# Pojmenování souborů
# ---------------------------------------------------------------------------

# Znaky zakázané v názvech souborů na Windows i macOS/Linux
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def make_filename(
    nazev: str,
    doc_type: Literal["or", "esm", "esm_grafika"],
) -> str:
    """Sestaví bezpečný název souboru pro stažený PDF podklad.

    Formáty:
      - ``{nazev}_výpis OR_{dd.mm.rrrr}.pdf``
      - ``{nazev}_ESM_{dd.mm.rrrr}.pdf``
      - ``{nazev}_ESM_{dd.mm.rrrr}_grafická struktura.pdf``

    Speciální a systémově nebezpečné znaky jsou nahrazeny pomlčkou.

    Args:
        nazev:    Název společnosti (např. ``"MatiDal s.r.o."``).
        doc_type: Typ dokumentu – ``"or"``, ``"esm"``, nebo ``"esm_grafika"``.
    """
    today = date.today().strftime("%d.%m.%Y")
    safe_nazev = _UNSAFE_CHARS.sub("-", nazev).strip(" .-")
    labels: dict[str, str] = {
        "or":          f"_výpis OR_{today}",
        "esm":         f"_ESM_{today}",
        "esm_grafika": f"_ESM_{today}_grafická struktura",
    }
    # ESM grafická struktura se stahuje jako SVG, ostatní jako PDF
    ext = ".svg" if doc_type == "esm_grafika" else ".pdf"
    return f"{safe_nazev}{labels[doc_type]}{ext}"


# ---------------------------------------------------------------------------
# ZIP s přejmenovanými soubory
# ---------------------------------------------------------------------------


def create_renamed_zip(files: list[dict]) -> bytes:
    """Vytvoří ZIP archiv s přejmenovanými soubory.

    Args:
        files: Seznam slovníků s klíči ``data`` (bytes) a ``filename`` (str).
               Každý slovník = jeden soubor v ZIP archivu.

    Returns:
        Celý ZIP soubor jako bytes (vhodné pro ``st.download_button``).
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f["filename"], f["data"])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Automatické přiřazení uploadnutých ESM souborů ke společnostem
# ---------------------------------------------------------------------------

# Pattern pro ESM výpis: server pojmenuje soubor přesně „vypis-{subjektId}.pdf"
# Záměrně jednoduchý – subjektId je přímý identifikátor, nepotřebujeme fallback.
# Pokud soubor NEOBSAHUJE „vypis-{čísla}", pravděpodobně jde o chybovou/login stránku.
_VYPIS_PATTERN = re.compile(r"vypis-(\d+)", re.IGNORECASE)
# Pattern pro ESM grafiku: server pojmenuje „grafickaStruktura.svg" / „grafickaStruktura-2.svg" atd.
_GRAFIKA_PATTERN = re.compile(r"grafick[aá]Struktura(?:-(\d+))?\.svg", re.IGNORECASE)


def match_esm_uploads(
    uploaded_names: list[str],
    company_order: list[dict],
) -> list[dict]:
    """Automaticky přiřadí uploadnuté ESM soubory ke společnostem.

    Strategie přiřazení:

    1. **Výpisy** (``vypis-XXXXXX.pdf``): obsahují subjektId přímo v názvu
       souboru → 100% spolehlivé přiřazení přes regex na subjektId.

    2. **Grafiky** (``grafickaStruktura*.svg``): mají deduplikační suffix
       od browseru (``-2``, ``-3``, …). Pořadí suffixu odpovídá pořadí
       stahování → mapujeme na ``company_order`` index.
       Soubor bez suffixu = první firma (index 0).

    3. Nerozpoznané soubory → ``matched=False`` pro ruční přiřazení v UI.

    Args:
        uploaded_names: Názvy uploadnutých souborů (``UploadedFile.name``).
        company_order:  Seznam ``{"nazev": str, "ico": str, "subjekt_id": str}``
                        **v pořadí v jakém byly stahovány** (stejné jako JS).

    Returns:
        Seznam slovníků, jeden pro každý uploadnutý soubor::

            {
                "original_name": str,       # původní název souboru
                "matched": bool,            # True pokud se přiřazení podařilo
                "doc_type": "esm" | "esm_grafika" | None,
                "company_idx": int | None,  # index do company_order
                "new_filename": str | None, # navržený nový název (make_filename)
            }
    """
    # Indexy: subjektId → pozice v company_order
    sid_to_idx: dict[str, int] = {}
    for i, c in enumerate(company_order):
        sid = c.get("subjekt_id", "")
        if sid:
            sid_to_idx[sid] = i

    result: list[dict] = []
    for name in uploaded_names:
        entry: dict = {"original_name": name, "matched": False,
                       "doc_type": None, "company_idx": None, "new_filename": None}

        # Zkusíme match jako výpis
        m_v = _VYPIS_PATTERN.search(name)
        if m_v:
            sid_found = m_v.group(1)
            idx = sid_to_idx.get(sid_found)
            if idx is not None:
                c = company_order[idx]
                fn_base = c["nazev"] or c["ico"]
                entry.update(
                    matched=True, doc_type="esm", company_idx=idx,
                    new_filename=make_filename(fn_base, "esm"),
                )
                result.append(entry)
                continue

        # Zkusíme match jako grafika
        m_g = _GRAFIKA_PATTERN.search(name)
        if m_g:
            # Bez suffixu → index 0, suffix N → index N-1
            suffix_str = m_g.group(1)
            if suffix_str is None:
                gidx = 0
            else:
                gidx = int(suffix_str) - 1   # -2.svg = 2. firma (index 1)
            if 0 <= gidx < len(company_order):
                c = company_order[gidx]
                fn_base = c["nazev"] or c["ico"]
                entry.update(
                    matched=True, doc_type="esm_grafika", company_idx=gidx,
                    new_filename=make_filename(fn_base, "esm_grafika"),
                )
                result.append(entry)
                continue

        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# JS pomocníky pro hromadné akce v prohlížeči
# ---------------------------------------------------------------------------

def bulk_download_js(items: list[dict]) -> str:
    """Vrátí HTML/JS snippet, který hromadně spustí stažení OR PDF v prohlížeči.

    Každý prvek ``items`` musí obsahovat klíče ``filename`` (str) a ``data``
    (bytes – obsah PDF).  Soubory jsou zakódovány jako base64 data-URI a každý
    <a> element je programaticky kliknut se 60ms rozestupem, aby prohlížeč
    neblokoval download popup blokerem.

    Args:
        items: Seznam ``{"filename": str, "data": bytes}`` slovníků.

    Returns:
        HTML string vhodný pro ``st.components.v1.html()``.
    """
    links_js = []
    for item in items:
        b64 = base64.b64encode(item["data"]).decode("ascii")
        fname = item["filename"].replace('"', "_")   # escape pro JS string
        links_js.append(
            f'  dl("{b64}", "{fname}");'
        )
    links_block = "\n".join(
        f"  setTimeout(function(){{ {line.strip()} }}, {i * 60});"
        for i, line in enumerate(links_js)
    )
    return f"""
<script>
function dl(b64, fname) {{
  var a = document.createElement('a');
  a.href = 'data:application/pdf;base64,' + b64;
  a.download = fname;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}}
{links_block}
</script>
"""


def bulk_open_esm_js(items: list[dict]) -> str:
    """Vrátí HTML/JS snippet, který hromadně otevře ESM URL v prohlížeči.

    Dvoufázové stahování:
      - **Fáze 1 – výpisy**: ``window.open`` s krátkým rozestupem (200ms).
        Výpisy mají unikátní názvy ``vypis-{subjektId}.pdf`` – pořadí je
        jedno, přiřazení v rename workflow je přes regex na subjektId.
      - **Fáze 2 – grafiky**: ``window.open`` s velkým rozestupem (3000ms).
        Grafiky sdílejí název ``grafickaStruktura.svg`` a browser přidává
        dedup suffíxy ``-2``, ``-3`` … Velký rozestup zajistí správné
        sekvenční stažení → suffix odpovídá pořadí firem.

    Název souboru při stažení určuje server (Content-Disposition).
    Pro přejmenování na správné názvy slouží sekce
    „Přejmenovat stažené ESM soubory" (upload-rename-ZIP workflow).

    Args:
        items: Seznam ``{"url": str, "filename": str, "type": str}`` slovníků.
               ``type`` je ``"vypis"`` nebo ``"grafika"``.
               ``filename`` se v JS nepoužívá (jen pro kontext / rename).
    """
    # Rozdělit na výpisy a grafiky, zachovat pořadí
    vypisy = [(i, item) for i, item in enumerate(items) if item.get("type") == "vypis"]
    grafiky = [(i, item) for i, item in enumerate(items) if item.get("type") == "grafika"]

    open_calls: list[str] = []
    # Fáze 1: výpisy s krátkým rozestupem
    for seq, (_orig_i, item) in enumerate(vypisy):
        url = item["url"]
        delay_ms = seq * 200
        open_calls.append(
            f"  setTimeout(function(){{ window.open({url!r}, '_blank'); }}, {delay_ms});"
        )
    # Fáze 2: grafiky s velkým rozestupem, start po konci fáze 1
    phase2_start = len(vypisy) * 200 + 500   # 500ms mezera mezi fázemi
    for seq, (_orig_i, item) in enumerate(grafiky):
        url = item["url"]
        delay_ms = phase2_start + seq * 3000
        open_calls.append(
            f"  setTimeout(function(){{ window.open({url!r}, '_blank'); }}, {delay_ms});"
        )
    calls = "\n".join(open_calls)
    return f"""
<script>
{calls}
</script>
"""
