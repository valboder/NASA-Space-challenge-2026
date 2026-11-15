"""
Servicio de interlock: traduce el estado de salud de la tripulación en el estado
operacional de la nave.

Es un interlock de SOFTWARE. No controla hardware: fija un estado que la interfaz
respeta y que queda auditado. El mapeo es deliberadamente conservador (favorecer
detección), coherente con la calibración del detector.

    peor nivel de la tripulación   ->   estado de la nave
    ─────────────────────────────       ─────────────────
    RED                                  LOCKED      (bloquea actividades críticas)
    ORANGE / YELLOW                      RESTRICTED  (bloquea actividades no esenciales)
    GREEN / UNKNOWN                      NORMAL

"Hasta que se normalice": el estado se recalcula en cada evaluación, así que al
volver el indicador a verde la nave vuelve sola a NORMAL (con su evento en la
bitácora). No queda bloqueada para siempre por una lectura vieja.
"""
from __future__ import annotations

from app.models import ship as ship_model
from app.services.emergency_service import evaluate_all_active_hazards
from app.services.assessment_status import assessment_summary

LEVEL_TO_STATE = {
    "RED": "LOCKED",
    "ORANGE": "RESTRICTED",
    "YELLOW": "RESTRICTED",
    "GREEN": "NORMAL",
    "UNKNOWN": "NORMAL",
}
LEVEL_RANK = {"RED": 4, "ORANGE": 3, "YELLOW": 2, "GREEN": 1, "UNKNOWN": 0}


def recompute_ship_state(mission_id: int, context_destination: str | None = None,
                         persist_alerts: bool = False) -> dict:
    """Recalcula el estado de la nave a partir del peor nivel de toda la tripulación.

    Devuelve el estado resultante, quién lo motivó y si hubo cambio.
    """
    peor_nivel, peor, assessment = _crew_assessment(mission_id, context_destination, persist_alerts)

    nuevo_estado = LEVEL_TO_STATE[peor_nivel]
    if peor:
        razon = f"{peor['call_sign']} / {peor['hazard']}: {peor['reason']}"
    else:
        razon = "Estado operacional NORMAL por defecto; salud sin evaluar."

    resultado = ship_model.set_state(
        mission_id, nuevo_estado, razon,
        driven_by_astronaut_id=peor["astronaut_id"] if peor else None,
        driven_by_hazard=peor["hazard"] if peor else None,
    )
    return {
        **resultado,
        "worst_level": peor_nivel,
        "assessment": assessment,
        "reason": razon,
        "driver": peor,
        "activities": ship_model.activities_with_status(mission_id),
    }


def _crew_assessment(mission_id, context_destination=None, persist_alerts=False):
    from app.models import mission as mission_model
    peor_nivel, peor = "UNKNOWN", None
    evaluations = []
    for a in mission_model.list_astronauts(mission_id):
        for ev in evaluate_all_active_hazards(a["astronaut_id"], context_destination, persist=persist_alerts):
            evaluations.append(ev)
            if LEVEL_RANK.get(ev["alert_level"], 0) > LEVEL_RANK[peor_nivel]:
                peor_nivel = ev["alert_level"]
                peor = {"astronaut_id": a["astronaut_id"], "call_sign": a["call_sign"],
                        "hazard": ev["hazard_code"], "reason": ev["reason"]}

    return peor_nivel, peor, assessment_summary(evaluations)


def get_ship_status(mission_id: int) -> dict:
    estado = ship_model.current_state(mission_id)
    level, driver, assessment = _crew_assessment(mission_id)
    return {
        **estado,
        "worst_level": level,
        "assessment": assessment,
        "driver": driver,
        "state_basis": "Último estado operacional registrado; assessment es la evaluación actual.",
        "activities": ship_model.activities_with_status(mission_id),
        "history": ship_model.state_history(mission_id, limit=10),
    }
