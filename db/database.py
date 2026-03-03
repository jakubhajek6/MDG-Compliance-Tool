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
    """Inicializuje databázi – vytvoří tabulky dle schema.sql."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        if SCHEMA_PATH.exists():
            sql = SCHEMA_PATH.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.commit()
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
