"""P06: reintentos persistentes y continuidad de episodios."""
import io
from unittest.mock import patch
from tests import test_shared_case as shared
from app.app_factory import create_app
from app.core import db
from app.models import emergency_session, anomaly, catalog


class IdempotencyTests(shared.SharedCaseTests):
    def count(self, table):
        with db.session() as conn:
            return conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]

    def test_button_replay_after_restart_and_conflicting_payload(self):
        headers = {'Idempotency-Key': 'button-1'}
        first = self.a.post('/api/emergency/button', json=self.body, headers=headers)
        counts = [self.count(t) for t in ('voice_log', 'emergency_session', 'emergency_session_event')]
        replay = create_app().test_client().post('/api/emergency/button', json=self.body, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data, replay.data)
        self.assertEqual(replay.headers['Idempotency-Replayed'], 'true')
        self.assertEqual(counts, [self.count(t) for t in ('voice_log', 'emergency_session', 'emergency_session_event')])
        conflict = self.a.post('/api/emergency/button', json={**self.body, 'transcript': 'otro reporte'}, headers=headers)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.count('voice_log'), counts[0])

    def test_new_reports_reuse_active_session_and_closed_case_starts_new(self):
        first = self.start()
        second = self.a.post('/api/emergency/button', json=self.body).json['case']
        self.assertEqual(first['emergency_session_id'], second['emergency_session_id'])
        self.assertEqual(len(second['events']), 2)
        emergency_session.update_session(first['emergency_session_id'], status='RESOLVED')
        third = self.start()
        self.assertNotEqual(third['emergency_session_id'], first['emergency_session_id'])

    def test_passive_open_reuses_guidance_given(self):
        first = self.start()
        passive = emergency_session.open_session(self.patient, self.mid, 'PASSIVE_AUTO')
        self.assertEqual(first['emergency_session_id'], passive)
        self.assertEqual(self.count('emergency_session'), 1)

    def test_reading_replay_does_not_duplicate_observation(self):
        body = {'astronaut_id': self.patient, 'indicator_code': 'SERUM_CALCIUM', 'value': 9.7,
                'recorded_at': '2026-11-14T12:00:00Z', 'unit': 'mg_dL',
                'measurement_method': 'test', 'data_origin': 'SIMULATED'}
        first = self.a.post('/api/monitoring/reading', json=body, headers={'Idempotency-Key': 'reading-1'})
        self.assertEqual(first.status_code, 200)
        before = self.count('observation')
        replay = self.b.post('/api/monitoring/reading', json=body, headers={'Idempotency-Key': 'reading-1'})
        self.assertEqual(first.data, replay.data)
        self.assertEqual(self.count('observation'), before)
        self.a.post('/api/monitoring/reading', json=body, headers={'Idempotency-Key': 'reading-2'})
        self.assertEqual(self.count('observation'), before + 1)

    def test_event_replay_precedes_version_check(self):
        case = self.start()
        url = f"/api/emergency/sessions/{case['emergency_session_id']}/events"
        body = {'operator_id': self.helper, 'kind': 'TAKEOVER', 'expected_version': case['version']}
        headers = {'Idempotency-Key': 'takeover-1'}
        first = self.a.post(url, json=body, headers=headers)
        self.assertEqual(first.status_code, 201)
        before = self.count('emergency_session_event')
        replay = self.b.post(url, json=body, headers=headers)
        self.assertEqual(replay.data, first.data)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(self.count('emergency_session_event'), before)

    def test_audio_replay_ignores_multipart_boundary(self):
        def send():
            return self.a.post('/api/emergency/button', data={'astronaut_id': str(self.patient),
                'mission_id': str(self.mid), 'audio': (io.BytesIO(b'audio'), 'a.wav')},
                headers={'Idempotency-Key': 'audio-1'})
        with patch('app.controllers.button_controller.transcribe_audio', return_value={'ok': False, 'text': None}) as transcribe:
            first, second = send(), send()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data, second.data)
        self.assertEqual(transcribe.call_count, 1)

    def test_interrupted_operation_is_not_executed_again(self):
        headers = {'Idempotency-Key': 'interrupted'}
        with patch('app.controllers.button_controller.handle_emergency', side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):
                self.a.post('/api/emergency/button', json=self.body, headers=headers)
        before = self.count('voice_log')
        response = self.b.post('/api/emergency/button', json=self.body, headers=headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['error'], 'operation_pending')
        self.assertEqual(self.count('voice_log'), before)

    def test_alert_updates_history_and_new_episode_after_resolution(self):
        model = anomaly.register_model('LEO', 'TEST_GRAVITY')
        hazard = next(h['hazard_id'] for h in catalog.list_hazards() if h['code'] == 'GRAVITY')
        def alert(level):
            event = anomaly.create_event(model, 0, hazard_id=hazard, astronaut_id=self.patient)
            return anomaly.create_alert(event, level, 'NOTIFY_CREW', 'test')
        first = alert('YELLOW')
        anomaly.set_alert_status(first, 'ACKNOWLEDGED')
        self.assertEqual(alert('YELLOW'), first)
        self.assertEqual(anomaly.list_alerts()[0]['status'], 'ACKNOWLEDGED')
        self.assertEqual(alert('ORANGE'), first)
        self.assertEqual(anomaly.list_alerts()[0]['status'], 'OPEN')
        history = self.a.get(f'/api/emergency/alerts/{first}/history').json
        self.assertEqual([e['level'] for e in history], ['YELLOW', 'YELLOW', 'ORANGE'])
        self.assertEqual(self.count('alert'), 1)
        anomaly.set_alert_status(first, 'RESOLVED')
        self.assertNotEqual(alert('YELLOW'), first)
        self.assertEqual(self.count('alert'), 2)


if __name__ == '__main__':
    import unittest
    unittest.main()
