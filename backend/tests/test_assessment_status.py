"""P04: consistencia de respuestas con evaluaciones controladas del detector."""
import unittest
from contextlib import ExitStack
from unittest.mock import patch
from app.services.assessment_status import assessment_summary
from app.services import assistant_service as assistant, interlock_service as interlock


def evaluation(level, action=None):
    return {"alert_level": level, "recommended_action": action, "hazard_code": "GRAVITY", "reason": "evaluación de prueba"}


class AssessmentTests(unittest.TestCase):
    def response(self, evaluations, symptom_urgency="BAJA", minimum="SELF_RESOLVE", symptoms=True):
        entries = [{"hazard": f"H{i}", "urgency": symptom_urgency, "min_action": minimum,
                    "steps": [], "measure": [], "patterns": ["síntoma"]} for i in range(len(evaluations))] if symptoms else []
        with ExitStack() as stack:
            stack.enter_context(patch.object(assistant, 'parse_transcript', return_value=[]))
            stack.enter_context(patch.object(assistant, 'detect_symptoms', return_value=entries))
            stack.enter_context(patch.object(assistant.catalog, 'list_hazards', return_value=[{'code': f'H{i}'} for i in range(len(evaluations))]))
            stack.enter_context(patch.object(assistant, 'evaluate_astronaut_hazard', side_effect=evaluations))
            stack.enter_context(patch.object(assistant.es_model, 'update_session'))
            return assistant.handle_emergency(1, 1, 'reporte', session_id=1)

    def test_red_passive_overrides_low_symptom_urgency(self):
        result = self.response([evaluation('RED', 'CONTACT_EARTH')])
        self.assertEqual(result['urgency'], 'ALTA')
        self.assertEqual(result['worst_passive_level'], 'RED')
        self.assertIn('ALTA', result['message'])

    def test_equal_actions_keep_highest_level_in_both_orders(self):
        for levels in [('YELLOW', 'ORANGE'), ('ORANGE', 'YELLOW')]:
            result = self.response([evaluation(level, 'NOTIFY_CREW') for level in levels])
            self.assertEqual(result['worst_passive_level'], 'ORANGE')
            self.assertEqual(result['urgency'], 'ALTA')

    def test_no_evaluation_is_not_green(self):
        result = self.response([], symptoms=False)
        self.assertEqual(result['worst_passive_level'], 'UNKNOWN')
        self.assertEqual(result['urgency'], 'UNKNOWN')
        self.assertEqual(result['assessment']['availability'], 'UNAVAILABLE')
        self.assertIsNone(result['recommended_action'])

    def test_serious_symptom_with_unknown_passive_still_has_high_urgency(self):
        result = self.response([evaluation('UNKNOWN')], 'ALTA', 'CONTACT_EARTH')
        self.assertEqual(result['urgency'], 'ALTA')
        self.assertEqual(result['assessment']['level'], 'UNKNOWN')
        self.assertEqual(result['assessment']['availability'], 'UNAVAILABLE')

    def test_green_and_missing_are_partial_not_complete(self):
        result = assessment_summary([evaluation('GREEN'), evaluation('UNKNOWN')])
        self.assertEqual(result['availability'], 'PARTIAL')
        self.assertEqual(result['evaluated_count'], 1)
        self.assertEqual(result['expected_count'], 2)
        self.assertEqual(assessment_summary([evaluation('GREEN')])['availability'], 'COMPLETE')
        self.assertEqual(assessment_summary([evaluation('GREEN')], 3)['availability'], 'PARTIAL')

    def test_ship_normal_does_not_claim_evaluated_health(self):
        with ExitStack() as stack:
            stack.enter_context(patch('app.models.mission.list_astronauts', return_value=[{'astronaut_id': 1, 'call_sign': 'A'}]))
            evaluator = stack.enter_context(patch.object(interlock, 'evaluate_all_active_hazards', return_value=[evaluation('UNKNOWN')]))
            stack.enter_context(patch.object(interlock.ship_model, 'set_state', return_value={'state': 'NORMAL', 'changed': False}))
            stack.enter_context(patch.object(interlock.ship_model, 'current_state', return_value={'state': 'NORMAL'}))
            stack.enter_context(patch.object(interlock.ship_model, 'activities_with_status', return_value=[]))
            stack.enter_context(patch.object(interlock.ship_model, 'state_history', return_value=[]))
            result = interlock.recompute_ship_state(1)
            self.assertEqual(result['state'], 'NORMAL')
            self.assertEqual(result['assessment']['availability'], 'UNAVAILABLE')
            self.assertIn('sin evaluar', result['reason'])
            status = interlock.get_ship_status(1)
            self.assertEqual(status['worst_level'], 'UNKNOWN')
            self.assertEqual(status['assessment']['availability'], 'UNAVAILABLE')
            self.assertFalse(evaluator.call_args.kwargs['persist'])


if __name__ == '__main__':
    unittest.main()
