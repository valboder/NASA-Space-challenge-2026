"""
Carga de datos REALES/SIMULADOS hacia la tabla `observation`, siguiendo
exactamente el ER. Tres fuentes, cada una con su procedencia correcta:

  1. NASA OSDR LSDS-8 Comprehensive Metabolic Panel  -> REAL   (hazard: GRAVITY)
  2. space_apps_habitat_emergency_scenarios.csv       -> SIMULATED (hazard: DISTANCE / ENCLOSED_ENV)
     (el propio CSV ya lo marca así; lo respetamos, no lo reinterpretamos)
  3. MMASH (dataset público de fisiología/sueño)      -> REAL, pero de sujetos
     de un estudio terrestre análogo — NUNCA se presenta como si fueran
     astronautas reales (se documenta en astronaut.display_name/notes).

Ejecutar: python -m data.seed.seed_real_data   (desde backend/, después de seed_catalog)
"""
from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path

from app.core.db import init_db
from app.models import catalog, mission as mission_model, observation as obs_model

RAW_DIR = Path(__file__).resolve().parents[1] / "raw"
CMP_CSV = RAW_DIR / "LSDS-8_CMP_TRANSFORMED.csv"
HABITAT_CSV = RAW_DIR / "space_apps_habitat_emergency_scenarios.csv"
MMASH_ZIP = Path("/mnt/user-data/uploads/5f41d312-MMASH.zip")

CMP_FIELD_MAP = {
    "albumin_value_gram_per_deciliter": ("SERUM_ALBUMIN", "g_dL"),
    "calcium_value_milligram_per_deciliter": ("SERUM_CALCIUM", "mg_dL"),
    "creatinine_value_milligram_per_deciliter": ("SERUM_CREATININE", "mg_dL"),
    "glucose_value_milligram_per_deciliter": ("SERUM_GLUCOSE", "mg_dL"),
}

HABITAT_FIELD_MAP = {
    "distance_earth_km": ("DISTANCE_EARTH_KM", "km"),
    "one_way_light_time_s": ("ONE_WAY_LIGHT_TIME_S", "s"),
    "temperature_c": ("CABIN_TEMP", "C"),
    "relative_humidity_pct": ("CABIN_HUMIDITY", "pct"),
    "co2_ppm": ("CABIN_CO2", "ppm"),
    "cabin_pressure_kpa": ("CABIN_PRESSURE", "kPa"),
    "radiation_rate_ugy_h": ("RADIATION_DOSE_RATE", "uGy_h"),
    "external_dust_mg_m3": ("DUST_LEVEL", "mg_m3"),
}

SCENARIO_TO_MISSION = {
    "LEO_ISS": ("DEMO-LEO", "Órbita baja (referencia ISS)", "LEO"),
    "LUNAR_SURFACE": ("DEMO-LUNAR", "Superficie lunar", "LUNAR_SURFACE"),
    "MARS_SURFACE": ("DEMO-MARS-SURF", "Superficie marciana", "MARS_SURFACE"),
    "DEEP_SPACE": ("DEMO-DEEPSPACE", "Tránsito en espacio profundo", "DEEP_SPACE"),
}


def _resolve_sample(sample_name: str) -> tuple[str, int, str]:
    """'C001_serum_L-3' -> ('C001', -3, 'PRE_FLIGHT'); 'C001_serum_R+45' -> ('C001', 45, 'POST_FLIGHT')"""
    m = re.match(r"^(C\d+)_serum_([LR])([+-]?\d+)$", sample_name.strip())
    if not m:
        raise ValueError(f"No se pudo parsear Sample Name: {sample_name}")
    subject, marker, offset = m.groups()
    day = int(offset)
    phase = "PRE_FLIGHT" if marker == "L" else "POST_FLIGHT"
    return subject, day, phase


def load_cmp():
    mission_id = mission_model.create_mission(
        "ANALOG-BEDREST", "Estudio análogo (reposo/pre-post vuelo) - NASA OSDR LSDS-8",
        "LEO", None, None, status="COMPLETED",
    )
    phase_cache: dict[str, int] = {}
    source_id = catalog.get_data_source_id("NASA_OSDR")
    n = 0
    with open(CMP_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sample = row.get("Sample Name", "").strip()
            if not sample:
                continue
            try:
                subject, day, phase_type = _resolve_sample(sample)
            except ValueError:
                continue
            astro_id = mission_model.create_astronaut(
                call_sign=subject, mission_id=mission_id,
                display_name=f"Sujeto {subject} (estudio NASA OSDR LSDS-8, análogo pre/post vuelo)",
            )
            phase_key = f"{mission_id}:{phase_type}"
            if phase_key not in phase_cache:
                phase_cache[phase_key] = mission_model.ensure_phase(mission_id, phase_type)
            phase_id = phase_cache[phase_key]

            for col, (indicator_code, unit) in CMP_FIELD_MAP.items():
                raw_val = row.get(col)
                if raw_val is None or raw_val.strip().upper() in ("", "N/A", "NA"):
                    continue
                try:
                    value = float(raw_val)
                except ValueError:
                    continue
                indicator_id = catalog.get_indicator_id(indicator_code)
                obs_model.record_observation(
                    indicator_id=indicator_id, mission_id=mission_id, data_source_id=source_id,
                    data_origin="REAL", recorded_at=f"{day:+d}d_relative_to_launch",
                    unit=unit, measurement_method="Panel metabólico completo (laboratorio clínico)",
                    astronaut_id=astro_id, mission_phase_id=phase_id,
                    value_numeric=value, day_relative_to_launch=day, raw_sample_label=sample,
                )
                n += 1
    print(f"[CMP] {n} observaciones REAL cargadas (NASA OSDR LSDS-8).")


def load_habitat_emergency():
    source_id = catalog.get_data_source_id("NASA_EDA")
    mission_cache: dict[str, tuple[int, int]] = {}
    n = 0
    with open(HABITAT_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            scenario = row.get("scenario", "").strip()
            if scenario not in SCENARIO_TO_MISSION:
                continue
            if scenario not in mission_cache:
                code, name, destination = SCENARIO_TO_MISSION[scenario]
                mission_id = mission_model.create_mission(code, name, destination, "2026-01-01", 500)
                phase_id = mission_model.ensure_phase(mission_id, "IN_FLIGHT")
                habitat_id = mission_model.create_habitat(mission_id, f"Hábitat {name}", None)
                mission_cache[scenario] = (mission_id, phase_id, habitat_id)
            mission_id, phase_id, habitat_id = mission_cache[scenario]
            recorded_at = row.get("timestamp_utc")
            data_origin = row.get("data_origin", "SIMULATED").strip().upper()
            if data_origin not in ("REAL", "SIMULATED", "DERIVED"):
                data_origin = "SIMULATED"

            for col, (indicator_code, unit) in HABITAT_FIELD_MAP.items():
                raw_val = row.get(col)
                if raw_val is None or raw_val == "":
                    continue
                try:
                    value = float(raw_val)
                except ValueError:
                    continue
                indicator_id = catalog.get_indicator_id(indicator_code)
                obs_model.record_observation(
                    indicator_id=indicator_id, mission_id=mission_id, data_source_id=source_id,
                    data_origin=data_origin, recorded_at=recorded_at,
                    unit=unit, measurement_method="Sensor ambiental de hábitat (escenario de demostración)",
                    habitat_id=habitat_id, mission_phase_id=phase_id, value_numeric=value,
                    notes="Registro sintético para pruebas; no es telemetría real NASA. "
                          "Umbrales de demostración, no límites médicos/operacionales.",
                )
                n += 1
            comm_status = row.get("communication_status")
            if comm_status:
                indicator_id = catalog.get_indicator_id("COMMUNICATION_STATUS")
                obs_model.record_observation(
                    indicator_id=indicator_id, mission_id=mission_id, data_source_id=source_id,
                    data_origin=data_origin, recorded_at=recorded_at,
                    unit="categorical", measurement_method="Escenario de demostración (EDA + DSN, contextual)",
                    habitat_id=habitat_id, mission_phase_id=phase_id, value_text=comm_status,
                )
                n += 1
    print(f"[Habitat emergency] {n} observaciones cargadas en {len(mission_cache)} misiones demo.")


def _avg(row: dict, *keys) -> float | None:
    vals = []
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            try:
                vals.append(float(v))
            except ValueError:
                pass
    return sum(vals) / len(vals) if vals else None


def load_mmash():
    if not MMASH_ZIP.exists():
        print("[MMASH] zip no encontrado, se omite.")
        return
    mission_id = mission_model.create_mission(
        "ANALOG-ISOLATION-MMASH", "Estudio análogo terrestre de aislamiento (MMASH, sujetos NO astronautas)",
        "LEO", None, None, status="COMPLETED",
    )
    phase_id = mission_model.ensure_phase(mission_id, "IN_FLIGHT")
    source_id = catalog.get_data_source_id("MMASH_PUBLIC")
    n = 0
    z = zipfile.ZipFile(MMASH_ZIP)
    users = sorted({p.split("/")[1] for p in z.namelist() if p.startswith("DataPaper/user_")})
    for u in users[:8]:
        call_sign = f"MMASH_{u}"
        astro_id = mission_model.create_astronaut(
            call_sign=call_sign, mission_id=mission_id,
            display_name=f"Sujeto {u} (MMASH, estudio terrestre público — NO es astronauta real)",
        )

        def read_csv_rows(name):
            path = f"DataPaper/{u}/{name}"
            if path not in z.namelist():
                return []
            text = z.read(path).decode("utf-8")
            return list(csv.DictReader(text.splitlines()))

        for row in read_csv_rows("questionnaire.csv"):
            stai = _avg(row, "STAI1", "STAI2")
            panas_pos = _avg(row, "panas_pos_10", "panas_pos_14", "panas_pos_18", "panas_pos_22", "panas_pos_9+1")
            panas_neg = _avg(row, "panas_neg_10", "panas_neg_14", "panas_neg_18", "panas_neg_22", "panas_neg_9+1")
            daily_stress = _avg(row, "Daily_stress")
            pittsburgh = _avg(row, "Pittsburgh")
            for code, val, unit in [
                ("STAI_ANXIETY", stai, "score"), ("PANAS_POSITIVE", panas_pos, "score"),
                ("PANAS_NEGATIVE", panas_neg, "score"), ("DAILY_STRESS_SCORE", daily_stress, "score_0_100"),
                ("PITTSBURGH_SLEEP_QUALITY", pittsburgh, "score"),
            ]:
                if val is None:
                    continue
                obs_model.record_observation(
                    indicator_id=catalog.get_indicator_id(code), mission_id=mission_id, data_source_id=source_id,
                    data_origin="REAL", recorded_at="study_day_1",
                    unit=unit, measurement_method="Cuestionario validado (MMASH)",
                    astronaut_id=astro_id, mission_phase_id=phase_id, value_numeric=val,
                    notes="Dato de sujeto de estudio terrestre análogo, no de un astronauta en misión real.",
                )
                n += 1

        for row in read_csv_rows("sleep.csv"):
            eff = row.get("Efficiency")
            lat = row.get("Latency")
            for code, raw, unit in [("SLEEP_EFFICIENCY", eff, "pct"), ("SLEEP_LATENCY_MIN", lat, "min")]:
                if raw in (None, ""):
                    continue
                try:
                    val = float(raw)
                except ValueError:
                    continue
                obs_model.record_observation(
                    indicator_id=catalog.get_indicator_id(code), mission_id=mission_id, data_source_id=source_id,
                    data_origin="REAL", recorded_at="study_night_1",
                    unit=unit, measurement_method="Actigrafía de saco/cama (MMASH)",
                    astronaut_id=astro_id, mission_phase_id=phase_id, value_numeric=val,
                )
                n += 1

        for row in read_csv_rows("saliva.csv"):
            sample = (row.get("SAMPLES") or "").strip()
            cortisol = row.get("Cortisol NORM")
            if cortisol not in (None, ""):
                try:
                    val = float(cortisol)
                    obs_model.record_observation(
                        indicator_id=catalog.get_indicator_id("CORTISOL_SALIVA"), mission_id=mission_id,
                        data_source_id=source_id, data_origin="REAL", recorded_at=f"saliva_{sample}",
                        unit="normalized_0_1", measurement_method="Análisis de saliva (MMASH, valor normalizado)",
                        astronaut_id=astro_id, mission_phase_id=phase_id, value_numeric=val,
                        notes="Unidad normalizada 0-1 del dataset original, no ug/dL absoluto.",
                    )
                    n += 1
                except ValueError:
                    pass
    print(f"[MMASH] {n} observaciones REAL cargadas de {len(users[:8])} sujetos análogos.")


#: Rangos de referencia clínicos que vienen DENTRO del propio CSV de NASA OSDR
#: (columnas range_min / range_max por indicador). No los inventamos: son del dataset.
CMP_RANGE_MAP = {
    "SERUM_ALBUMIN": ("albumin_range_min_gram_per_deciliter", "albumin_range_max_gram_per_deciliter"),
    "SERUM_CALCIUM": ("calcium_range_min_milligram_per_deciliter", "calcium_range_max_milligram_per_deciliter"),
    "SERUM_CREATININE": ("creatinine_range_min_milligram_per_deciliter", "creatinine_range_max_milligram_per_deciliter"),
    "SERUM_GLUCOSE": ("glucose_range_min_milligram_per_deciliter", "glucose_range_max_milligram_per_deciliter"),
}


def load_reference_ranges():
    """Carga los rangos de referencia del CMP a indicator_range.

    Varios indicadores traen más de un rango en el dataset (p.ej. creatinina
    0.5-1.05 y 0.6-1.35, que corresponden a referencias distintas por sexo).
    Tomamos el rango MÁS AMPLIO a propósito: un valor fuera incluso del rango
    más permisivo es inequívocamente anormal, así que esta señal queda
    específica (pocas falsas alarmas). La sensibilidad la aporta la línea base
    personal, no este chequeo. Ver docs/VALIDACION.md.
    """
    citations = {c["title"]: c["citation_id"] for c in catalog.list_citations()}
    cit_id = next((v for k, v in citations.items() if "Comprehensive Metabolic Panel" in k), None)

    mins: dict[str, list[float]] = {}
    maxs: dict[str, list[float]] = {}
    with open(CMP_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            for code, (min_col, max_col) in CMP_RANGE_MAP.items():
                for col, bucket in ((min_col, mins), (max_col, maxs)):
                    raw = row.get(col)
                    if raw and raw.strip().upper() not in ("", "NA", "N/A"):
                        try:
                            bucket.setdefault(code, []).append(float(raw))
                        except ValueError:
                            pass

    n = 0
    for code in CMP_RANGE_MAP:
        if code in mins and code in maxs:
            catalog.add_indicator_range(
                indicator_code=code, context_destination=None, sex="ALL",
                min_value=min(mins[code]), max_value=max(maxs[code]), citation_id=cit_id,
            )
            n += 1
            print(f"       {code}: rango de referencia {min(mins[code])} - {max(maxs[code])}")
    print(f"[Rangos NASA OSDR] {n} rangos de referencia cargados (el más amplio por indicador).")


def run():
    init_db(reset=False)
    load_cmp()
    load_reference_ranges()
    load_habitat_emergency()
    load_mmash()
    print("Datos reales/simulados cargados correctamente.")


if __name__ == "__main__":
    run()
