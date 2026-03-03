"""
Riziková klasifikace klienta dle ZAML (zákon č. 253/2008 Sb. §13).
"""

from datetime import datetime, timedelta
from typing import Optional

# FATF šedý/černý seznam – aktuální ke dni vývoje
FATF_HIGH_RISK_COUNTRIES = {
    # Černý seznam (Call for Action)
    "KLDR", "Severní Korea", "Írán", "Myanmar", "Barma",
    "North Korea", "Iran", "Myanmar",
    # Šedý seznam (Increased Monitoring)
    "Albánie", "Barbados", "Burkina Faso", "Kamerun", "Chorvatsko",
    "Demokratická republika Kongo", "Gibraltar", "Haiti", "Jamajka",
    "Jordánsko", "Mali", "Mosambik", "Nigérie", "Panama",
    "Filipíny", "Senegal", "Jižní Afrika", "Jižní Súdán",
    "Sýrie", "Tanzanie", "Turecko", "Uganda", "Vietnam", "Jemen",
    "Albania", "Barbados", "Burkina Faso", "Cameroon", "Croatia",
    "DRC", "Gibraltar", "Haiti", "Jamaica", "Jordan", "Mali",
    "Mozambique", "Nigeria", "Panama", "Philippines", "Senegal",
    "South Africa", "South Sudan", "Syria", "Tanzania", "Turkey",
    "Uganda", "Vietnam", "Yemen",
}

# Rizikové právní formy
RISKY_LEGAL_FORMS = {
    "nadace", "nadační fond", "svěřenský fond", "trust",
    "holding", "investiční fond", "podílový fond",
    "evropská společnost", "evropské hospodářské zájmové sdružení",
}

# Rizikové NACE kódy (obory)
RISKY_NACE_CODES = {
    "92": "Hazardní hry a sázení",
    "68": "Činnosti v oblasti nemovitostí",
    "6420": "Činnosti holdingových společností",
    "6499": "Ostatní finanční zprostředkování",
    "6612": "Zprostředkování obchodů s cennými papíry",
    "6619": "Ostatní pomocné činnosti související s finančním zprostředkováním",
    "6630": "Správa fondů",
    "7010": "Činnosti vedení podniků (head offices)",
}

# Riziková klíčová slova v předmětu podnikání
RISKY_KEYWORDS = [
    "kryptoměn", "crypto", "casino", "kasino", "sáz",
    "směnárn", "money service", "peněžní služ",
    "virtual", "digitální aktiv",
]


def calculate_risk_score(
    ico: str,
    company_info: dict,
    aml_results: Optional[dict] = None,
    client_since: Optional[str] = None,
    ownership_depth: int = 0,
) -> dict:
    """
    Vypočítá rizikové skóre klienta.

    Args:
        ico: IČO firmy
        company_info: Data z ARES (extract_company_info výstup)
        aml_results: Výsledky AML kontroly (z run_aml_check)
        client_since: Datum, kdy se klient stal klientem (ISO format)
        ownership_depth: Hloubka vlastnické struktury

    Returns:
        dict s celkovým skóre, kategorií, faktory a doporučeními
    """
    factors = []
    total_score = 0

    # 1. Sídlo v zemi na FATF šedém/černém seznamu (25 bodů)
    country = (company_info.get("sidlo_stat") or "").strip()
    if country and any(c.lower() in country.lower() for c in FATF_HIGH_RISK_COUNTRIES):
        total_score += 25
        factors.append({
            "factor": "Sídlo v zemi na FATF šedém/černém seznamu",
            "value": country,
            "score": 25,
        })

    # 2. PEP nebo RCA v angažmá (25 bodů)
    if aml_results:
        for check in aml_results.get("checks", []):
            if check.get("name") == "PEP kontrola" and check.get("hits", 0) > 0:
                total_score += 25
                factors.append({
                    "factor": "PEP nebo RCA v angažmá",
                    "value": f"{check['hits']} nálezů",
                    "score": 25,
                })
                break

    # 3. Hit na sankčním seznamu (50 bodů – automaticky Vysoké)
    if aml_results:
        sanction_hits = 0
        for check in aml_results.get("checks", []):
            if "sankční" in check.get("name", "").lower() and check.get("status") == "hit":
                sanction_hits += check.get("hits", 0)
        if sanction_hits > 0:
            total_score += 50
            factors.append({
                "factor": "Hit na sankčním seznamu",
                "value": f"{sanction_hits} nálezů",
                "score": 50,
            })

    # 4. Insolvence v historii (15 bodů)
    if aml_results:
        for check in aml_results.get("checks", []):
            if "insolvenčn" in check.get("name", "").lower() and check.get("hits", 0) > 0:
                total_score += 15
                factors.append({
                    "factor": "Insolvence v historii",
                    "value": f"{check['hits']} nálezů",
                    "score": 15,
                })
                break

    # 5. Riziková právní forma (10 bodů)
    pravni_forma = (company_info.get("pravni_forma") or "").lower()
    if any(rlf in pravni_forma for rlf in RISKY_LEGAL_FORMS):
        total_score += 10
        factors.append({
            "factor": "Riziková právní forma",
            "value": company_info.get("pravni_forma", ""),
            "score": 10,
        })

    # 6. Rizikový obor dle NACE (15 bodů)
    nace = (company_info.get("nace_kod") or "").strip()
    predmet = (company_info.get("predmet_podnikani") or "").lower()

    nace_hit = False
    for code, desc in RISKY_NACE_CODES.items():
        if nace.startswith(code):
            total_score += 15
            factors.append({
                "factor": "Rizikový obor (NACE)",
                "value": f"{nace} – {desc}",
                "score": 15,
            })
            nace_hit = True
            break

    if not nace_hit:
        for kw in RISKY_KEYWORDS:
            if kw.lower() in predmet:
                total_score += 15
                factors.append({
                    "factor": "Rizikový obor (klíčové slovo)",
                    "value": kw,
                    "score": 15,
                })
                break

    # 7. Negativní mediální nález (20 bodů) – z AML výsledků
    if aml_results:
        for check in aml_results.get("checks", []):
            if "mediáln" in check.get("name", "").lower() and check.get("hits", 0) > 0:
                total_score += 20
                factors.append({
                    "factor": "Negativní mediální nález",
                    "value": f"{check['hits']} nálezů",
                    "score": 20,
                })
                break

    # 8. Nový klient (< 6 měsíců) – 5 bodů
    if client_since:
        try:
            since_date = datetime.fromisoformat(client_since)
            if (datetime.now() - since_date) < timedelta(days=180):
                total_score += 5
                factors.append({
                    "factor": "Nový klient (< 6 měsíců)",
                    "value": client_since,
                    "score": 5,
                })
        except Exception:
            pass

    # 9. Komplexní vlastnická struktura (>3 úrovně) – 10 bodů
    if ownership_depth > 3:
        total_score += 10
        factors.append({
            "factor": "Komplexní vlastnická struktura",
            "value": f"{ownership_depth} úrovní",
            "score": 10,
        })

    # Celkové skóre (0–100)
    total_score = min(100, max(0, total_score))

    # Kategorie
    if total_score <= 30:
        category = "Nízké"
        review_frequency = "3 roky"
        color = "green"
    elif total_score <= 60:
        category = "Střední"
        review_frequency = "1 rok"
        color = "orange"
    else:
        category = "Vysoké"
        review_frequency = "6 měsíců"
        color = "red"

    # Doporučení
    recommendations = _get_recommendations(category, factors)

    return {
        "ico": ico,
        "total_score": total_score,
        "category": category,
        "color": color,
        "review_frequency": review_frequency,
        "factors": factors,
        "recommendations": recommendations,
        "score_date": datetime.now().isoformat(timespec="seconds"),
    }


def _get_recommendations(category: str, factors: list) -> list[str]:
    """Generuje doporučení opatření dle kategorie rizika."""
    recs = []

    if category == "Nízké":
        recs.append("Standardní identifikace a kontrola klienta dle §7-8 ZAML.")
        recs.append(f"Příští přezkum za 3 roky.")
    elif category == "Střední":
        recs.append("Zvýšená hloubková kontrola klienta dle §9 ZAML.")
        recs.append("Ověření zdroje finančních prostředků.")
        recs.append(f"Příští přezkum za 1 rok.")
        recs.append("Zvýšený monitoring transakcí.")
    else:
        recs.append("Zesílená identifikace a hloubková kontrola dle §9a ZAML.")
        recs.append("Podrobné ověření zdroje majetku a finančních prostředků.")
        recs.append("Souhlas vedení kanceláře s navázáním/pokračováním obchodního vztahu.")
        recs.append(f"Příští přezkum za 6 měsíců.")
        recs.append("Průběžný monitoring transakcí a chování klienta.")

    # Specifická doporučení dle faktorů
    factor_names = [f["factor"] for f in factors]
    if "Hit na sankčním seznamu" in factor_names:
        recs.insert(0, "POZOR: Hit na sankčním seznamu – zvážit oznamovací povinnost dle §18 ZAML!")
    if "PEP nebo RCA v angažmá" in factor_names:
        recs.append("Aplikovat opatření pro politicky exponované osoby dle §13 odst. 2 ZAML.")

    return recs
