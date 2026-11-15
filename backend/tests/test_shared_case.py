"""Integración del caso compartido con SQLite temporal y dos clientes Flask."""
import io
import tempfile
import unittest
from unittest.mock import patch

from app.core import db
from app.app_factory import create_app
from app.models import mission, emergency_session
from data.seed import seed_catalog


class SharedCaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = db.DB_PATH
        db.DB_PATH = self.temp.name + '/test.db'
        self.app = create_app()
        self.app.testing = True
        seed_catalog.run()
        self.mid = mission.create_mission('TEST', 'Test', 'LEO', None, None)
        self.patient = mission.create_astronaut('PATIENT', self.mid)
        self.helper = mission.create_astronaut('HELPER', self.mid)
        other = mission.create_mission('OTHER', 'Other', 'LEO', None, None)
        self.outsider = mission.create_astronaut('OUTSIDER', other)
        self.a, self.b = self.app.test_client(), self.app.test_client()
        self.body = dict(astronaut_id=self.patient, mission_id=self.mid, transcript='hola')

    def tearDown(self):
        db.DB_PATH = self.original
        self.temp.cleanup()

    def start(self):
        response = self.a.post('/api/emergency/button', json=self.body)
        self.assertEqual(response.status_code, 200)
        return response.json['case']

    def test_continue_takeover_and_persistent_progress(self):
        case = self.start()
        sid = case['emergency_session_id']
        url = f'/api/emergency/sessions/{sid}'
        response = self.b.post('/api/emergency/button', json={**self.body, 'session_id': sid, 'operator_id': self.helper})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['session_id'], sid)
        self.assertEqual(len(emergency_session.list_sessions()), 1)
        version = response.json['case']['version']
        for kind, payload in [('TAKEOVER', {}), ('STEP', {'step_id': 'check-1', 'completed': True})]:
            r = self.b.post(url + '/events', json={'operator_id': self.helper, 'expected_version': version, 'kind': kind, 'payload': payload})
            self.assertEqual(r.status_code, 201)
            version = r.json['version']
        reading = self.a.post('/api/voice/ingest', json={**self.body, 'transcript': 'pulso 80'})
        obs_id = reading.json['observation_ids'][0]
        r = self.b.post(url + '/events', json={'operator_id': self.helper, 'expected_version': version, 'kind': 'MEASUREMENT', 'payload': {'observation_id': obs_id}})
        self.assertEqual(r.status_code, 201)
        # Nueva aplicación/conexión: no depende de memoria del navegador o del servidor.
        restored = create_app().test_client().get(url).json
        self.assertEqual(restored, self.a.get(url).json)
        self.assertEqual(restored, self.b.get(url).json)
        self.assertEqual(restored['current_operator_id'], self.helper)
        self.assertEqual(restored['patient_id'], self.patient)
        self.assertTrue(restored['steps'][0]['payload']['completed'])
        self.assertEqual(restored['measurements'][0]['observation']['value_numeric'], 80)
        self.assertEqual(restored['status'], 'GUIDANCE_GIVEN')
        self.assertEqual([e['operator_id'] for e in restored['events'][:2]], [self.patient, self.helper])
        self.assertTrue(all(e['created_at'] for e in restored['events']))

    def test_stale_version_and_wrong_operator(self):
        case = self.start()
        url = f"/api/emergency/sessions/{case['emergency_session_id']}/events"
        body = {'operator_id': self.helper, 'expected_version': case['version'], 'kind': 'TAKEOVER'}
        self.assertEqual(self.b.post(url, json=body).status_code, 201)
        self.assertEqual(self.a.post(url, json=body).status_code, 409)
        self.assertEqual(self.b.post(url, json={**body, 'operator_id': self.outsider}).status_code, 400)

    def test_reject_wrong_patient_missing_and_closed_case(self):
        case = self.start()
        sid = case['emergency_session_id']
        self.assertEqual(self.a.post('/api/emergency/button', json={**self.body, 'session_id': sid, 'astronaut_id': self.helper}).status_code, 409)
        self.assertEqual(self.a.get('/api/emergency/sessions/999999').status_code, 404)
        emergency_session.update_session(sid, status='RESOLVED')
        self.assertEqual(self.a.post('/api/emergency/button', json={**self.body, 'session_id': sid}).status_code, 409)
        self.assertEqual(len(emergency_session.list_sessions()), 1)

    def test_audio_fallback_continues_same_case(self):
        case = self.start()
        sid = case['emergency_session_id']
        with patch('app.controllers.button_controller.transcribe_audio', return_value={'ok': False, 'text': None}):
            response = self.b.post('/api/emergency/button', data={'astronaut_id': str(self.patient), 'mission_id': str(self.mid), 'operator_id': str(self.helper), 'session_id': str(sid), 'audio': (io.BytesIO(b'test'), 'test.wav')})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['session_id'], sid)
        retry = self.b.post('/api/emergency/button', json={**self.body, 'session_id': sid, 'operator_id': self.helper})
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(len(emergency_session.list_sessions()), 1)


if __name__ == '__main__':
    unittest.main()
