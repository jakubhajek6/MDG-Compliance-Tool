"""
ARES API wrapper – rozšířený pro MDG Compliance Tool.
Využívá stávajícího AresVrClient z UBO Tool + přidává funkce pro další moduly.
"""

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests

ARES_VR_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty-vr/{ico}"
ARES_ES_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}"


def norm_ico(s: str) -> str:
    digits = re.sub(r"\D+", "", s or "")
    if len(digits) == 7:
        digits = "0" + digits
    return digits.zfill(8)


def fetch_ares_basic(ico: str, timeout: int = 20) -> Optional[dict]:
    """Načte základní data z ARES ekonomické-subjekty endpoint."""
    ico = norm_ico(ico)
    url = ARES_ES_URL.format(ico=ico)
    try:
        r = requests.get(url, timeout=timeout, headers={
            "Accept": "application/json",
            "User-Agent": "MDG-Compliance-Tool/1.0"
        })
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def fetch_ares_vr(ico: str, timeout: int = 20) -> Optional[dict]:
    """Načte data z ARES VR (výpis z rejstříku) endpoint."""
    ico = norm_ico(ico)
    url = ARES_VR_URL.format(ico=ico)
    try:
        r = requests.get(url, timeout=timeout, headers={
            "Accept": "application/json",
            "User-Agent": "MDG-Compliance-Tool/1.0"
        })
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def extract_company_info(vr_data: dict, basic_data: Optional[dict] = None) -> dict:
    """Extrahuje strukturovaná data o firmě z ARES VR + basic payloadu."""
    info = {
        "ico": "",
        "dic": "",
        "nazev": "",
        "pravni_forma": "",
        "datum_vzniku": "",
        "datum_zapisu": "",
        "sidlo_ulice": "",
        "sidlo_mesto": "",
        "sidlo_psc": "",
        "sidlo_stat": "Česká republika",
        "predmet_podnikani": "",
        "zakladni_kapital": "",
        "statutarni_organ": [],
        "spolecnici": [],
        "datova_schranka": "",
        "nace_kod": "",
    }

    if not vr_data:
        return info

    info["ico"] = norm_ico(vr_data.get("icoId", "") or "")

    # Basic data (ekonomické-subjekty endpoint)
    if basic_data:
        info["dic"] = basic_data.get("dic", "") or ""
        sidlo = basic_data.get("sidlo") or {}
        info["sidlo_ulice"] = _build_address_street(sidlo)
        info["sidlo_mesto"] = sidlo.get("nazevObce", "") or ""
        info["sidlo_psc"] = str(sidlo.get("psc", "") or "")
        info["sidlo_stat"] = sidlo.get("nazevStatu", "Česká republika") or "Česká republika"
        # pravniForma může přijít buď jako string (nový endpoint) nebo jako objekt {"nazev": ...}
        pf = basic_data.get("pravniForma") or ""
        info["pravni_forma"] = pf.get("nazev", "") if isinstance(pf, dict) else str(pf)
        info["datova_schranka"] = _extract_ds(basic_data)

        nace_list = basic_data.get("czNace") or []
        if nace_list:
            info["nace_kod"] = nace_list[0] if isinstance(nace_list[0], str) else str(nace_list[0])

    # VR data (rejstříkový výpis)
    zaznamy = vr_data.get("zaznamy") or []
    zaznam = _pick_primary(zaznamy)
    if not zaznam:
        return info

    # Název
    for oj in (zaznam.get("obchodniJmeno") or []):
        if not oj.get("datumVymazu"):
            info["nazev"] = oj.get("hodnota", "") or ""

    # Datum vzniku/zápisu
    info["datum_vzniku"] = zaznam.get("datumVzniku", "") or ""
    info["datum_zapisu"] = zaznam.get("datumZapisu", "") or ""

    # Předmět podnikání
    predmety = []
    for pp in (zaznam.get("predmetyPodnikani") or []):
        if not pp.get("datumVymazu"):
            for p in (pp.get("predmetPodnikani") or []):
                if not p.get("datumVymazu"):
                    predmety.append(p.get("hodnota", ""))
    info["predmet_podnikani"] = "; ".join(predmety[:5])

    # Základní kapitál
    for zk in (zaznam.get("zakladniKapital") or []):
        if not zk.get("datumVymazu"):
            vklad = zk.get("vklad") or {}
            hodnota = vklad.get("hodnota")
            mena = vklad.get("mena", "Kč")
            if hodnota:
                info["zakladni_kapital"] = f"{hodnota} {mena}"

    # Statutární orgán
    info["statutarni_organ"] = _extract_statutory_bodies(zaznam)

    # Společníci
    info["spolecnici"] = _extract_partners(zaznam)

    # Sídlo z VR jako fallback
    if not info["sidlo_ulice"]:
        for s in (zaznam.get("sidla") or []):
            if not s.get("datumVymazu"):
                sidlo_data = s.get("adresa") or s
                info["sidlo_ulice"] = _build_address_street_vr(sidlo_data)
                info["sidlo_mesto"] = sidlo_data.get("nazevObce", "") or ""
                info["sidlo_psc"] = str(sidlo_data.get("psc", "") or "")
                break

    return info


def _pick_primary(zaznamy: list) -> Optional[dict]:
    if not zaznamy:
        return None
    prim = [z for z in zaznamy if z.get("primarniZaznam")]
    return prim[0] if prim else zaznamy[0]


def _build_address_street(sidlo: dict) -> str:
    parts = []
    ulice = sidlo.get("nazevUlice", "")
    if ulice:
        parts.append(ulice)
    cd = sidlo.get("cisloDomovni", "")
    co = sidlo.get("cisloOrientacni", "")
    if cd:
        if co:
            parts.append(f"{cd}/{co}")
        else:
            parts.append(str(cd))
    return " ".join(parts)


def _build_address_street_vr(sidlo: dict) -> str:
    parts = []
    ulice = sidlo.get("ulice", "") or sidlo.get("nazevUlice", "")
    if ulice:
        parts.append(ulice)
    cd = sidlo.get("cisloPopisne", "") or sidlo.get("cisloDomovni", "")
    co = sidlo.get("cisloOrientacni", "")
    if cd:
        if co:
            parts.append(f"{cd}/{co}")
        else:
            parts.append(str(cd))
    return " ".join(parts)


def _extract_ds(basic_data: dict) -> str:
    """Extrahuje ID datové schránky."""
    ds_list = basic_data.get("datoveSchranky") or []
    if ds_list:
        item = ds_list[0]
        # Endpoint může vrátit seznam stringů nebo objektů {idDs: ...}
        if isinstance(item, dict):
            return item.get("idDs", "") or ""
        return str(item)
    return ""


def _extract_statutory_bodies(zaznam: dict) -> list[dict]:
    """Extrahuje statutární orgány (jednatelé, členové představenstva)."""
    bodies = []
    for org in (zaznam.get("statutarniOrgany") or []):
        if org.get("datumVymazu"):
            continue
        organ_name = org.get("nazevOrganu", "Statutární orgán")
        for clen in (org.get("clenoveOrganu") or []):
            if clen.get("datumVymazu"):
                continue
            fo = clen.get("fyzickaOsoba") or {}
            po = clen.get("pravnickaOsoba") or {}
            funkce = clen.get("funkce", "") or ""
            if fo:
                name = _person_name(fo)
                bodies.append({
                    "jmeno": name,
                    "funkce": funkce or organ_name,
                    "organ": organ_name,
                    "typ": "FO",
                    "datum_zapisu": clen.get("datumZapisu", ""),
                })
            elif po:
                name = po.get("obchodniJmeno", "") or po.get("nazev", "")
                bodies.append({
                    "jmeno": name,
                    "funkce": funkce or organ_name,
                    "organ": organ_name,
                    "typ": "PO",
                    "ico": po.get("ico", ""),
                    "datum_zapisu": clen.get("datumZapisu", ""),
                })
    return bodies


def _extract_partners(zaznam: dict) -> list[dict]:
    """Extrahuje společníky/akcionáře."""
    partners = []
    for blok in (zaznam.get("spolecnici") or []):
        if blok.get("datumVymazu"):
            continue
        label = blok.get("nazevOrganu", "Společníci")
        for sp in (blok.get("spolecnik") or []):
            if sp.get("datumVymazu"):
                continue
            osoba = sp.get("osoba") or {}
            fo = osoba.get("fyzickaOsoba")
            po = osoba.get("pravnickaOsoba")
            if po:
                partners.append({
                    "jmeno": po.get("obchodniJmeno", "") or po.get("nazev", ""),
                    "typ": "PO",
                    "ico": po.get("ico", ""),
                    "label": label,
                })
            elif fo:
                partners.append({
                    "jmeno": _person_name(fo),
                    "typ": "FO",
                    "label": label,
                })
    # Akcionáři
    for org in (zaznam.get("akcionari") or []):
        if org.get("datumVymazu"):
            continue
        label = org.get("nazevOrganu", "Akcionáři")
        for clen in (org.get("clenoveOrganu") or []):
            if clen.get("datumVymazu"):
                continue
            fo = clen.get("fyzickaOsoba")
            po = clen.get("pravnickaOsoba")
            if po:
                partners.append({
                    "jmeno": po.get("obchodniJmeno", "") or po.get("nazev", ""),
                    "typ": "PO",
                    "ico": po.get("ico", ""),
                    "label": label,
                })
            elif fo:
                partners.append({
                    "jmeno": _person_name(fo),
                    "typ": "FO",
                    "label": label,
                })
    return partners


def _person_name(fo: dict) -> str:
    parts = []
    if fo.get("titulPredJmenem"):
        parts.append(fo["titulPredJmenem"])
    if fo.get("jmeno"):
        parts.append(fo["jmeno"])
    if fo.get("prijmeni"):
        parts.append(fo["prijmeni"])
    return " ".join(parts).strip() or "Neznámá osoba"
