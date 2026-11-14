"""
Capa de acceso a la base de datos (núcleo del Model en MVC).

No usamos un ORM (SQLAlchemy no está disponible en este entorno de desarrollo
sin acceso a internet para pip) — en su lugar, un wrapper delgado sobre
sqlite3 con filas como dict (sqlite3.Row) y helpers de conveniencia.
Los modelos en app/models/*.py construyen sobre esto.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]          # backend/
SCHEMA_PATH = BASE_DIR / "app" / "models" / "schema.sql"
DB_PATH = os.environ.get("GUARDIAN_DB_PATH", str(BASE_DIR / "data" / "guardian.db"))


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session():
    """Context manager que da una conexión y hace commit/rollback automático."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(reset: bool = False) -> None:
    """Crea el esquema. Si reset=True, borra el archivo primero (solo dev/seed)."""
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with session() as conn:
        conn.executescript(schema_sql)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]
