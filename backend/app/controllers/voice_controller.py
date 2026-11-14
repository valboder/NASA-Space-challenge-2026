from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from app.services.voice_service import ingest_voice_report
from app.models import voice as voice_model
from app.views.schemas import VoiceIngestRequest, validation_error_payload

bp = Blueprint("voice", __name__, url_prefix="/api/voice")


@bp.post("/ingest")
def ingest():
    """Recibe un transcript (ya convertido de voz a texto por el cliente) y lo
    parsea a observaciones. El frontend que capture el audio/micrófono aún no
    está definido — este endpoint es la interfaz de voz a nivel de backend."""
    try:
        payload = VoiceIngestRequest(**(request.get_json(force=True) or {}))
    except ValidationError as e:
        return jsonify(validation_error_payload(e)), 400
    result = ingest_voice_report(payload.astronaut_id, payload.mission_id, payload.transcript)
    return jsonify(result), 201


@bp.get("/logs")
def logs():
    astronaut_id = request.args.get("astronaut_id", type=int)
    return jsonify(voice_model.list_voice_logs(astronaut_id=astronaut_id))
