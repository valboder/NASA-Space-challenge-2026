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
    from app.models import mission as mission_model
    peor_nivel, peor = "UNKNOWN", None
    for a in mission_model.list_astronauts(mission_id):
        for ev in evaluate_all_active_hazards(a["astronaut_id"], context_destination, persist=persist_alerts):
            if LEVEL_RANK.get(ev["alert_level"], 0) > LEVEL_RANK[peor_nivel]:
                peor_nivel = ev["alert_level"]
                peor = {"astronaut_id": a["astronaut_id"], "call_sign": a["call_sign"],
                        "hazard": ev["hazard_code"], "reason": ev["reason"]}

    nuevo_estado = LEVEL_TO_STATE[peor_nivel]
    if peor:
        razon = f"{peor['call_sign']} / {peor['hazard']}: {peor['reason']}"
    else:
        razon = "Tripulación sin anomalías evaluables; estado normal."

    resultado = ship_model.set_state(
        mission_id, nuevo_estado, razon,
        driven_by_astronaut_id=peor["astronaut_id"] if peor else None,
        driven_by_hazard=peor["hazard"] if peor else None,
    )
    return {
        **resultado,
        "worst_level": peor_nivel,
        "driver": peor,
        "activities": ship_model.activities_with_status(mission_id),
    }


def get_ship_status(mission_id: int) -> dict:
    estado = ship_model.current_state(mission_id)
    return {
        **estado,
        "activities": ship_model.activities_with_status(mission_id),
        "history": ship_model.state_history(mission_id, limit=10),
    }
