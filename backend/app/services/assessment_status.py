"""Resumen de evaluaciones disponibles; no sustituye al detector."""

LEVEL_RANK = {"UNKNOWN": 0, "GREEN": 1, "YELLOW": 2, "ORANGE": 3, "RED": 4}
LEVEL_URGENCY = {"UNKNOWN": "UNKNOWN", "GREEN": "BAJA", "YELLOW": "MEDIA",
                 "ORANGE": "ALTA", "RED": "ALTA"}
URGENCY_RANK = {"UNKNOWN": 0, "BAJA": 1, "MEDIA": 2, "ALTA": 3}


def assessment_summary(evaluations, expected_count=None):
    expected = len(evaluations) if expected_count is None else expected_count
    evaluated = [e for e in evaluations if e.get("alert_level") in LEVEL_RANK
                 and e["alert_level"] != "UNKNOWN"]
    level = max((e["alert_level"] for e in evaluated), key=LEVEL_RANK.get, default="UNKNOWN")
    availability = "UNAVAILABLE" if not evaluated else (
        "COMPLETE" if len(evaluated) == expected else "PARTIAL")
    note = {"UNAVAILABLE": "Sin evaluación suficiente; salud no confirmada como normal.",
            "PARTIAL": "Evaluación parcial; hay riesgos sin evaluar.",
            "COMPLETE": "Todos los riesgos previstos tienen evaluación; no implica diagnóstico."}[availability]
    return {"level": level, "availability": availability, "evaluated_count": len(evaluated),
            "expected_count": expected, "note": note}
