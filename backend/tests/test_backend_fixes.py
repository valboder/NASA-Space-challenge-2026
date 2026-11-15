"""
Pruebas nuevas para el cierre de P02, P03, P07, P08 y P09 (ver PROBLEMS.md).

Conservan las convenciones ya usadas en el resto de la suite:
- Integración con SQLite temporal + cliente Flask (test_shared_case.py) para
  lo que de verdad necesita la base de datos real (P02, P07, P09).
- Unidad con mocks sobre assistant_service para lo que es lógica pura de
  composición de respuesta (P03, P08), igual que test_assessment_status.py.
"""
import tempfile
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from app.core import db


# ─────────────────────────── P02: ciclo completo ───────────────────────────

class TrackedMeasurementTests(unittest.TestCase):
    """Una medición registrada por /api/observations o /api/voice/ingest con
    session_id debe tener el mismo efecto que el botón/monitoreo pasivo:
    quedar vinculada al caso (visible para el compañero) y reevaluar."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = db.DB_PATH
        db.DB_PATH = self.temp.name + '/test.db'
        from app.app_factory import create_app
        from app.models import mission
        from data.seed import seed_catalog
        self.app = create_app()
        self.app.testing = True
        seed_catalog.run()
        self.mid = mission.create_mission('TEST-P02', 'Test', 'LEO', None, None)
        self.patient = mission.create_astronaut('P02-PATIENT', self.mid)
        self.helper = mission.create_astronaut('P02-HELPER', self.mid)
        self.client = self.app.test_client()

    def tearDown(self):
        db.DB_PATH = self.original
        self.temp.cleanup()

    def _open_case(self):
        r = self.client.post('/api/emergency/button',
                             json={'astronaut_id': self.patient, 'mission_id': self.mid,
                                   'transcript': 'hola'})
        self.assertEqual(r.status_code, 200)
        return r.json['session_id']

    def test_observation_with_session_id_links_and_reevaluates(self):
        sid = self._open_case()
        r = self.client.post('/api/observations', json={
            'indicator_code': 'HEART_RATE', 'mission_id': self.mid,
            'data_source_code': 'CABIN_SENSOR', 'data_origin': 'REAL',
            'recorded_at': '2026-11-14T00:00:00Z', 'unit': 'bpm',
            'measurement_method': 'manual', 'astronaut_id': self.patient,
            'value_numeric': 130, 'session_id': sid, 'operator_id': self.helper,
        })
        self.assertEqual(r.status_code, 201)
        self.assertIn('case_effect', r.json)
        case = self.client.get(f'/api/emergency/sessions/{sid}').json
        obs_ids = [m['observation']['observation_id'] for m in case['measurements']]
        self.assertIn(r.json['observation_id'], obs_ids)
        # El evento quedó atribuido al compañero, no al paciente.
        measurement_events = [e for e in case['events'] if e['kind'] == 'MEASUREMENT']
        self.assertEqual(measurement_events[-1]['operator_id'], self.helper)

    def test_observation_without_session_id_behaves_as_before(self):
        """Compatibilidad: sin session_id, ningún efecto nuevo (registro crudo)."""
        r = self.client.post('/api/observations', json={
            'indicator_code': 'HEART_RATE', 'mission_id': self.mid,
            'data_source_code': 'CABIN_SENSOR', 'data_origin': 'REAL',
            'recorded_at': '2026-11-14T00:00:00Z', 'unit': 'bpm',
            'measurement_method': 'manual', 'astronaut_id': self.patient,
            'value_numeric': 70,
        })
        self.assertEqual(r.status_code, 201)
        self.assertNotIn('case_effect', r.json)

    def test_observation_session_id_requires_astronaut_id(self):
        sid = self._open_case()
        r = self.client.post('/api/observations', json={
            'indicator_code': 'HEART_RATE', 'mission_id': self.mid,
            'data_source_code': 'CABIN_SENSOR', 'data_origin': 'REAL',
            'recorded_at': '2026-11-14T00:00:00Z', 'unit': 'bpm',
            'measurement_method': 'manual', 'value_numeric': 70, 'session_id': sid,
        })
        self.assertEqual(r.status_code, 400)

    def test_observation_session_id_rejects_mismatched_case(self):
        """La observación de otro paciente no puede colarse en este caso."""
        sid = self._open_case()
        r = self.client.post('/api/observations', json={
            'indicator_code': 'HEART_RATE', 'mission_id': self.mid,
            'data_source_code': 'CABIN_SENSOR', 'data_origin': 'REAL',
            'recorded_at': '2026-11-14T00:00:00Z', 'unit': 'bpm',
            'measurement_method': 'manual', 'astronaut_id': self.helper,
            'value_numeric': 70, 'session_id': sid,
        })
        self.assertEqual(r.status_code, 400)

    def test_voice_ingest_with_session_id_links_and_reevaluates(self):
        sid = self._open_case()
        r = self.client.post('/api/voice/ingest', json={
            'astronaut_id': self.patient, 'mission_id': self.mid,
            'transcript': 'pulso 140', 'session_id': sid, 'operator_id': self.helper,
        })
        self.assertEqual(r.status_code, 201)
        self.assertIn('case_effect', r.json)
        case = self.client.get(f'/api/emergency/sessions/{sid}').json
        obs_ids = [m['observation']['observation_id'] for m in case['measurements']]
        self.assertIn(r.json['observation_ids'][0], obs_ids)

    def test_voice_ingest_without_session_id_behaves_as_before(self):
        r = self.client.post('/api/voice/ingest', json={
            'astronaut_id': self.patient, 'mission_id': self.mid, 'transcript': 'pulso 70',
        })
        self.assertEqual(r.status_code, 201)
        self.assertNotIn('case_effect', r.json)

    def test_voice_values_detected_during_panic_button_are_saved_and_linked(self):
        """P02 (vía botón): valores detectados por voz durante la emergencia ya
        no se pierden — quedan guardados como observación y vinculados al caso."""
        r = self.client.post('/api/emergency/button', json={
            'astronaut_id': self.patient, 'mission_id': self.mid,
            'transcript': 'me duele el pecho, pulso 150',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json['recorded_observation_ids']), 1)
        case = r.json['case']
        self.assertEqual(len(case['measurements']), 1)
        self.assertEqual(case['measurements'][0]['observation']['value_numeric'], 150)

    def test_completing_all_steps_does_not_auto_resolve_case(self):
        """P02 (checklist #4): marcar pasos como completados no cierra el caso."""
        sid = self._open_case()
        case = self.client.get(f'/api/emergency/sessions/{sid}').json
        version = case['version']
        for step_id in ('check-1', 'check-2'):
            r = self.client.post(f'/api/emergency/sessions/{sid}/events', json={
                'operator_id': self.patient, 'expected_version': version,
                'kind': 'STEP', 'payload': {'step_id': step_id, 'completed': True},
            })
            self.assertEqual(r.status_code, 201)
            version = r.json['version']
        self.assertEqual(self.client.get(f'/api/emergency/sessions/{sid}').json['status'],
                         'GUIDANCE_GIVEN')


# ──────────────── P08: antigüedad real de mediciones (no solo existencia) ──

class StaleMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = db.DB_PATH
        db.DB_PATH = self.temp.name + '/test.db'
        db.init_db()
        from data.seed import seed_catalog
        from app.models import mission, catalog
        seed_catalog.run()
        catalog.set_measurement_guide('HEART_RATE', 'manual', 'importa', typical_recheck_days=1)
        self.mid = mission.create_mission('TEST-P08', 'Test', 'LEO', None, None)
        self.astro = mission.create_astronaut('P08-PATIENT', self.mid)

    def tearDown(self):
        db.DB_PATH = self.original
        self.temp.cleanup()

    def _record(self, code, value, created_at=None):
        from app.models import observation as obs_model, catalog
        obs_id = obs_model.record_observation(
            indicator_id=catalog.get_indicator_id(code), mission_id=self.mid,
            data_source_id=catalog.get_data_source_id('CABIN_SENSOR'), data_origin='REAL',
            recorded_at='2026-11-14T00:00:00Z', unit='bpm', measurement_method='manual',
            astronaut_id=self.astro, value_numeric=value)
        if created_at is not None:
            with db.session() as conn:
                conn.execute('UPDATE observation SET created_at=? WHERE observation_id=?',
                            (created_at, obs_id))
        return obs_id

    def test_missing_indicator_is_flagged(self):
        from app.services.assistant_service import _stale_or_missing
        result = _stale_or_missing(self.astro, ['HEART_RATE'])
        self.assertEqual(result[0]['status'], 'MISSING')
        self.assertTrue(result[0]['needs_measurement'])

    def test_old_measurement_is_stale_not_sufficient(self):
        from app.services.assistant_service import _stale_or_missing
        self._record('HEART_RATE', 80, created_at='2020-01-01 00:00:00')
        result = _stale_or_missing(self.astro, ['HEART_RATE'])
        self.assertEqual(result[0]['status'], 'STALE')
        self.assertTrue(result[0]['needs_measurement'])

    def test_recent_measurement_within_window_is_fresh_and_reused(self):
        from app.services.assistant_service import _stale_or_missing
        self._record('HEART_RATE', 80)  # created_at = ahora (recién guardada)
        result = _stale_or_missing(self.astro, ['HEART_RATE'])
        self.assertEqual(result[0]['status'], 'FRESH')
        self.assertFalse(result[0]['needs_measurement'])

    def test_handle_emergency_splits_stale_vs_fresh_measurements(self):
        """Integración: una medición vencida no debe desaparecer de la lista
        de 'hay que medir' ni confundirse con una vigente reutilizable."""
        from app.services import assistant_service as assistant
        self._record('HEART_RATE', 80, created_at='2020-01-01 00:00:00')
        sintoma = {"hazard": "GRAVITY", "urgency": "ALTA", "min_action": "CONTACT_EARTH",
                  "steps": [], "measure": ["HEART_RATE"], "patterns": ["dolor"]}
        with ExitStack() as stack:
            stack.enter_context(patch.object(assistant, 'parse_transcript', return_value=[]))
            stack.enter_context(patch.object(assistant, 'detect_symptoms', return_value=[sintoma]))
            result = assistant.handle_emergency(self.astro, self.mid, 'dolor de pecho', session_id=None)
        codes_a_medir = {m['indicator_code'] for m in result['measurements_to_take']}
        codes_vigentes = {m['indicator_code'] for m in result['measurements_up_to_date']}
        self.assertIn('HEART_RATE', codes_a_medir)
        self.assertNotIn('HEART_RATE', codes_vigentes)


# ─────────────────────── P09: contexto de misión resuelto ───────────────────

class MissionContextResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = db.DB_PATH
        db.DB_PATH = self.temp.name + '/test.db'
        from app.app_factory import create_app
        from app.models import mission
        from data.seed import seed_catalog
        self.app = create_app()
        self.app.testing = True
        seed_catalog.run()
        # Luna, NO microgravedad: si el bug (asumir LEO) sigue presente, el
        # entorno devuelto dirá "Órbita baja terrestre"/microgravedad en vez
        # de la base lunar real de esta misión.
        self.mid = mission.create_mission('TEST-P09', 'Lunar Base', 'LUNAR_SURFACE', None, None)
        self.patient = mission.create_astronaut('P09-PATIENT', self.mid)
        self.client = self.app.test_client()

    def tearDown(self):
        db.DB_PATH = self.original
        self.temp.cleanup()

    def test_omitting_destination_uses_real_mission_destination(self):
        r = self.client.post('/api/emergency/button', json={
            'astronaut_id': self.patient, 'mission_id': self.mid, 'transcript': 'hola',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['environment']['label'], 'Base en superficie lunar')
        self.assertEqual(r.json['environment']['gravity'], 'gravedad parcial (~1/6 g)')
        self.assertEqual(r.json['context_resolution']['source'], 'mision')
        self.assertTrue(r.json['context_resolution']['resolved'])

    def test_explicit_override_still_wins_over_mission(self):
        r = self.client.post('/api/emergency/button', json={
            'astronaut_id': self.patient, 'mission_id': self.mid, 'transcript': 'hola',
            'context_destination': 'MARS_SURFACE',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['environment']['label'], 'Superficie de Marte')
        self.assertEqual(r.json['context_resolution']['source'], 'override_explicito')

    def test_step_adaptation_matches_environment_consistently(self):
        """El paso adaptado y la descripción de entorno deben hablar del MISMO
        destino: no puede decir 'microgravedad' y dejar el paso de recostar
        de superficie, ni viceversa (la inconsistencia original de P09)."""
        r = self.client.post('/api/emergency/button', json={
            'astronaut_id': self.patient, 'mission_id': self.mid,
            'transcript': 'se desmayó y no responde',
        })
        self.assertEqual(r.status_code, 200)
        steps_text = ' '.join(r.json['immediate_steps'])
        # Luna = gravedad parcial: la nota de "recuéstala de lado" normal
        # debe aparecer tal cual el perfil LUNAR_SURFACE, no la de microg.
        self.assertNotIn('SUJETARLA', steps_text)


# ───────────────────── P07: atomicidad y concurrencia ──────────────────────

class ShipStateConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = db.DB_PATH
        db.DB_PATH = self.temp.name + '/test.db'
        db.init_db()
        from app.models import mission
        self.mid = mission.create_mission('TEST-P07-SHIP', 'Test', 'LEO', None, None)

    def tearDown(self):
        db.DB_PATH = self.original
        self.temp.cleanup()

    def test_concurrent_set_state_produces_exactly_one_transition(self):
        from app.models import ship
        mission_id = self.mid
        results = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            results.append(ship.set_state(mission_id, 'LOCKED', 'prueba de concurrencia'))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        changed = [r for r in results if r['changed']]
        self.assertEqual(len(changed), 1, "exactamente una llamada debe registrar el cambio")
        history = ship.state_history(mission_id)
        self.assertEqual(len(history), 1, "no debe haber eventos duplicados en la bitácora")
        self.assertEqual(ship.current_state(mission_id)['state'], 'LOCKED')


class OpenSessionConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = db.DB_PATH
        db.DB_PATH = self.temp.name + '/test.db'
        db.init_db()
        from app.models import mission
        self.mid = mission.create_mission('TEST-P07', 'Test', 'LEO', None, None)
        self.astro = mission.create_astronaut('P07-PATIENT', self.mid)

    def tearDown(self):
        db.DB_PATH = self.original
        self.temp.cleanup()

    def test_concurrent_open_session_yields_single_case(self):
        """Dos operadores presionan el botón 'al mismo tiempo' para el mismo
        episodio: debe resultar un único caso activo, no dos."""
        from app.models import emergency_session as es_model
        ids = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            ids.append(es_model.open_session(self.astro, self.mid, 'PANIC_BUTTON'))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(set(ids)), 1, "las 10 llamadas concurrentes deben compartir un solo id")
        sessions = [s for s in es_model.list_sessions(astronaut_id=self.astro)
                   if s['status'] in ('OPEN', 'GUIDANCE_GIVEN')]
        self.assertEqual(len(sessions), 1)


# ───────────────── P03: alertas pasivas omitidas en modo activo ────────────

class PassiveHazardVisibilityTests(unittest.TestCase):
    """Reproduce el bug reportado: un hazard ya en RED debía desaparecer de la
    respuesta si el reporte nuevo no lo menciona (o no tiene síntomas).

    Igual que test_assessment_status.py, se mockean parse_transcript/
    detect_symptoms directamente (measure=[]) para no tocar la base real."""

    def response(self, levels_by_hazard, symptom_entries=()):
        from app.services import assistant_service as assistant

        def fake_eval(astronaut_id, hazard_code, destino, persist=True):
            return {"hazard_code": hazard_code, "alert_level": levels_by_hazard[hazard_code],
                    "reason": f"evaluación de {hazard_code}",
                    "recommended_action": {"RED": "CONTACT_EARTH", "GREEN": "SELF_RESOLVE"}
                                         .get(levels_by_hazard[hazard_code], "NOTIFY_CREW")}

        with ExitStack() as stack:
            stack.enter_context(patch.object(assistant, 'parse_transcript', return_value=[]))
            stack.enter_context(patch.object(assistant, 'detect_symptoms', return_value=list(symptom_entries)))
            stack.enter_context(patch.object(
                assistant.catalog, 'list_hazards',
                return_value=[{'code': c} for c in levels_by_hazard]))
            stack.enter_context(patch.object(assistant, 'evaluate_astronaut_hazard', side_effect=fake_eval))
            stack.enter_context(patch.object(assistant.es_model, 'update_session'))
            return assistant.handle_emergency(1, 1, 'reporte', session_id=1)

    def test_red_hazard_stays_visible_when_report_has_no_symptoms(self):
        result = self.response({'GRAVITY': 'RED', 'RADIATION': 'GREEN'}, symptom_entries=[])
        codes = {p['hazard']: p for p in result['passive_context']}
        self.assertIn('GRAVITY', codes)
        self.assertEqual(codes['GRAVITY']['level'], 'RED')
        self.assertFalse(codes['GRAVITY']['reported_now'])
        self.assertEqual(result['urgency'], 'ALTA')

    def test_red_hazard_stays_visible_when_report_mentions_other_risk(self):
        """Reporta otro síntoma (implica ISOLATION) pero el riesgo de
        gravedad en RED, no mencionado ahora, debe seguir presente y seguir
        mandando la acción recomendada."""
        otro_sintoma = {"hazard": "ISOLATION", "urgency": "BAJA", "min_action": "SELF_RESOLVE",
                        "steps": [], "measure": [], "patterns": ["aislamiento"]}
        result = self.response({'GRAVITY': 'RED', 'ISOLATION': 'YELLOW'},
                               symptom_entries=[otro_sintoma])
        codes = {p['hazard']: p for p in result['passive_context']}
        self.assertEqual(codes['GRAVITY']['level'], 'RED')
        self.assertFalse(codes['GRAVITY']['reported_now'])
        self.assertTrue(codes['ISOLATION']['reported_now'])
        self.assertEqual(result['recommended_action'], 'CONTACT_EARTH')
        self.assertIn('ALTA', result['message'])


# ───── Hallazgos adicionales: jerarquía de severidad y adaptación por entorno ─

class CrewSummaryHidesUnknownTests(unittest.TestCase):
    """`crew_summary` (GET /api/emergency/crew, panel de tripulación) no
    devolvía ningún campo de disponibilidad: un tripulante con un hazard sin
    evaluar (GRAVITY: UNKNOWN) y otro en GREEN (ISOLATION) se mostraba solo
    como "worst_level: GREEN, worst_hazard: ISOLATION", sin ninguna forma de
    saber que GRAVITY nunca se evaluó. `worst_level` en sí no salía mal (su
    jerarquía local ya ordenaba UNKNOWN por debajo de todo lo evaluado); lo
    que faltaba era exponer `assessment.availability`, igual que ya hacen
    `handle_emergency` y el estado de la nave (P04)."""

    def test_unevaluated_hazard_is_now_visible_via_availability(self):
        from app.services import emergency_service as svc
        evals = [
            {"hazard_code": "GRAVITY", "alert_level": "UNKNOWN", "reason": "sin datos"},
            {"hazard_code": "ISOLATION", "alert_level": "GREEN", "reason": "normal",
             "recommended_action": "SELF_RESOLVE"},
        ]
        with ExitStack() as stack:
            stack.enter_context(patch('app.models.mission.list_astronauts',
                                      return_value=[{'astronaut_id': 1, 'call_sign': 'A', 'display_name': 'A'}]))
            stack.enter_context(patch.object(svc, 'evaluate_all_active_hazards', return_value=evals))
            result = svc.crew_summary(1)
        self.assertEqual(len(result), 1)
        # worst_level sigue siendo GREEN (es lo único evaluado) — correcto.
        self.assertEqual(result[0]['worst_level'], 'GREEN')
        self.assertEqual(result[0]['worst_hazard'], 'ISOLATION')
        # Antes: no existía ningún campo que revelara que GRAVITY quedó sin evaluar.
        self.assertIn('assessment', result[0])
        self.assertEqual(result[0]['assessment']['availability'], 'PARTIAL')
        self.assertEqual(result[0]['assessment']['evaluated_count'], 1)
        self.assertEqual(result[0]['assessment']['expected_count'], 2)

    def test_all_green_still_reports_green(self):
        """La corrección no debe volver todo UNKNOWN: si de verdad todo está
        evaluado y en verde, sigue reportándose GREEN."""
        from app.services import emergency_service as svc
        evals = [{"hazard_code": "GRAVITY", "alert_level": "GREEN", "reason": "normal",
                  "recommended_action": "SELF_RESOLVE"}]
        with ExitStack() as stack:
            stack.enter_context(patch('app.models.mission.list_astronauts',
                                      return_value=[{'astronaut_id': 1, 'call_sign': 'A', 'display_name': 'A'}]))
            stack.enter_context(patch.object(svc, 'evaluate_all_active_hazards', return_value=evals))
            result = svc.crew_summary(1)
        self.assertEqual(result[0]['worst_level'], 'GREEN')
        self.assertEqual(result[0]['assessment']['availability'], 'COMPLETE')


class DuplicateFreshMeasurementTests(unittest.TestCase):
    """Dos síntomas que comparten un indicador ya vigente (FRESH) no deben
    duplicarlo en measurements_up_to_date (antes sólo `medir` se deduplicaba,
    no `medir_vigentes`)."""

    def test_shared_fresh_indicator_appears_once(self):
        from app.services import assistant_service as assistant
        sintoma_a = {"hazard": "GRAVITY", "urgency": "ALTA", "min_action": "CONTACT_EARTH",
                    "steps": [], "measure": ["HEART_RATE", "SPO2"], "patterns": ["a"]}
        sintoma_b = {"hazard": "ENCLOSED_ENV", "urgency": "MEDIA", "min_action": "NOTIFY_CREW",
                    "steps": [], "measure": ["HEART_RATE"], "patterns": ["b"]}
        fresh = {"indicator_code": "HEART_RATE", "status": "FRESH", "last_measured_at": "x"}
        spo2_missing = {"indicator_code": "SPO2", "status": "MISSING", "last_measured_at": None,
                        "needs_measurement": True}

        def fake_stale_or_missing(astronaut_id, codes):
            lookup = {"HEART_RATE": fresh, "SPO2": spo2_missing}
            return [lookup[c] for c in codes]

        with ExitStack() as stack:
            stack.enter_context(patch.object(assistant, 'parse_transcript', return_value=[]))
            stack.enter_context(patch.object(assistant, 'detect_symptoms', return_value=[sintoma_a, sintoma_b]))
            stack.enter_context(patch.object(assistant.catalog, 'list_hazards', return_value=[]))
            stack.enter_context(patch.object(assistant.catalog, 'get_indicator', return_value={'name': 'SPO2'}))
            stack.enter_context(patch.object(assistant, '_stale_or_missing', side_effect=fake_stale_or_missing))
            stack.enter_context(patch.object(assistant.es_model, 'update_session'))
            result = assistant.handle_emergency(1, 1, 'reporte', session_id=1)

        heart_rate_vigentes = [m for m in result['measurements_up_to_date'] if m['indicator_code'] == 'HEART_RATE']
        self.assertEqual(len(heart_rate_vigentes), 1)


class MicrogravityFallAdaptationTests(unittest.TestCase):
    """_adapt_step_text solo reescribía 'recuéstala de lado' (a alguien más,
    en tercera persona). 'Siéntate o recuéstate para no caer.' (síntoma de
    mareo, en primera persona) es el mismo problema físico -no hay 'caída'
    sin gravedad- pero no coincidía con ese texto exacto, así que un reporte
    de mareo en microgravedad seguía diciendo que uno puede "caer"."""

    def test_dizziness_step_is_rewritten_in_microgravity(self):
        from app.services.assistant_service import _adapt_step_text
        original = "Siéntate o recuéstate para no caer."
        for destino in ("LEO", "MARS_TRANSIT", "DEEP_SPACE"):
            adaptado = _adapt_step_text(original, destino)
            self.assertNotEqual(adaptado, original, destino)
            self.assertIn("microgravedad", adaptado)

    def test_dizziness_step_unchanged_with_partial_gravity(self):
        from app.services.assistant_service import _adapt_step_text
        original = "Siéntate o recuéstate para no caer."
        for destino in ("LUNAR_SURFACE", "MARS_SURFACE", None):
            self.assertEqual(_adapt_step_text(original, destino), original)

    def test_chest_pain_step_still_rewritten(self):
        """No regression del caso original (P09) al generalizar el mecanismo."""
        from app.services.assistant_service import _adapt_step_text
        original = "Si respira, recuéstala de lado y no la dejes sola."
        self.assertIn("SUJETARLA", _adapt_step_text(original, "LEO"))
        self.assertEqual(_adapt_step_text(original, "MARS_SURFACE"), original)


if __name__ == '__main__':
    unittest.main()
