"""
Seed de catálogos: hazard, data_source, indicator, data_source_citation,
emergency_protocol. Este script es la fuente de verdad de "qué sabe medir
GUARDIAN" — correrlo de nuevo es idempotente (usa upsert).

Ejecutar: python -m data.seed.seed_catalog   (desde backend/)
"""
from __future__ import annotations

from app.core.db import init_db
from app.models import catalog, anomaly

TODAY = "2026-11-14"


def seed_hazards():
    # Los 5 peligros oficiales del HRP de la NASA. Solo 3 activos en esta entrega
    # (decisión explícita del equipo) — el resto queda listo para activarse.
    catalog.upsert_hazard("DISTANCE", "Distancia a la Tierra",
                           "Retraso de comunicación y autonomía médica por la distancia al planeta.", True)
    catalog.upsert_hazard("ISOLATION", "Aislamiento y confinamiento",
                           "Efectos psicológicos y de convivencia en espacios cerrados por periodos largos.", True)
    catalog.upsert_hazard("GRAVITY", "Campos gravitacionales",
                           "Pérdida de hueso/músculo y redistribución de fluidos por micro/hipogravedad.", True)
    catalog.upsert_hazard("RADIATION", "Radiación espacial",
                           "Exposición a radiación ionizante fuera de la magnetosfera terrestre.", False)
    catalog.upsert_hazard("ENCLOSED_ENV", "Ambiente cerrado hostil",
                           "Calidad de aire, presión y toxicidad del hábitat.", False)


def seed_sources():
    # 4 fuentes "a bordo" (de la guía de mentoría) + fuentes de referencia NASA + públicas + voz/simulación.
    catalog.upsert_data_source("EARPIECE", "Audífono (temperatura, pulso, SpO2, voz)", "ONBOARD_SENSOR")
    catalog.upsert_data_source("SLEEP_SACK", "Saco de dormir (sueño, respiración)", "ONBOARD_SENSOR")
    catalog.upsert_data_source("BATHROOM", "Baño (calcio, hidratación, glucosa)", "ONBOARD_SENSOR")
    catalog.upsert_data_source("CABIN_SENSOR", "Cámaras y sensores de cabina (pulso, CO2, radiación)", "ONBOARD_SENSOR")
    catalog.upsert_data_source("NASA_EDA", "NASA Environmental Data Application", "NASA_REFERENCE_DATASET")
    catalog.upsert_data_source("NASA_RADLAB", "NASA RadLab", "NASA_REFERENCE_DATASET")
    catalog.upsert_data_source("NASA_LRO_DIVINER", "LRO Diviner (temperatura superficie lunar)", "NASA_REFERENCE_DATASET")
    catalog.upsert_data_source("NASA_MSL_REMS", "Mars Science Laboratory REMS", "NASA_REFERENCE_DATASET")
    catalog.upsert_data_source("NASA_DSN", "Deep Space Network (DSN Now)", "NASA_REFERENCE_DATASET")
    catalog.upsert_data_source("NASA_HORIZONS", "JPL Horizons (distancia / tiempo de luz)", "NASA_REFERENCE_DATASET")
    catalog.upsert_data_source("NASA_OSDR", "NASA Open Science Data Repository", "NASA_REFERENCE_DATASET")
    catalog.upsert_data_source("MMASH_PUBLIC", "MMASH - Multilevel Monitoring of Activity and Sleep", "PUBLIC_RESEARCH_DATASET")
    catalog.upsert_data_source("VOICE_INPUT", "Entrada por voz del astronauta", "MANUAL_VOICE_INPUT")
    catalog.upsert_data_source("SIMULATION_ENGINE", "Motor de simulación de escenarios de emergencia", "SIMULATED")
    catalog.upsert_data_source("APP_SELF", "App propia (estado de conexión/sincronización)", "ONBOARD_SENSOR")


def seed_indicators():
    I = catalog.upsert_indicator

    # --- Audífono ---
    I("HEART_RATE", "Frecuencia cardiaca", "bpm", "NUMERIC", False,
      "Audífono (PPG)", None, None, "EARPIECE")
    I("SPO2", "Saturación de oxígeno", "%", "NUMERIC", False,
      "Oxímetro en audífono", None, None, "EARPIECE")
    I("SKIN_TEMP", "Temperatura corporal (piel, oído)", "C", "NUMERIC", False,
      "Termómetro en audífono", "No equivale a temperatura corporal central.", None, "EARPIECE")
    I("VOICE_STRESS_SCORE", "Score de estrés por análisis de voz", "score_0_100", "NUMERIC", False,
      "Análisis acústico de voz", "Proxy indirecto de estrés, no un diagnóstico.", "ISOLATION", "EARPIECE")

    # --- Saco de dormir ---
    I("SLEEP_EFFICIENCY", "Eficiencia de sueño", "%", "NUMERIC", False,
      "Sensor de movimiento/respiración en saco de dormir", None, "ISOLATION", "SLEEP_SACK")
    I("SLEEP_LATENCY_MIN", "Latencia de sueño", "min", "NUMERIC", False,
      "Saco de dormir", None, "ISOLATION", "SLEEP_SACK")
    I("RESP_RATE_SLEEP", "Frecuencia respiratoria durante el sueño", "rpm", "NUMERIC", False,
      "Saco de dormir", None, None, "SLEEP_SACK")
    I("DAILY_STRESS_SCORE", "Estrés diario autorreportado", "score_0_100", "NUMERIC", False,
      "Cuestionario diario", "Autorreporte subjetivo, no una medición fisiológica directa.", "ISOLATION", "SLEEP_SACK")
    I("CORTISOL_SALIVA", "Cortisol en saliva", "ug_dL", "NUMERIC", True,
      "Análisis de muestra de saliva", "Requiere análisis de muestra, no es pasivo.", "ISOLATION", "BATHROOM")
    I("MELATONIN_SALIVA", "Melatonina en saliva", "pg_mL", "NUMERIC", True,
      "Análisis de muestra de saliva", "Requiere análisis de muestra, no es pasivo.", "ISOLATION", "BATHROOM")

    # --- Baño (¡calcio en dos unidades, registros SEPARADOS!) ---
    I("URINARY_CALCIUM_MGDL", "Calcio urinario (concentración)", "mg_dL", "NUMERIC", True,
      "Análisis de orina puntual", "Concentración puntual; NO es lo mismo que la excreción de 24h (ver MG24H).",
      "GRAVITY", "BATHROOM")
    I("URINARY_CALCIUM_MG24H", "Calcio urinario (excreción 24h)", "mg_24h", "NUMERIC", True,
      "Recolección de orina de 24 horas", "Excreción acumulada; NO comparable directamente con mg/dL.",
      "GRAVITY", "BATHROOM")
    I("HYDRATION_INDEX", "Índice de hidratación (densidad urinaria)", "index", "NUMERIC", False,
      "Baño (análisis de orina)", None, None, "BATHROOM")
    I("URINE_GLUCOSE", "Glucosa en orina", "mg_dL", "NUMERIC", True,
      "Análisis de orina", None, None, "BATHROOM")
    I("SERUM_CALCIUM", "Calcio sérico", "mg_dL", "NUMERIC", True,
      "Panel metabólico (sangre, laboratorio)", "Requiere extracción de sangre; dato de referencia NASA OSDR.",
      "GRAVITY", "NASA_OSDR")
    I("SERUM_CREATININE", "Creatinina sérica", "mg_dL", "NUMERIC", True,
      "Panel metabólico (sangre, laboratorio)", None, "GRAVITY", "NASA_OSDR")
    I("SERUM_ALBUMIN", "Albúmina sérica", "g_dL", "NUMERIC", True,
      "Panel metabólico (sangre, laboratorio)", "Indicador de balance de fluidos, afectado por redistribución en microgravedad.",
      "GRAVITY", "NASA_OSDR")
    I("SERUM_GLUCOSE", "Glucosa sérica", "mg_dL", "NUMERIC", True,
      "Panel metabólico (sangre, laboratorio)", None, "GRAVITY", "NASA_OSDR")

    # --- Cámaras / sensores de cabina (ambiente del hábitat, no del astronauta) ---
    I("CABIN_CO2", "CO2 de cabina", "ppm", "NUMERIC", False,
      "Sensor ambiental de cabina (EDA)", "Mide CO2 del aire de cabina, NO el CO2 en sangre del astronauta.",
      "ENCLOSED_ENV", "CABIN_SENSOR")
    I("CABIN_TEMP", "Temperatura de cabina", "C", "NUMERIC", False,
      "Sensor ambiental de cabina (EDA)", "Temperatura del aire, NO la temperatura corporal.",
      "ENCLOSED_ENV", "CABIN_SENSOR")
    I("CABIN_HUMIDITY", "Humedad relativa de cabina", "pct", "NUMERIC", False,
      "Sensor ambiental de cabina (EDA)", None, "ENCLOSED_ENV", "CABIN_SENSOR")
    I("CABIN_PRESSURE", "Presión de cabina", "kPa", "NUMERIC", False,
      "Sensor ambiental de cabina (EDA)", None, "ENCLOSED_ENV", "CABIN_SENSOR")
    I("RADIATION_DOSE_RATE", "Tasa de dosis de radiación", "uGy_h", "NUMERIC", False,
      "RadLab", None, "RADIATION", "NASA_RADLAB")
    I("RADIATION_DOSE_DAILY", "Dosis diaria de radiación (derivada)", "uGy_day", "NUMERIC", False,
      "Calculado a partir de la tasa (EDA, series compatibles con RadLab)",
      "Valor DERIVADO, no medido directamente.", "RADIATION", "NASA_EDA")
    I("MARS_SURFACE_RADIATION", "Radiación en superficie marciana (referencia)", "uGy_h", "NUMERIC", False,
      "MSL REMS (rover Curiosity)", "Medido por un rover, NO por una nave/hábitat tripulado.",
      "RADIATION", "NASA_MSL_REMS")
    I("LUNAR_SURFACE_TEMP", "Temperatura de superficie lunar (referencia)", "C", "NUMERIC", False,
      "LRO Diviner", "Temperatura de la superficie, NO la temperatura dentro del traje/hábitat.",
      "ENCLOSED_ENV", "NASA_LRO_DIVINER")
    I("HR_FROM_CAMERA", "Frecuencia cardiaca por cámara (rPPG)", "bpm", "NUMERIC", False,
      "Cámara de cabina (fotopletismografía remota)", "Estimación óptica; más ruidosa que el audífono.",
      None, "CABIN_SENSOR")
    I("DUST_LEVEL", "Nivel de polvo externo/cabina", "mg_m3", "NUMERIC", False,
      "Sensor ambiental de cabina", None, "ENCLOSED_ENV", "CABIN_SENSOR")

    # --- Comunicación / distancia a la Tierra ---
    I("DISTANCE_EARTH_KM", "Distancia a la Tierra", "km", "NUMERIC", False,
      "JPL Horizons", "Distancia geométrica del cuerpo objetivo, no la ruta real de la señal.",
      "DISTANCE", "NASA_HORIZONS")
    I("ONE_WAY_LIGHT_TIME_S", "Tiempo de propagación de señal (un sentido)", "s", "NUMERIC", False,
      "JPL Horizons", "Componente física del retraso; no incluye colas de procesamiento en tierra.",
      "DISTANCE", "NASA_HORIZONS")
    I("DSN_LINK_STATUS", "Estado de enlace/antena DSN", "categorical", "CATEGORICAL", False,
      "DSN Now", "Contexto de qué misiones están comunicándose, no garantiza el enlace propio.",
      "DISTANCE", "NASA_DSN")
    I("APP_CONN_STATUS", "Estado de conexión de la app", "categorical", "CATEGORICAL", False,
      "App propia", None, "DISTANCE", "APP_SELF")
    I("APP_PENDING_MESSAGES", "Mensajes pendientes de sincronizar", "count", "NUMERIC", False,
      "App propia", None, "DISTANCE", "APP_SELF")
    I("COMMUNICATION_STATUS", "Estado general de comunicación (escenario)", "categorical", "CATEGORICAL", False,
      "Escenario de emergencia (EDA + DSN, contextual)", None, "DISTANCE", "NASA_EDA")

    # --- Psicológico / aislamiento (de MMASH, dato público real) ---
    I("STAI_ANXIETY", "Ansiedad estado (STAI)", "score", "NUMERIC", True,
      "Cuestionario STAI", "Autorreporte validado, no diagnóstico clínico.", "ISOLATION", "MMASH_PUBLIC")
    I("PANAS_POSITIVE", "Afecto positivo (PANAS)", "score", "NUMERIC", True,
      "Cuestionario PANAS", None, "ISOLATION", "MMASH_PUBLIC")
    I("PANAS_NEGATIVE", "Afecto negativo (PANAS)", "score", "NUMERIC", True,
      "Cuestionario PANAS", None, "ISOLATION", "MMASH_PUBLIC")
    I("PITTSBURGH_SLEEP_QUALITY", "Índice de calidad de sueño (Pittsburgh)", "score", "NUMERIC", True,
      "Cuestionario Pittsburgh", None, "ISOLATION", "MMASH_PUBLIC")


def seed_citations():
    C = catalog.add_citation
    C("NASA_EDA", "Environmental Data Application", "https://www.nasa.gov", TODAY,
      "Referencia ambiental de hábitat (EDA).")
    C("NASA_RADLAB", "NASA RadLab", "https://www.nasa.gov", TODAY, "Series de tasa de dosis de radiación.")
    C("NASA_LRO_DIVINER", "Lunar Reconnaissance Orbiter - Diviner", "https://www.nasa.gov", TODAY,
      "Temperatura de superficie lunar.")
    C("NASA_MSL_REMS", "Mars Science Laboratory - REMS", "https://www.nasa.gov", TODAY,
      "Ambiente marciano medido por el rover Curiosity.")
    C("NASA_DSN", "Deep Space Network (DSN Now)", "https://eyes.nasa.gov/dsn/dsn.html", TODAY,
      "Actividad de antenas/enlaces de comunicación profunda.")
    C("NASA_HORIZONS", "JPL Horizons System", "https://ssd.jpl.nasa.gov/horizons/", TODAY,
      "Distancia y tiempo de propagación de señal entre cuerpos celestes.")
    C("NASA_OSDR", "LSDS-8 Comprehensive Metabolic Panel (CMP)",
      "https://osdr.nasa.gov/bio/repo/", TODAY,
      "Panel metabólico de sujetos en estudio de reposo/análogo de vuelo espacial; usado para "
      "calcio, albúmina, glucosa y creatinina séricos antes/durante/después.")
    C("MMASH_PUBLIC", "MMASH: Multilevel Monitoring of Activity and Sleep in Healthy humans",
      "https://physionet.org/content/mmash/1.0.0/", TODAY,
      "Dataset público de fisiología/sueño/cuestionarios usado como proxy de bienestar psicológico "
      "para el hazard de aislamiento (no son astronautas reales).")


def seed_protocols():
    P = anomaly.add_protocol
    # DISTANCE
    P("DISTANCE", "GREEN", "Comunicación y distancia dentro de rango esperado para la fase de misión.",
      "SELF_RESOLVE", "Sin acción requerida. Continuar monitoreo pasivo.")
    P("DISTANCE", "YELLOW", "Retraso de señal mayor al esperado o enlace DSN intermitente.",
      "NOTIFY_CREW", "Informar a la tripulación y preparar mensajes offline (la app ya los encola).")
    P("DISTANCE", "RED", "Pérdida de enlace sostenida o distancia fuera de ventana de comunicación segura.",
      "CONTACT_EARTH", "Activar protocolo de autonomía médica: seguir guía offline y registrar todo "
      "para transmitir en cuanto se restaure el enlace.")
    # ISOLATION
    P("ISOLATION", "GREEN", "Indicadores de sueño/ánimo/estrés dentro de rango normal.",
      "SELF_RESOLVE", "Sin acción. Continuar rutina habitual.")
    P("ISOLATION", "YELLOW", "Caída sostenida de eficiencia de sueño o aumento de estrés/ansiedad reportado.",
      "NOTIFY_CREW", "Sugerir pausa de descanso y avisar a un compañero de tripulación (apoyo entre pares).")
    P("ISOLATION", "RED", "Patrón compatible con deterioro psicológico significativo (ansiedad alta sostenida "
      "+ sueño muy fragmentado + afecto negativo elevado).",
      "CONTACT_EARTH", "Contactar al equipo de soporte psicológico en Tierra y activar protocolo de "
      "acompañamiento de la tripulación.")
    # GRAVITY
    P("GRAVITY", "GREEN", "Calcio/marcadores óseos dentro de rango esperado para la fase de misión.",
      "SELF_RESOLVE", "Continuar rutina de ejercicio contra pérdida ósea/muscular.")
    P("GRAVITY", "YELLOW", "Tendencia ascendente de calcio urinario (mg/24h) por varios días consecutivos.",
      "NOTIFY_CREW", "Reforzar ejercicio de carga y registrar ingesta de calcio/hidratación; avisar a la tripulación.")
    P("GRAVITY", "RED", "Calcio urinario muy por encima de rango NASA sostenido (riesgo de pérdida ósea acelerada) "
      "o marcadores de fluido/renal fuera de rango.",
      "CONTACT_EARTH", "Contactar a control médico en Tierra para ajustar contramedidas (ejercicio/fármaco).")


def run():
    init_db(reset=False)
    seed_hazards()
    seed_sources()
    seed_indicators()
    seed_citations()
    seed_protocols()
    print("Catálogo sembrado correctamente.")


if __name__ == "__main__":
    run()
