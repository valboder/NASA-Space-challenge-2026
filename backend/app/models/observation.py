"""
Model: observation — la tabla de hechos. Toda lectura (de sensor, de NASA,
simulada, derivada o por voz) pasa por aquí. Esta es la única función de
escritura: así se garantiza en un solo lugar que ningún registro quede sin
astronauta/hábitat, unidad, método y procedencia (regla explícita del equipo).
"""
from __future__ import annotations

from app.core.db import session, rows_to_list, row_to_dict

VALID_ORIGINS = {"REAL", "SIMULATED", "DERIVED"}


class ObservationValidationError(ValueError):
    pass


def record_observation(
    indicator_id: int,
    mission_id: int,
    data_source_id: int,
    data_origin: str,
    recorded_at: str,
    unit: str,
    measurement_method: str,
    astronaut_id: int | None = None,
    habitat_id: int | None = None,
    mission_phase_id: int | None = None,
    value_numeric: float | None = None,
    value_text: str | None = None,
    day_relative_to_launch: int | None = None,
    raw_sample_label: str | None = None,
    derived_from_observation_id: int | None = None,
    voice_log_id: int | None = None,
    notes: str | None = None,
) -> int:
    if astronaut_id is None and habitat_id is None:
        raise ObservationValidationError(
            "Toda observación necesita astronaut_id o habitat_id (regla del equipo)."
        )
    if data_origin not in VALID_ORIGINS:
        raise ObservationValidationError(f"data_origin inválido: {data_origin}")
    if not unit:
        raise ObservationValidationError("unit es obligatorio en cada observación.")
    if not measurement_method:
        raise ObservationValidationError("measurement_method es obligatorio en cada observación.")
    if value_numeric is None and value_text is None:
        raise ObservationValidationError("Se necesita value_numeric o value_text.")

    with session() as conn:
        cur = conn.execute(
            """INSERT INTO observation
                 (astronaut_id, habitat_id, indicator_id, mission_id, mission_phase_id,
                  data_source_id, data_origin, recorded_at, day_relative_to_launch,
                  value_numeric, value_text, unit, measurement_method, raw_sample_label,
                  derived_from_observation_id, voice_log_id, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (astronaut_id, habitat_id, indicator_id, mission_id, mission_phase_id,
             data_source_id, data_origin, recorded_at, day_relative_to_launch,
             value_numeric, value_text, unit, measurement_method, raw_sample_label,
             derived_from_observation_id, voice_log_id, notes),
        )
        return cur.lastrowid


def bulk_record(rows: list[dict]) -> list[int]:
    return [record_observation(**r) for r in rows]


def list_observations(
    astronaut_id: int | None = None,
    habitat_id: int | None = None,
    indicator_code: str | None = None,
    mission_id: int | None = None,
    limit: int = 500,
) -> list[dict]:
    q = """SELECT o.*, i.code AS indicator_code, i.name AS indicator_name,
                  ds.code AS source_code, mp.phase_type
           FROM observation o
           JOIN indicator i ON i.indicator_id = o.indicator_id
           JOIN data_source ds ON ds.data_source_id = o.data_source_id
           LEFT JOIN mission_phase mp ON mp.mission_phase_id = o.mission_phase_id
           WHERE 1=1"""
    params: list = []
    if astronaut_id is not None:
        q += " AND o.astronaut_id = ?"
        params.append(astronaut_id)
    if habitat_id is not None:
        q += " AND o.habitat_id = ?"
        params.append(habitat_id)
    if indicator_code is not None:
        q += " AND i.code = ?"
        params.append(indicator_code)
    if mission_id is not None:
        q += " AND o.mission_id = ?"
        params.append(mission_id)
    q += " ORDER BY o.recorded_at DESC LIMIT ?"
    params.append(limit)
    with session() as conn:
        return rows_to_list(conn.execute(q, params).fetchall())


def series_for_indicator(astronaut_id: int, indicator_code: str) -> list[dict]:
    """Serie temporal de un indicador para un astronauta — insumo directo del detector.

    Ordena por `day_relative_to_launch` cuando existe, y solo cae a `recorded_at`
    si no hay día. Importante: en varias fuentes NASA `recorded_at` es texto
    (p.ej. '+45d_relative_to_launch'), así que ordenar por ese campo daría un
    orden alfabético, no cronológico, y el "valor actual" saldría equivocado.
    """
    with session() as conn:
        q = """SELECT o.recorded_at, o.day_relative_to_launch, o.value_numeric, o.unit,
                      o.data_origin, mp.phase_type
               FROM observation o
               JOIN indicator i ON i.indicator_id = o.indicator_id
               LEFT JOIN mission_phase mp ON mp.mission_phase_id = o.mission_phase_id
               WHERE o.astronaut_id = ? AND i.code = ? AND o.value_numeric IS NOT NULL
               ORDER BY (o.day_relative_to_launch IS NULL),
                        o.day_relative_to_launch,
                        o.recorded_at"""
        return rows_to_list(conn.execute(q, (astronaut_id, indicator_code)).fetchall())
