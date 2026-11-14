"""Model: mission, mission_phase, astronaut, habitat."""
from __future__ import annotations

from app.core.db import session, rows_to_list, row_to_dict


def create_mission(code: str, name: str, destination: str, launch_date: str | None,
                    expected_duration_d: int | None, status: str = "ACTIVE") -> int:
    with session() as conn:
        cur = conn.execute(
            """INSERT INTO mission (code, name, destination, launch_date, expected_duration_d, status)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(code) DO UPDATE SET name=excluded.name, destination=excluded.destination,
                 launch_date=excluded.launch_date, expected_duration_d=excluded.expected_duration_d,
                 status=excluded.status""",
            (code, name, destination, launch_date, expected_duration_d, status),
        )
        row = conn.execute("SELECT mission_id FROM mission WHERE code=?", (code,)).fetchone()
        return row["mission_id"]


def get_mission_by_code(code: str) -> dict | None:
    with session() as conn:
        return row_to_dict(conn.execute("SELECT * FROM mission WHERE code=?", (code,)).fetchone())


def list_missions() -> list[dict]:
    with session() as conn:
        return rows_to_list(conn.execute("SELECT * FROM mission ORDER BY mission_id").fetchall())


def ensure_phase(mission_id: int, phase_type: str, start_date: str | None = None, end_date: str | None = None) -> int:
    with session() as conn:
        conn.execute(
            """INSERT INTO mission_phase (mission_id, phase_type, start_date, end_date)
               VALUES (?,?,?,?)
               ON CONFLICT(mission_id, phase_type) DO UPDATE SET
                 start_date=excluded.start_date, end_date=excluded.end_date""",
            (mission_id, phase_type, start_date, end_date),
        )
        row = conn.execute(
            "SELECT mission_phase_id FROM mission_phase WHERE mission_id=? AND phase_type=?",
            (mission_id, phase_type),
        ).fetchone()
        return row["mission_phase_id"]


def create_astronaut(call_sign: str, mission_id: int | None, display_name: str | None = None,
                      sex: str | None = None, birth_date: str | None = None,
                      height_cm: float | None = None, weight_kg_baseline: float | None = None) -> int:
    with session() as conn:
        cur = conn.execute(
            """INSERT INTO astronaut (call_sign, mission_id, display_name, sex, birth_date,
                                       height_cm, weight_kg_baseline)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(call_sign) DO UPDATE SET mission_id=excluded.mission_id,
                 display_name=excluded.display_name""",
            (call_sign, mission_id, display_name, sex, birth_date, height_cm, weight_kg_baseline),
        )
        row = conn.execute("SELECT astronaut_id FROM astronaut WHERE call_sign=?", (call_sign,)).fetchone()
        return row["astronaut_id"]


def get_astronaut_by_call_sign(call_sign: str) -> dict | None:
    with session() as conn:
        return row_to_dict(conn.execute("SELECT * FROM astronaut WHERE call_sign=?", (call_sign,)).fetchone())


def list_astronauts(mission_id: int | None = None) -> list[dict]:
    with session() as conn:
        if mission_id:
            return rows_to_list(conn.execute(
                "SELECT * FROM astronaut WHERE mission_id=? ORDER BY astronaut_id", (mission_id,)).fetchall())
        return rows_to_list(conn.execute("SELECT * FROM astronaut ORDER BY astronaut_id").fetchall())


def mission_id_of_astronaut(astronaut_id: int) -> int | None:
    with session() as conn:
        row = conn.execute("SELECT mission_id FROM astronaut WHERE astronaut_id=?",
                           (astronaut_id,)).fetchone()
        return row["mission_id"] if row else None


def create_habitat(mission_id: int, name: str, habitat_type: str | None = None) -> int:
    with session() as conn:
        cur = conn.execute(
            "INSERT INTO habitat (mission_id, name, habitat_type) VALUES (?,?,?)",
            (mission_id, name, habitat_type),
        )
        return cur.lastrowid


def list_habitats(mission_id: int | None = None) -> list[dict]:
    with session() as conn:
        if mission_id:
            return rows_to_list(conn.execute(
                "SELECT * FROM habitat WHERE mission_id=? ORDER BY habitat_id", (mission_id,)).fetchall())
        return rows_to_list(conn.execute("SELECT * FROM habitat ORDER BY habitat_id").fetchall())
