from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from app.models import observation as obs_model, catalog
from app.models.observation import ObservationValidationError
from app.models.emergency_session import CaseError
from app.services.monitoring_service import reevaluate_and_link
from app.views.schemas import ObservationCreateRequest, validation_error_payload

bp = Blueprint("observation", __name__, url_prefix="/api/observations")


@bp.errorhandler(CaseError)
def case_error(error):
    return jsonify({"error": str(error)}), error.status


@bp.get("")
def list_observations():
    return jsonify(obs_model.list_observations(
        astronaut_id=request.args.get("astronaut_id", type=int),
        habitat_id=request.args.get("habitat_id", type=int),
        indicator_code=request.args.get("indicator_code"),
        mission_id=request.args.get("mission_id", type=int),
        limit=request.args.get("limit", default=200, type=int),
    ))


@bp.get("/series")
def series():
    astronaut_id = request.args.get("astronaut_id", type=int)
    indicator_code = request.args.get("indicator_code")
    if not astronaut_id or not indicator_code:
        return jsonify({"error": "se requieren astronaut_id e indicator_code"}), 400
    return jsonify(obs_model.series_for_indicator(astronaut_id, indicator_code))


@bp.post("")
def create_observation():
    try:
        payload = ObservationCreateRequest(**(request.get_json(force=True) or {}))
    except ValidationError as e:
        return jsonify(validation_error_payload(e)), 400

    indicator_id = catalog.get_indicator_id(payload.indicator_code)
    source_id = catalog.get_data_source_id(payload.data_source_code)
    if indicator_id is None:
        return jsonify({"error": f"indicator_code desconocido: {payload.indicator_code}"}), 400
    if source_id is None:
        return jsonify({"error": f"data_source_code desconocido: {payload.data_source_code}"}), 400
    if payload.session_id is not None and payload.astronaut_id is None:
        return jsonify({"error": "session_id requiere astronaut_id (el caso es por paciente)"}), 400

    try:
        obs_id = obs_model.record_observation(
            indicator_id=indicator_id, mission_id=payload.mission_id, data_source_id=source_id,
            data_origin=payload.data_origin, recorded_at=payload.recorded_at, unit=payload.unit,
            measurement_method=payload.measurement_method, astronaut_id=payload.astronaut_id,
            habitat_id=payload.habitat_id, value_numeric=payload.value_numeric,
            value_text=payload.value_text, day_relative_to_launch=payload.day_relative_to_launch,
            notes=payload.notes,
        )
    except ObservationValidationError as e:
        return jsonify({"error": str(e)}), 400

    result = {"observation_id": obs_id}
    # P02: si esta medición pertenece a un caso en curso, vincularla y
    # reevaluar — mismo efecto que tendría si hubiera llegado por el flujo
    # de monitoreo pasivo o por el botón de pánico. Sin session_id, el
    # endpoint se comporta exactamente como antes.
    if payload.session_id is not None and payload.astronaut_id is not None:
        result["case_effect"] = reevaluate_and_link(
            payload.astronaut_id, payload.mission_id, obs_id,
            session_id=payload.session_id, operator_id=payload.operator_id,
            context_destination=payload.context_destination,
        )

    return jsonify(result), 201
