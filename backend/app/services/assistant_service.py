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

from datetime import datetime, timezone

from app.models import catalog, observation as obs_model, emergency_session as es_model
from app.models import mission as mission_model
from app.services.voice_service import parse_transcript
from app.services.emergency_service import evaluate_astronaut_hazard, evaluate_all_active_hazards
from app.ml.personal_baseline import evaluate_indicator

# P08: si el catálogo no define typical_recheck_days para un indicador, se usa
# esta ventana por defecto (conservadora: medio día) en lugar de tratar
# cualquier dato histórico, sin importar su edad, como vigente.
DEFAULT_RECHECK_DAYS = 0.5

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
        "fall_note": "En microgravedad no hay 'caída': sujétate a un asa o superficie fija "
                     "para no quedar flotando sin control mientras se te pasa el mareo.",
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
        "fall_note": "En microgravedad no hay 'caída': sujétate a un asa o superficie fija "
                     "para no quedar flotando sin control mientras se te pasa el mareo.",
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
        "fall_note": "En microgravedad no hay 'caída': sujétate a un asa o superficie fija "
                     "para no quedar flotando sin control mientras se te pasa el mareo.",
    },
}

MICROGRAVITY_DESTINATIONS = {"LEO", "MARS_TRANSIT", "DEEP_SPACE"}

# Pasos del léxico que no tienen sentido literal en microgravedad y necesitan
# reescritura, mapeados a la nota de ENVIRONMENT_PROFILES que los reemplaza.
# Antes solo se cubría "recuéstala de lado" (alguien asistiendo a OTRA
# persona, en tercera persona): "Siéntate o recuéstate para no caer" es el
# mismo problema físico (recostarse / no hay "caída" sin gravedad) pero
# dirigido a quien reporta el síntoma EN PRIMERA PERSONA, así que no podía
# reusar el mismo texto (está escrito para alguien haciendo RCP a otro) ni
# coincidir con el `in` original — se perdía en silencio.
_MICROGRAVITY_STEP_OVERRIDES = {
    "recuéstala de lado": "restrain_note",
    "para no caer": "fall_note",
}


def _adapt_step_text(step: str, destination: str | None) -> str:
    """Reescribe un paso puntual cuando el entorno cambia cómo se ejecuta.

    Los pasos de medir, avisar o hidratarse no cambian por entorno, así que
    se dejan igual; solo los que asumen gravedad (recostarse, "caerse") se
    reescriben en destinos de microgravedad.
    """
    if destination in MICROGRAVITY_DESTINATIONS:
        for fragmento, nota in _MICROGRAVITY_STEP_OVERRIDES.items():
            if fragmento in step:
                return ENVIRONMENT_PROFILES[destination][nota]
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


def _parse_created_at(value: str | None):
    if not value:
        return None
    try:
        # SQLite datetime('now') produce 'YYYY-MM-DD HH:MM:SS' en UTC.
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


def _stale_or_missing(astronaut_id: int, indicator_codes: list[str]) -> list[dict]:
    """Para cada indicador: si falta, está vigente o está vencido (P08).

    Antes esta función solo comprobaba existencia ('¿hay algún dato?'), así
    que una medición de hace semanas bastaba para no pedir una nueva. Ahora
    compara la antigüedad REAL de la última observación (su `created_at`,
    hora de escritura en la base — no `recorded_at`, que en varias fuentes
    NASA es texto como 'study_day_1' y no sirve como reloj) contra la ventana
    de revisión del indicador (`typical_recheck_days` del catálogo). No se usa
    `day_relative_to_launch`/`recorded_at` para esta decisión a propósito.
    """
    resultado = []
    ahora = datetime.now(timezone.utc)
    for code in indicator_codes:
        ultima = obs_model.latest_for_indicator(astronaut_id, code)
        if ultima is None:
            resultado.append({"indicator_code": code, "status": "MISSING",
                              "last_measured_at": None, "needs_measurement": True})
            continue
        ind = catalog.get_indicator(code) or {}
        ventana_dias = ind.get("typical_recheck_days") or DEFAULT_RECHECK_DAYS
        momento = _parse_created_at(ultima.get("created_at"))
        if momento is None:
            # No se puede establecer antigüedad real: no se asume vigente en silencio.
            resultado.append({"indicator_code": code, "status": "STALE",
                              "last_measured_at": ultima.get("created_at"), "needs_measurement": True,
                              "reason": "antigüedad no determinable"})
            continue
        edad_dias = (ahora - momento).total_seconds() / 86400
        if edad_dias > ventana_dias:
            resultado.append({"indicator_code": code, "status": "STALE",
                              "last_measured_at": ultima.get("created_at"), "needs_measurement": True,
                              "age_days": round(edad_dias, 2), "recheck_days": ventana_dias})
        else:
            resultado.append({"indicator_code": code, "status": "FRESH",
                              "last_measured_at": ultima.get("created_at"), "needs_measurement": False,
                              "age_days": round(edad_dias, 2), "recheck_days": ventana_dias})
    return resultado


def handle_emergency(astronaut_id: int, mission_id: int, transcript: str,
                     context_destination: str | None = None,
                     session_id: int | None = None, voice_log_id: int | None = None,
                     operator_id: int | None = None) -> dict:
    """Orquesta la respuesta del asistente a un reporte por voz."""
    if session_id is None:
        session_id = es_model.open_session(astronaut_id, mission_id, "PANIC_BUTTON", voice_log_id)

    # P09: el destino se resuelve UNA SOLA VEZ aquí y se reutiliza para todo lo
    # demás (evaluación, adaptación de pasos, mensaje de entorno). Antes, si el
    # cliente omitía context_destination, cada función que lo recibía (perfil
    # de entorno, evaluación de hazard, modelo de IA) le ponía por su cuenta un
    # valor por defecto de LEO -> un tripulante en Marte podía ver "LEO,
    # microgravedad" aunque su misión real fuera MARS_SURFACE.
    resolucion_contexto = mission_model.resolve_destination(mission_id, context_destination)
    destino = resolucion_contexto["destination"]

    # 1. Qué reportó el astronauta: valores numéricos + síntomas cualitativos
    valores = parse_transcript(transcript)
    sintomas = detect_symptoms(transcript)

    # P02: los valores que el astronauta reportó por voz durante la emergencia
    # se guardan como observaciones reales y quedan vinculados al caso — antes
    # se detectaban (`valores`) pero nunca se persistían, así que una lectura
    # dicha por voz durante una emergencia se perdía en cuanto terminaba la
    # respuesta HTTP.
    valores_guardados = []
    voice_source_id = catalog.get_data_source_id("VOICE_INPUT") if valores else None
    for v in valores:
        indicator_id = catalog.get_indicator_id(v["indicator_code"])
        if indicator_id is None or voice_source_id is None:
            continue
        obs_id = obs_model.record_observation(
            indicator_id=indicator_id, mission_id=mission_id, data_source_id=voice_source_id,
            data_origin="REAL", recorded_at=datetime.now(timezone.utc).isoformat(),
            unit=v["unit"], measurement_method=v["method"], astronaut_id=astronaut_id,
            value_numeric=v["value"], voice_log_id=voice_log_id,
            notes="Generado por el asistente de emergencia (botón/voz activa).",
        )
        v["observation_id"] = obs_id
        valores_guardados.append(obs_id)
        es_model.append_event(session_id, operator_id or astronaut_id, "MEASUREMENT",
                              {"observation_id": obs_id})

    # 2. Hazards implicados por lo que dijo
    hazards_implicados = {s["hazard"] for s in sintomas}
    activos = {h["code"] for h in catalog.list_hazards(active_only=True)}

    # 3. P03: evaluar SIEMPRE todos los hazards activos, no solo los que el
    # reporte menciona. Antes se cruzaba hazards_implicados & activos, así que
    # un hazard ya en rojo por telemetría pasiva desaparecía de la respuesta
    # si el astronauta reportaba síntomas de OTRO hazard (o ninguno). Se marca
    # cuál evaluación corresponde a lo recién reportado para no perder esa
    # distinción (de qué evaluación salió la acción recomendada).
    evaluaciones = []
    for hz in sorted(activos):
        ev = evaluate_astronaut_hazard(astronaut_id, hz, destino, persist=True)
        ev["reported_now"] = hz in hazards_implicados
        evaluaciones.append(ev)

    # 4. Construir la guía: pasos + qué medir + acción
    pasos: list[str] = []
    medir: list[dict] = []
    medir_vigentes: list[dict] = []
    from app.services.assessment_status import assessment_summary, LEVEL_URGENCY, URGENCY_RANK
    urgencia_max = "UNKNOWN"
    orden_urgencia = URGENCY_RANK
    # Códigos a verificar, deduplicados ANTES de consultar la base: si dos
    # síntomas reportados piden el mismo indicador (p.ej. HEART_RATE en dos
    # entradas del léxico), antes se consultaba dos veces y, si el resultado
    # era FRESH, `medir_vigentes` terminaba con el mismo indicador repetido
    # (a diferencia de `medir`, que sí se deduplicaba más abajo). Con una
    # sola consulta por código, ninguna de las dos listas puede duplicarse.
    codigos_a_verificar = list(dict.fromkeys(c for s in sintomas for c in s["measure"]))
    estados_por_codigo = {e["indicator_code"]: e for e in _stale_or_missing(astronaut_id, codigos_a_verificar)}
    for s in sintomas:
        pasos.extend(_adapt_step_text(p, destino) for p in s["steps"])
        if orden_urgencia[s["urgency"]] > orden_urgencia[urgencia_max]:
            urgencia_max = s["urgency"]
    # P08: distingue indicador sin dato nunca / con dato vencido / vigente,
    # en vez de bastar con "¿existe alguna observación alguna vez?".
    for code, estado in estados_por_codigo.items():
        if estado["status"] == "FRESH":
            medir_vigentes.append(estado)
            continue
        ind = catalog.get_indicator(code) or {}
        # Incluye CÓMO medir y POR QUÉ importa (requisito del brief):
        medir.append({
            "indicator_code": code, "name": ind.get("name", code),
            "unit": ind.get("default_unit"), "method": ind.get("default_method"),
            "how_to_measure": ind.get("how_to_measure"),
            "why_it_matters": ind.get("why_it_matters"),
            "status": estado["status"],
            "last_measured_at": estado.get("last_measured_at"),
        })

    # 5. Acción recomendada: la MÁS SEVERA entre (a) las evaluaciones pasivas y
    #    (b) el piso de acción de cada síntoma reportado. Así un síntoma grave
    #    nunca queda sin acción aunque el sistema pasivo todavía no lo vea, y un
    #    hazard que el sistema ya ve en rojo tampoco se minimiza por lo que diga
    #    el astronauta. Es el corazón de "combinar pasivo + activo".
    rank = {"CONTACT_EARTH": 3, "NOTIFY_CREW": 2, "SELF_RESOLVE": 1, None: 0}
    accion = None
    assessment = assessment_summary(evaluaciones, expected_count=len(activos))
    nivel_peor = assessment["level"]
    for e in evaluaciones:
        if rank.get(e.get("recommended_action"), 0) > rank.get(accion, 0):
            accion = e.get("recommended_action")
    for s in sintomas:
        if rank.get(s.get("min_action"), 0) > rank.get(accion, 0):
            accion = s["min_action"]

    action_urgency = {"CONTACT_EARTH": "ALTA", "NOTIFY_CREW": "MEDIA",
                      "SELF_RESOLVE": "BAJA"}.get(accion, "UNKNOWN")
    urgencia_max = max((urgencia_max, LEVEL_URGENCY[nivel_peor], action_urgency),
                       key=URGENCY_RANK.get)

    # deduplicar pasos preservando orden
    pasos_unicos = list(dict.fromkeys(pasos))
    medir_unicos = list({m["indicator_code"]: m for m in medir}.values())

    entorno = environment_context(destino)

    if not sintomas and not valores:
        mensaje = ("No identifiqué síntomas ni valores en tu reporte. ¿Puedes decir qué sientes "
                   "o qué medición tienes? Por ejemplo: 'me falta el aire' o 'mi pulso está en 120'.")
    else:
        mensaje = ("No hay evaluación suficiente para estimar la urgencia."
                   if urgencia_max == "UNKNOWN" else f"Entendido. Urgencia estimada: {urgencia_max}.")
    mensaje += " " + assessment["note"]
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
                              "reason": e["reason"], "reported_now": e["reported_now"]} for e in evaluaciones],
        "urgency": urgencia_max,
        "message": mensaje,
        "immediate_steps": pasos_unicos,
        "measurements_to_take": medir_unicos,
        "measurements_up_to_date": medir_vigentes,
        "recorded_observation_ids": valores_guardados,
        "recommended_action": accion,
        "worst_passive_level": nivel_peor,
        "assessment": assessment,
        "environment": entorno,
        "context_resolution": resolucion_contexto,
    }
