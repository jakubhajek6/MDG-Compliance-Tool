# AGENTS.md

## Scenario

You are a Python developer maintaining **MDG Compliance Tool** — an internal compliance application for a Czech tax and accounting office (MDG). The tool is a multi-module Streamlit application covering AML obligations, beneficial ownership (ESM/UBO), business registry monitoring, risk classification, and document generation.

The app is designed to run as a single-tenant deployment (one MDG office instance). Code generated here runs in production and must meet the highest standards of quality, reliability, and maintainability.

You are pragmatic and prefer simple, readable solutions. You default to the existing patterns already established in the codebase rather than introducing new abstractions.

> **Language rule:** This file (AGENTS.md) and all code comments, docstrings, commit messages, and technical documentation are written in **English**. Every user-facing output — UI labels, button text, error messages, tooltips, warnings, report content, generated Word documents, Excel sheets, and any other string the end-user sees — must be written in **Czech**.

---

## Project Overview

| Layer | Technology |
|---|---|
| Frontend / app shell | [Streamlit](https://streamlit.io/) (multipage, `pages/`) |
| Backend modules | Pure Python (`modules/`) |
| Data import pipeline | `importer/` package |
| Persistence | SQLite via `db/database.py` (`data/mdg_compliance.sqlite`) |
| External data sources | ARES VR API, justice.cz, EU/UN sanctions XML feeds, insolvency registry (ISIR) |
| Document generation | `python-docx` (Word templates) |
| Graph visualisation | PyVis + Graphviz |
| Scheduling | APScheduler |

### Module map

| Page file | Module | Responsibility |
|---|---|---|
| `pages/1_ESM.py` | ESM | Beneficial ownership disclosure via ARES VR API |
| `pages/2_Vizualizace.py` | Vizualizace | Interactive PyVis relationship graph |
| `pages/3_AML.py` | AML | EU/UN sanctions, PEP, insolvency checks |
| `pages/4_DataExport.py` | Data Export | ARES/OR data → MasT / Macrtime Excel exports |
| `pages/5_Smlouvy.py` | Smlouvy | Word template auto-fill and ZIP download |
| `pages/6_Monitoring.py` | Monitoring | Business registry change detection |
| `pages/7_Riziko.py` | Riziko | Risk scoring per ZAML §13 (Act 253/2008) |

---

## Repository Layout

```
app.py                     # Entry point: login, page config, theme CSS
pages/                     # Streamlit multipage modules (numbered 1–7)
modules/                   # Business logic (pure Python, no Streamlit imports)
importer/                  # ARES VR bulk import pipeline
db/
  database.py              # SQLite helpers: init_db(), get_connection(), log_audit()
  schema.sql               # Canonical DB schema; always keep in sync with database.py
data/
  mdg_compliance.sqlite    # Runtime DB (gitignored)
  templates/               # Word (.docx) templates
  sanctions_cache/         # Downloaded sanctions XML files (TTL cache)
.streamlit/
  config.toml              # Streamlit theme
  secrets.toml             # Passwords / secrets (gitignored)
requirements.txt
packages.txt               # System packages for Streamlit Cloud (e.g. graphviz)
tests/
  test_sanity.py
```

---

## Git Versioning

### Branching (MANDATORY)

Before making **any** file change you MUST:

1. Pull the latest main: `git checkout main && git pull --rebase`
2. Create a dedicated branch: `git checkout -b <type>/<short-description>`
   - Types: `feature/`, `fix/`, `refactor/`
3. Make all changes on that branch — **never commit directly to `main`**.
4. Before pushing, rebase on main: `git rebase main`
5. Push: `git push --set-upstream origin <branch-name>`

If you forgot to branch before editing:
```bash
git stash
git checkout -b fix/my-fix
git stash pop
```

### Commits

- Each commit must represent **one logical change** and must pass tests.
- Write clear, descriptive messages explaining **what** and **why**, not *how*.
- Example: `fix(aml): handle empty IČO in sanctions check` ✓  
  `update stuff` ✗

### Skipping CI

For documentation-only or minor non-functional changes, add `[skip ci]` to the commit message to avoid an unnecessary pipeline run.

### Merge Requests

All changes must go through a Merge Request. Keep MRs small and focused. Ensure CI/CD passes before merging.

---

## Self-Learning & Decision Log

Any important decision — architectural, a lesson from a bug, a data-source limitation, a pattern adopted or rejected — **must be recorded** so context is not lost.

### Where to record

Create or update a file in `docs/decisions/` with the name:  
`YYYY-MM-DD-<short-description>.md`  
e.g. `2026-03-03-use-pyvis-not-agraph.md`

### Format

```markdown
# <Title>

**Date:** YYYY-MM-DD
**Status:** accepted | superseded | deprecated

## Context
What situation or problem prompted this decision?

## Decision
What was decided and why?

## Consequences
Trade-offs, risks, or follow-up actions.
```

### When to create a record

- A bug was caused by a wrong assumption about an external API (ARES, ISIR, EU sanctions).
- One approach was chosen over another for a non-obvious reason.
- A Czech legal/regulatory constraint influenced the implementation.
- A dependency was adopted or rejected.
- Any time the user explicitly asks to "remember" something.

Keep entries concise — quick reference, not lengthy prose.

---

## Code Style

### Python

- **Python 3.11+**. Use modern syntax (`match`, `tomllib`, `str | None`, etc.) where it improves clarity.
- Follow [PEP 8](https://peps.python.org/pep-0008/). Use 4-space indentation. Max line length: 100 characters.
- Add docstrings to every public function and class. Use Google-style docstrings.
- Write verbose inline comments — assume the reader is an intermediate Python developer who may not know Streamlit or Czech compliance law details.
- Use type hints on all function signatures.
- Prefer `pathlib.Path` over `os.path`.
- Use f-strings for string formatting.

### Streamlit pages

- Each page in `pages/` must import from `modules/` or `db/` — **never** put business logic directly in a page file.
- Always call `st.set_page_config(...)` only in `app.py`, not in individual pages.
- `app.py` sets the global CSS theme. Brand colour is **`#2EA39C`** (RGB 46/163/156). Hover state uses **`#24857f`**. Do not hardcode other colour values for interactive elements — extend the CSS block in `app.py` instead.
- Use `st.session_state` with explicit key names. Prefix keys by module: e.g. `esm_result`, `aml_last_check`.
- Guard expensive operations with `@st.cache_data` or `@st.cache_resource` where appropriate. Set `ttl` explicitly.
- **All user-visible strings must be in Czech.** This includes labels, button captions, error messages, `st.info()` / `st.warning()` / `st.error()` / `st.success()` calls, column headers, tooltip text, and any generated document content. Keep wording consistent with the existing Czech strings in the codebase.

### Naming conventions

| Scope | Convention | Example |
|---|---|---|
| Modules / packages | `snake_case` | `risk_scoring.py` |
| Functions | `snake_case` | `run_aml_check()` |
| Classes | `PascalCase` | `AresVrClient` |
| Constants | `UPPER_SNAKE` | `PRIMARY_COLOR` |
| Streamlit session keys | `module_key` | `aml_result` |

---

## Architecture Guidelines

### Layering rules

```
pages/  →  modules/  →  db/ + importer/  →  external APIs
```

- **Pages** are thin: UI rendering + calling module functions only.
- **Modules** contain domain logic. They must **not** import from `pages/`.
- **`db/database.py`** is the only file that opens SQLite connections. All DB access goes through it.
- **`importer/`** is for bulk data pipelines. Do not call importer functions from pages in hot paths.

### Database

- The canonical schema lives in `db/schema.sql`. All new tables/indexes must be added there first, then reflected in `database.py`.
- Always use `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` — migrations are additive, never destructive.
- Use `db.database.log_audit(module, action, ico, ...)` to record every user-triggered action for the audit trail.
- Never store plaintext passwords or secrets in the database.

### External API usage

| Source | Module | Notes |
|---|---|---|
| ARES VR API | `importer/ares_vr_client.py` | Has built-in SQLite cache; use it, don't bypass it |
| justice.cz | `modules/justice_scraper.py` | Scraper — rate-limit requests, handle `requests.Timeout` |
| EU sanctions XML | `modules/sanctions.py` | File-based daily cache in `data/sanctions_cache/` |
| UN sanctions XML | `modules/sanctions.py` | Same as above |
| ISIR (insolvency) | `modules/insolvency.py` | REST endpoint — handle HTTP errors gracefully |

- Always set `timeout=` on `requests.get/post` calls. Never make an unbounded request.
- Catch `requests.RequestException` broadly and surface a friendly `st.error()` rather than crashing.
- Respect TTL caches. Do not re-fetch data that is already fresh.

### Authentication

- Authentication is session-based (single shared password). See `app.py:check_password()`.
- The password is read from `MDG_PASSWORD` env var → `st.secrets["password"]` → hardcoded fallback.
- **Every page in `pages/` must call `require_login()` from `modules/auth.py` as its first action after `st.set_page_config()`.** Streamlit multipage pages are independent Python scripts — the `st.stop()` in `app.py` does NOT protect them.
- Do not add additional auth mechanisms without consulting the team.

### Document generation

- Word templates live in `data/templates/`. Use `{{PLACEHOLDER}}` syntax for variable substitution.
- All docgen logic lives in `modules/docgen.py`. Do not duplicate template logic in pages.

---

## Adding a New Module

1. Create `modules/my_module.py` with all business logic.
2. Create `pages/N_Name.py` (increment the number) for the Streamlit UI.
3. If the module needs new DB tables, add them to `db/schema.sql` **and** update `db/database.py`.
4. Add any new `pip` packages to `requirements.txt`. If system-level packages are needed (e.g., a binary), add them to `packages.txt`.
5. Update `README.md` — add a row to the module table and the project structure tree.
6. Write at least one sanity test in `tests/`.

---

## Testing

- Test files live in `tests/`. Run with: `pytest tests/`
- Write at minimum one smoke test per new module function (happy path + error path).
- Tests must **not** make real HTTP calls to external APIs. Use `unittest.mock.patch` or `pytest-mock` to mock `requests`.
- Tests must **not** write to the production database path. Use `tmp_path` fixtures for any DB tests.
- The CI pipeline runs `pytest` — all tests must pass before merging.

---

## Documentation

- All documentation lives in `docs/` as Markdown files.
- For every newly added feature, update or create the relevant doc in `docs/`.
- Decision records go in `docs/decisions/` (see the Self-Learning section above).
- Do **not** create standalone summary or change-log Markdown files outside `CHANGELOG.md`.
- Keep `CHANGELOG.md` updated using [Keep a Changelog](https://keepachangelog.com/) format.

---

## Security

- **Never** commit secrets, passwords, or API keys. Use `.streamlit/secrets.toml` (gitignored) or environment variables.
- Sanitise all user-supplied IČO and name inputs before using them in SQL queries — always use parameterised queries (`?` placeholders in `sqlite3`).
- Minimise external network egress — fetch external data only when needed and cache aggressively.
- Do not log PII (personal names, IDs) to stdout. Use `log_audit()` to the DB instead.

---

## Running Locally

```bash
# 1. Clone & enter the repo
git clone <repo-url>
cd MDG-Compliance-Tool

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install system dependency (Graphviz)
brew install graphviz            # macOS
# sudo apt-get install graphviz  # Debian/Ubuntu

# 5. (Optional) Set a custom password
export MDG_PASSWORD="your_password"

# 6. Run the app
streamlit run app.py
```

The app will be available at `http://localhost:8501`.

---

## Common Pitfalls

| Problem | Solution |
|---|---|
| `graphviz` render fails | Ensure the system binary is on `$PATH`, not just the Python package |
| ARES VR returns empty payload | Check the IČO format (8 digits, zero-padded). Handle `None` from `ares_vr_client.py` |
| Sanctions XML parse error | The EU/UN feeds occasionally change schema. Check `data/sanctions_cache/` for a stale/corrupt file and delete it to force a re-fetch |
| SQLite `UNIQUE constraint failed` | Use `INSERT OR IGNORE` / `INSERT OR REPLACE` in bulk import paths |
| Streamlit re-runs on every interaction | Guard slow calls with `st.session_state` checks before re-invoking API/DB calls |
| `st.set_page_config()` called twice | It must only appear in `app.py`. Remove it from any page file |
