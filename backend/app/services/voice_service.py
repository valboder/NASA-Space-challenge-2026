"""
Servicio de recolección de datos por voz (capa backend; la captura de audio/
micrófono es frontend y no se toca en esta entrega).

Flujo: el frontend (cuando se defina) sube un transcript de texto (ya
convertido de voz a texto por el navegador/Web Speech API u otro motor) ->
este servicio lo guarda crudo en voice_log, lo parsea con reglas simples de
palabras clave + números, y genera una Observation por cada indicador que
reconoce, con data_source='VOICE_INPUT' y data_origin='REAL' (es el propio
astronauta reportando, no una simulación).

Deliberadamente basado en reglas (no LLM) para que sea rápido, determinístico
y 100% auditable en un hackathon — fácil de reemplazar después por un modelo
de NLU sin tocar el resto del backend.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.models import catalog, voice as voice_model, observation as obs_model, mission as mission_model

# patrón: palabras clave en español -> (indicator_code, unidad, método)
KEYWORD_RULES: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"(pulso|frecuencia cardiaca|ritmo cardiaco)\D{0,15}(\d{2,3})", re.I),
     "HEART_RATE", "bpm", "Reporte de voz (audífono)"),
    (re.compile(r"(spo2|saturaci[oó]n( de ox[ií]geno)?)\D{0,15}(\d{2,3})", re.I),
     "SPO2", "%", "Reporte de voz (audífono)"),
    (re.compile(r"(temperatura)\D{0,15}(\d{2}(\.\d+)?)", re.I),
     "SKIN_TEMP", "C", "Reporte de voz (audífono)"),
    (re.compile(r"(dorm[ií]|sue[ñn]o)\D{0,15}(\d{1,2}(\.\d+)?)\s*(horas|hrs|h)?", re.I),
     "SLEEP_EFFICIENCY", "pct", "Reporte de voz (saco de dormir, estimado)"),
    (re.compile(r"(estr[eé]s)\D{0,15}(\d{1,3})", re.I),
     "DAILY_STRESS_SCORE", "score_0_100", "Autorreporte de voz"),
    (re.compile(r"(ansie[dt]ad)\D{0,15}(\d{1,3})", re.I),
     "STAI_ANXIETY", "score", "Autorreporte de voz"),
    (re.compile(r"(calcio)\D{0,15}(\d{1,3}(\.\d+)?)\D{0,10}(24\s*h|24h)", re.I),
     "URINARY_CALCIUM_MG24H", "mg_24h", "Reporte de voz (baño, recolección 24h)"),
    (re.compile(r"(calcio)\D{0,15}(\d{1,3}(\.\d+)?)", re.I),
     "URINARY_CALCIUM_MGDL", "mg_dL", "Reporte de voz (baño, puntual)"),
    (re.compile(r"(glucosa)\D{0,15}(\d{2,3}(\.\d+)?)", re.I),
     "URINE_GLUCOSE", "mg_dL", "Reporte de voz (baño)"),
    (re.compile(r"(hidrataci[oó]n)\D{0,15}(\d{1,3}(\.\d+)?)", re.I),
     "HYDRATION_INDEX", "index", "Reporte de voz (baño)"),
]


def _extract_number(match: re.Match) -> float | None:
    for g in match.groups():
        if g and re.match(r"^\d+(\.\d+)?$", g):
            return float(g)
    return None


def parse_transcript(transcript: str) -> list[dict]:
    """Devuelve lista de {indicator_code, value, unit, method} detectados."""
    found = []
    for pattern, code, unit, method in KEYWORD_RULES:
        m = pattern.search(transcript)
        if m:
            value = _extract_number(m)
            if value is not None:
                found.append({"indicator_code": code, "value": value, "unit": unit, "method": method})
    return found


def ingest_voice_report(astronaut_id: int, mission_id: int, transcript: str) -> dict:
    voice_log_id = voice_model.create_voice_log(astronaut_id, mission_id, transcript)
    parsed = parse_transcript(transcript)
    now_iso = datetime.now(timezone.utc).isoformat()
    source_id = catalog.get_data_source_id("VOICE_INPUT")

    created_observation_ids = []
    for item in parsed:
        indicator_id = catalog.get_indicator_id(item["indicator_code"])
        if indicator_id is None:
            continue
        obs_id = obs_model.record_observation(
            indicator_id=indicator_id, mission_id=mission_id, data_source_id=source_id,
            data_origin="REAL", recorded_at=now_iso, unit=item["unit"],
            measurement_method=item["method"], astronaut_id=astronaut_id,
            value_numeric=item["value"], voice_log_id=voice_log_id,
            notes="Generado por recolección de voz; verificar si requiere confirmación manual.",
        )
        created_observation_ids.append(obs_id)

    status = "PARSED" if parsed else "FAILED"
    confidence = min(1.0, 0.5 + 0.1 * len(parsed)) if parsed else 0.0
    voice_model.update_voice_log_parse(
        voice_log_id, parsed_payload={"detected": parsed}, confidence=confidence, status=status,
    )

    return {
        "voice_log_id": voice_log_id, "status": status, "detected": parsed,
        "observation_ids": created_observation_ids, "confidence": confidence,
    }
