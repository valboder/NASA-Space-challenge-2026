"""
Transcripción de voz a texto (faster-whisper), con degradación elegante.

El brief pide que el astronauta pueda reportar por voz. faster-whisper es la
elección correcta porque corre OFFLINE dentro de la nave (no depende del enlace
a Tierra). Pero:

  - Es una dependencia pesada (modelo de varios cientos de MB) que no siempre
    está instalada, y el entorno de desarrollo donde se construyó GUARDIÁN no
    tiene acceso a internet para instalarla.

Por eso este módulo NO asume que faster-whisper esté. Si está, transcribe audio.
Si no, el sistema sigue funcionando con texto (el astronauta escribe, o el
cliente transcribe por otro medio). Así la demo nunca se cae por una dependencia.

Instalación en la máquina de la nave / del compañero:
    pip install faster-whisper
Modelo recomendado para español: 'base' o 'small' (equilibrio velocidad/precisión).
"""
from __future__ import annotations

import os

_MODEL = None
_MODEL_SIZE = os.environ.get("GUARDIAN_WHISPER_MODEL", "base")


def is_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _get_model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        # compute_type int8 para correr en CPU sin GPU (caso típico en una laptop)
        _MODEL = WhisperModel(_MODEL_SIZE, device="cpu", compute_type="int8")
    return _MODEL


def transcribe_audio(audio_path: str, language: str = "es") -> dict:
    """Transcribe un archivo de audio. Devuelve {ok, text, engine, ...}.

    No lanza si faster-whisper no está: devuelve ok=False con instrucciones, para
    que el endpoint responda que se use texto en su lugar.
    """
    if not is_available():
        return {
            "ok": False,
            "engine": None,
            "reason": "faster-whisper no está instalado en este entorno. "
                      "Instálalo con 'pip install faster-whisper' en la máquina de la nave, "
                      "o envía el reporte como texto.",
            "text": None,
        }
    if not os.path.exists(audio_path):
        return {"ok": False, "engine": "faster-whisper", "reason": f"No existe el audio: {audio_path}",
                "text": None}

    model = _get_model()
    segments, info = model.transcribe(audio_path, language=language)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return {
        "ok": True,
        "engine": f"faster-whisper ({_MODEL_SIZE})",
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "text": text,
    }
