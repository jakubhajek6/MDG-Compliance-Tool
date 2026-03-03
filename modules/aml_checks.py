"""
AML kontrolní logika – sekvenční kontroly s progress reportingem.
"""

import json
from datetime import datetime
from typing import Callable, Optional

from modules.sanctions import check_sanctions, load_eu_sanctions, load_un_sanctions
from modules.pep_check import check_pep
from modules.insolvency import check_insolvency_ico, check_insolvency_name


# Typ callback funkce pro progress: (step_name, status, detail, progress_pct)
ProgressCallback = Optional[Callable[[str, str, str, float], None]]


def run_aml_check(
    name: str,
    ico: str = "",
    entity_type: str = "FO",
    progress_cb: ProgressCallback = None,
) -> dict:
    """
    Spustí kompletní AML kontrolu.

    Args:
        name: Jméno osoby nebo název firmy
        ico: IČO (volitelné, pro PO)
        entity_type: FO (fyzická osoba) nebo PO (právnická osoba)
        progress_cb: Callback pro hlášení průběhu

    Returns:
        dict s výsledky všech kontrol
    """
    results = {
        "entity_name": name,
        "ico": ico,
        "entity_type": entity_type,
        "check_date": datetime.now().isoformat(timespec="seconds"),
        "overall_status": "clean",  # clean / warning / hit
        "checks": [],
        "total_hits": 0,
    }

    checks = [
        ("Sankční seznam EU", _check_eu_sanctions),
        ("Sankční seznam UN", _check_un_sanctions),
        ("Insolvenční rejstřík ČR", _check_insolvency),
        ("PEP kontrola", _check_pep),
    ]

    for i, (check_name, check_fn) in enumerate(checks):
        progress = (i / len(checks))
        if progress_cb:
            progress_cb(check_name, "running", f"Kontroluji {check_name}...", progress)

        try:
            check_result = check_fn(name=name, ico=ico, entity_type=entity_type)
        except Exception as e:
            check_result = {
                "name": check_name,
                "status": "error",
                "hits": 0,
                "details": [{"error": str(e)}],
            }

        results["checks"].append(check_result)
        results["total_hits"] += check_result.get("hits", 0)

        status_icon = "✓" if check_result["status"] == "clean" else ("⚠" if check_result["status"] == "warning" else "✗")
        if progress_cb:
            progress_cb(
                check_name,
                check_result["status"],
                f"{status_icon} {check_name}: {check_result['hits']} nálezů",
                (i + 1) / len(checks),
            )

    # Celkový status
    statuses = [c["status"] for c in results["checks"]]
    if "hit" in statuses:
        results["overall_status"] = "hit"
    elif "warning" in statuses:
        results["overall_status"] = "warning"
    else:
        results["overall_status"] = "clean"

    return results


def _check_eu_sanctions(name: str, ico: str = "", entity_type: str = "FO") -> dict:
    """Kontrola proti EU sankčnímu seznamu."""
    hits = check_sanctions(name, threshold=0.85)
    eu_hits = [h for h in hits if h["source"] == "EU"]

    status = "clean"
    if eu_hits:
        status = "hit"

    return {
        "name": "Sankční seznam EU",
        "status": status,
        "hits": len(eu_hits),
        "details": eu_hits[:10],
    }


def _check_un_sanctions(name: str, ico: str = "", entity_type: str = "FO") -> dict:
    """Kontrola proti UN sankčnímu seznamu."""
    hits = check_sanctions(name, threshold=0.85)
    un_hits = [h for h in hits if h["source"] == "UN"]

    status = "clean"
    if un_hits:
        status = "hit"

    return {
        "name": "Sankční seznam UN",
        "status": status,
        "hits": len(un_hits),
        "details": un_hits[:10],
    }


def _check_insolvency(name: str, ico: str = "", entity_type: str = "FO") -> dict:
    """Kontrola v insolvenčním rejstříku."""
    results = []
    if ico:
        results = check_insolvency_ico(ico)
    if not results and name:
        results = check_insolvency_name(name)

    status = "clean"
    if results:
        status = "warning"

    return {
        "name": "Insolvenční rejstřík ČR",
        "status": status,
        "hits": len(results),
        "details": results[:10],
    }


def _check_pep(name: str, ico: str = "", entity_type: str = "FO") -> dict:
    """PEP kontrola."""
    if entity_type == "PO":
        return {
            "name": "PEP kontrola",
            "status": "clean",
            "hits": 0,
            "details": [{"note": "PEP kontrola není relevantní pro právnické osoby"}],
        }

    hits = check_pep(name, threshold=0.85)

    status = "clean"
    if hits:
        status = "warning"

    return {
        "name": "PEP kontrola",
        "status": status,
        "hits": len(hits),
        "details": hits[:10],
    }
