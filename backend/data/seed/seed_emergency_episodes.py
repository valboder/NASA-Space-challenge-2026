"""
Generador de episodios de emergencia SIMULADOS, anclados a los datos reales.

No existen registros públicos de emergencias médicas reales en vuelo, así que
—como pidió el equipo— se construyen escenarios sintéticos "impuestos sobre los
reales": cada tripulante de demostración recibe una LÍNEA BASE muestreada de las
distribuciones reales de la NASA (calcio sérico real: media 9.73, sd 0.31), y
luego se le inyecta una trayectoria de deterioro fisiológicamente plausible.

TODO lo que genera este script queda marcado data_origin='SIMULATED' en la base
de datos. No se mezcla con las mediciones reales ni se presenta como tal. Sirve
para una sola cosa: poder demostrar el flujo de alerta → bloqueo de la nave →
asistencia, que con los datos reales (que solo llegan a amarillo) no se puede
mostrar.

Escenario principal: el del propio pitch — "Día 340 rumbo a Marte, el calcio en
orina sube". Lo modelamos sobre calcio SÉRICO (que es el que tiene rango de
referencia cargado) subiendo por desmineralización ósea hasta salir de rango.

Ejecutar: python -m data.seed.seed_emergency_episodes   (desde backend/)
"""
from __future__ import annotations

import random

from app.core.db import init_db
from app.models import catalog, mission as mission_model, observation as obs_model

RNG = random.Random(2026)

DEMO_MISSION = ("DEMO-MARS-500", "Misión de demostración a Marte (día 500)", "MARS_SURFACE")


def _astronaut(call_sign: str, mission_id: int, name: str) -> int:
    return mission_model.create_astronaut(call_sign=call_sign, mission_id=mission_id, display_name=name)


def _seed_baseline(astro_id, mission_id, phase_id, indicator_code, source_id,
                   media, sd, unit, method, n=6):
    """Línea base pre-vuelo muestreada de la distribución real. DERIVED: viene de
    estadísticas reales, no es una medición real ni puramente inventada."""
    ids = []
    for i in range(n):
        val = round(RNG.gauss(media, sd), 2)
        ids.append(obs_model.record_observation(
            indicator_id=catalog.get_indicator_id(indicator_code), mission_id=mission_id,
            data_source_id=source_id, data_origin="DERIVED",
            recorded_at=f"{-(n - i) * 7}d_relative_to_launch", unit=unit,
            measurement_method=method, astronaut_id=astro_id, mission_phase_id=phase_id,
            value_numeric=val, day_relative_to_launch=-(n - i) * 7,
            notes="Línea base muestreada de la distribución real NASA (DERIVED, no es medición real)."))
    return ids


def _seed_trajectory(astro_id, mission_id, phase_id, indicator_code, source_id,
                     start, end, n, unit, method, note):
    """Trayectoria de deterioro lineal con ruido. SIMULATED."""
    ids = []
    for i in range(n):
        frac = i / (n - 1)
        val = round(start + (end - start) * frac + RNG.gauss(0, (end - start) * 0.04), 2)
        day = int(frac * 300) + 20
        ids.append(obs_model.record_observation(
            indicator_id=catalog.get_indicator_id(indicator_code), mission_id=mission_id,
            data_source_id=source_id, data_origin="SIMULATED",
            recorded_at=f"+{day}d_relative_to_launch", unit=unit, measurement_method=method,
            astronaut_id=astro_id, mission_phase_id=phase_id, value_numeric=val,
            day_relative_to_launch=day, notes=note))
    return ids


def run():
    init_db(reset=False)
    mission_id = mission_model.create_mission(*DEMO_MISSION, launch_date="2026-01-01",
                                               expected_duration_d=500)
    pre = mission_model.ensure_phase(mission_id, "PRE_FLIGHT")
    inflight = mission_model.ensure_phase(mission_id, "IN_FLIGHT")
    src_sim = catalog.get_data_source_id("SIMULATION_ENGINE")

    # ── Tripulante 1: episodio de pérdida ósea (calcio sube hasta fuera de rango) → RED ──
    a1 = _astronaut("MARS-01", mission_id, "Comandante (demo) — episodio de pérdida ósea")
    _seed_baseline(a1, mission_id, pre, "SERUM_CALCIUM", src_sim, 9.73, 0.31, "mg_dL",
                   "Panel metabólico (demo, línea base derivada de datos reales)")
    _seed_trajectory(a1, mission_id, inflight, "SERUM_CALCIUM", src_sim,
                     start=9.8, end=11.6, n=12, unit="mg_dL",
                     method="Panel metabólico (demo)",
                     note="Episodio SIMULADO: calcio sérico sube por desmineralización ósea "
                          "(escenario del pitch 'Día 340 rumbo a Marte'). Cruza el rango 8.6-10.4.")

    # ── Tripulante 2: deterioro de sueño (aislamiento) → tendencia WARN ──
    a2 = _astronaut("MARS-02", mission_id, "Ingeniera de vuelo (demo) — deterioro de sueño")
    _seed_baseline(a2, mission_id, pre, "SLEEP_EFFICIENCY", src_sim, 93.0, 1.5, "pct",
                   "Actigrafía (demo, línea base derivada)")
    _seed_trajectory(a2, mission_id, inflight, "SLEEP_EFFICIENCY", src_sim,
                     start=92.0, end=81.0, n=20, unit="pct",
                     method="Actigrafía (demo)",
                     note="Episodio SIMULADO: eficiencia de sueño cae por aislamiento prolongado.")

    # ── Tripulante 3: sano, se mantiene en verde (control del demo) ──
    a3 = _astronaut("MARS-03", mission_id, "Especialista de misión (demo) — control sano")
    _seed_baseline(a3, mission_id, pre, "SERUM_CALCIUM", src_sim, 9.73, 0.31, "mg_dL",
                   "Panel metabólico (demo, línea base derivada)")
    _seed_trajectory(a3, mission_id, inflight, "SERUM_CALCIUM", src_sim,
                     start=9.7, end=9.9, n=10, unit="mg_dL",
                     method="Panel metabólico (demo)",
                     note="Control SIMULADO: calcio estable dentro de rango.")

    print(f"[Emergencias demo] Misión {DEMO_MISSION[0]} con 3 tripulantes "
          f"(1 pérdida ósea → RED, 1 deterioro de sueño → WARN, 1 control sano).")


if __name__ == "__main__":
    run()
