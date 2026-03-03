"""
Justice.cz OR scraper – pro Modul 2 (Vizualizace) a doplňkové načítání dat.
Rate limiting: 0.5–1s mezi requesty.
"""

import re
import time
from typing import Optional
from datetime import datetime

import requests
from bs4 import BeautifulSoup

_last_request_ts = 0.0
MIN_DELAY = 0.7

JUSTICE_FIRMA_URL = "https://or.justice.cz/ias/ui/rejstrik-$firma?ico={ico}&jenPlatne=VSECHNY"
JUSTICE_OSOBA_URL = "https://or.justice.cz/ias/ui/rejstrik-$osoba?nazev={name}"
JUSTICE_SPOLECNICI_URL = "https://or.justice.cz/ias/ui/rejstrik-$spolecnici?nazev={name}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MDG-Compliance-Tool/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "cs-CZ,cs;q=0.9",
}


def _rate_limit():
    global _last_request_ts
    now = time.time()
    dt = now - _last_request_ts
    if dt < MIN_DELAY:
        time.sleep(MIN_DELAY - dt)
    _last_request_ts = time.time()


def _fetch_page(url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
    """Načte HTML stránku s rate limitingem."""
    _rate_limit()
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "lxml")
        return None
    except Exception:
        return None


def search_person_engagements(name: str) -> list[dict]:
    """
    Hledá angažmá fyzické osoby na justice.cz.
    Vrací seznam {nazev, ico, role, typ_angažmá}.
    """
    url = JUSTICE_OSOBA_URL.format(name=requests.utils.quote(name))
    soup = _fetch_page(url)
    if not soup:
        return []

    results = []
    for row in soup.select("table.result-details tr, div.search-results li"):
        try:
            text = row.get_text(separator=" ", strip=True)
            # Pokus o extrakci IČO a názvu
            ico_match = re.search(r"IČO:\s*(\d{7,8})", text)
            if ico_match:
                ico = ico_match.group(1).zfill(8)
                # Název firmy je obvykle v prvním odkazu
                link = row.find("a")
                nazev = link.get_text(strip=True) if link else "Neznámá firma"
                results.append({
                    "nazev": nazev,
                    "ico": ico,
                    "role": _extract_role(text),
                    "zdroj": "justice.cz",
                })
        except Exception:
            continue
    return results


def search_company_persons(ico: str) -> list[dict]:
    """
    Hledá osoby angažované u firmy dle IČO na justice.cz.
    """
    url = JUSTICE_FIRMA_URL.format(ico=ico.zfill(8))
    soup = _fetch_page(url)
    if not soup:
        return []

    results = []
    # Parsování výpisu z OR
    for section in soup.select("div.vr-hlavicka, div.aunp-obsah, div.section"):
        text = section.get_text(separator=" ", strip=True)
        # Hledání jmen osob
        name_pattern = re.compile(r"((?:Ing\.|Mgr\.|JUDr\.|PhDr\.|MUDr\.|Bc\.)\s+)?([A-ZÁČĎÉĚÍŇÓŘŠŤŮÚÝŽ][a-záčďéěíňóřšťůúýž]+\s+[A-ZÁČĎÉĚÍŇÓŘŠŤŮÚÝŽ][a-záčďéěíňóřšťůúýž]+)")
        for match in name_pattern.finditer(text):
            results.append({
                "jmeno": match.group(0).strip(),
                "role": _extract_role(text[:200]),
                "zdroj": "justice.cz",
            })
    return results


def _extract_role(text: str) -> str:
    """Extrahuje roli z textu OR."""
    text_lower = text.lower()
    if "jednatel" in text_lower:
        return "jednatel"
    if "předseda představenstva" in text_lower:
        return "předseda představenstva"
    if "člen představenstva" in text_lower:
        return "člen představenstva"
    if "prokurista" in text_lower:
        return "prokurista"
    if "společník" in text_lower:
        return "společník"
    if "akcionář" in text_lower:
        return "akcionář"
    if "člen dozorčí rady" in text_lower:
        return "člen dozorčí rady"
    if "likvidátor" in text_lower:
        return "likvidátor"
    return "angažmá"
