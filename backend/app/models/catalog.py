"""
Model: catálogos (hazard, data_source, indicator, indicator_range, data_source_citation).
Son tablas expandibles por INSERT — estas funciones son el único punto de
contacto entre el resto del backend y esas tablas.
"""
from __future__ import annotations

from app.core.db import session, rows_to_list, row_to_dict


def upsert_hazard(code: str, name: str, description: str, is_active_scope: bool) -> int:
    with session() as conn:
        cur = conn.execute(
            """INSERT INTO hazard (code, name, description, is_active_scope)
               VALUES (?,?,?,?)
               ON CONFLICT(code) DO UPDATE SET
                   name=excluded.name, description=excluded.description,
                   is_active_scope=excluded.is_active_scope""",
            (code, name, description, int(is_active_scope)),
        )
        row = conn.execute("SELECT hazard_id FROM hazard WHERE code=?", (code,)).fetchone()
        return row["hazard_id"]


def list_hazards(active_only: bool = False) -> list[dict]:
    with session() as conn:
        q = "SELECT * FROM hazard"
        if active_only:
            q += " WHERE is_active_scope = 1"
        return rows_to_list(conn.execute(q).fetchall())


def upsert_data_source(code: str, name: str, category: str) -> int:
    with session() as conn:
        conn.execute(
            """INSERT INTO data_source (code, name, category) VALUES (?,?,?)
               ON CONFLICT(code) DO UPDATE SET name=excluded.name, category=excluded.category""",
            (code, name, category),
        )
        row = conn.execute("SELECT data_source_id FROM data_source WHERE code=?", (code,)).fetchone()
        return row["data_source_id"]


def list_data_sources() -> list[dict]:
    with session() as conn:
        return rows_to_list(conn.execute("SELECT * FROM data_source ORDER BY category, code").fetchall())


def get_data_source_id(code: str) -> int | None:
    with session() as conn:
        row = conn.execute("SELECT data_source_id FROM data_source WHERE code=?", (code,)).fetchone()
        return row["data_source_id"] if row else None


def upsert_indicator(
    code: str,
    name: str,
    default_unit: str,
    data_type: str,
    requires_equipment: bool,
    default_method: str,
    measurement_caveat: str | None,
    hazard_code: str | None,
    default_source_code: str | None,
) -> int:
    with session() as conn:
        hazard_id = None
        if hazard_code:
            r = conn.execute("SELECT hazard_id FROM hazard WHERE code=?", (hazard_code,)).fetchone()
            hazard_id = r["hazard_id"] if r else None
        source_id = None
        if default_source_code:
            r = conn.execute("SELECT data_source_id FROM data_source WHERE code=?", (default_source_code,)).fetchone()
            source_id = r["data_source_id"] if r else None

        conn.execute(
            """INSERT INTO indicator
                 (code, name, default_unit, data_type, requires_equipment, default_method,
                  measurement_caveat, hazard_id, default_source_id)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(code) DO UPDATE SET
                 name=excluded.name, default_unit=excluded.default_unit,
                 data_type=excluded.data_type, requires_equipment=excluded.requires_equipment,
                 default_method=excluded.default_method, measurement_caveat=excluded.measurement_caveat,
                 hazard_id=excluded.hazard_id, default_source_id=excluded.default_source_id""",
            (code, name, default_unit, data_type, int(requires_equipment), default_method,
             measurement_caveat, hazard_id, source_id),
        )
        row = conn.execute("SELECT indicator_id FROM indicator WHERE code=?", (code,)).fetchone()
        return row["indicator_id"]


def set_measurement_guide(indicator_code: str, how_to_measure: str, why_it_matters: str,
                          typical_recheck_days: int | None = None) -> None:
    """Guarda la guía 'cómo medir / por qué importa' que pide el brief del reto."""
    with session() as conn:
        conn.execute(
            """UPDATE indicator SET how_to_measure=?, why_it_matters=?, typical_recheck_days=?
               WHERE code=?""",
            (how_to_measure, why_it_matters, typical_recheck_days, indicator_code),
        )


def get_indicator(indicator_code: str) -> dict | None:
    with session() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM indicator WHERE code=?", (indicator_code,)).fetchone())


def get_indicator_id(code: str) -> int | None:
    with session() as conn:
        row = conn.execute("SELECT indicator_id FROM indicator WHERE code=?", (code,)).fetchone()
        return row["indicator_id"] if row else None


def list_indicators(hazard_code: str | None = None) -> list[dict]:
    with session() as conn:
        if hazard_code:
            q = """SELECT i.* FROM indicator i JOIN hazard h ON h.hazard_id = i.hazard_id
                   WHERE h.code = ? ORDER BY i.code"""
            return rows_to_list(conn.execute(q, (hazard_code,)).fetchall())
        return rows_to_list(conn.execute("SELECT * FROM indicator ORDER BY code").fetchall())


def add_indicator_range(
    indicator_code: str, context_destination: str | None, sex: str | None,
    min_value: float | None, max_value: float | None, citation_id: int | None = None,
) -> int:
    with session() as conn:
        ind = conn.execute("SELECT indicator_id FROM indicator WHERE code=?", (indicator_code,)).fetchone()
        if not ind:
            raise ValueError(f"Indicador desconocido: {indicator_code}")
        cur = conn.execute(
            """INSERT INTO indicator_range
                 (indicator_id, context_destination, sex, min_value, max_value, source_citation_id)
               VALUES (?,?,?,?,?,?)""",
            (ind["indicator_id"], context_destination, sex, min_value, max_value, citation_id),
        )
        return cur.lastrowid


def get_ranges_for_indicator(indicator_code: str, context_destination: str | None = None) -> list[dict]:
    with session() as conn:
        q = """SELECT ir.* FROM indicator_range ir
               JOIN indicator i ON i.indicator_id = ir.indicator_id
               WHERE i.code = ?"""
        params = [indicator_code]
        if context_destination:
            q += " AND (ir.context_destination IS NULL OR ir.context_destination = ?)"
            params.append(context_destination)
        return rows_to_list(conn.execute(q, params).fetchall())


def add_citation(source_code: str, title: str, url: str, accessed_at: str, license_note: str = "") -> int:
    with session() as conn:
        src = conn.execute("SELECT data_source_id FROM data_source WHERE code=?", (source_code,)).fetchone()
        if not src:
            raise ValueError(f"Fuente desconocida: {source_code}")
        cur = conn.execute(
            """INSERT INTO data_source_citation (data_source_id, title, url, accessed_at, license_note)
               VALUES (?,?,?,?,?)""",
            (src["data_source_id"], title, url, accessed_at, license_note),
        )
        return cur.lastrowid


def list_citations() -> list[dict]:
    with session() as conn:
        q = """SELECT c.*, s.code AS source_code, s.name AS source_name
               FROM data_source_citation c JOIN data_source s ON s.data_source_id = c.data_source_id
               ORDER BY s.code"""
        return rows_to_list(conn.execute(q).fetchall())
