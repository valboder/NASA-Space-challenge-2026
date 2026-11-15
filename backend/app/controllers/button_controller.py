"""
Controller del botón de emergencia (modo activo) y la transcripción de voz.
"""
import os
import tempfile

from flask import Blueprint, jsonify, request

from app.services.assistant_service import handle_emergency
from app.services.transcription import transcribe_audio, is_available
from app.models import voice as voice_model, emergency_session as es_model

bp = Blueprint("button", __name__, url_prefix="/api/emergency")


@bp.get("/voice/status")
def voice_status():
    """Dice si la transcripción por voz está disponible en este despliegue."""
    return jsonify({"faster_whisper_available": is_available(),
                    "fallback": "texto" if not is_available() else None})


@bp.errorhandler(es_model.CaseError)
def case_error(error):
    return jsonify({"error": str(error)}), error.status


def positive_id(body, key, default=None):
    value = body.get(key, default)
    if isinstance(value, bool):
        raise es_model.CaseError(f"{key} debe ser un entero positivo")
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if not isinstance(value, int) or value < 1:
        raise es_model.CaseError(f"{key} debe ser un entero positivo")
    return value


def json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise es_model.CaseError("Se requiere un objeto JSON")
    return body


@bp.post("/button")
def panic_button():
    """Inicia o continúa un caso; astronaut_id identifica al paciente."""
    audio = request.files.get("audio")
    body = request.form if audio else json_body()
    astronaut_id = positive_id(body, "astronaut_id")
    mission_id = positive_id(body, "mission_id")
    operator_id = positive_id(body, "operator_id", astronaut_id)
    session_id = positive_id(body, "session_id") if "session_id" in body else None
    es_model.validate_case(astronaut_id, mission_id, operator_id, session_id)
    trans = None
    if audio:
        suffix = os.path.splitext(audio.filename or "audio.wav")[1] or ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            audio.save(tmp.name)
            tmp_path = tmp.name
        try:
            trans = transcribe_audio(tmp_path, language=body.get("language", "es"))
        finally:
            os.remove(tmp_path)
        if not trans["ok"]:
            if session_id is None:
                session_id = es_model.open_session(astronaut_id, mission_id, "PANIC_BUTTON")
            es_model.append_event(session_id, operator_id, "REPORT", {"needs_text": True, "transcription": trans})
            return jsonify({"session_id": session_id, "transcription": trans,
                            "needs_text": True, "case": es_model.case_detail(session_id)})
        transcript = trans["text"]
    else:
        transcript = body.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        raise es_model.CaseError("Se requiere transcript no vacío")
    vl_id = voice_model.create_voice_log(astronaut_id, mission_id, transcript)
    result = handle_emergency(astronaut_id, mission_id, transcript,
                              body.get("context_destination"), session_id=session_id,
                              voice_log_id=vl_id, operator_id=operator_id)
    if trans is not None:
        result["transcription"] = trans
    es_model.append_event(result["session_id"], operator_id, "REPORT", dict(result))
    result["case"] = es_model.case_detail(result["session_id"])
    return jsonify(result)


@bp.get("/sessions/<int:session_id>")
def session_detail(session_id):
    return jsonify(es_model.case_detail(session_id))


@bp.post("/sessions/<int:session_id>/events")
def session_event(session_id):
    """Colaboración persistente; una toma debe existir antes de vincularla."""
    body = json_body()
    operator_id = positive_id(body, "operator_id")
    version = body.get("expected_version")
    if type(version) is not int or version < 0:
        raise es_model.CaseError("Se requiere expected_version entero no negativo")
    kind = body.get("kind")
    payload = body.get("payload", {})
    if not isinstance(payload, dict):
        raise es_model.CaseError("payload debe ser un objeto")
    if kind == "TAKEOVER":
        payload = {}
    elif kind == "STEP":
        if not isinstance(payload.get("step_id"), str) or not payload["step_id"].strip() or type(payload.get("completed")) is not bool:
            raise es_model.CaseError("STEP requiere step_id no vacío y completed booleano")
        payload = {"step_id": payload["step_id"], "completed": payload["completed"]}
    elif kind == "MEASUREMENT":
        payload = {"observation_id": positive_id(payload, "observation_id")}
    else:
        raise es_model.CaseError("kind debe ser TAKEOVER, STEP o MEASUREMENT")
    es_model.append_event(session_id, operator_id, kind, payload, version)
    return jsonify(es_model.case_detail(session_id)), 201


@bp.get("/sessions")
def sessions():
    return jsonify(es_model.list_sessions(
        astronaut_id=request.args.get("astronaut_id", type=int),
        status=request.args.get("status")))
