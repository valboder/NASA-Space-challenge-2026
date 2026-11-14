"""
Seed de actividades de la nave y su estado mínimo permitido.

min_allowed_state = el estado MÁS restrictivo en que la actividad sigue permitida:
  - NORMAL      -> solo con la nave en NORMAL (se bloquea apenas hay anomalía)
  - RESTRICTED  -> permitida también en RESTRICTED (solo se bloquea en LOCKED)
  - LOCKED      -> permitida siempre, incluso bloqueada (soporte vital, comunicación)

La lógica: cuanto más riesgosa o prescindible la actividad, más fácil se bloquea;
el soporte vital y la comunicación nunca se bloquean.

Ejecutar: python -m data.seed.seed_ship   (desde backend/)
"""
from __future__ import annotations

from app.core.db import init_db
from app.models import ship as ship_model

ACTIVITIES = [
    # code, nombre, categoría, min_allowed_state, racional
    ("EVA", "Actividad extravehicular (caminata espacial)", "alto_riesgo", "NORMAL",
     "La más riesgosa: se bloquea ante cualquier anomalía de salud del tripulante."),
    ("HEAVY_EXERCISE", "Ejercicio de alta intensidad", "fisico", "NORMAL",
     "Carga cardiovascular; se suspende si hay signos fuera de rango."),
    ("EXPERIMENT_HAZARDOUS", "Experimento con materiales peligrosos", "alto_riesgo", "NORMAL",
     "Requiere plena capacidad cognitiva y motora."),
    ("PILOTING_MANEUVER", "Maniobra de pilotaje no automática", "operacional", "NORMAL",
     "Decisiones críticas: exige estado normal del operador."),
    ("MAINTENANCE_ROUTINE", "Mantenimiento rutinario", "operacional", "RESTRICTED",
     "Se permite en estado restringido, se bloquea solo en bloqueo total."),
    ("SCIENCE_ROUTINE", "Tareas científicas de rutina", "ciencia", "RESTRICTED",
     "No esenciales; se permiten salvo bloqueo total."),
    ("MEAL_PREP", "Preparación de alimentos", "cotidiano", "RESTRICTED",
     "Cotidiano; se mantiene salvo bloqueo total."),
    ("LIFE_SUPPORT", "Soporte vital", "critico", "LOCKED",
     "Nunca se bloquea: es lo que mantiene con vida a la tripulación."),
    ("COMMUNICATION", "Comunicación con la tripulación y la Tierra", "critico", "LOCKED",
     "Nunca se bloquea: es como se pide y recibe ayuda."),
    ("MEDICAL_RESPONSE", "Respuesta médica / primeros auxilios", "critico", "LOCKED",
     "Nunca se bloquea: es la acción que resuelve la emergencia."),
    ("REST", "Descanso / sueño", "cotidiano", "LOCKED",
     "Siempre permitido: suele ser parte de la recuperación."),
]


def run():
    init_db(reset=False)
    for code, name, cat, state, rationale in ACTIVITIES:
        ship_model.upsert_activity(code, name, cat, state, rationale)
    print(f"[Nave] {len(ACTIVITIES)} actividades sembradas con su estado mínimo permitido.")


if __name__ == "__main__":
    run()
