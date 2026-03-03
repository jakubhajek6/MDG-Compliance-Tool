# MDG Compliance Tool

Interní compliance nástroj pro daňově-účetní kancelář MDG. Multimodulová Streamlit aplikace pro správu AML povinností, evidenci skutečných majitelů, monitoring obchodního rejstříku a rizikovou klasifikaci klientů.

## Moduly

| # | Modul | Popis |
|---|-------|-------|
| 1 | **ESM** | Evidence skutečných majitelů – rozkrytí vlastnické struktury přes ARES VR API |
| 2 | **Vizualizace** | Interaktivní mapa vztahů osob a firem (PyVis graf) |
| 3 | **AML** | Automatická AML prověrka – sankční seznamy EU/UN, PEP, insolvenční rejstřík |
| 4 | **Data Export** | Export dat z ARES/OR do formátů MasT a Macrtime (Excel) |
| 5 | **Smlouvy** | Automatické předvyplnění Word šablon daty klienta z OR |
| 6 | **Monitoring** | Automatické hlídání změn v OR u sledovaných klientů |
| 7 | **Riziko** | Riziková klasifikace klienta dle ZAML §13 (zákon č. 253/2008 Sb.) |

## Požadavky

- Python 3.11+
- Graphviz (systémový balíček pro generování grafů)

## Instalace

```bash
# 1. Klonování repozitáře
git clone <repo-url>
cd mdg-compliance-tool

# 2. Virtuální prostředí
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 3. Instalace závislostí
pip install -r requirements.txt

# 4. Systémový Graphviz (pro grafy v Modulu 1)
# Ubuntu/Debian:
sudo apt-get install graphviz
# macOS:
brew install graphviz

# 5. Spuštění
streamlit run app.py
```

## Konfigurace

### Heslo
Výchozí heslo: `mdg2024`

Změna hesla:
- Nastavte environment variable `MDG_PASSWORD`
- Nebo vytvořte soubor `.streamlit/secrets.toml`:
  ```toml
  password = "vase_heslo"
  ```

### Streamlit Cloud
Pro nasazení na Streamlit Cloud:
1. Vytvořte soubor `packages.txt` s řádkem `graphviz`
2. Nastavte secrets v administraci Streamlit Cloud

## Struktura projektu

```
mdg-compliance-tool/
├── app.py                    # Hlavní vstupní bod, login, dashboard
├── pages/
│   ├── 1_ESM.py              # Modul 1 – ESM (UBO Tool)
│   ├── 2_Vizualizace.py      # Modul 2 – Vizualizace vztahů
│   ├── 3_AML.py              # Modul 3 – AML kontroly
│   ├── 4_DataExport.py       # Modul 4 – Export dat
│   ├── 5_Smlouvy.py          # Modul 5 – Smluvní dokumentace
│   ├── 6_Monitoring.py       # Modul 6 – Monitoring OR
│   └── 7_Riziko.py           # Modul 7 – Riziková klasifikace
├── modules/
│   ├── ares_api.py           # ARES API wrapper
│   ├── justice_scraper.py    # Scraper pro justice.cz
│   ├── aml_checks.py         # AML kontrolní logika
│   ├── sanctions.py          # Sankční seznamy EU/UN
│   ├── pep_check.py          # PEP kontrola
│   ├── insolvency.py         # Insolvenční rejstřík
│   ├── docgen.py             # Generování Word dokumentů
│   └── risk_scoring.py       # Rizikové skóre
├── importer/                 # Převzato z UBO Tool
│   ├── ares_vr_client.py     # ARES VR klient s cache
│   ├── ares_vr_extract.py    # Extrakce vlastníků z VR
│   ├── ownership_resolve_online.py  # Online rozkrytí struktury
│   └── graphviz_render.py    # Graphviz renderování
├── db/
│   ├── database.py           # Databázový modul
│   └── schema.sql            # SQL schéma
├── data/
│   ├── templates/            # Word šablony (.docx)
│   └── sanctions_cache/      # Cache sankčních seznamů
├── .streamlit/config.toml    # Streamlit theme
├── requirements.txt
└── packages.txt              # Systémové závislosti
```

## Databáze

SQLite databáze se automaticky vytvoří při prvním spuštění v `data/mdg_compliance.sqlite`. Obsahuje tabulky pro:
- Cache ARES dat
- AML kontroly (audit trail)
- OR snapshoty a detekované změny
- Rizikové skóre
- Sledované klienty

## Word šablony

Ukázkové šablony se automaticky vytvoří při prvním spuštění. Pro použití reálných šablon:
1. Připravte .docx soubory s placeholdery ve formátu `{{TAG}}`
2. Umístěte je do složky `data/templates/`

Dostupné placeholdery:
```
{{NAZEV_FIRMY}}, {{ICO}}, {{DIC}}, {{SIDLO_ULICE}}, {{SIDLO_MESTO}},
{{SIDLO_PSC}}, {{PRAVNI_FORMA}}, {{JEDNATEL_JMENO}}, {{JEDNATEL_FUNKCE}},
{{DATUM_VZNIKU}}, {{DATOVA_SCHRANKA}}, {{DATUM_DNES}}, {{ROK_DNES}}
```

## Licence

Interní nástroj MDG. Není určen pro veřejné použití.
