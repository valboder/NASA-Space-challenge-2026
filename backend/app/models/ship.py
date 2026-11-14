"""
Model: estado operacional de la nave (interlock de software) y actividades.

Recordatorio de honestidad: esto NO controla hardware. Fija un estado que la
interfaz respeta y que queda auditado en ship_state_event (append-only). El
estado actual de una misión es su evento más reciente; NORMAL si no hay ninguno.
"""
from __future__ import annotations

from app.core.db import session, row_to_dict, rows_to_list

VALID_STATES = ("NORMAL", "RESTRICTED", "LOCKED")
STATE_RANK = {"NORMAL": 0, "RESTRICTED": 1, "LOCKED": 2}


def current_state(mission_id: int) -> dict:
    """Estado actual de la nave = evento más reciente. NORMAL por defecto."""
    with session() as conn:
        row = conn.execute(
            """SELECT * FROM ship_state_event WHERE mission_id=?
               ORDER BY created_at DESC, ship_state_event_id DESC LIMIT 1""",
            (mission_id,),
        ).fetchone()
    if row is None:
        return {"mission_id": mission_id, "state": "NORMAL", "reason": "Sin eventos; estado por defecto.",
                "driven_by_astronaut_id": None, "driven_by_hazard": None, "created_at": None}
    return row_to_dict(row)


def set_state(mission_id: int, state: str, reason: str,
              driven_by_astronaut_id: int | None = None,
              driven_by_hazard: str | None = None) -> dict:
    """Registra un cambio de estado SOLO si difiere del actual (evita ruido en la
    bitácora). Devuelve {changed: bool, previous, current}."""
    if state not in VALID_STATES:
        raise ValueError(f"Estado inválido: {state}")
    prev = current_state(mission_id)
    if prev["state"] == state:
        return {"changed": False, "previous_state": prev["state"], "state": state,
                "mission_id": mission_id}
    with session() as conn:
        conn.execute(
            """INSERT INTO ship_state_event
                 (mission_id, state, previous_state, reason, driven_by_astronaut_id, driven_by_hazard)
               VALUES (?,?,?,?,?,?)""",
            (mission_id, state, prev["state"], reason, driven_by_astronaut_id, driven_by_hazard),
        )
        conn.execute(
            """INSERT INTO data_access_log (actor, action, entity_touched, purpose)
               VALUES ('ship_interlock','UPDATE','ship_state_event', ?)""",
            (f"Nave {prev['state']} -> {state}: {reason}",),
        )
    return {"changed": True, "previous_state": prev["state"], "state": state,
            "mission_id": mission_id, "reason": reason}


def state_history(mission_id: int, limit: int = 50) -> list[dict]:
    with session() as conn:
        return rows_to_list(conn.execute(
            """SELECT * FROM ship_state_event WHERE mission_id=?
               ORDER BY created_at DESC, ship_state_event_id DESC LIMIT ?""",
            (mission_id, limit),
        ).fetchall())


# ───────────────────────────── Actividades ─────────────────────────────

def upsert_activity(code: str, name: str, category: str, min_allowed_state: str,
                    rationale: str = "") -> int:
    with session() as conn:
        conn.execute(
            """INSERT INTO ship_activity (code, name, category, min_allowed_state, rationale)
               VALUES (?,?,?,?,?)
               ON CONFLICT(code) DO UPDATE SET name=excluded.name, category=excluded.category,
                 min_allowed_state=excluded.min_allowed_state, rationale=excluded.rationale""",
            (code, name, category, min_allowed_state, rationale),
        )
        return conn.execute("SELECT ship_activity_id FROM ship_activity WHERE code=?", (code,)).fetchone()[0]


def activities_with_status(mission_id: int) -> list[dict]:
    """Lista de actividades con si están permitidas en el estado actual.

    Una actividad se permite si el estado actual de la nave es tan o más
    permisivo que el estado mínimo que ella exige. Ej.: una actividad que exige
    NORMAL queda bloqueada en RESTRICTED o LOCKED.
    """
    estado = current_state(mission_id)["state"]
    rango_actual = STATE_RANK[estado]
    with session() as conn:
        rows = rows_to_list(conn.execute(
            "SELECT * FROM ship_activity ORDER BY min_allowed_state, code").fetchall())
    for r in rows:
        r["allowed"] = rango_actual <= STATE_RANK[r["min_allowed_state"]]
    return rows
