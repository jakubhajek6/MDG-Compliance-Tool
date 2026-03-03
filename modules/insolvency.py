"""
Insolvenční rejstřík ČR – kontrola v ISIR (isir.justice.cz).
"""

import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

ISIR_SEARCH_URL = "https://isir.justice.cz/isir/ueu/vysledek_lustrace.do"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MDG-Compliance-Tool/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "cs-CZ,cs;q=0.9",
}


def check_insolvency_ico(ico: str) -> list[dict]:
    """Kontroluje IČO v insolvenčním rejstříku."""
    ico = ico.strip().zfill(8)
    return _search_isir(ic=ico)


def check_insolvency_name(name: str) -> list[dict]:
    """Kontroluje jméno osoby v insolvenčním rejstříku."""
    name = name.strip()
    if not name:
        return []
    parts = name.split()
    if len(parts) >= 2:
        # Pokusíme se rozdělit na příjmení a jméno
        prijmeni = parts[-1]
        jmeno = " ".join(parts[:-1])
        # Zkusíme i opačné pořadí
        results = _search_isir(prijmeni=prijmeni, jmeno=jmeno)
        if not results:
            results = _search_isir(prijmeni=parts[0], jmeno=" ".join(parts[1:]))
        return results
    return _search_isir(prijmeni=name)


def _search_isir(ic: str = "", prijmeni: str = "", jmeno: str = "") -> list[dict]:
    """Vyhledá v ISIR dle parametrů."""
    results = []
    try:
        params = {}
        if ic:
            params["ic"] = ic
        if prijmeni:
            params["prijmeni"] = prijmeni
        if jmeno:
            params["jmeno"] = jmeno

        if not params:
            return []

        time.sleep(0.5)  # rate limiting

        r = requests.get(ISIR_SEARCH_URL, params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "lxml")

        # Parsování výsledků z tabulky
        tables = soup.select("table")
        for table in tables:
            for row in table.select("tr"):
                cells = row.select("td")
                if len(cells) >= 3:
                    text = " | ".join(c.get_text(strip=True) for c in cells)
                    # Hledání spisové značky
                    spis_match = re.search(r"(INS\s*\d+/\d+|MSPH\s*\d+\s*INS\s*\d+/\d+)", text)
                    link = row.find("a")
                    url = ""
                    if link and link.get("href"):
                        href = link["href"]
                        if not href.startswith("http"):
                            url = f"https://isir.justice.cz{href}"
                        else:
                            url = href

                    results.append({
                        "text": text[:300],
                        "spisova_znacka": spis_match.group(1) if spis_match else "",
                        "url": url,
                        "source": "ISIR",
                    })

        # Alternativní parsing – hledání výsledků v div elementech
        if not results:
            for div in soup.select("div.search-result, div.vysledek, p"):
                text = div.get_text(strip=True)
                if "INS" in text or "insolvenc" in text.lower():
                    results.append({
                        "text": text[:300],
                        "spisova_znacka": "",
                        "url": "",
                        "source": "ISIR",
                    })

        # Kontrola, zda stránka neobsahuje "žádné záznamy"
        page_text = soup.get_text().lower()
        if "žádné záznamy" in page_text or "nebyl nalezen" in page_text:
            return []

    except Exception:
        pass

    return results
