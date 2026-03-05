-- MDG Compliance Tool – kompletní DB schéma
-- ===========================================

-- Původní tabulky z UBO Tool
CREATE TABLE IF NOT EXISTS company (
  ico TEXT PRIMARY KEY,
  name TEXT
);

CREATE TABLE IF NOT EXISTS entity (
  entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,              -- PERSON / COMPANY
  ico TEXT,                        -- jen pro COMPANY
  name TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_company_ico
ON entity(type, ico)
WHERE type='COMPANY' AND ico IS NOT NULL;

CREATE TABLE IF NOT EXISTS ownership_edge (
  target_ico TEXT NOT NULL,
  owner_entity_id INTEGER NOT NULL,
  share_num INTEGER,
  share_den INTEGER,
  share_pct REAL,
  share_raw TEXT,
  FOREIGN KEY (target_ico) REFERENCES company(ico),
  FOREIGN KEY (owner_entity_id) REFERENCES entity(entity_id)
);

CREATE INDEX IF NOT EXISTS idx_edges_target ON ownership_edge(target_ico);

-- Cache ARES VR odpovědí
CREATE TABLE IF NOT EXISTS ares_vr_cache (
  ico TEXT PRIMARY KEY,
  fetched_at TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ares_vr_cache_fetched_at ON ares_vr_cache(fetched_at);

-- ===========================================
-- Nové tabulky pro MDG Compliance Tool
-- ===========================================

-- Klienti – sledování a monitoring
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY,
    ico TEXT UNIQUE NOT NULL,
    nazev TEXT,
    added_date TEXT,
    monitoring_active INTEGER DEFAULT 1,
    subjekt_id TEXT              -- justice.cz interní ID pro OR/ESM výpisy
);

-- Podklady ESM – běhy stahování (OR výpis, ESM, ESM grafika)
CREATE TABLE IF NOT EXISTS podklady_runs (
    id INTEGER PRIMARY KEY,
    run_date TEXT NOT NULL,       -- ISO timestamp
    ico TEXT NOT NULL,
    subjekt_id TEXT,
    nazev TEXT,
    or_status TEXT DEFAULT 'pending',       -- pending / ok / error
    esm_status TEXT DEFAULT 'pending',
    esm_grafika_status TEXT DEFAULT 'pending',
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_podklady_runs_ico     ON podklady_runs(ico);
CREATE INDEX IF NOT EXISTS idx_podklady_runs_date    ON podklady_runs(run_date);
CREATE INDEX IF NOT EXISTS idx_podklady_runs_ico_date ON podklady_runs(ico, run_date);

-- AML kontroly – audit trail
CREATE TABLE IF NOT EXISTS aml_checks (
    id INTEGER PRIMARY KEY,
    ico TEXT,
    entity_name TEXT,
    entity_type TEXT DEFAULT 'PO',  -- PO / FO
    check_date TEXT,
    result_status TEXT,             -- clean / warning / hit
    details_json TEXT,
    risk_score INTEGER
);

CREATE INDEX IF NOT EXISTS idx_aml_checks_ico ON aml_checks(ico);
CREATE INDEX IF NOT EXISTS idx_aml_checks_date ON aml_checks(check_date);

-- OR snapshoty pro monitoring změn
CREATE TABLE IF NOT EXISTS or_snapshots (
    id INTEGER PRIMARY KEY,
    ico TEXT,
    snapshot_date TEXT,
    data_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_or_snapshots_ico ON or_snapshots(ico);
CREATE INDEX IF NOT EXISTS idx_or_snapshots_date ON or_snapshots(snapshot_date);

-- Detekované změny v OR
CREATE TABLE IF NOT EXISTS or_changes (
    id INTEGER PRIMARY KEY,
    ico TEXT,
    detected_date TEXT,
    change_type TEXT,
    old_value TEXT,
    new_value TEXT,
    processed INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_or_changes_ico ON or_changes(ico);
CREATE INDEX IF NOT EXISTS idx_or_changes_processed ON or_changes(processed);

-- Rizikové skóre
CREATE TABLE IF NOT EXISTS risk_scores (
    id INTEGER PRIMARY KEY,
    ico TEXT,
    score_date TEXT,
    total_score INTEGER,
    category TEXT,                  -- Nízké / Střední / Vysoké
    factors_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_risk_scores_ico ON risk_scores(ico);

-- Audit log – obecný log všech operací
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    module TEXT,
    action TEXT,
    ico TEXT,
    entity_name TEXT,
    details TEXT,
    user_name TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_log_module    ON audit_log(module);
CREATE INDEX IF NOT EXISTS idx_audit_log_module ON audit_log(module);
