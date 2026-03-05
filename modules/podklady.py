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
import re
import time
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
    subjekt_id: str, timeout: int = 30
) -> tuple[bytes | None, str]:
    """Stáhne PDF výpisu z obchodního rejstříku ze serveru or.justice.cz.

    Endpoint je veřejný a nevyžaduje autentizaci.

    Args:
        subjekt_id: justice.cz interní ID subjektu.
        timeout:    Timeout HTTP požadavku v sekundách.

    Returns:
        Dvojice ``(bytes, "ok")`` při úspěchu, nebo ``(None, popis_chyby)``
        při jakékoli chybě (HTTP chyba, příliš malý soubor, timeout, …).
    """
    url = _OR_PDF_URL.format(subjekt_id=subjekt_id)
    try:
        r = requests.get(url, timeout=timeout, headers={
            "Accept": "application/pdf,*/*",
            "User-Agent": "MDG-Compliance-Tool/1.0",
        })
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        ct = r.headers.get("Content-Type", "")
        if "pdf" not in ct.lower():
            return None, f"Neočekávaný Content-Type: {ct!r}"
        if len(r.content) < _MIN_PDF_BYTES:
            return None, f"Soubor příliš malý ({len(r.content)} B) – pravděpodobně chybová stránka"
        return r.content, "ok"
    except requests.Timeout:
        return None, "Timeout při stahování"
    except requests.RequestException as exc:
        return None, f"Chyba sítě: {exc}"


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
    return f"{safe_nazev}{labels[doc_type]}.pdf"


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


def bulk_open_esm_js(urls: list[str]) -> str:
    """Vrátí HTML/JS snippet, který hromadně otevře ESM URL v nových záložkách.

    Využívá ``window.open()`` iniciované na GUI event (tlačítko v Streamlit
    odesílá component click), takže popup bloker nezasahuje.

    Args:
        urls: Seznam ESM URL (střídavě výpis / grafika nebo libovolný seznam).
    """
    open_calls = "\n".join(
        f"  setTimeout(function(){{ window.open({url!r}, '_blank'); }}, {i * 100});"
        for i, url in enumerate(urls)
    )
    return f"""
<script>
{open_calls}
</script>
"""
