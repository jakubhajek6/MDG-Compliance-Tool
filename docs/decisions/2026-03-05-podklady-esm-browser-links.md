# Podklady ESM – OR server-side vs. ESM browser-link

**Date:** 2026-03-05
**Status:** accepted

## Context

Modul 8 potřebuje stahovat tři PDF podklady pro každého klienta:
1. Výpis z obchodního rejstříku (or.justice.cz)
2. Výpis z ESM (esm.justice.cz)
3. Grafická struktura ESM (esm.justice.cz)

Streamlit běží na serveru. Uživatel má aplikaci otevřenou v prohlížeči, kde téhož dne
provedl přihlášení do ESM bankovní identitou.

## Decision

**OR výpis** – stahujeme server-side přes `requests.get()`. Endpoint
`or.justice.cz/ias/ui/print-pdf?subjektId=…` je veřejný a nevyžaduje autentizaci.
Server drží bytes v `session_state` a předá je uživateli jako data-URI download
(JS bulk-trigger pro hromadné stahování), aby každá společnost dostala pojmenovaný
samostatný soubor bez ZIPu.

**ESM výpis + grafická struktura** – předáváme jako plain URL, které se otevřou
v prohlížeči uživatele (`st.link_button` / JS `window.open`). ESM vyžaduje
přihlášení bankovní identitou, které je vázáno výhradně na browser session.
Session cookie není přenositelná na server bez vědomého souhlasu uživatele a
pravidelné ruční obnovy, což by zvyšovalo složitost a bezpečnostní riziko.

**subjektId auto-lookup** – justice.cz nemá veřejné API pro mapování IČO →
interní subjektId. Řešíme HTML scrapingem výsledkové stránky OR vyhledávání
(`BeautifulSoup`), kde je subjektId obsaženo v odkazu na výpis.

**Potvrzení stavu ESM** – server nemůže detekovat výsledek browser downloadu
(cross-origin, žádný callback). Uživatel potvrzuje ✅/❌ ručně přes radio button;
stav se ukládá do `podklady_runs` pro audit trail.

## Consequences

- OR stahování je plně automatické a ověřitelné (kontrola HTTP statusu, Content-Type,
  velikosti souboru).
- ESM stahování závisí na aktivní browser session – nelze automatizovat bez
  sdílení session cookie.
- Přidána závislost na `beautifulsoup4` (scraping), která je již v `requirements.txt`.
- Žádné PDF soubory se neukládají na disk serveru – vše přes paměť a session_state.
