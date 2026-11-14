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
- ✅ Dataset real cargado según el ER (NASA OSDR + MMASH público + escenarios de hábitat)
- ✅ Interfaz de voz **a nivel backend** (endpoint que recibe transcript y lo convierte en datos)
- ✅ Capa de IA: IsolationForest por contexto de misión + motor de protocolos de emergencia
- ✅ Auditoría de acceso a datos de salud (`data_access_log`)
- ⏳ **Frontend (HTML/UI) — pendiente a propósito.** El equipo todavía no define el stack visual;
  este repo no lo toca aún. Todo lo de arriba se consume por API REST (JSON) en cuanto se decida.

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
| **NASA OSDR — LSDS-8 Comprehensive Metabolic Panel** | Panel metabólico real de un estudio análogo (pre/post vuelo) | Calcio, albúmina, glucosa y creatinina séricos → hazard **gravedad** | `REAL` |
| **MMASH** (PhysioNet, dataset público) | Fisiología/sueño/cuestionarios de sujetos de un estudio terrestre | Sueño, estrés, ansiedad (STAI), afecto (PANAS) → hazard **aislamiento**. Se documenta explícitamente que **no son astronautas reales** | `REAL` (sujetos análogos) |
| **Escenario de emergencia de hábitat** (CSV del reto) | Series ambientales/comunicación por escenario (LEO/Lunar/Marte/espacio profundo) | CO₂, temperatura, presión, radiación, distancia a la Tierra, tiempo de luz → hazards **distancia** y ambiente | `SIMULATED` (así lo marca el propio dataset) |
| EDA, RadLab, LRO-Diviner, MSL-REMS, DSN, JPL Horizons | Catalogadas como fuentes de referencia (`data_source`) con sus cita en `data_source_citation` | Listas para alimentar nuevos indicadores sin cambiar el esquema | referencia |

Cada indicador en catálogo lleva su **advertencia de validez** explícita (p.ej. *"radiación de
Marte es de un rover, no de una nave tripulada"*), para que ningún dato se sobre-interprete.

## Interfaz por voz (backend)

`POST /api/voice/ingest` recibe `{astronaut_id, mission_id, transcript}` — el transcript ya viene
convertido de voz a texto por el cliente (Web Speech API u otro motor, a definir en el frontend).
El backend:
1. Guarda el transcript crudo en `voice_log` (trazabilidad).
2. Lo parsea con reglas de palabras clave + números (determinístico, auditable, fácil de hackear
   en vivo durante el hackathon).
3. Genera una `Observation` por cada indicador reconocido, con `data_source='VOICE_INPUT'` y
   `data_origin='REAL'`.

## IA de emergencia

- `app/ml/anomaly_detector.py`: un **IsolationForest por contexto de misión** (LEO/lunar/tránsito
  Marte/superficie Marte/espacio profundo) y por hazard activo. Si no hay modelo entrenado todavía,
  cae a un *fallback* basado en los rangos normales NASA (`indicator_range`) para no dejar al
  astronauta sin respuesta.
- `app/services/emergency_service.py`: convierte el score en un nivel de semáforo
  (`GREEN/YELLOW/ORANGE/RED`) y busca el protocolo correspondiente en `emergency_protocol`
  (árbol de decisión por hazard), devolviendo una acción concreta:
  `SELF_RESOLVE` / `NOTIFY_CREW` / `CONTACT_EARTH`.
- Cada alerta generada queda registrada en `data_access_log` (manejo seguro/auditable de datos
  de salud).

## Cómo correrlo

```bash
cd backend
pip install -r requirements.txt   # Flask, pydantic, scikit-learn, pandas, numpy, joblib
python -m data.seed.seed_catalog      # catálogos (hazards, fuentes, indicadores, protocolos)
python -m data.seed.seed_real_data    # carga NASA OSDR + habitat emergency + MMASH
python run.py                         # http://localhost:8000
```

Endpoints principales: `GET /api/health`, `GET /api/catalog/{hazards,data-sources,indicators,citations}`,
`GET/POST /api/observations`, `POST /api/voice/ingest`, `POST /api/emergency/evaluate`,
`GET /api/emergency/alerts`.

## Uso de IA (Claude) en este proyecto

Este backend completo — modelo entidad-relación, esquema SQL, DAOs, servicios de voz y de
emergencia, modelo IsolationForest por contexto, API REST y ETL de los datasets NASA/MMASH — se
construyó con asistencia de Claude (Anthropic), sin usar ningún logo ni material de marca de la
NASA en el contenido generado.
