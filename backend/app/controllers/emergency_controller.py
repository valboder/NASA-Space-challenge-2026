from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from app.services.emergency_service import (
    evaluate_astronaut_hazard, evaluate_all_active_hazards, crew_summary,
)
from app.ml.personal_baseline import evaluate_indicator, project_to_day
from app.models import anomaly as anomaly_model
from app.views.schemas import EmergencyEvaluateRequest, validation_error_payload

bp = Blueprint("emergency", __name__, url_prefix="/api/emergency")


@bp.post("/evaluate")
def evaluate():
    """Evalúa el estado de salud de un tripulante contra su propia línea base.

    Si no se da hazard_code, evalúa los hazards activos (distancia, aislamiento,
    gravedad). Devuelve nivel de semáforo, qué indicador lo motivó, qué señales
    pudieron calcularse y la acción recomendada según el protocolo.
    """
    try:
        payload = EmergencyEvaluateRequest(**(request.get_json(force=True) or {}))
    except ValidationError as e:
        return jsonify(validation_error_payload(e)), 400

    if payload.hazard_code:
        return jsonify(evaluate_astronaut_hazard(
            payload.astronaut_id, payload.hazard_code, payload.context_destination))
    return jsonify(evaluate_all_active_hazards(
        payload.astronaut_id, payload.context_destination))


@bp.get("/indicator")
def indicator_detail():
    """Detalle de un solo indicador: valor actual, línea base personal, rango de
    referencia NASA, tendencia, y la advertencia de validez de esa medición."""
    astronaut_id = request.args.get("astronaut_id", type=int)
    indicator_code = request.args.get("indicator_code")
    if not astronaut_id or not indicator_code:
        return jsonify({"error": "se requieren astronaut_id e indicator_code"}), 400
    context = request.args.get("context_destination")
    return jsonify(evaluate_indicator(astronaut_id, indicator_code, context).to_dict())


@bp.get("/projection")
def projection():
    """Proyección al día N de misión (el 'Día 500' del pitch).

    Es una extrapolación lineal de la tendencia observada, no una predicción del
    modelo; la respuesta incluye las advertencias que la limitan.
    """
    astronaut_id = request.args.get("astronaut_id", type=int)
    indicator_code = request.args.get("indicator_code")
    target_day = request.args.get("target_day", default=500, type=int)
    if not astronaut_id or not indicator_code:
        return jsonify({"error": "se requieren astronaut_id e indicator_code"}), 400
    return jsonify(project_to_day(astronaut_id, indicator_code, target_day,
                                   request.args.get("context_destination")))


@bp.get("/crew")
def crew():
    """Panel de tripulación: una línea por tripulante con su peor nivel."""
    mission_id = request.args.get("mission_id", type=int)
    if not mission_id:
        return jsonify({"error": "se requiere mission_id"}), 400
    return jsonify(crew_summary(mission_id, request.args.get("context_destination")))


@bp.get("/alerts")
def alerts():
    return jsonify(anomaly_model.list_alerts(
        status=request.args.get("status"), limit=request.args.get("limit", default=100, type=int)))


@bp.post("/alerts/<int:alert_id>/status")
def update_alert_status(alert_id):
    body = request.get_json(force=True) or {}
    status = body.get("status")
    if status not in ("OPEN", "ACKNOWLEDGED", "RESOLVED"):
        return jsonify({"error": "status debe ser OPEN, ACKNOWLEDGED o RESOLVED"}), 400
    anomaly_model.set_alert_status(alert_id, status)
    return jsonify({"alert_id": alert_id, "status": status})


@bp.get("/protocols")
def protocols():
    return jsonify(anomaly_model.list_protocols(hazard_code=request.args.get("hazard_code")))


@bp.get("/alerts/<int:alert_id>/history")
def alert_history(alert_id):
    return jsonify(anomaly_model.alert_history(alert_id))
