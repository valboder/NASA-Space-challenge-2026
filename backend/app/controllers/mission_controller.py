from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from app.models import mission as mission_model
from app.views.schemas import AstronautCreateRequest, validation_error_payload

bp = Blueprint("mission", __name__, url_prefix="/api")


@bp.get("/missions")
def get_missions():
    return jsonify(mission_model.list_missions())


@bp.get("/missions/<int:mission_id>/astronauts")
def get_astronauts(mission_id):
    return jsonify(mission_model.list_astronauts(mission_id))


@bp.get("/astronauts")
def get_all_astronauts():
    return jsonify(mission_model.list_astronauts())


@bp.post("/astronauts")
def create_astronaut():
    try:
        payload = AstronautCreateRequest(**(request.get_json(force=True) or {}))
    except ValidationError as e:
        return jsonify(validation_error_payload(e)), 400
    astro_id = mission_model.create_astronaut(
        call_sign=payload.call_sign, mission_id=payload.mission_id,
        display_name=payload.display_name, sex=payload.sex,
    )
    return jsonify({"astronaut_id": astro_id}), 201


@bp.get("/missions/<int:mission_id>/habitats")
def get_habitats(mission_id):
    return jsonify(mission_model.list_habitats(mission_id))
