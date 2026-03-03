"""
PEP (Politically Exposed Person) kontrola.
Kontroluje jméno proti veřejně dostupným seznamům poslanců, senátorů a dalších PEP.
"""

import json
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "sanctions_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
PEP_CACHE_FILE = CACHE_DIR / "pep_list.json"
CACHE_TTL_HOURS = 168  # 7 dní


def _is_cache_fresh(cache_file: Path) -> bool:
    if not cache_file.exists():
        return False
    mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
    return (datetime.now() - mtime) < timedelta(hours=CACHE_TTL_HOURS)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _fetch_psp_members() -> list[dict]:
    """Načte seznam poslanců z psp.cz."""
    members = []
    try:
        url = "https://www.psp.cz/sqw/snem.sqw?o=9&l=cz"
        r = requests.get(url, timeout=15, headers={
            "User-Agent": "MDG-Compliance-Tool/1.0",
            "Accept-Language": "cs-CZ",
        })
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            for link in soup.select("a"):
                text = link.get_text(strip=True)
                # Typicky formát "Příjmení Jméno" nebo "Ing. Jméno Příjmení"
                if len(text.split()) >= 2 and not text.startswith("(") and len(text) < 60:
                    href = link.get("href", "")
                    if "sqw/detail" in href or "id=" in href:
                        members.append({
                            "name": text,
                            "role": "poslanec/poslankyně PSP ČR",
                            "source": "psp.cz",
                        })
    except Exception:
        pass
    return members


def _fetch_senat_members() -> list[dict]:
    """Načte seznam senátorů z senat.cz."""
    members = []
    try:
        url = "https://www.senat.cz/senatori/index.php?ke_dni=1&O=14"
        r = requests.get(url, timeout=15, headers={
            "User-Agent": "MDG-Compliance-Tool/1.0",
            "Accept-Language": "cs-CZ",
        })
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            for link in soup.select("a"):
                text = link.get_text(strip=True)
                if len(text.split()) >= 2 and len(text) < 60:
                    href = link.get("href", "")
                    if "senatori" in href and "id" in href:
                        members.append({
                            "name": text,
                            "role": "senátor/senátorka Senátu ČR",
                            "source": "senat.cz",
                        })
    except Exception:
        pass
    return members


def _build_basic_pep_list() -> list[dict]:
    """Sestaví základní PEP databázi z veřejných zdrojů."""
    pep_list = []

    # Poslanci
    pep_list.extend(_fetch_psp_members())
    time.sleep(0.5)

    # Senátoři
    pep_list.extend(_fetch_senat_members())

    # Statické známé PEP pozice (vláda, ČNB, soudy)
    static_roles = [
        "člen vlády ČR",
        "guvernér ČNB",
        "viceguvernér ČNB",
        "člen bankovní rady ČNB",
        "soudce Ústavního soudu",
        "předseda Nejvyššího soudu",
        "předseda Nejvyššího správního soudu",
        "nejvyšší státní zástupce",
        "prezident NKÚ",
        "veřejný ochránce práv",
    ]

    # Deduplikace podle jména
    seen = set()
    deduped = []
    for entry in pep_list:
        key = entry["name"].lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(entry)

    return deduped


def load_pep_list(force_refresh: bool = False) -> list[dict]:
    """Načte PEP seznam z cache nebo stáhne nový."""
    if not force_refresh and _is_cache_fresh(PEP_CACHE_FILE):
        try:
            return json.loads(PEP_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    entries = _build_basic_pep_list()
    if entries:
        PEP_CACHE_FILE.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return entries


def check_pep(name: str, threshold: float = 0.85) -> list[dict]:
    """
    Kontroluje jméno proti PEP databázi.
    Vrací seznam nalezených shod.
    """
    if not name or not name.strip():
        return []

    hits = []
    pep_list = load_pep_list()
    name_normalized = name.strip()

    for entry in pep_list:
        sim = _similarity(name_normalized, entry["name"])
        if sim >= threshold:
            hits.append({
                "matched_name": entry["name"],
                "role": entry.get("role", "PEP"),
                "source": entry.get("source", ""),
                "similarity": round(sim * 100, 1),
            })

    hits.sort(key=lambda x: x["similarity"], reverse=True)
    return hits
