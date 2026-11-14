"""
Servicio de monitoreo pasivo en tiempo real.

Es el "análisis pasivo" que pidió el equipo: el sistema observa sin que el
astronauta haga nada. Cada vez que llega una lectura nueva (de un sensor, o del
stream de telemetría simulada para la demo), este servicio:

  1. La guarda como observación (procedencia incluida).
  2. Reevalúa los hazards activos del tripulante contra su línea base.
  3. Recalcula el estado operacional de la nave (interlock).
  4. Si algo empeoró, abre una sesión de emergencia automática (PASSIVE_AUTO).
  5. Devuelve exactamente qué cambió, para que la interfaz reaccione.

En una nave real la lectura vendría del sensor; aquí viene del stream simulado.
El servicio no distingue: procesa una lectura venga de donde venga.
"""
from __future__ import annotations

from app.models import (
    catalog, observation as obs_model, mission as mission_model,
    ship as ship_model, emergency_session as es_model,
)
from app.services.emergency_service import evaluate_all_active_hazards
from app.services.interlock_service import recompute_ship_state, LEVEL_RANK

# Un nivel que, al aparecer de forma pasiva, dispara una sesión de emergencia
# automática (sin que el astronauta toque el botón).
AUTO_SESSION_FROM = "RED"


def ingest_reading(astronaut_id: int, indicator_code: str, value: float,
                   recorded_at: str, unit: str, measurement_method: str,
                   data_source_code: str = "CABIN_SENSOR",
                   data_origin: str = "REAL",
                   context_destination: str | None = None,
                   day_relative_to_launch: int | None = None,
                   mission_phase_id: int | None = None) -> dict:
    """Procesa una lectura nueva y devuelve el efecto completo en el sistema."""
    indicator_id = catalog.get_indicator_id(indicator_code)
    source_id = catalog.get_data_source_id(data_source_code)
    if indicator_id is None:
        return {"error": f"indicador desconocido: {indicator_code}"}
    if source_id is None:
        return {"error": f"fuente desconocida: {data_source_code}"}

    # 1. Guardar la observación
    obs_id = obs_model.record_observation(
        indicator_id=indicator_id, mission_id=_mission_of(astronaut_id),
        data_source_id=source_id, data_origin=data_origin, recorded_at=recorded_at,
        unit=unit, measurement_method=measurement_method, astronaut_id=astronaut_id,
        mission_phase_id=mission_phase_id, value_numeric=value,
        day_relative_to_launch=day_relative_to_launch)

    mission_id = _mission_of(astronaut_id)

    # 2. Reevaluar hazards del tripulante
    evals = evaluate_all_active_hazards(astronaut_id, context_destination, persist=True)
    peor = max(evals, key=lambda e: LEVEL_RANK.get(e["alert_level"], 0)) if evals else None

    # 3. Recalcular estado de la nave
    estado_nave = recompute_ship_state(mission_id, context_destination, persist_alerts=False)

    # 4. Sesión de emergencia automática si el nivel es crítico
    auto_session_id = None
    if peor and LEVEL_RANK.get(peor["alert_level"], 0) >= LEVEL_RANK[AUTO_SESSION_FROM]:
        abierta = [s for s in es_model.list_sessions(astronaut_id=astronaut_id, status="OPEN")]
        if not abierta:
            auto_session_id = es_model.open_session(astronaut_id, mission_id, "PASSIVE_AUTO")
            es_model.update_session(auto_session_id, summary=(
                f"Sesión automática: {peor['hazard_code']} en nivel {peor['alert_level']}. "
                f"{peor['reason']}"))

    return {
        "observation_id": obs_id,
        "astronaut_id": astronaut_id,
        "worst_hazard": peor["hazard_code"] if peor else None,
        "worst_level": peor["alert_level"] if peor else "UNKNOWN",
        "reason": peor["reason"] if peor else None,
        "recommended_action": peor.get("recommended_action") if peor else None,
        "ship_state": estado_nave["state"],
        "ship_state_changed": estado_nave["changed"],
        "auto_emergency_session_id": auto_session_id,
    }


def _mission_of(astronaut_id: int) -> int:
    mid = mission_model.mission_id_of_astronaut(astronaut_id)
    if mid is None:
        raise ValueError(f"astronauta {astronaut_id} sin misión")
    return mid


def replay_stream(readings: list[dict], context_destination: str | None = None) -> list[dict]:
    """Procesa una secuencia de lecturas en orden (para demo de 'tiempo real').

    Cada elemento: {astronaut_id, indicator_code, value, recorded_at, unit,
    measurement_method, ...}. Devuelve el efecto de cada una, resaltando los
    momentos en que la nave cambió de estado.
    """
    out = []
    for r in readings:
        res = ingest_reading(context_destination=context_destination, **r)
        out.append(res)
    return out
