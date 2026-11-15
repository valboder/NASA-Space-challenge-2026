"""Seguimiento durable de respuestas y outbox. No confirma recuperación clínica."""
import json
import time
import uuid
from datetime import datetime, timezone

from app.core.db import session, rows_to_list
from app.models import emergency_session as cases

ACTIVE = ('OPEN', 'GUIDANCE_GIVEN')


def record_recommendation(session_id, action):
    if action in ('NOTIFY_CREW', 'CONTACT_EARTH'):
        with session() as conn:
            conn.execute('INSERT OR IGNORE INTO escalation_recommendation VALUES (?,?)', (session_id, action))


def queue_report(notification_id, operator_id):
    with session() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('''SELECT n.*,s.mission_id,s.status AS case_status FROM notification_outbox n
            JOIN emergency_session s ON s.emergency_session_id=n.session_id
            WHERE notification_id=?''', (notification_id,)).fetchone()
        if not row:
            raise cases.CaseError('Notificación no encontrada', 404)
        actor = conn.execute('SELECT mission_id FROM astronaut WHERE astronaut_id=?', (operator_id,)).fetchone()
        if not actor or actor[0] != row['mission_id']:
            raise cases.CaseError('El operador no pertenece a la misión')
        if row['status'] == 'CANCELLED':
            raise cases.CaseError('Notificación cancelada', 409)
        if row['case_status'] not in ACTIVE:
            raise cases.CaseError('El caso no está activo', 409)
        conn.execute("UPDATE notification_outbox SET status='PENDING' WHERE notification_id=? AND status='PREPARED'", (notification_id,))
        status = conn.execute('SELECT status FROM notification_outbox WHERE notification_id=?', (notification_id,)).fetchone()[0]
    return {'notification_id': notification_id, 'status': status, 'queued': status == 'PENDING'}


def configure_policy(mission_id, seconds):
    if type(seconds) is not int or seconds <= 0:
        raise cases.CaseError('response_timeout_seconds debe ser un entero positivo')
    with session() as conn:
        if not conn.execute('SELECT 1 FROM mission WHERE mission_id=?', (mission_id,)).fetchone():
            raise cases.CaseError('Misión no encontrada', 404)
        conn.execute("""INSERT INTO escalation_policy VALUES (?,?) ON CONFLICT(mission_id)
            DO UPDATE SET response_timeout_seconds=excluded.response_timeout_seconds""", (mission_id, seconds))
    return {'mission_id': mission_id, 'response_timeout_seconds': seconds,
            'existing_deadlines': 'Se conservan los plazos ya asignados.'}


def acknowledge(session_id, operator_id, now=None):
    now = time.time() if now is None else now
    with session() as conn:
        conn.execute('BEGIN IMMEDIATE')
        case = conn.execute('SELECT * FROM emergency_session WHERE emergency_session_id=?', (session_id,)).fetchone()
        if not case:
            raise cases.CaseError('Caso no encontrado', 404)
        operator = conn.execute('SELECT mission_id FROM astronaut WHERE astronaut_id=?', (operator_id,)).fetchone()
        if not operator or operator['mission_id'] != case['mission_id']:
            raise cases.CaseError('El operador no pertenece a la misión')
        if case['status'] not in ACTIVE:
            raise cases.CaseError('El caso no está activo', 409)
        conn.execute('INSERT OR IGNORE INTO escalation_watch(session_id) VALUES (?)', (session_id,))
        conn.execute("""UPDATE escalation_watch SET acknowledged_at=?,acknowledged_by=?
            WHERE session_id=? AND acknowledged_at IS NULL""", (now, operator_id, session_id))
        # La confirmación de atención suprime avisos NO_RESPONSE aún no enviados.
        # Un envío que ya está en vuelo puede llegar; no fingimos retirarlo.
        conn.execute("""UPDATE notification_outbox SET status='CANCELLED'
            WHERE session_id=? AND reason='NO_RESPONSE' AND status IN ('PREPARED','PENDING')
              AND (lease_until IS NULL OR lease_until<=?)""", (session_id, now))
    return session_status(session_id)


def confirm_delivery(notification_id, now=None):
    now = time.time() if now is None else now
    with session() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT status FROM notification_outbox WHERE notification_id=?', (notification_id,)).fetchone()
        if not row:
            raise cases.CaseError('Notificación no encontrada', 404)
        if row['status'] not in ('SENT', 'CONFIRMED'):
            raise cases.CaseError('No se puede confirmar un envío no realizado', 409)
        conn.execute("UPDATE notification_outbox SET status='CONFIRMED',confirmed_at=COALESCE(confirmed_at,?) WHERE notification_id=?", (now, notification_id))
    return {'notification_id': notification_id, 'status': 'CONFIRMED'}


def session_status(session_id):
    with session() as conn:
        case = conn.execute('SELECT mission_id FROM emergency_session WHERE emergency_session_id=?', (session_id,)).fetchone()
        if not case:
            raise cases.CaseError('Caso no encontrado', 404)
        policy = conn.execute('SELECT * FROM escalation_policy WHERE mission_id=?', (case['mission_id'],)).fetchone()
        watch = conn.execute('SELECT * FROM escalation_watch WHERE session_id=?', (session_id,)).fetchone()
        notifications = rows_to_list(conn.execute("""SELECT notification_id,channel,reason,status,attempts,
            next_attempt_at,created_at,sent_at,confirmed_at,last_error FROM notification_outbox
            WHERE session_id=? ORDER BY created_at,notification_id""", (session_id,)).fetchall())
    return {'session_id': session_id, 'policy_configured': policy is not None,
            'watch': dict(watch) if watch else None, 'notifications': notifications}


def _enqueue(conn, case, channel, reason, now):
    if conn.execute('SELECT 1 FROM notification_outbox WHERE session_id=? AND channel=? AND reason=?',
                    (case['emergency_session_id'], channel, reason)).fetchone():
        return
    # Instantánea auditable de lo registrado; no genera instrucciones ni diagnósticos.
    events = rows_to_list(conn.execute('SELECT * FROM emergency_session_event WHERE session_id=? ORDER BY event_id',
                                      (case['emergency_session_id'],)).fetchall())
    for event in events:
        event['payload'] = json.loads(event.pop('payload_json'))
    observations = rows_to_list(conn.execute("""SELECT * FROM observation WHERE astronaut_id=? AND mission_id=?
        ORDER BY observation_id DESC LIMIT 200""", (case['astronaut_id'], case['mission_id'])).fetchall())
    notification_id = str(uuid.uuid4())
    payload = {'notification_id': notification_id, 'channel': channel, 'reason': reason,
               'prepared_at': now, 'case': dict(case), 'case_events': events,
               'recent_observations': observations, 'observation_limit': 200,
               'note': 'Resumen de registros disponibles; no confirma recuperación ni diagnóstico.'}
    conn.execute("""INSERT INTO notification_outbox
        (notification_id,session_id,channel,reason,payload_json,status,next_attempt_at,created_at)
        VALUES (?,?,?,?,?,'PREPARED',?,?)""",
        (notification_id, case['emergency_session_id'], channel, reason, json.dumps(payload, ensure_ascii=False), now, now))


def prepare_notifications(now=None):
    """Se ejecuta sin solicitudes del frontend y recupera sesiones previas al reinicio."""
    now = time.time() if now is None else now
    with session() as conn:
        conn.execute('BEGIN IMMEDIATE')
        # Un caso finalizado no debe generar nuevos avisos pendientes.
        conn.execute("""UPDATE notification_outbox SET status='CANCELLED'
            WHERE reason='NO_RESPONSE' AND status IN ('PREPARED','PENDING')
              AND (lease_until IS NULL OR lease_until<=?) AND session_id IN
              (SELECT session_id FROM escalation_watch WHERE acknowledged_at IS NOT NULL)""", (now,))
        conn.execute("""UPDATE notification_outbox SET status='CANCELLED'
            WHERE status IN ('PREPARED','PENDING') AND (lease_until IS NULL OR lease_until<=?)
            AND session_id IN (SELECT emergency_session_id FROM emergency_session
                              WHERE status NOT IN ('OPEN','GUIDANCE_GIVEN'))""", (now,))
        active = conn.execute("SELECT * FROM emergency_session WHERE status IN ('OPEN','GUIDANCE_GIVEN')").fetchall()
        for case in active:
            sid = case['emergency_session_id']
            conn.execute('INSERT OR IGNORE INTO escalation_watch(session_id) VALUES (?)', (sid,))
            policy = conn.execute('SELECT response_timeout_seconds FROM escalation_policy WHERE mission_id=?', (case['mission_id'],)).fetchone()
            if policy:
                opened = datetime.fromisoformat(case['opened_at']).replace(tzinfo=timezone.utc).timestamp()
                conn.execute('UPDATE escalation_watch SET deadline_at=? WHERE session_id=? AND deadline_at IS NULL',
                             (opened + policy[0], sid))
            watch = conn.execute('SELECT * FROM escalation_watch WHERE session_id=?', (sid,)).fetchone()
            # No rebaja una recomendación grave anterior del mismo caso aún activo.
            reports = conn.execute("SELECT payload_json FROM emergency_session_event WHERE session_id=? AND kind='REPORT'", (sid,)).fetchall()
            actions = {json.loads(r[0]).get('recommended_action') for r in reports}
            actions.update(r[0] for r in conn.execute('SELECT action FROM escalation_recommendation WHERE session_id=?', (sid,)))
            if case['trigger'] == 'PASSIVE_AUTO':
                actions.add('CONTACT_EARTH')
            if actions & {'NOTIFY_CREW', 'CONTACT_EARTH'}:
                _enqueue(conn, case, 'CREW', 'RECOMMENDATION', now)
            if 'CONTACT_EARTH' in actions:
                _enqueue(conn, case, 'EARTH', 'RECOMMENDATION', now)
            if watch['acknowledged_at'] is None and watch['deadline_at'] is not None and now >= watch['deadline_at']:
                _enqueue(conn, case, 'CREW', 'NO_RESPONSE', now)
                # Ante silencio se prepara resumen a Tierra; el canal decidirá su entrega.
                _enqueue(conn, case, 'EARTH', 'NO_RESPONSE', now)


def dispatch_notifications(sender, channels, retry_seconds, now=None, limit=100):
    """Lease durable; mismo ID en cada intento. El receptor debe deduplicar por ID."""
    if retry_seconds <= 0:
        raise ValueError('retry_seconds debe ser positivo')
    fixed_now = now
    processed = 0
    for _ in range(limit):
        now = time.time() if fixed_now is None else fixed_now
        with session() as conn:
            conn.execute('BEGIN IMMEDIATE')
            rows = conn.execute("""SELECT * FROM notification_outbox
                WHERE status IN ('PREPARED','PENDING') AND next_attempt_at<=?
                AND (lease_until IS NULL OR lease_until<=?)
                AND session_id IN (SELECT emergency_session_id FROM emergency_session
                                   WHERE status IN ('OPEN','GUIDANCE_GIVEN'))
                AND NOT (reason='NO_RESPONSE' AND session_id IN
                    (SELECT session_id FROM escalation_watch WHERE acknowledged_at IS NOT NULL))
                ORDER BY created_at,notification_id""", (now, now)).fetchall()
            row = next((r for r in rows if r['channel'] in channels and not (
                r['channel'] == 'EARTH' and r['reason'] == 'NO_RESPONSE' and r['status'] == 'PREPARED')), None)
            if row is None:
                break
            token = str(uuid.uuid4())
            conn.execute("""UPDATE notification_outbox SET status='PENDING',attempts=attempts+1,
                lease_until=?,lease_token=? WHERE notification_id=?""", (now + 60, token, row['notification_id']))
        try:
            accepted = sender(row['channel'], row['notification_id'], json.loads(row['payload_json']))
            if accepted is not True:
                raise RuntimeError('El receptor no aceptó el envío')
        except Exception:
            # No persistir secretos, URLs ni cuerpos de error de servicios externos.
            with session() as conn:
                conn.execute("""UPDATE notification_outbox SET lease_until=NULL,lease_token=NULL,
                    next_attempt_at=?,last_error='delivery_failed' WHERE notification_id=? AND lease_token=?""",
                    (now + retry_seconds, row['notification_id'], token))
        else:
            with session() as conn:
                conn.execute("""UPDATE notification_outbox SET status='SENT',sent_at=?,lease_until=NULL,
                    lease_token=NULL,last_error=NULL WHERE notification_id=? AND lease_token=?""",
                    (now, row['notification_id'], token))
        processed += 1
    return processed
