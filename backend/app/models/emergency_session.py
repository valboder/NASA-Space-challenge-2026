"""Model: sesiones de emergencia (botón de pánico o auto-disparo pasivo)."""
from __future__ import annotations

from app.core.db import session, row_to_dict, rows_to_list


def open_session(astronaut_id: int, mission_id: int, trigger: str,
                 voice_log_id: int | None = None) -> int:
    if trigger not in ("PANIC_BUTTON", "PASSIVE_AUTO"):
        raise ValueError(f"trigger inválido: {trigger}")
    with session() as conn:
        cur = conn.execute(
            """INSERT INTO emergency_session (astronaut_id, mission_id, trigger, voice_log_id)
               VALUES (?,?,?,?)""",
            (astronaut_id, mission_id, trigger, voice_log_id),
        )
        return cur.lastrowid


def update_session(session_id: int, status: str | None = None,
                   summary: str | None = None, voice_log_id: int | None = None) -> None:
    sets, params = [], []
    if status is not None:
        sets.append("status=?"); params.append(status)
        if status in ("RESOLVED", "ESCALATED"):
            sets.append("closed_at=datetime('now')")
    if summary is not None:
        sets.append("summary=?"); params.append(summary)
    if voice_log_id is not None:
        sets.append("voice_log_id=?"); params.append(voice_log_id)
    if not sets:
        return
    params.append(session_id)
    with session() as conn:
        conn.execute(f"UPDATE emergency_session SET {', '.join(sets)} WHERE emergency_session_id=?", params)


def get_session(session_id: int) -> dict | None:
    with session() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM emergency_session WHERE emergency_session_id=?", (session_id,)).fetchone())


def list_sessions(astronaut_id: int | None = None, status: str | None = None,
                  limit: int = 50) -> list[dict]:
    q = "SELECT * FROM emergency_session WHERE 1=1"
    params: list = []
    if astronaut_id is not None:
        q += " AND astronaut_id=?"; params.append(astronaut_id)
    if status is not None:
        q += " AND status=?"; params.append(status)
    q += " ORDER BY opened_at DESC LIMIT ?"; params.append(limit)
    with session() as conn:
        return rows_to_list(conn.execute(q, params).fetchall())
