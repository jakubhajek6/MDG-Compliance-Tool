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


def bulk_open_esm_js(items: list[dict]) -> str:
    """Vrátí HTML/JS snippet, který hromadně stáhne ESM dokumenty v prohlížeči.

    Každý prvek ``items`` musí obsahovat klíče ``url`` (str) a ``filename``
    (str – požadovaný název souboru, např. ``'MatiDal s.r.o._ESM_05.03.2026.pdf'``).

    Strategie: pokusí se stáhnout soubor přes ``fetch()`` s session cookies
    (browser má aktivní ESM session) a pojmenovat ho zadaným názvem.
    Pokud fetch selže (CORS, network error), otevře URL v nové záložce jako
    fallback – soubor se stáhne bez vlastního názvu dle hlaviček serveru.

    Args:
        items: Seznam ``{"url": str, "filename": str}`` slovníků.
    """
    calls_parts = []
    for i, item in enumerate(items):
        url = item["url"]
        fname = item["filename"].replace('"', "_")  # escape pro JS string literal
        calls_parts.append(
            f'  downloadEsmItem("{url}", "{fname}", {i * 200});'
        )
    calls = "\n".join(calls_parts)
    return f"""
<script>
function downloadEsmItem(url, fname, delay) {{
  setTimeout(function() {{
    fetch(url, {{credentials: 'include', mode: 'cors'}})
      .then(function(r) {{
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.blob();
      }})
      .then(function(b) {{
        var a = document.createElement('a');
        a.href = URL.createObjectURL(b);
        a.download = fname;
        document.body.appendChild(a);
        a.click();
        setTimeout(function() {{
          URL.revokeObjectURL(a.href);
          document.body.removeChild(a);
        }}, 1000);
      }})
      .catch(function() {{
        // CORS nebo chyba sítě – fallback na window.open (soubor bez vlastního názvu)
        window.open(url, '_blank');
      }});
  }}, delay);
}}
{calls}
</script>
"""
