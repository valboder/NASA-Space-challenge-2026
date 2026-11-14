from flask import Blueprint, jsonify, request
from app.models import catalog

bp = Blueprint("catalog", __name__, url_prefix="/api/catalog")


@bp.get("/hazards")
def get_hazards():
    active_only = request.args.get("active_only", "false").lower() == "true"
    return jsonify(catalog.list_hazards(active_only=active_only))


@bp.get("/data-sources")
def get_sources():
    return jsonify(catalog.list_data_sources())


@bp.get("/indicators")
def get_indicators():
    hazard_code = request.args.get("hazard_code")
    return jsonify(catalog.list_indicators(hazard_code=hazard_code))


@bp.get("/citations")
def get_citations():
    return jsonify(catalog.list_citations())
