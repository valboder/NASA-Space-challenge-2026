"""
Servicio de emergencia: toma el resultado del detector de anomalías y lo
traduce en una Alert + instrucción concreta usando emergency_protocol
(árbol de decisión en BD). Esta es la "ayuda en una emergencia" que pidió
el equipo, y queda separada del modelo ML para poder razonar/depurar sin
re-entrenar nada.
"""
from __future__ import annotations

from app.ml.anomaly_detector import score_astronaut
from app.models import anomaly as anomaly_model, catalog


def evaluate_astronaut(astronaut_id: int, context_destination: str, hazard_code: str) -> dict:
    result = score_astronaut(astronaut_id, context_destination, hazard_code)
    if result["status"] != "OK":
        return result

    hazard_rows = {h["code"]: h for h in catalog.list_hazards()}
    hazard_id = hazard_rows.get(hazard_code, {}).get("hazard_id")

    # anomaly_model_id: si no hubo modelo entrenado para este contexto+hazard,
    # igual necesitamos uno para loggear el evento -> se registra un
    # "rule_based_fallback" versionado (mismo patrón de nombre que usa el detector).
    from app.models.anomaly import register_model, latest_model_for_context_hazard
    existing = latest_model_for_context_hazard(context_destination, hazard_code)
    anomaly_model_id = existing["anomaly_model_id"] if existing else register_model(
        context_destination, f"{context_destination}_{hazard_code}_rule_based_fallback_v1",
        algorithm="rule_based",
    )

    event_id = anomaly_model.create_event(
        anomaly_model_id=anomaly_model_id, anomaly_score=result["anomaly_score"],
        hazard_id=hazard_id, astronaut_id=astronaut_id,
    )

    protocol = anomaly_model.find_protocol(hazard_code, result["alert_level"])
    if protocol:
        action = protocol["recommended_action"]
        message = f"{protocol['condition_description']} → {protocol['instructions_text']}"
    else:
        action = "SELF_RESOLVE" if result["alert_level"] == "GREEN" else "NOTIFY_CREW"
        message = f"Nivel {result['alert_level']} detectado en {hazard_code} sin protocolo específico cargado."

    alert_id = anomaly_model.create_alert(event_id, result["alert_level"], action, message)

    return {
        **result,
        "anomaly_event_id": event_id,
        "alert_id": alert_id,
        "recommended_action": action,
        "message": message,
    }


def evaluate_all_active_hazards(astronaut_id: int, context_destination: str) -> list[dict]:
    from app.ml.anomaly_detector import HAZARD_FEATURES
    active_codes = {h["code"] for h in catalog.list_hazards(active_only=True)}
    results = []
    for hazard_code in HAZARD_FEATURES:
        if hazard_code in active_codes:
            results.append(evaluate_astronaut(astronaut_id, context_destination, hazard_code))
    return results
