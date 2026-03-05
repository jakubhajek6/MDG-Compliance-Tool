"""
MDG Compliance Tool – Database module.
Centrální správa SQLite databáze.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "mdg_compliance.sqlite"
SCHEMA_PATH = BASE_DIR / "db" / "schema.sql"


def get_db_path() -> str:
    return str(DB_PATH)


def init_db():
    """Inicializuje databázi – vytvoří tabulky dle schema.sql a spustí additivní migrace."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        if SCHEMA_PATH.exists():
            sql = SCHEMA_PATH.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.commit()
        # Additivní migrace – přidají sloupec pokud ještě neexistuje.
        # SQLite nepodporuje ADD COLUMN IF NOT EXISTS, proto zachytíme OperationalError.
        try:
            conn.execute("ALTER TABLE clients ADD COLUMN subjekt_id TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # sloupec již existuje

        # Belt-and-suspenders: explicitně vytvoříme podklady_runs pokud ještě neexistuje.
        # Pokrývá případ, kdy DB vznikla ze starší verze schema.sql (bez podklady_runs)
        # a executescript výše tabulku nevytvořil. CREATE TABLE IF NOT EXISTS je idempotentní.
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS podklady_runs (
                id INTEGER PRIMARY KEY,
                run_date TEXT NOT NULL,
                ico TEXT NOT NULL,
                subjekt_id TEXT,
                nazev TEXT,
                or_status TEXT DEFAULT 'pending',
                esm_status TEXT DEFAULT 'pending',
                esm_grafika_status TEXT DEFAULT 'pending',
                notes TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_podklady_runs_ico
                ON podklady_runs(ico);
            CREATE INDEX IF NOT EXISTS idx_podklady_runs_date
                ON podklady_runs(run_date);
            CREATE INDEX IF NOT EXISTS idx_podklady_runs_ico_date
                ON podklady_runs(ico, run_date);
        """)
    finally:
        conn.close()


def get_connection() -> sqlite3.Connection:
    """Vrátí připojení k databázi."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def log_audit(module: str, action: str, ico: str = "", entity_name: str = "",
              details: str = "", user_name: str = ""):
    """Zapíše záznam do audit logu."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO audit_log (timestamp, module, action, ico, entity_name, details, user_name)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now().isoformat(timespec="seconds"), module, action,
             ico, entity_name, details, user_name)
        )
        conn.commit()
    finally:
        conn.close()


# --- Klienti ---

def add_client(ico: str, nazev: str = ""):
    """Přidá klienta do sledování."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO clients (ico, nazev, added_date, monitoring_active)
               VALUES (?, ?, ?, 1)""",
            (ico, nazev, datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
    finally:
        conn.close()


def remove_client(ico: str):
    """Odebere klienta ze sledování."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM clients WHERE ico = ?", (ico,))
        conn.commit()
    finally:
        conn.close()


def get_clients(active_only: bool = True) -> list[dict]:
    """Vrátí seznam klientů."""
    conn = get_connection()
    try:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM clients WHERE monitoring_active = 1 ORDER BY nazev"
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM clients ORDER BY nazev").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- AML checks ---

def save_aml_check(ico: str, entity_name: str, entity_type: str,
                   result_status: str, details: dict, risk_score: int = 0):
    """Uloží výsledek AML kontroly."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO aml_checks (ico, entity_name, entity_type, check_date,
               result_status, details_json, risk_score)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ico, entity_name, entity_type,
             datetime.now().isoformat(timespec="seconds"),
             result_status, json.dumps(details, ensure_ascii=False), risk_score)
        )
        conn.commit()
    finally:
        conn.close()


def get_aml_checks(ico: str = "", limit: int = 100) -> list[dict]:
    """Vrátí historii AML kontrol."""
    conn = get_connection()
    try:
        if ico:
            rows = conn.execute(
                "SELECT * FROM aml_checks WHERE ico = ? ORDER BY check_date DESC LIMIT ?",
                (ico, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM aml_checks ORDER BY check_date DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- OR Snapshots ---

def save_or_snapshot(ico: str, data: dict):
    """Uloží snapshot dat z OR."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO or_snapshots (ico, snapshot_date, data_json)
               VALUES (?, ?, ?)""",
            (ico, datetime.now().isoformat(timespec="seconds"),
             json.dumps(data, ensure_ascii=False))
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_snapshot(ico: str) -> Optional[dict]:
    """Vrátí poslední snapshot pro dané IČO."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM or_snapshots WHERE ico = ? ORDER BY snapshot_date DESC LIMIT 1",
            (ico,)
        ).fetchone()
        if row:
            result = dict(row)
            result["data"] = json.loads(result["data_json"])
            return result
        return None
    finally:
        conn.close()


# --- OR Changes ---

def save_or_change(ico: str, change_type: str, old_value: str, new_value: str):
    """Uloží detekovanou změnu v OR."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO or_changes (ico, detected_date, change_type, old_value, new_value, processed)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (ico, datetime.now().isoformat(timespec="seconds"),
             change_type, old_value, new_value)
        )
        conn.commit()
    finally:
        conn.close()


def get_unprocessed_changes() -> list[dict]:
    """Vrátí nezpracované změny."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM or_changes WHERE processed = 0 ORDER BY detected_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_change_processed(change_id: int):
    """Označí změnu jako zpracovanou."""
    conn = get_connection()
    try:
        conn.execute("UPDATE or_changes SET processed = 1 WHERE id = ?", (change_id,))
        conn.commit()
    finally:
        conn.close()


# --- Risk Scores ---

def save_risk_score(ico: str, total_score: int, category: str, factors: dict):
    """Uloží rizikové skóre."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO risk_scores (ico, score_date, total_score, category, factors_json)
               VALUES (?, ?, ?, ?, ?)""",
            (ico, datetime.now().isoformat(timespec="seconds"),
             total_score, category, json.dumps(factors, ensure_ascii=False))
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_risk_score(ico: str) -> Optional[dict]:
    """Vrátí poslední rizikové skóre pro dané IČO."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM risk_scores WHERE ico = ? ORDER BY score_date DESC LIMIT 1",
            (ico,)
        ).fetchone()
        if row:
            result = dict(row)
            result["factors"] = json.loads(result["factors_json"])
            return result
        return None
    finally:
        conn.close()


# --- Podklady ESM ---

# Povolené hodnoty pro sloupce stavu – whitelist proti SQL injection.
_PODKLADY_STATUS_FIELDS = {"or_status", "esm_status", "esm_grafika_status"}
_PODKLADY_STATUS_VALUES = {"pending", "ok", "error"}


def upsert_client_subjekt_id(ico: str, subjekt_id: str) -> None:
    """Uloží nebo aktualizuje subjektId (justice.cz interní ID) ke klientovi.

    Pokud klient v tabulce clients ještě neexistuje, nic neprovede –
    subjektId se ukládá pouze k existujícím klientům.
    """
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE clients SET subjekt_id = ? WHERE ico = ?",
            (subjekt_id, ico)
        )
        conn.commit()
    finally:
        conn.close()


def save_podklady_run(ico: str, subjekt_id: str, nazev: str) -> int:
    """Vytvoří nový záznam běhu stahování podkladů a vrátí jeho ``id``.

    Všechny tři statusy jsou inicializovány na ``'pending'``.
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO podklady_runs (run_date, ico, subjekt_id, nazev,
               or_status, esm_status, esm_grafika_status)
               VALUES (?, ?, ?, ?, 'pending', 'pending', 'pending')""",
            (datetime.now().isoformat(timespec="seconds"), ico, subjekt_id, nazev)
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def update_podklady_status(run_id: int, field: str, status: str) -> None:
    """Aktualizuje jeden status sloupec záznamu v ``podklady_runs``.

    Args:
        run_id: ID záznamu v podklady_runs.
        field:  Název sloupce – musí být jedním z ``or_status``, ``esm_status``,
                ``esm_grafika_status``.
        status: Nová hodnota – ``'pending'``, ``'ok'``, nebo ``'error'``.

    Raises:
        ValueError: Pokud ``field`` nebo ``status`` nejsou v povoleném whitelistu.
    """
    if field not in _PODKLADY_STATUS_FIELDS:
        raise ValueError(f"Nepovolený field: {field!r}. Povoleno: {_PODKLADY_STATUS_FIELDS}")
    if status not in _PODKLADY_STATUS_VALUES:
        raise ValueError(f"Nepovolený status: {status!r}. Povoleno: {_PODKLADY_STATUS_VALUES}")
    conn = get_connection()
    try:
        # field je ze striktního whitelistu, parametrická substituce pro identifikátory
        # v sqlite3 není možná – literal safe interpolation je zde záměrná a bezpečná.
        conn.execute(
            f"UPDATE podklady_runs SET {field} = ? WHERE id = ?",  # noqa: S608
            (status, run_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_podklady_history(ico: str = "", limit: int = 50) -> list[dict]:
    """Vrátí historii běhů stahování podkladů.

    Args:
        ico:   Pokud zadáno, filtruje záznamy pro jedno IČO.
        limit: Maximální počet vrácených záznamů (seřazeno od nejnovějšího).
    """
    conn = get_connection()
    try:
        if ico:
            rows = conn.execute(
                "SELECT * FROM podklady_runs WHERE ico = ? ORDER BY run_date DESC LIMIT ?",
                (ico, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM podklady_runs ORDER BY run_date DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
