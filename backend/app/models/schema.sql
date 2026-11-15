-- GUARDIAN — Esquema SQLite (capa Model)
-- Implementa docs/ER_MODEL.md. SQLite no tiene ENUM nativo -> se usa CHECK.
-- Todas las tablas de catálogo son expandibles por INSERT, no por ALTER.

PRAGMA foreign_keys = ON;

-- ───────────────────────────── Misión / contexto ─────────────────────────────

CREATE TABLE IF NOT EXISTS mission (
    mission_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code                TEXT NOT NULL UNIQUE,                 -- 'DEMO-MARS-01'
    name                TEXT NOT NULL,
    destination         TEXT NOT NULL CHECK (destination IN
                         ('LEO','LUNAR_SURFACE','MARS_TRANSIT','MARS_SURFACE','DEEP_SPACE')),
    launch_date         TEXT,                                  -- ISO date
    expected_duration_d INTEGER,
    status              TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('PLANNED','ACTIVE','COMPLETED')),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mission_phase (
    mission_phase_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id          INTEGER NOT NULL REFERENCES mission(mission_id) ON DELETE CASCADE,
    phase_type          TEXT NOT NULL CHECK (phase_type IN ('PRE_FLIGHT','IN_FLIGHT','POST_FLIGHT')),
    start_date          TEXT,
    end_date            TEXT,
    UNIQUE (mission_id, phase_type)
);

CREATE TABLE IF NOT EXISTS astronaut (
    astronaut_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id          INTEGER REFERENCES mission(mission_id) ON DELETE SET NULL,
    call_sign           TEXT NOT NULL UNIQUE,                  -- identificador del astronauta (requerido en cada registro)
    display_name        TEXT,
    sex                 TEXT CHECK (sex IN ('M','F','OTHER', NULL)),
    birth_date          TEXT,
    height_cm           REAL,
    weight_kg_baseline  REAL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS habitat (
    habitat_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id          INTEGER NOT NULL REFERENCES mission(mission_id) ON DELETE CASCADE,
    name                TEXT NOT NULL,                         -- 'Módulo Hábitat A'
    habitat_type        TEXT CHECK (habitat_type IN ('CAPSULE','STATION','LUNAR_BASE','MARS_BASE', NULL))
);

-- ───────────────────────────── Catálogos (expandibles) ─────────────────────────────

CREATE TABLE IF NOT EXISTS hazard (
    hazard_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code                TEXT NOT NULL UNIQUE CHECK (code IN
                         ('RADIATION','ISOLATION','DISTANCE','GRAVITY','ENCLOSED_ENV')),
    name                TEXT NOT NULL,
    description         TEXT,
    is_active_scope     INTEGER NOT NULL DEFAULT 0 CHECK (is_active_scope IN (0,1))
);

CREATE TABLE IF NOT EXISTS data_source (
    data_source_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    code                 TEXT NOT NULL UNIQUE,                 -- 'EARPIECE','SLEEP_SACK','BATHROOM','CABIN_SENSOR',
                                                                 -- 'NASA_EDA','NASA_RADLAB','NASA_LRO_DIVINER',
                                                                 -- 'NASA_MSL_REMS','NASA_DSN','NASA_HORIZONS',
                                                                 -- 'NASA_OSDR','MMASH_PUBLIC','VOICE_INPUT','SIMULATION_ENGINE'
    name                  TEXT NOT NULL,
    category              TEXT NOT NULL CHECK (category IN
                          ('ONBOARD_SENSOR','NASA_REFERENCE_DATASET','PUBLIC_RESEARCH_DATASET',
                           'SIMULATED','MANUAL_VOICE_INPUT'))
);

CREATE TABLE IF NOT EXISTS indicator (
    indicator_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code                  TEXT NOT NULL UNIQUE,                -- p.ej. 'URINARY_CALCIUM_MGDL' (distinto de MG24H)
    name                  TEXT NOT NULL,
    default_unit          TEXT NOT NULL,
    data_type             TEXT NOT NULL CHECK (data_type IN ('NUMERIC','CATEGORICAL','TEXT')),
    requires_equipment     INTEGER NOT NULL DEFAULT 0 CHECK (requires_equipment IN (0,1)),
    default_method         TEXT,                               -- 'oxímetro de pulso', 'análisis de orina 24h', ...
    measurement_caveat      TEXT,                               -- advertencia de validez (ver ER_MODEL.md punto 6)
    -- El brief del reto lo pide explícitamente ("los astronautas no son médicos:
    -- explica cómo tomar cada medición y por qué importa"):
    how_to_measure           TEXT,                              -- pasos para tomar la medición sin ser médico
    why_it_matters            TEXT,                              -- por qué este indicador importa en el espacio
    typical_recheck_days       INTEGER,                          -- cada cuántos días remedir (para recordatorios)
    hazard_id               INTEGER REFERENCES hazard(hazard_id) ON DELETE SET NULL,
    default_source_id       INTEGER REFERENCES data_source(data_source_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS indicator_range (
    indicator_range_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator_id           INTEGER NOT NULL REFERENCES indicator(indicator_id) ON DELETE CASCADE,
    context_destination    TEXT CHECK (context_destination IN
                            ('LEO','LUNAR_SURFACE','MARS_TRANSIT','MARS_SURFACE','DEEP_SPACE', NULL)),
    sex                     TEXT CHECK (sex IN ('M','F','ALL', NULL)),
    min_value               REAL,
    max_value               REAL,
    source_citation_id      INTEGER REFERENCES data_source_citation(citation_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS data_source_citation (
    citation_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    data_source_id          INTEGER NOT NULL REFERENCES data_source(data_source_id) ON DELETE CASCADE,
    title                   TEXT NOT NULL,
    url                     TEXT,
    accessed_at              TEXT,
    license_note             TEXT
);

-- ───────────────────────────── Voz ─────────────────────────────

CREATE TABLE IF NOT EXISTS voice_log (
    voice_log_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    astronaut_id             INTEGER NOT NULL REFERENCES astronaut(astronaut_id) ON DELETE CASCADE,
    mission_id               INTEGER NOT NULL REFERENCES mission(mission_id) ON DELETE CASCADE,
    recorded_at               TEXT NOT NULL DEFAULT (datetime('now')),
    transcript                TEXT NOT NULL,
    parsed_payload             TEXT,                            -- JSON con los indicadores detectados
    parse_confidence            REAL,
    status                      TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN
                                 ('PENDING','PARSED','FAILED','REVIEWED'))
);

-- ───────────────────────────── Observación (tabla de hechos) ─────────────────────────────

CREATE TABLE IF NOT EXISTS observation (
    observation_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    astronaut_id                INTEGER REFERENCES astronaut(astronaut_id) ON DELETE CASCADE,   -- NULL si es lectura de hábitat
    habitat_id                  INTEGER REFERENCES habitat(habitat_id) ON DELETE CASCADE,         -- NULL si es del astronauta
    indicator_id                 INTEGER NOT NULL REFERENCES indicator(indicator_id) ON DELETE RESTRICT,
    mission_id                   INTEGER NOT NULL REFERENCES mission(mission_id) ON DELETE CASCADE,
    mission_phase_id              INTEGER REFERENCES mission_phase(mission_phase_id) ON DELETE SET NULL,
    data_source_id                 INTEGER NOT NULL REFERENCES data_source(data_source_id) ON DELETE RESTRICT,
    data_origin                     TEXT NOT NULL CHECK (data_origin IN ('REAL','SIMULATED','DERIVED')),
    recorded_at                      TEXT NOT NULL,                -- fecha/hora de la medición (ISO)
    day_relative_to_launch            INTEGER,                      -- p.ej. -3, +45 (como en CMP: L-3, R+45)
    value_numeric                     REAL,
    value_text                        TEXT,                         -- para indicadores CATEGORICAL/TEXT
    unit                               TEXT NOT NULL,
    measurement_method                  TEXT NOT NULL,
    raw_sample_label                     TEXT,                       -- 'C001_serum_L-3' tal como viene en la fuente
    derived_from_observation_id            INTEGER REFERENCES observation(observation_id) ON DELETE SET NULL,
    voice_log_id                            INTEGER REFERENCES voice_log(voice_log_id) ON DELETE SET NULL,
    notes                                     TEXT,
    created_at                                 TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (astronaut_id IS NOT NULL OR habitat_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_observation_astronaut ON observation(astronaut_id, indicator_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_observation_habitat ON observation(habitat_id, indicator_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_observation_mission ON observation(mission_id, recorded_at);

-- ───────────────────────────── IA / anomalías / alertas ─────────────────────────────

CREATE TABLE IF NOT EXISTS anomaly_model (
    anomaly_model_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    context_destination        TEXT NOT NULL CHECK (context_destination IN
                                ('LEO','LUNAR_SURFACE','MARS_TRANSIT','MARS_SURFACE','DEEP_SPACE')),
    algorithm                    TEXT NOT NULL DEFAULT 'IsolationForest',
    version                       TEXT NOT NULL,
    trained_at                    TEXT NOT NULL DEFAULT (datetime('now')),
    params_json                    TEXT,
    artifact_path                   TEXT                          -- ruta al .joblib persistido
);

CREATE TABLE IF NOT EXISTS anomaly_event (
    anomaly_event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    astronaut_id                  INTEGER REFERENCES astronaut(astronaut_id) ON DELETE CASCADE,
    habitat_id                    INTEGER REFERENCES habitat(habitat_id) ON DELETE CASCADE,
    anomaly_model_id               INTEGER NOT NULL REFERENCES anomaly_model(anomaly_model_id),
    hazard_id                       INTEGER REFERENCES hazard(hazard_id) ON DELETE SET NULL,
    triggered_at                     TEXT NOT NULL DEFAULT (datetime('now')),
    anomaly_score                     REAL NOT NULL,                -- score crudo de IsolationForest
    CHECK (astronaut_id IS NOT NULL OR habitat_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS anomaly_event_observation (
    anomaly_event_id          INTEGER NOT NULL REFERENCES anomaly_event(anomaly_event_id) ON DELETE CASCADE,
    observation_id              INTEGER NOT NULL REFERENCES observation(observation_id) ON DELETE CASCADE,
    PRIMARY KEY (anomaly_event_id, observation_id)
);

CREATE TABLE IF NOT EXISTS alert (
    alert_id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    anomaly_event_id             INTEGER NOT NULL UNIQUE REFERENCES anomaly_event(anomaly_event_id) ON DELETE CASCADE,
    level                          TEXT NOT NULL CHECK (level IN ('GREEN','YELLOW','ORANGE','RED')),
    recommended_action              TEXT NOT NULL CHECK (recommended_action IN
                                     ('SELF_RESOLVE','NOTIFY_CREW','CONTACT_EARTH')),
    message                           TEXT NOT NULL,
    status                             TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','ACKNOWLEDGED','RESOLVED')),
    created_at                          TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at                          TEXT
);

CREATE TABLE IF NOT EXISTS emergency_protocol (
    emergency_protocol_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    hazard_id                     INTEGER NOT NULL REFERENCES hazard(hazard_id) ON DELETE CASCADE,
    parent_protocol_id             INTEGER REFERENCES emergency_protocol(emergency_protocol_id) ON DELETE SET NULL,
    alert_level                     TEXT NOT NULL CHECK (alert_level IN ('GREEN','YELLOW','ORANGE','RED')),
    condition_description             TEXT NOT NULL,
    recommended_action                 TEXT NOT NULL CHECK (recommended_action IN
                                        ('SELF_RESOLVE','NOTIFY_CREW','CONTACT_EARTH')),
    instructions_text                   TEXT NOT NULL
);

-- ───────────────────────────── Seguridad / auditoría ─────────────────────────────

CREATE TABLE IF NOT EXISTS data_access_log (
    data_access_log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    actor                         TEXT NOT NULL,                  -- quién/qué hizo la acción (servicio, usuario)
    action                         TEXT NOT NULL CHECK (action IN ('CREATE','READ','UPDATE','DELETE')),
    entity_touched                 TEXT NOT NULL,                  -- nombre de tabla
    entity_id                       INTEGER,
    alert_id                         INTEGER REFERENCES alert(alert_id) ON DELETE SET NULL,
    purpose                           TEXT,
    occurred_at                        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ───────────────────────────── Estado operacional de la nave (interlock) ─────────────────────────────
-- IMPORTANTE: esto es un interlock de SOFTWARE, no control de hardware real.
-- GUARDIÁN fija un estado que la interfaz respeta y que queda auditado; no apaga
-- motores ni sella escotillas. Tabla append-only: el estado actual es el evento
-- más reciente por misión (NORMAL si no hay ninguno).

CREATE TABLE IF NOT EXISTS ship_state_event (
    ship_state_event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id                   INTEGER NOT NULL REFERENCES mission(mission_id) ON DELETE CASCADE,
    state                         TEXT NOT NULL CHECK (state IN ('NORMAL','RESTRICTED','LOCKED')),
    previous_state                 TEXT CHECK (previous_state IN ('NORMAL','RESTRICTED','LOCKED', NULL)),
    reason                          TEXT,
    driven_by_astronaut_id           INTEGER REFERENCES astronaut(astronaut_id) ON DELETE SET NULL,
    driven_by_hazard                  TEXT,
    created_at                         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ship_state_mission ON ship_state_event(mission_id, created_at);

-- Actividades de la nave y qué estado mínimo las permite. Cuando la nave está
-- RESTRICTED o LOCKED, las actividades con required_state más permisivo quedan
-- bloqueadas. Es una tabla de catálogo: agregar una actividad es un INSERT.
CREATE TABLE IF NOT EXISTS ship_activity (
    ship_activity_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code                          TEXT NOT NULL UNIQUE,
    name                           TEXT NOT NULL,
    category                        TEXT,
    min_allowed_state                TEXT NOT NULL CHECK (min_allowed_state IN ('NORMAL','RESTRICTED','LOCKED')),
    rationale                         TEXT
);

-- ───────────────────────────── Sesión de emergencia (botón + voz activa) ─────────────────────────────

CREATE TABLE IF NOT EXISTS emergency_session (
    emergency_session_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    astronaut_id                  INTEGER NOT NULL REFERENCES astronaut(astronaut_id) ON DELETE CASCADE,
    mission_id                     INTEGER NOT NULL REFERENCES mission(mission_id) ON DELETE CASCADE,
    trigger                         TEXT NOT NULL CHECK (trigger IN ('PANIC_BUTTON','PASSIVE_AUTO')),
    status                           TEXT NOT NULL DEFAULT 'OPEN'
                                      CHECK (status IN ('OPEN','GUIDANCE_GIVEN','RESOLVED','ESCALATED')),
    opened_at                         TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at                          TEXT,
    voice_log_id                        INTEGER REFERENCES voice_log(voice_log_id) ON DELETE SET NULL,
    summary                              TEXT
);

CREATE INDEX IF NOT EXISTS idx_emergency_session_astro ON emergency_session(astronaut_id, opened_at);

-- Historial compartido: el paciente permanece en emergency_session; actor es quien opera.
CREATE TABLE IF NOT EXISTS emergency_session_event (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES emergency_session(emergency_session_id),
    operator_id INTEGER NOT NULL REFERENCES astronaut(astronaut_id),
    kind TEXT NOT NULL CHECK (kind IN ('REPORT', 'TAKEOVER', 'STEP', 'MEASUREMENT')),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_session_event ON emergency_session_event(session_id, event_id);

CREATE TABLE IF NOT EXISTS api_operation (
    operation_key TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    status_code INTEGER,
    response_body BLOB,
    content_type TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alert_evaluation (
    evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL REFERENCES alert(alert_id),
    anomaly_event_id INTEGER NOT NULL REFERENCES anomaly_event(anomaly_event_id),
    level TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS escalation_policy (
    mission_id INTEGER PRIMARY KEY REFERENCES mission(mission_id),
    response_timeout_seconds INTEGER NOT NULL CHECK(response_timeout_seconds > 0)
);
CREATE TABLE IF NOT EXISTS escalation_watch (
    session_id INTEGER PRIMARY KEY REFERENCES emergency_session(emergency_session_id),
    deadline_at REAL,
    acknowledged_at REAL,
    acknowledged_by INTEGER REFERENCES astronaut(astronaut_id)
);
CREATE TABLE IF NOT EXISTS escalation_recommendation (
    session_id INTEGER NOT NULL REFERENCES emergency_session(emergency_session_id),
    action TEXT NOT NULL CHECK(action IN ('NOTIFY_CREW','CONTACT_EARTH')),
    PRIMARY KEY(session_id, action)
);
CREATE TABLE IF NOT EXISTS notification_outbox (
    notification_id TEXT PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES emergency_session(emergency_session_id),
    channel TEXT NOT NULL CHECK(channel IN ('CREW','EARTH')),
    reason TEXT NOT NULL CHECK(reason IN ('RECOMMENDATION','NO_RESPONSE')),
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PREPARED','PENDING','SENT','CONFIRMED','CANCELLED')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL,
    lease_until REAL,
    lease_token TEXT,
    last_error TEXT,
    created_at REAL NOT NULL,
    sent_at REAL,
    confirmed_at REAL,
    UNIQUE(session_id, channel, reason)
);
