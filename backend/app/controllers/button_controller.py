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


@bp.post("/button")
def panic_button():
    """El astronauta presiona el botón y reporta por voz (o texto).

    Acepta:
      - JSON {astronaut_id, mission_id, transcript, context_destination?}  (texto)
      - multipart con un archivo 'audio' + campos astronaut_id, mission_id    (voz)

    En modo voz, si faster-whisper no está, responde pidiendo texto en su lugar.
    """
    # ── modo audio (multipart) ──
    if request.files.get("audio"):
        astronaut_id = request.form.get("astronaut_id", type=int)
        mission_id = request.form.get("mission_id", type=int)
        context = request.form.get("context_destination")
        if not astronaut_id or not mission_id:
            return jsonify({"error": "se requieren astronaut_id y mission_id"}), 400

        audio = request.files["audio"]
        suffix = os.path.splitext(audio.filename or "audio.wav")[1] or ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            audio.save(tmp.name)
            tmp_path = tmp.name
        try:
            trans = transcribe_audio(tmp_path, language=request.form.get("language", "es"))
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        if not trans["ok"]:
            # Abrimos la sesión igual (el botón se presionó) pero pedimos texto.
            session_id = es_model.open_session(astronaut_id, mission_id, "PANIC_BUTTON")
            return jsonify({"session_id": session_id, "transcription": trans,
                            "message": "No se pudo transcribir el audio. Envía tu reporte como texto.",
                            "needs_text": True}), 200
        transcript = trans["text"]
        vl_id = voice_model.create_voice_log(astronaut_id, mission_id, transcript)
        result = handle_emergency(astronaut_id, mission_id, transcript, context,
                                   voice_log_id=vl_id)
        result["transcription"] = trans
        return jsonify(result), 200

    # ── modo texto (JSON) ──
    body = request.get_json(force=True) or {}
    astronaut_id = body.get("astronaut_id")
    mission_id = body.get("mission_id")
    transcript = body.get("transcript")
    if not astronaut_id or not mission_id or not transcript:
        return jsonify({"error": "se requieren astronaut_id, mission_id y transcript"}), 400
    vl_id = voice_model.create_voice_log(astronaut_id, mission_id, transcript)
    result = handle_emergency(astronaut_id, mission_id, transcript,
                               body.get("context_destination"), voice_log_id=vl_id)
    return jsonify(result), 200


@bp.get("/sessions")
def sessions():
    return jsonify(es_model.list_sessions(
        astronaut_id=request.args.get("astronaut_id", type=int),
        status=request.args.get("status")))
