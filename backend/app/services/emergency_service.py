"""
Servicio de emergencia: convierte la evaluación de salud en una alerta con una
instrucción concreta, usando el árbol de protocolos de la base de datos.

Diseño en dos capas, deliberado:

  CAPA 1 - Detección (app/ml/personal_baseline.py)
      Línea base personal + rango de referencia NASA + tendencia intra-sujeto.
      Es la vía principal. No usa etiquetas inventadas por el equipo.

  CAPA 2 - Decisión (emergency_protocol, en la BD)
      Traduce el nivel de semáforo en una acción: resolver solo / avisar a la
      tripulación / contactar a la Tierra. Son reglas explícitas y auditables,
      no una predicción, porque una acción que puede soltar oxígeno de
      emergencia debe ser trazable a una regla que un médico pueda revisar.

El IsolationForest (app/ml/anomaly_detector.py) queda disponible para el caso
multivariado, pero NO es la vía por defecto: medimos que con los datos análogos
disponibles no separa el estado de reposo del basal (AUC ~0.5). Ver
docs/VALIDACION.md.
"""
from __future__ import annotations

from app.ml.personal_baseline import evaluate_hazard, evaluate_indicator
from app.models import anomaly as anomaly_model, catalog, observation as obs_model

# Calibración elegida: favorecer detección. Sin médico a bordo y con hasta 20
# minutos de retraso hacia la Tierra, perder una emergencia real cuesta más que
# una falsa alarma. Queda explícito aquí para que sea discutible, no implícito.
CALIBRACION = "favorecer_deteccion"


def _nivel_a_accion_por_defecto(nivel: str) -> str:
    return {"GREEN": "SELF_RESOLVE", "YELLOW": "NOTIFY_CREW",
            "ORANGE": "NOTIFY_CREW", "RED": "CONTACT_EARTH"}.get(nivel, "NOTIFY_CREW")


def evaluate_astronaut_hazard(astronaut_id: int, hazard_code: str,
                               context_destination: str | None = None,
                               persist: bool = True) -> dict:
    """Evalúa un hazard para un tripulante y, si corresponde, registra la alerta."""
    resultado = evaluate_hazard(astronaut_id, hazard_code, context_destination)
    nivel = resultado["alert_level"]

    if nivel == "UNKNOWN":
        return {**resultado, "recommended_action": None, "alert_id": None,
                "message": resultado["reason"], "calibration": CALIBRACION}

    protocolo = anomaly_model.find_protocol(hazard_code, nivel)
    if protocolo:
        accion = protocolo["recommended_action"]
        mensaje = f"{protocolo['instructions_text']}"
        condicion = protocolo["condition_description"]
    else:
        accion = _nivel_a_accion_por_defecto(nivel)
        mensaje = f"Nivel {nivel} en {hazard_code} sin protocolo específico cargado."
        condicion = None

    alert_id = None
    if persist and nivel != "GREEN":
        hazards = {h["code"]: h["hazard_id"] for h in catalog.list_hazards()}
        modelo = anomaly_model.latest_model_for_context_hazard(
            context_destination or "LEO", hazard_code)
        modelo_id = modelo["anomaly_model_id"] if modelo else anomaly_model.register_model(
            context_destination or "LEO",
            f"{context_destination or 'LEO'}_{hazard_code}_personal_baseline_v1",
            algorithm="personal_baseline")
        evento_id = anomaly_model.create_event(
            anomaly_model_id=modelo_id,
            anomaly_score=0.0,          # este detector no produce score de IsolationForest
            hazard_id=hazards.get(hazard_code), astronaut_id=astronaut_id)
        alert_id = anomaly_model.create_alert(evento_id, nivel, accion,
                                               f"{resultado['reason']} -> {mensaje}")

    return {
        **resultado,
        "recommended_action": accion,
        "protocol_condition": condicion,
        "instructions": mensaje,
        "alert_id": alert_id,
        "calibration": CALIBRACION,
        "detector": "personal_baseline",
    }


def evaluate_all_active_hazards(astronaut_id: int, context_destination: str | None = None,
                                 persist: bool = True) -> list[dict]:
    """Evalúa los hazards marcados como activos (hoy: distancia, aislamiento, gravedad)."""
    activos = catalog.list_hazards(active_only=True)
    return [evaluate_astronaut_hazard(astronaut_id, h["code"], context_destination, persist)
            for h in activos]


def crew_summary(mission_id: int, context_destination: str | None = None) -> list[dict]:
    """Resumen de toda la tripulación: una línea por tripulante con su peor nivel.

    Sin persistir alertas — es una vista de lectura para el panel.
    """
    from app.models import mission as mission_model
    rank = {"RED": 3, "ORANGE": 2, "YELLOW": 1, "GREEN": 0, "UNKNOWN": -1}
    salida = []
    for a in mission_model.list_astronauts(mission_id):
        evals = evaluate_all_active_hazards(a["astronaut_id"], context_destination, persist=False)
        peor = max(evals, key=lambda e: rank.get(e["alert_level"], -1)) if evals else None
        salida.append({
            "astronaut_id": a["astronaut_id"],
            "call_sign": a["call_sign"],
            "display_name": a["display_name"],
            "worst_level": peor["alert_level"] if peor else "UNKNOWN",
            "worst_hazard": peor["hazard_code"] if peor else None,
            "reason": peor["reason"] if peor else None,
            "recommended_action": peor.get("recommended_action") if peor else None,
        })
    return salida
