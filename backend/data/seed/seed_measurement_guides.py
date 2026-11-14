"""
Guías de medición: cómo tomar cada medición y por qué importa.

Responde al requisito explícito del brief del reto (video oficial):
  "Los astronautas no son médicos. Tu herramienta debe explicar cómo tomar cada
   medición, por qué importa, y qué hacer cuando un valor no se ve normal."

El "qué hacer cuando no se ve normal" ya lo da el motor de protocolos; aquí
cubrimos el "cómo" y el "por qué", en lenguaje para alguien que no es médico.

typical_recheck_days alimenta los recordatorios de medición ("recuérdale a la
tripulación tomar mediciones", también del brief).

Ejecutar: python -m data.seed.seed_measurement_guides   (desde backend/)
"""
from __future__ import annotations

from app.core.db import init_db
from app.models import catalog

GUIDES = {
    "SPO2": (
        "Colócate el oxímetro en la punta del dedo, con la uña hacia arriba. Quédate quieto "
        "y espera a que el número se estabilice (unos 10-15 segundos). Anota el porcentaje.",
        "Mide cuánto oxígeno lleva tu sangre. Por debajo de 90% el cuerpo no está recibiendo "
        "suficiente oxígeno; es una de las señales más urgentes y fáciles de medir.",
        1),
    "HEART_RATE": (
        "Con el oxímetro puesto aparece junto al SpO2. Sin equipo: pon dos dedos en el cuello o "
        "la muñeca, cuenta los latidos durante 60 segundos completos (no 15 x 4, en el espacio "
        "el ritmo puede ser irregular).",
        "El pulso muy alto, muy bajo o irregular puede indicar problemas del corazón, falta de "
        "oxígeno o deshidratación. Es el signo vital más rápido de revisar.",
        1),
    "SKIN_TEMP": (
        "Mide en el oído o la frente con el termómetro, siguiendo la marca del equipo. No midas "
        "justo después de ejercicio.",
        "La fiebre indica infección; la temperatura muy baja, otros problemas. En un hábitat "
        "cerrado una infección se contagia rápido a toda la tripulación.",
        1),
    "URINARY_CALCIUM_MG24H": (
        "Recolecta TODA la orina de 24 horas en el recipiente marcado (desde la primera de la "
        "mañana del día 1 hasta la primera del día 2). El equipo analiza el total.",
        "En microgravedad los huesos pierden calcio y lo eliminan por la orina. Es el aviso "
        "temprano de pérdida ósea, el riesgo lento más importante en misiones largas.",
        30),
    "SERUM_CALCIUM": (
        "Requiere una muestra de sangre procesada por el equipo del panel metabólico. No es una "
        "medición que hagas tú solo; el sistema te indica cuándo programarla.",
        "Confirma el estado del calcio en el cuerpo. Fuera de rango puede afectar el corazón y "
        "los músculos, no solo los huesos.",
        30),
    "HYDRATION_INDEX": (
        "Usa la tira o sensor del baño en una muestra de orina. Un color más oscuro o densidad "
        "alta indica deshidratación.",
        "La deshidratación es común en el espacio y empeora casi todo lo demás: pulso, mareo, "
        "rendimiento. Es fácil de corregir si se detecta a tiempo.",
        3),
    "CABIN_CO2": (
        "Es una lectura automática del sensor de cabina; no la tomas tú. Revísala en la pantalla "
        "si sientes dolor de cabeza o te cuesta concentrarte.",
        "El CO2 alto en la cabina causa dolor de cabeza, fatiga y confusión. OJO: mide el aire "
        "de la cabina, NO el CO2 de tu sangre.",
        None),
    "SLEEP_EFFICIENCY": (
        "La registra el saco de dormir / actigrafía automáticamente cada noche. También puedes "
        "anotar a qué hora te acostaste y cuánto tardaste en dormir.",
        "El sueño se deteriora en aislamiento prolongado y afecta el ánimo, la concentración y "
        "la toma de decisiones. Su caída sostenida es una señal temprana del hazard de aislamiento.",
        1),
    "DAILY_STRESS_SCORE": (
        "Es un autorreporte: califica tu nivel de estrés de 0 a 100 cuando el sistema te lo pida "
        "o cuando lo sientas necesario.",
        "El estrés acumulado en confinamiento afecta la salud y la convivencia. Registrarlo "
        "permite pedir apoyo antes de que se vuelva un problema serio.",
        1),
    "STAI_ANXIETY": (
        "Responde el cuestionario corto de ansiedad cuando el sistema lo sugiera. Son pocas "
        "preguntas, toma un par de minutos.",
        "Mide ansiedad de forma estructurada, no solo 'cómo te sientes'. Permite seguir la "
        "tendencia y detectar un deterioro psicológico a tiempo.",
        7),
}


def run():
    init_db(reset=False)
    n = 0
    for code, (how, why, recheck) in GUIDES.items():
        if catalog.get_indicator_id(code) is not None:
            catalog.set_measurement_guide(code, how, why, recheck)
            n += 1
    print(f"[Guías de medición] {n} indicadores con 'cómo medir / por qué importa'.")


if __name__ == "__main__":
    run()
