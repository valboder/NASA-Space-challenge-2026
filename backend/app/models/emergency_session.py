"""Model: sesiones de emergencia (botón de pánico o auto-disparo pasivo)."""
from __future__ import annotations

import json
from app.core.db import session, row_to_dict, rows_to_list


class CaseError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def validate_case(astronaut_id, mission_id, operator_id, session_id=None):
    """Comprueba pertenencia; operator_id es identidad declarada, no autenticación."""
    with session() as conn:
        for person in (astronaut_id, operator_id):
            row = conn.execute("SELECT mission_id FROM astronaut WHERE astronaut_id=?", (person,)).fetchone()
            if row is None or row['mission_id'] != mission_id:
                raise CaseError('Paciente y operador deben pertenecer a la misión', 400)
        if session_id is not None:
            case = conn.execute('SELECT * FROM emergency_session WHERE emergency_session_id=?', (session_id,)).fetchone()
            if case is None:
                raise CaseError('Caso no encontrado', 404)
            if case['astronaut_id'] != astronaut_id or case['mission_id'] != mission_id:
                raise CaseError('El caso no corresponde al paciente y misión', 409)
            if case['status'] not in ('OPEN', 'GUIDANCE_GIVEN'):
                raise CaseError('El caso ya está finalizado', 409)


def append_event(session_id, operator_id, kind, payload, expected_version=None):
    """Añade historial sin sobrescribir acciones ajenas; versión = último evento."""
    with session() as conn:
        conn.execute('BEGIN IMMEDIATE')
        case = conn.execute('SELECT * FROM emergency_session WHERE emergency_session_id=?', (session_id,)).fetchone()
        if case is None:
            raise CaseError('Caso no encontrado', 404)
        if case['status'] not in ('OPEN', 'GUIDANCE_GIVEN'):
            raise CaseError('El caso ya está finalizado', 409)
        actor = conn.execute('SELECT mission_id FROM astronaut WHERE astronaut_id=?', (operator_id,)).fetchone()
        if actor is None or actor['mission_id'] != case['mission_id']:
            raise CaseError('El operador no pertenece a la misión', 400)
        version = conn.execute('SELECT COALESCE(MAX(event_id),0) FROM emergency_session_event WHERE session_id=?', (session_id,)).fetchone()[0]
        if expected_version is not None and version != expected_version:
            raise CaseError('Versión desactualizada: consulta el caso y reintenta', 409)
        if kind == 'MEASUREMENT':
            obs = conn.execute('SELECT astronaut_id, mission_id FROM observation WHERE observation_id=?', (payload['observation_id'],)).fetchone()
            if obs is None or obs['astronaut_id'] != case['astronaut_id'] or obs['mission_id'] != case['mission_id']:
                raise CaseError('La medición no corresponde al paciente y misión', 400)
        conn.execute('INSERT INTO emergency_session_event (session_id,operator_id,kind,payload_json) VALUES (?,?,?,?)',
                     (session_id, operator_id, kind, json.dumps(payload, ensure_ascii=False)))


def case_detail(session_id):
    with session() as conn:
        conn.execute('BEGIN')
        case = row_to_dict(conn.execute('SELECT * FROM emergency_session WHERE emergency_session_id=?', (session_id,)).fetchone())
        if case is None:
            raise CaseError('Caso no encontrado', 404)
        events = rows_to_list(conn.execute('SELECT * FROM emergency_session_event WHERE session_id=? ORDER BY event_id', (session_id,)).fetchall())
        steps, measurements, guidance = {}, [], None
        operator = None
        for event in events:
            event['payload'] = json.loads(event.pop('payload_json'))
            payload = event['payload']
            if event['kind'] == 'TAKEOVER':
                operator = event['operator_id']
            elif event['kind'] == 'STEP':
                steps[payload['step_id']] = event
            elif event['kind'] == 'MEASUREMENT':
                observation = row_to_dict(conn.execute('SELECT * FROM observation WHERE observation_id=?', (payload['observation_id'],)).fetchone())
                measurements.append({'event_id': event['event_id'], 'operator_id': event['operator_id'], 'observation': observation})
            elif event['kind'] == 'REPORT':
                guidance = payload
                if operator is None:
                    operator = event['operator_id']
        return {**case, 'patient_id': case['astronaut_id'], 'current_operator_id': operator,
                'version': events[-1]['event_id'] if events else 0, 'events': events,
                'steps': list(steps.values()), 'measurements': measurements, 'latest_guidance': guidance}


def open_session(astronaut_id: int, mission_id: int, trigger: str,
                 voice_log_id: int | None = None) -> int:
    if trigger not in ("PANIC_BUTTON", "PASSIVE_AUTO"):
        raise ValueError(f"trigger inválido: {trigger}")
    with session() as conn:
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute(
            """SELECT emergency_session_id FROM emergency_session
               WHERE astronaut_id=? AND mission_id=? AND status IN ('OPEN','GUIDANCE_GIVEN')
               ORDER BY emergency_session_id DESC LIMIT 1""", (astronaut_id, mission_id)).fetchone()
        if existing:
            return existing['emergency_session_id']
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
