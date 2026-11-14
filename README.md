# GUARDIÁN

**NASA Space Apps Challenge 2026 — "Create Health Monitoring Software for Astronauts on Space Missions"**

GUARDIÁN monitorea la salud del astronauta sin que tenga que hacer nada manual: sensores pasivos
(audífono, saco de dormir, baño, cámaras/sensores de cabina) alimentan un modelo de IA que detecta
anomalías según el **contexto de la misión** (órbita, Luna, Marte) y responde con una instrucción
concreta: *resolverlo solo, avisar a la tripulación o contactar a la Tierra*.

> Esta entrega cubre 3 de los 5 peligros oficiales del vuelo espacial (NASA HRP):
> **distancia a la Tierra**, **aislamiento** y **campos gravitacionales**. El modelo de datos queda
> listo para activar radiación y ambiente cerrado sin cambios de esquema (ver `docs/ER_MODEL.md`).

## Equipo

| Persona | Rol |
|---|---|
| Valeska, Ezequiel, David | Base de datos y sensores |
| André | Pitch, interfaz y diseño |
| Arelys | Investigación y documentación |
| Nardia | Rúbrica y coordinación con mentores |

## Estado de este repo

- ✅ Modelo entidad-relación completo y expandible (`docs/ER_MODEL.md`)
- ✅ Backend en **MVC** (Model-View-Controller), API REST funcionando
- ✅ **1840 observaciones** cargadas según el ER, con procedencia trazable
  (6 datasets NASA reales + MMASH público + escenarios simulados marcados como tales)
- ✅ **Análisis pasivo en tiempo real**: cada lectura reevalúa al tripulante y actualiza la nave
- ✅ **Interlock de software**: la nave pasa a RESTRICTED/LOCKED y bloquea actividades según la salud
- ✅ **Botón de emergencia + voz** (modo activo): reporte por voz → guía con pasos y mediciones
- ✅ **Guía de medición** (cómo medir / por qué importa) — requisito explícito del brief del reto
- ✅ **Adaptación por entorno** (LEO / Luna / tránsito a Marte / superficie de Marte / espacio
  profundo): el retraso de comunicación con la Tierra y la instrucción de sujeción en
  microgravedad cambian el mensaje y los pasos de la guía, no solo los rangos de referencia
- ✅ **Recordatorios** de medición por tripulante
- ✅ Detección por **línea base personal** + rangos de referencia NASA + tendencia intra-sujeto
- ✅ Motor de protocolos de emergencia (semáforo → acción concreta) con auditoría de acceso
- ✅ **Validación honesta documentada y reproducible** (`docs/VALIDACION.md`), con suite de pruebas
- ⏳ **Frontend (HTML/UI) — pendiente a propósito.** El equipo todavía no define el stack visual;
  este repo no lo toca aún. Todo lo de arriba se consume por API REST (JSON) en cuanto se decida.

## Los dos modos (como pide el brief del reto)

**Pasivo (siempre activo).** El sistema analiza en tiempo real los datos del tripulante sin que
haga nada. Si detecta una anomalía, **restringe o bloquea actividades de la nave** (interlock de
software, auditado) hasta que el estado se normaliza — al volver el indicador a verde, la nave
vuelve sola a NORMAL. Las actividades críticas (soporte vital, comunicación, respuesta médica)
**nunca** se bloquean.

**Activo (botón de emergencia).** El astronauta presiona el botón y reporta por voz qué siente. El
asistente —basado en protocolos, 100% offline— combina ese reporte con el contexto pasivo y su
perfil, y responde con: urgencia, pasos inmediatos, **qué medir (con cómo y por qué)**, y la acción
(resolver solo / avisar a la tripulación / contactar a la Tierra). Cubre el escenario del video:
*"un compañero tiene dolor en el pecho y colapsa"* → contactar a la Tierra, con pasos de evaluación
del tripulante inconsciente.

**Adaptado por entorno.** El mismo reporte cambia de guía según el `context_destination`: en LEO
"contactar a la Tierra" implica ayuda casi en vivo (segundos de retraso); en tránsito a Marte o
espacio profundo, el mensaje aclara explícitamente que no hay que esperar respuesta (hasta ~20 min
por tramo) y que se debe actuar ya con el protocolo. En microgravedad (LEO, tránsito, espacio
profundo) el paso "recuéstala de lado" se sustituye por una instrucción de sujeción, porque en
gravedad cero una persona no se queda recostada. Ver `docs/VALIDACION.md` sección 7 para el detalle
y los límites honestos de esta adaptación (es operativa, no un protocolo médico distinto por
hábitat).

> **Voz:** la transcripción usa **faster-whisper** (offline, encaja con 'dentro de la nave'). Si no
> está instalado, el sistema degrada a texto sin caerse. Instalación: `pip install faster-whisper`.

## Arquitectura (MVC)

```
backend/
  app/
    models/        # Model: esquema SQLite (schema.sql) + DAOs (mission.py, observation.py, ...)
    views/         # View: esquemas Pydantic de entrada/salida (schemas.py)
    controllers/    # Controller: blueprints Flask (rutas /api/...)
    services/        # lógica de negocio (voz, emergencia)
    ml/                # IsolationForest por contexto de misión
  data/
    raw/              # CSVs/datasets originales (NASA OSDR, habitat emergency, MMASH subset)
    seed/             # ETL idempotente: catálogos + carga de datos reales
    models/           # modelos entrenados (.joblib), no versionados en git
  run.py              # punto de entrada (Flask dev server, puerto 8000)
docs/
  ER_MODEL.md         # diagrama y razonamiento del modelo de datos
```

**Nota de stack:** la propuesta inicial era FastAPI + SQLAlchemy. El entorno donde se construyó
este backend no tenía acceso a internet para `pip install`, así que se usó **Flask + `sqlite3`
estándar** — mismo patrón MVC, cero dependencias nuevas que instalar. Los DAOs en `app/models/`
están escritos para migrar a un ORM después sin tocar los controladores.

## Modelo de datos

Ver `docs/ER_MODEL.md` para el diagrama completo. Reglas que el esquema fuerza:

- Toda observación lleva astronauta **o** hábitat, fecha, unidad, método de medición y
  procedencia (`REAL` / `SIMULATED` / `DERIVED`).
- Calcio urinario en `mg/dL` y en `mg/24h` son **indicadores distintos** — nunca se mezclan.
- Cada indicador documenta si requiere equipo/laboratorio y su **advertencia de validez**
  (p.ej. "CO₂ de cabina ≠ CO₂ en sangre").
- Nuevo sensor o fuente = una fila nueva en un catálogo, no una migración de esquema.

## Datos NASA usados (y cómo)

| Fuente | Qué es | Cómo se usa | Procedencia |
|---|---|---|---|
| **NASA OSDR — LSDS-8 Comprehensive Metabolic Panel** | Panel metabólico real, con timepoints antes (`L-`) y después (`R+`) del vuelo | Calcio, albúmina, glucosa y creatinina séricos → hazard **gravedad**. Aporta además los **rangos de referencia clínicos** que usa el detector | `REAL` |
| **NASA LSDA — MR001G** (estudio de reposo) | Hormonas en sangre con fases PRE/IN/POST y postura del sujeto | ANP (desplazamiento de fluidos) → **gravedad**; ACTH (eje de estrés) → **aislamiento** | `REAL` |
| **NASA LSDA — BRSMAct** (estudio de reposo) | Actigrafía de sueño, hasta 60 días por sujeto | Latencia, duración y eficiencia de sueño → **aislamiento**. Es la fuente de la única señal con respaldo estadístico | `REAL` |
| **NASA LSDA — BRSMCF** (estudio de reposo) | Ecocardiografía con fases PRE/IN/POST | Diámetros y grosores cardiacos → **gravedad** | `REAL` |
| **MMASH** (PhysioNet, dataset público) | Fisiología/sueño/cuestionarios de sujetos de un estudio terrestre | Sueño, estrés, ansiedad (STAI), afecto (PANAS) → **aislamiento**. **No** es NASA y **no** son astronautas | `REAL` (sujetos análogos) |
| **Escenario de emergencia de hábitat** (CSV del reto) | Series ambientales/comunicación por escenario (LEO/Lunar/Marte/espacio profundo) | CO₂, temperatura, presión, radiación, distancia a la Tierra, tiempo de luz → **distancia** y ambiente | `SIMULATED` (así lo marca el propio dataset) |
| EDA, RadLab, LRO-Diviner, MSL-REMS, DSN, JPL Horizons | Catalogadas como fuentes de referencia con su cita en `data_source_citation` | Listas para alimentar nuevos indicadores sin cambiar el esquema | referencia |

Los estudios de reposo prolongado con inclinación negativa son el **análogo terrestre estándar de
la microgravedad**: los fluidos se desplazan hacia la cabeza, los huesos pierden carga y el sistema
cardiovascular se desacondiciona, igual que en vuelo. Sus sujetos **no son astronautas en órbita**,
y eso queda documentado en cada registro de la base de datos.

Cada indicador en catálogo lleva su **advertencia de validez** explícita (p.ej. *"el CO₂ de cabina
no mide el CO₂ en sangre"*, *"la radiación de Marte es de un rover, no de una nave tripulada"*),
para que ningún dato se sobre-interprete.

**Excluido a propósito:** el DSO 484 (STS-46, astronautas reales) tiene decimales perdidos no
verificables en el archivo de origen, así que se cita como respaldo científico pero no alimenta el
modelo. Ver `docs/VALIDACION.md` sección 7.

## Interfaz por voz (backend)

`POST /api/voice/ingest` recibe `{astronaut_id, mission_id, transcript}` — el transcript ya viene
convertido de voz a texto por el cliente (Web Speech API u otro motor, a definir en el frontend).
El backend:
1. Guarda el transcript crudo en `voice_log` (trazabilidad).
2. Lo parsea con reglas de palabras clave + números (determinístico, auditable, fácil de hackear
   en vivo durante el hackathon).
3. Genera una `Observation` por cada indicador reconocido, con `data_source='VOICE_INPUT'` y
   `data_origin='REAL'`.

## Detección e IA de emergencia

Dos capas separadas a propósito.

**Capa 1 — Detección** (`app/ml/personal_baseline.py`). Cada tripulante es su propio control, que
es como trabaja la medicina espacial. Tres señales independientes:

1. **Línea base personal** — desviación contra sus propias mediciones pre-vuelo (z robusto con
   mediana/MAD, con piso de escala anclado al rango de referencia).
2. **Rango de referencia clínico** — los rangos publicados que trae el dataset de NASA OSDR.
3. **Tendencia intra-sujeto** — pendiente de Theil-Sen, reportada solo si su efecto acumulado
   supera el ruido propio de la serie.

Cada veredicto dice en `signals_used` cuáles pudo calcular, y devuelve `NOT_EVALUABLE` en lugar de
adivinar cuando no alcanza para ninguna.

**Capa 2 — Decisión** (`app/services/emergency_service.py`). Traduce el nivel de semáforo
(`GREEN/YELLOW/ORANGE/RED`) en una acción concreta —`SELF_RESOLVE` / `NOTIFY_CREW` /
`CONTACT_EARTH`— buscando el protocolo en `emergency_protocol` (árbol de decisión por hazard).
Son reglas explícitas y auditables, no una predicción: una acción que puede soltar oxígeno de
emergencia debe ser trazable a una regla que un médico pueda revisar. Cada alerta queda registrada
en `data_access_log`.

**Proyección al "Día 500"**: `GET /api/emergency/projection` extrapola la tendencia a un día futuro
de misión, devolviendo junto con el número las advertencias que lo limitan (cuántas veces se está
extrapolando más allá del rango observado, y que la fisiología suele estabilizarse por adaptación).

**Por qué no un clasificador supervisado**: medimos que las variables NASA disponibles no separan
el estado de reposo del basal (AUC entre 0.49 y 0.51, nivel del azar, con 10–16 sujetos). Un modelo
entrenado sobre eso estaría ajustando ruido. El IsolationForest se conserva en
`app/ml/anomaly_detector.py` como vía de expansión para cuando exista telemetría real por
tripulante, pero no es la vía por defecto. Todo medido y reproducible en **`docs/VALIDACION.md`**.

## Cómo correrlo

```bash
cd backend
pip install -r requirements.txt       # Flask, pydantic, scikit-learn, pandas, numpy, joblib
python -m data.seed.seed_all          # siembra toda la BD en orden (NASA + demo + guías)
python -m tests.test_personal_baseline     # verifica el detector
python -m tests.test_assistant_environment # verifica la adaptación por entorno
python run.py                         # http://localhost:8000
```

Para la voz offline (opcional, se corre en la máquina de la nave):
```bash
pip install faster-whisper            # transcripción local; sin esto, el botón usa texto
```

Endpoints principales:

| Endpoint | Qué hace |
|---|---|
| `GET /api/health` | Estado del servicio |
| `GET /api/catalog/{hazards,data-sources,indicators,citations}` | Catálogos y citas de fuentes |
| `GET/POST /api/observations` | Lectura y alta de observaciones |
| `GET /api/observations/series` | Serie temporal de un indicador |
| `POST /api/voice/ingest` | Recolección por voz → observaciones |
| `POST /api/emergency/evaluate` | Evalúa hazards de un tripulante |
| `GET /api/emergency/indicator` | Detalle de un indicador con sus 3 señales |
| `GET /api/emergency/projection` | Proyección al día N de misión |
| `GET /api/emergency/crew` | Panel de toda la tripulación |
| `GET /api/emergency/alerts` | Alertas registradas |
| `GET /api/emergency/protocols` | Árbol de protocolos de emergencia |
| `POST /api/emergency/button` | **Botón de emergencia**: voz (audio) o texto → guía |
| `GET /api/emergency/voice/status` | Si faster-whisper está disponible |
| `GET /api/emergency/sessions` | Sesiones de emergencia (botón o auto-disparo) |
| `GET /api/ship/<mission_id>/status` | **Estado de la nave** + actividades permitidas/bloqueadas |
| `POST /api/ship/<mission_id>/recompute` | Recalcula el estado de la nave |
| `POST /api/monitoring/reading` | **Análisis pasivo**: ingresa una lectura y devuelve su efecto |
| `GET /api/reminders` | Mediciones pendientes por tripulante o tripulación |

## Uso de IA (Claude) en este proyecto

Este backend completo — modelo entidad-relación, esquema SQL, DAOs, servicios de voz y de
emergencia, modelo IsolationForest por contexto, API REST y ETL de los datasets NASA/MMASH — se
construyó con asistencia de Claude (Anthropic), sin usar ningún logo ni material de marca de la
NASA en el contenido generado.
