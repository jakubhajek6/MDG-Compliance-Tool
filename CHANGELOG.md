# Changelog

## [1.0.0] - 2026-03-03

### Nová aplikace: MDG Compliance Tool

MDG UBO Tool se stává součástí nové multimodulové aplikace MDG Compliance Tool. Původní funkcionalita UBO Tool je plně zachována jako Modul 1 (ESM) a rozšířena o 6 dalších modulů.

### Přidáno (oproti UBO Tool)

#### Architektura
- Multipage Streamlit architektura se 7 moduly
- Centrální SQLite databáze s rozšířeným schématem
- Session-based autentizace (heslem chráněný přístup)
- Jednotný UI/UX design s MDG brandingem (primary color #1B3A6B)
- Sidebar navigace s ikonami a breadcrumby

#### Modul 1 – ESM (rozšíření UBO Tool)
- Zobrazení statutárních orgánů (jednatelé, členové představenstva) z ARES VR
- Vizuální odlišení: společnosti (modrý), FO/UBO (zelený), statutáři (oranžový)
- Tlačítko „Spustit AML kontrolu" na statutárních orgánech → přesměrování do Modulu 3
- Automatické ukládání OR snapshotů při načtení

#### Modul 2 – Vizualizace vztahů (NOVÉ)
- Interaktivní PyVis graf propojených entit
- Vyhledávání dle IČO i jména osoby
- Filtr hloubky vztahů (1–4 úrovně)
- Export grafu a seznamu vztahů do Excelu
- Caching dat v SQLite (TTL 24 hodin)

#### Modul 3 – AML kontroly (NOVÉ)
- Sekvenční AML kontrola s progress barem
- Kontrola proti sankčním seznamům EU a UN (XML, denní cache)
- Kontrola v insolvenčním rejstříku ČR
- PEP kontrola (poslanci PSP, senátoři)
- Barevný souhrn: zelená/žlutá/červená
- Export AML reportu do .docx
- Audit trail – uložení každé kontroly do DB

#### Modul 4 – Export dat pro MasT a MT (NOVÉ)
- Načtení kompletních dat z ARES/OR
- Export do 2 formátů Excelu (MasT, Macrtime)
- Hromadné zpracování z Excel souboru
- Preview dat před exportem
- Seznam chybných/nenalezených IČO

#### Modul 5 – Návrh smluvní dokumentace (NOVÉ)
- 4 ukázkové Word šablony (smlouva, plná moc, GDPR, OPDP)
- Automatické předvyplnění {{PLACEHOLDER}} tagů
- Editace placeholderů v UI
- Export jednotlivých dokumentů nebo ZIP archivu

#### Modul 6 – Monitoring změn v OR (NOVÉ)
- Správa sledovaných klientů (přidat/odebrat/import z Excelu)
- Porovnání aktuálních dat s posledním snapshotem
- Detekce změn: sídlo, statutáři, předmět podnikání, ZK, název
- In-app notifikace nezpracovaných změn
- Export timeline změn do Excelu

#### Modul 7 – Riziková klasifikace (NOVÉ)
- Automatický výpočet rizikového skóre dle ZAML §13
- 9 rizikových faktorů s váhami (FATF, PEP, sankce, insolvence, ...)
- Vizuální gauge chart (Plotly)
- Kategorizace: Nízké (0–30) / Střední (31–60) / Vysoké (61–100)
- Doporučení opatření dle kategorie

#### Core moduly (NOVÉ)
- `modules/ares_api.py` – rozšířený ARES wrapper s extrakcí statutárů, společníků, DS
- `modules/sanctions.py` – stahování a caching EU/UN sankčních seznamů
- `modules/pep_check.py` – PEP kontrola z veřejných zdrojů
- `modules/insolvency.py` – kontrola v insolvenčním rejstříku
- `modules/aml_checks.py` – orchestrace AML kontrol
- `modules/risk_scoring.py` – výpočet rizikového skóre
- `modules/docgen.py` – generování Word dokumentů ze šablon
- `modules/justice_scraper.py` – scraper justice.cz s rate limitingem
- `db/database.py` – centrální databázový modul s audit logem

### Zachováno z UBO Tool
- Kompletní funkčnost rozkrytí vlastnické struktury přes ARES VR
- Graphviz vizualizace vlastnického grafu
- PDF export s logem, grafem a vyhodnocením SM
- Manuální doplnění vlastníků (CZ, zahraniční, FO)
- XML export/import stavu
- Výpočet efektivních podílů a hlasovacích práv
- Vyhodnocení SM dle zákonných kritérií (§ 4 ZESM)
- Voting block / jednání ve shodě
- Kontrolní otázky a poznámky

### Technické změny
- Nové DB tabulky: clients, aml_checks, or_snapshots, or_changes, risk_scores, audit_log
- Nové závislosti: python-docx, plotly, APScheduler, pyvis, streamlit-agraph
- Streamlit theme: primary #1B3A6B (MDG firemní barva)
- Rate limiting na všech externích API voláních
