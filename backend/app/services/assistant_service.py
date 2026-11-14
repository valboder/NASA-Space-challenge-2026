"""
Asistente de emergencia (modo activo: botón + voz).

Esta es la "IA que dice qué hacer" — y es deliberadamente BASADA EN PROTOCOLOS,
no un LLM generativo. Motivos (ver docs/VALIDACION.md y la decisión del equipo):

  - Debe funcionar OFFLINE dentro de la nave (el enlace a Tierra tarda hasta
    20 min). Un LLM conversacional offline es pesado e inviable en una laptop.
  - Nunca debe INVENTAR instrucciones médicas. Cada paso que da es trazable a
    una regla que un médico puede revisar antes del vuelo.

Qué hace la "inteligencia" aquí: combinar tres cosas que ninguna por sí sola
alcanza —el contexto pasivo (lo que el sistema ya mide del tripulante), lo que
el astronauta reporta por voz, y qué mediciones faltan— para dar: pasos
inmediatos, qué medir a continuación, y la acción según protocolo.

El flujo lo orquesta handle_emergency(): recibe el transcript (ya convertido de
voz a texto), detecta síntomas y valores, cruza con la evaluación pasiva, y
devuelve una guía estructurada.
"""
from __future__ import annotations

import re

from app.models import catalog, observation as obs_model, emergency_session as es_model
from app.services.voice_service import parse_transcript
from app.services.emergency_service import evaluate_astronaut_hazard
from app.ml.personal_baseline import evaluate_indicator

# ---------------------------------------------------------------------------
# Adaptación por entorno (lo que pide explícitamente el video del brief:
# "adapt to different environments — spacecraft, space station, lunar
# surface base"). No inventamos fisiología nueva por entorno: lo que SÍ
# cambia de forma verificable entre entornos y afecta la respuesta de
# emergencia es (a) el retraso de comunicación con la Tierra, que decide si
# "contactar a la Tierra" significa pedir ayuda en vivo o actuar solo con el
# protocolo mientras se envía el aviso, y (b) el nivel de gravedad, que
# cambia cómo se puede acomodar o reanimar a una persona (en microgravedad
# no se la puede "recostar": hay que sujetarla). Esto queda documentado aquí
# mismo para que sea auditable, igual que el resto del sistema.
# ---------------------------------------------------------------------------
ENVIRONMENT_PROFILES: dict[str, dict] = {
    "LEO": {
        "label": "Órbita baja terrestre",
        "gravity": "microgravedad",
        "comm_delay": "near_real_time",
        "comm_note": "El retraso con el control de misión es de segundos. "
                      "Contactar a la Tierra significa pedir ayuda en vivo, casi de inmediato.",
        "restrain_note": "En microgravedad no se puede recostar a una persona: hay que "
                          "SUJETARLA contra una superficie o restricción (correa, pared) "
                          "para que no quede flotando, antes de evaluarla o hacer RCP.",
    },
    "LUNAR_SURFACE": {
        "label": "Base en superficie lunar",
        "gravity": "gravedad parcial (~1/6 g)",
        "comm_delay": "short",
        "comm_note": "El retraso con la Tierra es de 1 a 3 segundos: alcanza para pedir "
                      "guía en vivo, aunque con una conversación algo más lenta que en órbita.",
        "restrain_note": "Con gravedad parcial la persona sí puede recostarse, pero los "
                          "movimientos y objetos sueltos flotan más de lo habitual: "
                          "verifica que quede realmente apoyada antes de dejarla.",
        "shelter_note": "Si hay un refugio presurizado o módulo de hábitat separado, "
                         "trasladar ahí a la persona antes de evaluarla con calma.",
    },
    "MARS_TRANSIT": {
        "label": "Tránsito a Marte",
        "gravity": "microgravedad",
        "comm_delay": "long",
        "comm_note": "El retraso con la Tierra puede llegar a ~20 minutos por tramo "
                      "(40 min ida y vuelta). 'Contactar a la Tierra' aquí NO significa "
                      "esperar instrucciones: envía el aviso y actúa de inmediato con los "
                      "pasos de este protocolo; la respuesta de la Tierra llegará después.",
        "restrain_note": "En microgravedad no se puede recostar a una persona: hay que "
                          "SUJETARLA contra una superficie o restricción (correa, pared) "
                          "para que no quede flotando, antes de evaluarla o hacer RCP.",
    },
    "MARS_SURFACE": {
        "label": "Superficie de Marte",
        "gravity": "gravedad parcial (~1/3 g)",
        "comm_delay": "long",
        "comm_note": "El retraso con la Tierra puede llegar a ~20 minutos por tramo. "
                      "'Contactar a la Tierra' significa enviar el aviso ahora y seguir el "
                      "protocolo sin esperar respuesta inmediata.",
        "restrain_note": "Con gravedad parcial la persona puede recostarse de lado con "
                          "normalidad; de todas formas verifica que quede estable.",
        "shelter_note": "Si hay un hábitat o refugio presurizado cercano, traslada ahí a "
                         "la persona antes de continuar la evaluación.",
    },
    "DEEP_SPACE": {
        "label": "Espacio profundo / tránsito largo",
        "gravity": "microgravedad",
        "comm_delay": "very_long",
        "comm_note": "El retraso con la Tierra puede superar los 20 minutos o depender de "
                      "un relevo. Trata cada emergencia como si no hubiera ayuda externa "
                      "disponible a tiempo: envía el aviso, pero actúa ya con el protocolo.",
        "restrain_note": "En microgravedad no se puede recostar a una persona: hay que "
                          "SUJETARLA contra una superficie o restricción (correa, pared) "
                          "para que no quede flotando, antes de evaluarla o hacer RCP.",
    },
}

MICROGRAVITY_DESTINATIONS = {"LEO", "MARS_TRANSIT", "DEEP_SPACE"}


def _adapt_step_text(step: str, destination: str | None) -> str:
    """Reescribe un paso puntual cuando el entorno cambia cómo se ejecuta.

    Por ahora el único caso con texto distinto es "recuéstala de lado", que no
    tiene sentido en microgravedad. El resto de los pasos (medir, avisar,
    hidratarse) no cambian por entorno, así que se dejan igual.
    """
    if destination in MICROGRAVITY_DESTINATIONS and "recuéstala de lado" in step:
        return ENVIRONMENT_PROFILES[destination]["restrain_note"]
    return step


def environment_context(destination: str | None) -> dict:
    """Resumen del entorno para mostrar junto con la guía de emergencia."""
    perfil = ENVIRONMENT_PROFILES.get(destination or "LEO", ENVIRONMENT_PROFILES["LEO"])
    return {
        "destination": destination or "LEO (asumido, no especificado)",
        "label": perfil["label"],
        "gravity": perfil["gravity"],
        "comm_delay": perfil["comm_delay"],
        "comm_note": perfil["comm_note"],
        "shelter_note": perfil.get("shelter_note"),
    }

# Léxico de síntomas → hazard implicado, urgencia, qué medir y pasos inmediatos.
# Es el conocimiento clínico codificado, no generado. Ampliable por fila.
SYMPTOM_LEXICON: list[dict] = [
    {
        # Escenario canónico del brief: "dolor fuerte en el pecho y colapsa".
        # Máxima urgencia. Puede que quien reporta esté evaluando a OTRO tripulante.
        "patterns": [r"dolor.{0,15}pecho", r"dolor de pecho", r"me duele el pecho",
                     r"se desmay", r"desmay", r"colaps", r"inconsciente", r"no responde",
                     r"perdió el conocimiento", r"perdio el conocimiento"],
        "hazard": "GRAVITY", "urgency": "ALTA", "min_action": "CONTACT_EARTH",
        "assessing_other_possible": True,
        "measure": ["HEART_RATE", "SPO2", "SKIN_TEMP"],
        "steps": ["Si la persona no responde: verifica si respira y tiene pulso.",
                  "Si respira, recuéstala de lado y no la dejes sola.",
                  "Mídele el pulso y la SpO2 cuanto antes.",
                  "Avisa a toda la tripulación y prepara contacto con la Tierra de inmediato.",
                  "Si no respira o no tiene pulso, inicia RCP si estás entrenado."],
    },
    {
        "patterns": [r"no puedo respirar", r"falta.{0,8}aire", r"me ahog", r"\bahog", r"no.{0,6}respir"],
        "hazard": "ENCLOSED_ENV", "urgency": "ALTA", "min_action": "CONTACT_EARTH",
        "measure": ["SPO2", "HEART_RATE", "CABIN_CO2"],
        "steps": ["Deja de hacer esfuerzo y siéntate.",
                  "Colócate la máscara de oxígeno si está a tu alcance.",
                  "Mide tu SpO2 ahora y repórtala."],
    },
    {
        "patterns": [r"\bmareo\b", r"maread", r"me voy a desmayar", r"vértigo", r"vertigo",
                     r"vision borrosa", r"visión borrosa"],
        "hazard": "ENCLOSED_ENV", "urgency": "MEDIA", "min_action": "NOTIFY_CREW",
        "measure": ["SPO2", "HEART_RATE", "HYDRATION_INDEX", "CABIN_CO2"],
        "steps": ["Siéntate o recuéstate para no caer.",
                  "Mide SpO2 y pulso.",
                  "Toma agua si la deshidratación es posible."],
    },
    {
        "patterns": [r"palpitacion", r"palpitación", r"corazón acelerado", r"se me acelera el corazón",
                     r"taquicardia"],
        "hazard": "GRAVITY", "urgency": "ALTA", "min_action": "NOTIFY_CREW",
        "measure": ["HEART_RATE", "SPO2"],
        "steps": ["Detente y respira lento.",
                  "Mide tu pulso durante un minuto completo.",
                  "Si supera 150 o es irregular, avisa a la tripulación de inmediato."],
    },
    {
        "patterns": [r"dolor de cabeza", r"me duele la cabeza", r"cefalea"],
        "hazard": "ENCLOSED_ENV", "urgency": "MEDIA", "min_action": "NOTIFY_CREW",
        "measure": ["CABIN_CO2", "HYDRATION_INDEX"],
        "steps": ["Revisa el CO2 de la cabina; si está alto, ve a una zona ventilada.",
                  "Hidrátate.",
                  "Si el dolor es intenso o súbito, avisa a la tripulación."],
    },
    {
        "patterns": [r"no puedo dormir", r"insomnio", r"duermo mal", r"cansad", r"agotad"],
        "hazard": "ISOLATION", "urgency": "BAJA", "min_action": "SELF_RESOLVE",
        "measure": ["SLEEP_EFFICIENCY", "SLEEP_LATENCY_MIN", "DAILY_STRESS_SCORE"],
        "steps": ["Registra cómo dormiste las últimas noches.",
                  "Reduce pantallas antes de dormir y mantén un horario fijo.",
                  "Si persiste varios días, avisa para apoyo de la tripulación."],
    },
    {
        "patterns": [r"ansiedad", r"ansios", r"estresad", r"estrés", r"estres", r"triste",
                     r"\bsolo\b", r"deprimid"],
        "hazard": "ISOLATION", "urgency": "MEDIA", "min_action": "NOTIFY_CREW",
        "measure": ["DAILY_STRESS_SCORE", "STAI_ANXIETY"],
        "steps": ["Haz una pausa y una respiración guiada.",
                  "Contacta a un compañero de tripulación (apoyo entre pares).",
                  "Registra tu nivel de estrés para seguimiento."],
    },
    {
        "patterns": [r"hueso", r"me duele.*espalda", r"calambre"],
        "hazard": "GRAVITY", "urgency": "BAJA", "min_action": "SELF_RESOLVE",
        "measure": ["URINARY_CALCIUM_MG24H", "SERUM_CALCIUM"],
        "steps": ["Completa tu sesión de ejercicio de resistencia de hoy.",
                  "Registra ingesta de calcio e hidratación.",
                  "Programa una medición de calcio."],
    },
]


def detect_symptoms(transcript: str) -> list[dict]:
    t = transcript.lower()
    found = []
    for entry in SYMPTOM_LEXICON:
        if any(re.search(p, t) for p in entry["patterns"]):
            found.append(entry)
    return found


def _stale_or_missing(astronaut_id: int, indicator_codes: list[str]) -> list[str]:
    """De una lista de indicadores, cuáles no tienen dato o no son evaluables ahora."""
    faltantes = []
    for code in indicator_codes:
        series = obs_model.series_for_indicator(astronaut_id, code)
        if not series:
            faltantes.append(code)
    return faltantes


def handle_emergency(astronaut_id: int, mission_id: int, transcript: str,
                     context_destination: str | None = None,
                     session_id: int | None = None, voice_log_id: int | None = None) -> dict:
    """Orquesta la respuesta del asistente a un reporte por voz."""
    if session_id is None:
        session_id = es_model.open_session(astronaut_id, mission_id, "PANIC_BUTTON", voice_log_id)

    # 1. Qué reportó el astronauta: valores numéricos + síntomas cualitativos
    valores = parse_transcript(transcript)
    sintomas = detect_symptoms(transcript)

    # 2. Hazards implicados por lo que dijo
    hazards_implicados = {s["hazard"] for s in sintomas}
    # siempre incluye los hazards activos para no perder el contexto pasivo
    activos = {h["code"] for h in catalog.list_hazards(active_only=True)}

    # 3. Evaluación pasiva de cada hazard implicado que esté activo
    evaluaciones = []
    for hz in sorted(hazards_implicados & activos):
        evaluaciones.append(evaluate_astronaut_hazard(astronaut_id, hz, context_destination, persist=True))

    # 4. Construir la guía: pasos + qué medir + acción
    pasos: list[str] = []
    medir: list[dict] = []
    urgencia_max = "BAJA"
    orden_urgencia = {"BAJA": 0, "MEDIA": 1, "ALTA": 2}
    for s in sintomas:
        pasos.extend(_adapt_step_text(p, context_destination) for p in s["steps"])
        if orden_urgencia[s["urgency"]] > orden_urgencia[urgencia_max]:
            urgencia_max = s["urgency"]
        for code in _stale_or_missing(astronaut_id, s["measure"]):
            ind = catalog.get_indicator(code) or {}
            # Incluye CÓMO medir y POR QUÉ importa (requisito del brief):
            medir.append({
                "indicator_code": code, "name": ind.get("name", code),
                "unit": ind.get("default_unit"), "method": ind.get("default_method"),
                "how_to_measure": ind.get("how_to_measure"),
                "why_it_matters": ind.get("why_it_matters"),
            })

    # 5. Acción recomendada: la MÁS SEVERA entre (a) las evaluaciones pasivas y
    #    (b) el piso de acción de cada síntoma reportado. Así un síntoma grave
    #    nunca queda sin acción aunque el sistema pasivo todavía no lo vea, y un
    #    hazard que el sistema ya ve en rojo tampoco se minimiza por lo que diga
    #    el astronauta. Es el corazón de "combinar pasivo + activo".
    rank = {"CONTACT_EARTH": 3, "NOTIFY_CREW": 2, "SELF_RESOLVE": 1, None: 0}
    accion = None
    nivel_peor = "GREEN"
    for e in evaluaciones:
        if rank.get(e.get("recommended_action"), 0) > rank.get(accion, 0):
            accion = e.get("recommended_action")
            nivel_peor = e["alert_level"]
    for s in sintomas:
        if rank.get(s.get("min_action"), 0) > rank.get(accion, 0):
            accion = s["min_action"]

    # deduplicar pasos preservando orden
    pasos_unicos = list(dict.fromkeys(pasos))
    medir_unicos = list({m["indicator_code"]: m for m in medir}.values())

    entorno = environment_context(context_destination)

    if not sintomas and not valores:
        mensaje = ("No identifiqué síntomas ni valores en tu reporte. ¿Puedes decir qué sientes "
                   "o qué medición tienes? Por ejemplo: 'me falta el aire' o 'mi pulso está en 120'.")
    else:
        mensaje = f"Entendido. Urgencia estimada: {urgencia_max}."
        if accion == "CONTACT_EARTH":
            mensaje += " " + entorno["comm_note"]

    es_model.update_session(session_id, status="GUIDANCE_GIVEN",
                            summary=f"Síntomas: {[','.join(p for e in sintomas for p in e['patterns'][:1])]}; "
                                    f"acción: {accion}", voice_log_id=voice_log_id)

    return {
        "session_id": session_id,
        "astronaut_id": astronaut_id,
        "transcript": transcript,
        "detected_values": valores,
        "detected_symptoms": [s["patterns"][0] for s in sintomas],
        "implicated_hazards": sorted(hazards_implicados),
        "passive_context": [{"hazard": e["hazard_code"], "level": e["alert_level"],
                              "reason": e["reason"]} for e in evaluaciones],
        "urgency": urgencia_max,
        "message": mensaje,
        "immediate_steps": pasos_unicos,
        "measurements_to_take": medir_unicos,
        "recommended_action": accion,
        "worst_passive_level": nivel_peor,
        "environment": entorno,
    }
