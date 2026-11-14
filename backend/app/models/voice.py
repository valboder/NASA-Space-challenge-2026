"""Model: voice_log — captura cruda de la interfaz por voz."""
from __future__ import annotations

import json
from app.core.db import session, row_to_dict, rows_to_list


def create_voice_log(astronaut_id: int, mission_id: int, transcript: str) -> int:
    with session() as conn:
        cur = conn.execute(
            """INSERT INTO voice_log (astronaut_id, mission_id, transcript, status)
               VALUES (?,?,?, 'PENDING')""",
            (astronaut_id, mission_id, transcript),
        )
        return cur.lastrowid


def update_voice_log_parse(voice_log_id: int, parsed_payload: dict, confidence: float, status: str) -> None:
    with session() as conn:
        conn.execute(
            """UPDATE voice_log SET parsed_payload=?, parse_confidence=?, status=?
               WHERE voice_log_id=?""",
            (json.dumps(parsed_payload, ensure_ascii=False), confidence, status, voice_log_id),
        )


def get_voice_log(voice_log_id: int) -> dict | None:
    with session() as conn:
        row = row_to_dict(conn.execute(
            "SELECT * FROM voice_log WHERE voice_log_id=?", (voice_log_id,)).fetchone())
        if row and row.get("parsed_payload"):
            row["parsed_payload"] = json.loads(row["parsed_payload"])
        return row


def list_voice_logs(astronaut_id: int | None = None, limit: int = 100) -> list[dict]:
    with session() as conn:
        if astronaut_id:
            rows = rows_to_list(conn.execute(
                "SELECT * FROM voice_log WHERE astronaut_id=? ORDER BY recorded_at DESC LIMIT ?",
                (astronaut_id, limit)).fetchall())
        else:
            rows = rows_to_list(conn.execute(
                "SELECT * FROM voice_log ORDER BY recorded_at DESC LIMIT ?", (limit,)).fetchall())
        for r in rows:
            if r.get("parsed_payload"):
                r["parsed_payload"] = json.loads(r["parsed_payload"])
        return rows
