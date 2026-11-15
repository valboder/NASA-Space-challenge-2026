"""Escalamiento con SQLite temporal, reloj controlado y receptor HTTP local."""
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from tests import test_shared_case as shared
from app.app_factory import create_app
from app.models import emergency_session as cases
from app.services import escalation_service as service
from app.services.notification_transport import WebhookSender
from escalation_worker import run_forever


class EscalationTests(shared.SharedCaseTests):
    def setup_case(self, action=None, timeout=30):
        case = self.start()
        self.sid = case['emergency_session_id']
        self.t0 = datetime.fromisoformat(case['opened_at']).replace(tzinfo=timezone.utc).timestamp()
        if timeout is not None:
            service.configure_policy(self.mid, timeout)
        if action:
            service.record_recommendation(self.sid, action)

    def notifications(self):
        return service.session_status(self.sid)['notifications']

    def test_deadline_once_and_earth_prepared_until_explicit_queue(self):
        self.setup_case()
        service.prepare_notifications(self.t0 + 29)
        self.assertEqual(self.notifications(), [])
        service.prepare_notifications(self.t0 + 30)
        service.prepare_notifications(self.t0 + 90)
        self.assertEqual(len(self.notifications()), 2)
        service.dispatch_notifications(lambda *a: True, {'CREW', 'EARTH'}, 10, self.t0 + 90)
        self.assertEqual({n['channel']: n['status'] for n in self.notifications()}, {'CREW': 'SENT', 'EARTH': 'PREPARED'})
        earth = next(n for n in self.notifications() if n['channel'] == 'EARTH')
        r = self.a.post(f"/api/notifications/{earth['notification_id']}/queue", json={'operator_id': self.helper})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(service.dispatch_notifications(lambda *a: True, {'EARTH'}, 10, self.t0 + 91), 1)

    def test_ack_prevents_timeout_without_closing_case(self):
        self.setup_case()
        url = f'/api/emergency/sessions/{self.sid}/acknowledge'
        self.assertEqual(self.b.post(url, json={'operator_id': self.outsider}).status_code, 400)
        self.assertEqual(self.b.post(url, json={'operator_id': self.helper}).status_code, 200)
        service.prepare_notifications(self.t0 + 40)
        self.assertEqual(self.notifications(), [])
        self.assertEqual(cases.get_session(self.sid)['status'], 'GUIDANCE_GIVEN')

    def test_missing_policy_and_channels_are_explicit(self):
        self.setup_case(timeout=None)
        service.prepare_notifications(self.t0 + 1000)
        state = self.a.get(f'/api/emergency/sessions/{self.sid}/escalation').json
        self.assertFalse(state['policy_configured'])
        self.assertIsNone(state['watch']['deadline_at'])
        url = f'/api/missions/{self.mid}/escalation-policy'
        self.assertEqual(self.a.post(url, json={'response_timeout_seconds': 0}).status_code, 400)
        self.assertEqual(self.a.post(url, json={'response_timeout_seconds': 30}).status_code, 200)
        service.record_recommendation(self.sid, 'CONTACT_EARTH')
        service.prepare_notifications(self.t0)
        self.assertEqual(service.dispatch_notifications(lambda *a: True, set(), 10, self.t0), 0)
        self.assertTrue(all(n['status'] == 'PREPARED' and n['sent_at'] is None for n in self.notifications()))

    def test_network_failure_restart_retry_and_confirmation(self):
        self.setup_case('CONTACT_EARTH')
        service.prepare_notifications(self.t0)
        calls = []
        def fail(channel, key, payload):
            calls.append((key, payload))
            raise OSError('offline')
        service.dispatch_notifications(fail, {'EARTH'}, 10, self.t0)
        earth = next(n for n in self.notifications() if n['channel'] == 'EARTH')
        self.assertEqual(earth['status'], 'PENDING')
        self.assertIsNone(earth['sent_at'])
        url = f"/api/notifications/{earth['notification_id']}/confirm"
        with patch.dict(os.environ, {'GUARDIAN_DELIVERY_CONFIRM_TOKEN': 'test'}):
            self.assertEqual(self.a.post(url).status_code, 401)
            self.assertEqual(self.a.post(url, headers={'Authorization': 'Bearer test'}).status_code, 409)
            create_app()
            service.prepare_notifications(self.t0 + 1)
            self.assertEqual(len(self.notifications()), 2)
            self.assertEqual(service.dispatch_notifications(fail, {'EARTH'}, 10, self.t0 + 9), 0)
            def accept(channel, key, payload):
                calls.append((key, payload))
                return True
            service.dispatch_notifications(accept, {'EARTH'}, 10, self.t0 + 10)
            self.assertEqual(calls[0], calls[1])
            self.assertEqual(self.a.post(url, headers={'Authorization': 'Bearer test'}).json['status'], 'CONFIRMED')
            self.assertEqual(service.dispatch_notifications(accept, {'EARTH'}, 10, self.t0 + 20), 0)

    def test_expired_lease_recovers_same_notification(self):
        self.setup_case('CONTACT_EARTH')
        service.prepare_notifications(self.t0)
        ids = []
        def interrupt(channel, key, payload):
            ids.append(key)
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            service.dispatch_notifications(interrupt, {'EARTH'}, 10, self.t0)
        self.assertEqual(service.dispatch_notifications(lambda *a: True, {'EARTH'}, 10, self.t0 + 59), 0)
        def accept(channel, key, payload):
            ids.append(key)
            return True
        service.dispatch_notifications(accept, {'EARTH'}, 10, self.t0 + 61)
        self.assertEqual(ids[0], ids[1])

    def test_background_loop_without_frontend(self):
        self.setup_case('CONTACT_EARTH')
        delivered, stop = threading.Event(), threading.Event()
        class Sender:
            channels = {'CREW', 'EARTH'}
            def __call__(self, *args):
                delivered.set()
                return True
        thread = threading.Thread(target=run_forever, args=(Sender(), 10, .01, stop))
        thread.start()
        try:
            self.assertTrue(delivered.wait(3))
        finally:
            stop.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(all(n['status'] == 'SENT' for n in self.notifications()))

    def test_http_adapter_local_receiver(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.headers['Idempotency-Key'], json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(202)
                self.end_headers()
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with patch.dict(os.environ, {'GUARDIAN_EARTH_WEBHOOK_URL': f'http://127.0.0.1:{server.server_port}/reports'}, clear=True):
                self.assertTrue(WebhookSender()('EARTH', 'same-id', {'test': True}))
            self.assertEqual(received, [('same-id', {'test': True})])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_active_button_recommendation_reaches_outbox(self):
        result = self.a.post('/api/emergency/button', json={**self.body, 'transcript': 'dolor de pecho'})
        self.assertEqual(result.status_code, 200)
        self.sid = result.json['session_id']
        self.assertEqual(result.json['recommended_action'], 'CONTACT_EARTH')
        service.prepare_notifications()
        self.assertEqual({n['channel'] for n in self.notifications()}, {'CREW', 'EARTH'})

    def test_passive_red_in_existing_case_reaches_outbox(self):
        self.setup_case()
        from app.services import monitoring_service
        assessment = {'level': 'RED', 'availability': 'COMPLETE'}
        evaluation = {'alert_level': 'RED', 'hazard_code': 'GRAVITY', 'reason': 'test', 'recommended_action': 'CONTACT_EARTH'}
        with patch.object(monitoring_service, 'evaluate_all_active_hazards', return_value=[evaluation]), patch.object(monitoring_service, 'recompute_ship_state', return_value={'state': 'LOCKED', 'changed': True, 'assessment': assessment}):
            response = self.a.post('/api/monitoring/reading', json={'astronaut_id': self.patient,
                'indicator_code': 'SERUM_CALCIUM', 'value': 15, 'recorded_at': '2026-11-14T12:00:00Z',
                'unit': 'mg_dL', 'measurement_method': 'test', 'data_origin': 'SIMULATED'})
        self.assertEqual(response.status_code, 200)
        service.prepare_notifications(self.t0)
        self.assertEqual(len(cases.list_sessions()), 1)
        self.assertEqual({n['channel'] for n in self.notifications()}, {'CREW', 'EARTH'})

    def test_ack_and_resolution_cancel_pending(self):
        self.setup_case()
        service.prepare_notifications(self.t0 + 30)
        service.acknowledge(self.sid, self.helper, self.t0 + 31)
        self.assertTrue(all(n['status'] == 'CANCELLED' for n in self.notifications()))
        service.record_recommendation(self.sid, 'CONTACT_EARTH')
        service.prepare_notifications(self.t0 + 32)
        cases.update_session(self.sid, status='RESOLVED')
        service.prepare_notifications(self.t0 + 33)
        self.assertEqual(service.dispatch_notifications(lambda *a: True, {'CREW', 'EARTH'}, 10, self.t0 + 34), 0)


if __name__ == '__main__':
    import unittest
    unittest.main()
