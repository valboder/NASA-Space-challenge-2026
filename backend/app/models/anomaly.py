"""Model: anomaly_model, anomaly_event, anomaly_event_observation, alert,
emergency_protocol, data_access_log — la capa de datos de la IA de emergencia."""
from __future__ import annotations

from app.core.db import session, row_to_dict, rows_to_list


def register_model(context_destination: str, version: str, algorithm: str = "IsolationForest",
                    params_json: str | None = None, artifact_path: str | None = None) -> int:
    with session() as conn:
        cur = conn.execute(
            """INSERT INTO anomaly_model (context_destination, algorithm, version, params_json, artifact_path)
               VALUES (?,?,?,?,?)""",
            (context_destination, algorithm, version, params_json, artifact_path),
        )
        return cur.lastrowid


def latest_model_for_context(context_destination: str) -> dict | None:
    with session() as conn:
        row = conn.execute(
            """SELECT * FROM anomaly_model WHERE context_destination=?
               ORDER BY trained_at DESC LIMIT 1""",
            (context_destination,),
        ).fetchone()
        return row_to_dict(row)


def latest_model_for_context_hazard(context_destination: str, hazard_code: str) -> dict | None:
    """Un mismo context_destination puede tener varios modelos (uno por hazard);
    se distinguen por convención de nombre en `version` (ver anomaly_detector.py),
    ya que la columna context_destination está restringida por CHECK a los 5
    destinos oficiales y no puede llevar el hazard concatenado."""
    with session() as conn:
        row = conn.execute(
            """SELECT * FROM anomaly_model WHERE context_destination=? AND version LIKE ?
               ORDER BY trained_at DESC LIMIT 1""",
            (context_destination, f"%_{hazard_code}_%"),
        ).fetchone()
        return row_to_dict(row)


def create_event(anomaly_model_id: int, anomaly_score: float, hazard_id: int | None = None,
                  astronaut_id: int | None = None, habitat_id: int | None = None,
                  observation_ids: list[int] | None = None) -> int:
    if astronaut_id is None and habitat_id is None:
        raise ValueError("anomaly_event necesita astronaut_id o habitat_id")
    with session() as conn:
        cur = conn.execute(
            """INSERT INTO anomaly_event (astronaut_id, habitat_id, anomaly_model_id, hazard_id, anomaly_score)
               VALUES (?,?,?,?,?)""",
            (astronaut_id, habitat_id, anomaly_model_id, hazard_id, anomaly_score),
        )
        event_id = cur.lastrowid
        for obs_id in (observation_ids or []):
            conn.execute(
                "INSERT INTO anomaly_event_observation (anomaly_event_id, observation_id) VALUES (?,?)",
                (event_id, obs_id),
            )
        return event_id


def create_alert(anomaly_event_id: int, level: str, recommended_action: str, message: str) -> int:
    with session() as conn:
        conn.execute('BEGIN IMMEDIATE')
        event = conn.execute("""SELECT e.*, m.context_destination FROM anomaly_event e
            JOIN anomaly_model m ON m.anomaly_model_id=e.anomaly_model_id
            WHERE e.anomaly_event_id=?""", (anomaly_event_id,)).fetchone()
        if event is None:
            raise ValueError('Evento de evaluación inexistente')
        existing = conn.execute("""SELECT a.* FROM alert a
            JOIN anomaly_event e ON e.anomaly_event_id=a.anomaly_event_id
            JOIN anomaly_model m ON m.anomaly_model_id=e.anomaly_model_id
            WHERE e.astronaut_id IS ? AND e.habitat_id IS ? AND e.hazard_id IS ?
              AND m.context_destination=? AND a.status IN ('OPEN','ACKNOWLEDGED')
            ORDER BY a.alert_id DESC LIMIT 1""",
            (event['astronaut_id'], event['habitat_id'], event['hazard_id'], event['context_destination'])).fetchone()
        if existing:
            alert_id = existing['alert_id']
            # Conserva también el estado anterior de alertas creadas antes de esta mejora.
            if not conn.execute('SELECT 1 FROM alert_evaluation WHERE alert_id=? LIMIT 1', (alert_id,)).fetchone():
                conn.execute("""INSERT INTO alert_evaluation
                    (alert_id,anomaly_event_id,level,recommended_action,message,created_at)
                    VALUES (?,?,?,?,?,?)""", (alert_id, existing['anomaly_event_id'], existing['level'],
                    existing['recommended_action'], existing['message'], existing['created_at']))
            # .get(..., -1) en vez de indexar directo: el único llamador hoy
            # (emergency_service.evaluate_astronaut_hazard) nunca pasa GREEN
            # ni UNKNOWN aquí, pero si algo cambiara eso un día, un nivel
            # fuera de este diccionario no debe tumbar con KeyError la
            # persistencia de una alerta ya creada.
            rank = {'GREEN': 0, 'YELLOW': 1, 'ORANGE': 2, 'RED': 3}
            status = 'OPEN' if rank.get(level, -1) > rank.get(existing['level'], -1) else existing['status']
            conn.execute('UPDATE alert SET level=?,recommended_action=?,message=?,status=? WHERE alert_id=?',
                         (level, recommended_action, message, status, alert_id))
            action = 'UPDATE'
        else:
            cur = conn.execute("""INSERT INTO alert (anomaly_event_id,level,recommended_action,message)
                VALUES (?,?,?,?)""", (anomaly_event_id, level, recommended_action, message))
            alert_id = cur.lastrowid
            action = 'CREATE'
        conn.execute("""INSERT INTO alert_evaluation
            (alert_id,anomaly_event_id,level,recommended_action,message) VALUES (?,?,?,?,?)""",
            (alert_id, anomaly_event_id, level, recommended_action, message))
        conn.execute("""INSERT INTO data_access_log (actor,action,entity_touched,entity_id,alert_id,purpose)
            VALUES ('anomaly_service',?,'alert',?,?, 'Evaluación del episodio activo')""",
            (action, alert_id, alert_id))
        return alert_id


def alert_history(alert_id):
    with session() as conn:
        return rows_to_list(conn.execute(
            'SELECT * FROM alert_evaluation WHERE alert_id=? ORDER BY evaluation_id', (alert_id,)).fetchall())


def set_alert_status(alert_id: int, status: str) -> None:
    with session() as conn:
        if status == "RESOLVED":
            conn.execute(
                "UPDATE alert SET status=?, resolved_at=datetime('now') WHERE alert_id=?",
                (status, alert_id),
            )
        else:
            conn.execute("UPDATE alert SET status=? WHERE alert_id=?", (status, alert_id))
        conn.execute(
            """INSERT INTO data_access_log (actor, action, entity_touched, entity_id, alert_id, purpose)
               VALUES ('api','UPDATE','alert',?,?, 'Cambio de estado de alerta')""",
            (alert_id, alert_id),
        )


def list_alerts(status: str | None = None, limit: int = 100) -> list[dict]:
    q = """SELECT a.*, e.astronaut_id, e.habitat_id, e.anomaly_score, e.hazard_id, h.code AS hazard_code
           FROM alert a
           JOIN anomaly_event e ON e.anomaly_event_id = a.anomaly_event_id
           LEFT JOIN hazard h ON h.hazard_id = e.hazard_id
           WHERE 1=1"""
    params: list = []
    if status:
        q += " AND a.status = ?"
        params.append(status)
    q += " ORDER BY a.created_at DESC LIMIT ?"
    params.append(limit)
    with session() as conn:
        return rows_to_list(conn.execute(q, params).fetchall())


def add_protocol(hazard_code: str, alert_level: str, condition_description: str,
                  recommended_action: str, instructions_text: str,
                  parent_protocol_id: int | None = None) -> int:
    with session() as conn:
        hz = conn.execute("SELECT hazard_id FROM hazard WHERE code=?", (hazard_code,)).fetchone()
        if not hz:
            raise ValueError(f"Hazard desconocido: {hazard_code}")
        cur = conn.execute(
            """INSERT INTO emergency_protocol
                 (hazard_id, parent_protocol_id, alert_level, condition_description,
                  recommended_action, instructions_text)
               VALUES (?,?,?,?,?,?)""",
            (hz["hazard_id"], parent_protocol_id, alert_level, condition_description,
             recommended_action, instructions_text),
        )
        return cur.lastrowid


def find_protocol(hazard_code: str, alert_level: str) -> dict | None:
    with session() as conn:
        q = """SELECT p.* FROM emergency_protocol p JOIN hazard h ON h.hazard_id = p.hazard_id
               WHERE h.code=? AND p.alert_level=? LIMIT 1"""
        return row_to_dict(conn.execute(q, (hazard_code, alert_level)).fetchone())


def list_protocols(hazard_code: str | None = None) -> list[dict]:
    with session() as conn:
        if hazard_code:
            q = """SELECT p.*, h.code as hazard_code FROM emergency_protocol p
                   JOIN hazard h ON h.hazard_id = p.hazard_id WHERE h.code=?"""
            return rows_to_list(conn.execute(q, (hazard_code,)).fetchall())
        q = """SELECT p.*, h.code as hazard_code FROM emergency_protocol p
               JOIN hazard h ON h.hazard_id = p.hazard_id"""
        return rows_to_list(conn.execute(q).fetchall())
