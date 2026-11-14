"""
Recordatorios de medición: "recuérdale a la tripulación tomar mediciones"
(requisito del brief del reto).

Lógica simple y honesta: para cada indicador que un tripulante debería medir
periódicamente (typical_recheck_days en el catálogo), compara la fecha de su
última medición con hoy. Si pasó el intervalo —o nunca midió—, lo lista como
pendiente, con la guía de cómo medirlo y por qué.

No usa fechas reales de reloj para los datos de estudio (que vienen con días
relativos al lanzamiento), así que opera en días de misión: recibe el día de
misión actual y compara contra el day_relative_to_launch de la última medición.
"""
from __future__ import annotations

from app.models import catalog, observation as obs_model, mission as mission_model


def due_measurements(astronaut_id: int, current_mission_day: int = 0) -> list[dict]:
    """Indicadores que este tripulante debería medir ya.

    current_mission_day: día de misión actual (p.ej. +120). Para indicadores sin
    historial se marcan como pendientes desde el inicio.
    """
    pendientes = []
    for ind in catalog.list_indicators():
        recheck = ind.get("typical_recheck_days")
        if not recheck:
            continue  # no es un indicador con recordatorio periódico
        series = obs_model.series_for_indicator(astronaut_id, ind["code"])
        ultimos = [r for r in series if r.get("day_relative_to_launch") is not None]
        if not ultimos:
            dias_desde = None
            vencido = True
            razon = "Nunca se ha medido en esta misión."
        else:
            ultimo_dia = max(r["day_relative_to_launch"] for r in ultimos)
            dias_desde = current_mission_day - ultimo_dia
            vencido = dias_desde >= recheck
            razon = (f"Última medición hace {dias_desde} días (se recomienda cada {recheck})."
                     if vencido else "")
        if vencido:
            pendientes.append({
                "indicator_code": ind["code"],
                "name": ind["name"],
                "unit": ind["default_unit"],
                "recommended_every_days": recheck,
                "days_since_last": dias_desde,
                "reason": razon,
                "how_to_measure": ind.get("how_to_measure"),
                "why_it_matters": ind.get("why_it_matters"),
                "requires_equipment": bool(ind.get("requires_equipment")),
            })
    # los más urgentes primero: los que nunca se midieron, luego por intervalo corto
    pendientes.sort(key=lambda p: (p["days_since_last"] is not None, p["recommended_every_days"]))
    return pendientes


def crew_due_measurements(mission_id: int, current_mission_day: int = 0) -> list[dict]:
    salida = []
    for a in mission_model.list_astronauts(mission_id):
        pend = due_measurements(a["astronaut_id"], current_mission_day)
        salida.append({"astronaut_id": a["astronaut_id"], "call_sign": a["call_sign"],
                       "due_count": len(pend), "due": pend})
    return salida
