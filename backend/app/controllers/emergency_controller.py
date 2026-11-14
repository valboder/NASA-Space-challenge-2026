from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from app.services.emergency_service import evaluate_astronaut, evaluate_all_active_hazards
from app.models import anomaly as anomaly_model
from app.views.schemas import EmergencyEvaluateRequest, validation_error_payload

bp = Blueprint("emergency", __name__, url_prefix="/api/emergency")


@bp.post("/evaluate")
def evaluate():
    """Corre el detector de anomalías (IA) + protocolo de emergencia para un
    astronauta en su contexto de misión. Si no se da hazard_code, evalúa los
    3 hazards activos (distancia, aislamiento, gravedad) de una vez."""
    try:
        payload = EmergencyEvaluateRequest(**(request.get_json(force=True) or {}))
    except ValidationError as e:
        return jsonify(validation_error_payload(e)), 400

    if payload.hazard_code:
        result = evaluate_astronaut(payload.astronaut_id, payload.context_destination, payload.hazard_code)
        return jsonify(result)
    results = evaluate_all_active_hazards(payload.astronaut_id, payload.context_destination)
    return jsonify(results)


@bp.get("/alerts")
def alerts():
    return jsonify(anomaly_model.list_alerts(
        status=request.args.get("status"), limit=request.args.get("limit", default=100, type=int)
    ))


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
