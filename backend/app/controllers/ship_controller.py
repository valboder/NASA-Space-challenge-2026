"""Controller del estado operacional de la nave (interlock) y monitoreo pasivo."""
from flask import Blueprint, jsonify, request

from app.services.interlock_service import get_ship_status, recompute_ship_state
from app.services.monitoring_service import ingest_reading
from app.services.reminder_service import crew_due_measurements, due_measurements

bp = Blueprint("ship", __name__, url_prefix="/api")


@bp.get("/ship/<int:mission_id>/status")
def ship_status(mission_id):
    """Estado actual de la nave + qué actividades están permitidas/bloqueadas."""
    return jsonify(get_ship_status(mission_id))


@bp.post("/ship/<int:mission_id>/recompute")
def ship_recompute(mission_id):
    """Fuerza un recálculo del estado de la nave (normalmente es automático)."""
    return jsonify(recompute_ship_state(mission_id, request.args.get("context_destination")))


@bp.post("/monitoring/reading")
def monitoring_reading():
    """Ingresa una lectura nueva (análisis pasivo en tiempo real) y devuelve su
    efecto: nivel del tripulante, estado de la nave y si se abrió sesión auto."""
    body = request.get_json(force=True) or {}
    required = ("astronaut_id", "indicator_code", "value", "recorded_at", "unit", "measurement_method")
    missing = [k for k in required if k not in body]
    if missing:
        return jsonify({"error": f"faltan campos: {missing}"}), 400
    return jsonify(ingest_reading(
        astronaut_id=body["astronaut_id"], indicator_code=body["indicator_code"],
        value=body["value"], recorded_at=body["recorded_at"], unit=body["unit"],
        measurement_method=body["measurement_method"],
        data_source_code=body.get("data_source_code", "CABIN_SENSOR"),
        data_origin=body.get("data_origin", "REAL"),
        context_destination=body.get("context_destination"),
        day_relative_to_launch=body.get("day_relative_to_launch"),
    ))


@bp.get("/reminders")
def reminders():
    """Mediciones pendientes. Por tripulante (astronaut_id) o toda la tripulación (mission_id)."""
    day = request.args.get("current_mission_day", default=0, type=int)
    astronaut_id = request.args.get("astronaut_id", type=int)
    mission_id = request.args.get("mission_id", type=int)
    if astronaut_id:
        return jsonify(due_measurements(astronaut_id, day))
    if mission_id:
        return jsonify(crew_due_measurements(mission_id, day))
    return jsonify({"error": "se requiere astronaut_id o mission_id"}), 400
