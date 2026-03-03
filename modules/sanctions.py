"""
Modul pro kontrolu sankčních seznamů EU a UN.
Cachuje lokálně, obnova 1× denně.
"""

import os
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from difflib import SequenceMatcher

import requests

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "sanctions_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

EU_SANCTIONS_URL = "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"
UN_SANCTIONS_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"

EU_CACHE_FILE = CACHE_DIR / "eu_sanctions.json"
UN_CACHE_FILE = CACHE_DIR / "un_sanctions.json"
CACHE_TTL_HOURS = 24


def _is_cache_fresh(cache_file: Path) -> bool:
    if not cache_file.exists():
        return False
    mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
    return (datetime.now() - mtime) < timedelta(hours=CACHE_TTL_HOURS)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _download_eu_sanctions() -> list[dict]:
    """Stáhne a zparsuje EU sankční seznam."""
    try:
        r = requests.get(EU_SANCTIONS_URL, timeout=60, headers={
            "User-Agent": "MDG-Compliance-Tool/1.0"
        })
        if r.status_code != 200:
            return []

        root = ET.fromstring(r.content)
        ns = {"": root.tag.split("}")[0] + "}" if "}" in root.tag else ""}

        entries = []
        # Parse XML – EU consolidated list format
        for entity in root.iter():
            if "SubjectType" in entity.tag or "NameAlias" in entity.tag:
                continue
            name_els = entity.findall(".//{*}NameAlias") or []
            for name_el in name_els:
                whole_name = name_el.get("WholeName", "")
                if whole_name:
                    entries.append({
                        "name": whole_name,
                        "type": name_el.get("SubjectType", entity.get("SubjectType", "")),
                        "source": "EU",
                        "regulation": entity.get("Regulation", ""),
                    })

        # Fallback: jednodušší parsing
        if not entries:
            for el in root.iter():
                tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
                if tag in ("wholeName", "WholeName"):
                    if el.text and el.text.strip():
                        entries.append({
                            "name": el.text.strip(),
                            "type": "",
                            "source": "EU",
                        })
                elif tag == "NameAlias":
                    wn = el.get("WholeName", "")
                    if wn:
                        entries.append({
                            "name": wn,
                            "type": el.get("SubjectType", ""),
                            "source": "EU",
                        })

        return entries
    except Exception:
        return []


def _download_un_sanctions() -> list[dict]:
    """Stáhne a zparsuje UN sankční seznam."""
    try:
        r = requests.get(UN_SANCTIONS_URL, timeout=60, headers={
            "User-Agent": "MDG-Compliance-Tool/1.0"
        })
        if r.status_code != 200:
            return []

        root = ET.fromstring(r.content)
        entries = []

        for individual in root.iter():
            tag = individual.tag.split("}")[-1] if "}" in individual.tag else individual.tag
            if tag == "INDIVIDUAL":
                first = ""
                second = ""
                third = ""
                for child in individual:
                    ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if ctag == "FIRST_NAME":
                        first = (child.text or "").strip()
                    elif ctag == "SECOND_NAME":
                        second = (child.text or "").strip()
                    elif ctag == "THIRD_NAME":
                        third = (child.text or "").strip()
                full_name = " ".join(p for p in [first, second, third] if p)
                if full_name:
                    entries.append({
                        "name": full_name,
                        "type": "individual",
                        "source": "UN",
                    })
            elif tag == "ENTITY":
                for child in individual:
                    ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if ctag == "FIRST_NAME":
                        name = (child.text or "").strip()
                        if name:
                            entries.append({
                                "name": name,
                                "type": "entity",
                                "source": "UN",
                            })

        return entries
    except Exception:
        return []


def load_eu_sanctions(force_refresh: bool = False) -> list[dict]:
    """Načte EU sankční seznam z cache nebo stáhne nový."""
    if not force_refresh and _is_cache_fresh(EU_CACHE_FILE):
        try:
            return json.loads(EU_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    entries = _download_eu_sanctions()
    if entries:
        EU_CACHE_FILE.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return entries


def load_un_sanctions(force_refresh: bool = False) -> list[dict]:
    """Načte UN sankční seznam z cache nebo stáhne nový."""
    if not force_refresh and _is_cache_fresh(UN_CACHE_FILE):
        try:
            return json.loads(UN_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    entries = _download_un_sanctions()
    if entries:
        UN_CACHE_FILE.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return entries


def check_sanctions(name: str, threshold: float = 0.85) -> list[dict]:
    """
    Kontroluje jméno proti EU a UN sankčním seznamům.
    Vrací seznam nalezených shod s mírou podobnosti.
    """
    if not name or not name.strip():
        return []

    hits = []
    name_normalized = name.strip()

    eu_list = load_eu_sanctions()
    for entry in eu_list:
        sim = _similarity(name_normalized, entry["name"])
        if sim >= threshold:
            hits.append({
                "matched_name": entry["name"],
                "source": "EU",
                "similarity": round(sim * 100, 1),
                "type": entry.get("type", ""),
            })

    un_list = load_un_sanctions()
    for entry in un_list:
        sim = _similarity(name_normalized, entry["name"])
        if sim >= threshold:
            hits.append({
                "matched_name": entry["name"],
                "source": "UN",
                "similarity": round(sim * 100, 1),
                "type": entry.get("type", ""),
            })

    hits.sort(key=lambda x: x["similarity"], reverse=True)
    return hits
