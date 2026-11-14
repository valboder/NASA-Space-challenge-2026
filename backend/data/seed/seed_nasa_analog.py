"""
Carga de los estudios análogos de la NASA (NASA LSDA / Flight Analogs Project).

Son estudios de REPOSO PROLONGADO CON INCLINACIÓN NEGATIVA (bed rest), que es
el análogo terrestre estándar de la microgravedad: los fluidos se desplazan
hacia la cabeza, los huesos pierden carga y el sistema cardiovascular se
desacondiciona, igual que en vuelo. No son astronautas en órbita, y eso queda
documentado en cada registro.

Lo valioso para GUARDIÁN: cada estudio trae las fases PRE_TEST / IN_TEST /
POST_TEST, que mapean directo a antes / durante / después del vuelo. Eso nos da
una VERDAD EXTERNA para validar el modelo sin inventar etiquetas:
"normal" = PRE_TEST (lo define el diseño del estudio NASA, no nosotros).

Datasets cargados:
  - MR001G  ANP (péptido natriurético atrial), 20 sujetos  -> hazard GRAVITY
  - MR001G  ACTH (hormona adrenocorticotropa),  20 sujetos -> hazard ISOLATION (estrés)
  - BRSMAct actigrafía de sueño, 3 sujetos                 -> hazard ISOLATION
  - BRSMCF  ecocardiografía, 3 sujetos                     -> hazard GRAVITY

EXCLUIDO a propósito:
  - MR001G renina: el archivo exportado no trae columna de valores.
  - DSO 484 (STS-46, astronautas reales): tiene decimales perdidos en el origen
    (celdas guardadas como entero, p.ej. 169 donde debería ser 16.9) y la
    relación antes+desfase=después no se cumple ni en las filas limpias, así que
    no hay forma de validar una corrección. Se cita como respaldo científico en
    el README, pero NO se usa como insumo del modelo.

Ejecutar: python -m data.seed.seed_nasa_analog   (desde backend/)
"""
from __future__ import annotations

import csv
from pathlib import Path

from app.core.db import init_db
from app.models import catalog, mission as mission_model, observation as obs_model

RAW = Path(__file__).resolve().parents[1] / "raw" / "nasa_lsda"

PHASE_MAP = {"PRE_TEST": "PRE_FLIGHT", "IN_TEST": "IN_FLIGHT", "POST_TEST": "POST_FLIGHT"}

# Medidas de ecocardiografía que sí interesan (el archivo trae muchas siglas)
ECHO_TESTS = {
    "LVDD": ("ECHO_LVDD", "cm", "Diámetro diastólico del ventrículo izquierdo"),
    "IVS": ("ECHO_IVS", "cm", "Grosor del septo interventricular"),
    "RVD": ("ECHO_RVD", "cm", "Diámetro del ventrículo derecho"),
}


def _f(val) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "NA", "N/A", "nan", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _hhmm_to_minutes(val) -> float | None:
    """'0:38' -> 38.0 ; '7:44:00' -> 464.0"""
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "NA", "nan", "-"):
        return None
    parts = s.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 60 + nums[1] + nums[2] / 60
    return None


def seed_indicators():
    I = catalog.upsert_indicator
    catalog.upsert_data_source("NASA_LSDA", "NASA Life Science Data Archive / Flight Analogs Project",
                                "NASA_REFERENCE_DATASET")

    I("ANP_PLASMA", "Péptido natriurético atrial en plasma", "pg_mL", "NUMERIC", True,
      "Extracción de sangre y radioinmunoensayo",
      "Sube cuando los fluidos se desplazan hacia el tórax (microgravedad o inclinación negativa). "
      "Depende fuertemente de la POSTURA del sujeto al momento de la toma.",
      "GRAVITY", "NASA_LSDA")
    I("ACTH_PLASMA", "Hormona adrenocorticotropa en plasma", "pg_mL", "NUMERIC", True,
      "Extracción de sangre y radioinmunoensayo",
      "Marcador del eje de estrés; también varía por ritmo circadiano, no solo por estrés psicológico.",
      "ISOLATION", "NASA_LSDA")
    I("SLEEP_DURATION_MIN", "Duración total del sueño", "min", "NUMERIC", False,
      "Actigrafía de muñeca", None, "ISOLATION", "NASA_LSDA")
    for code, unit, desc in ECHO_TESTS.values():
        I(code, desc, unit, "NUMERIC", True,
          "Ecocardiografía en modo 2D",
          "Medición operador-dependiente; requiere equipo y personal especializado.",
          "GRAVITY", "NASA_LSDA")

    catalog.add_citation("NASA_LSDA",
        "NASA Flight Analogs Project - Bed Rest Studies (MR001G, BRSMAct, BRSMCF)",
        "https://lsda.jsc.nasa.gov/", "2026-11-14",
        "Estudios de reposo prolongado con inclinación negativa, análogo terrestre de microgravedad. "
        "Los sujetos NO son astronautas en vuelo.")
    catalog.add_citation("NASA_LSDA",
        "DSO 484 (STS-46) - Whitson PA, Putcha L, Chen YM, Baker E. Melatonin and cortisol "
        "assessment of circadian shifts in astronauts before flight. J Pineal Research.",
        "https://lsda.jsc.nasa.gov/", "2026-11-14",
        "CITADO COMO RESPALDO CIENTÍFICO, NO USADO COMO DATO DE ENTRENAMIENTO: el archivo "
        "de origen tiene decimales perdidos no verificables.")


def _setup_mission():
    mission_id = mission_model.create_mission(
        "NASA-ANALOG-BEDREST", "Estudios de reposo prolongado NASA (análogo de microgravedad)",
        "LEO", None, None, status="COMPLETED")
    phases = {p: mission_model.ensure_phase(mission_id, p)
              for p in ("PRE_FLIGHT", "IN_FLIGHT", "POST_FLIGHT")}
    return mission_id, phases


def _astronaut(subject: str, mission_id: int) -> int:
    return mission_model.create_astronaut(
        call_sign=f"BR-{subject}", mission_id=mission_id,
        display_name=f"Sujeto {subject} (estudio de reposo NASA, análogo — NO astronauta en vuelo)")


def load_anp_acth(mission_id, phases) -> int:
    source_id = catalog.get_data_source_id("NASA_LSDA")
    n = 0
    files = [("MR001G_ANP.csv", "ANP..pg.ml.", "ANP_PLASMA", "pg_mL"),
             ("MR001G_ACTH_male.csv", "ACTH..pg.ml.", "ACTH_PLASMA", "pg_mL"),
             ("MR001G_ACTH_female.csv", "ACTH..pg.ml.", "ACTH_PLASMA", "pg_mL")]
    for fname, value_col, indicator_code, unit in files:
        path = RAW / fname
        if not path.exists():
            continue
        indicator_id = catalog.get_indicator_id(indicator_code)
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                value = _f(row.get(value_col))
                phase = PHASE_MAP.get((row.get("Test_Phase") or "").strip())
                if value is None or phase is None:
                    continue
                astro_id = _astronaut(row["Subject"].strip(), mission_id)
                br_day = _f(row.get("BR_Day"))
                day = int(br_day) if br_day is not None else None
                if day is not None and phase == "PRE_FLIGHT":
                    day = -abs(day)
                position = (row.get("Position") or "").strip()
                obs_model.record_observation(
                    indicator_id=indicator_id, mission_id=mission_id, data_source_id=source_id,
                    data_origin="REAL", recorded_at=row.get("Date") or "unknown",
                    unit=unit, measurement_method="Extracción de sangre y radioinmunoensayo",
                    astronaut_id=astro_id, mission_phase_id=phases[phase],
                    value_numeric=value, day_relative_to_launch=day,
                    raw_sample_label=f"{row.get('Campaign','')}_{row['Subject']}_{row.get('Study_Day','')}",
                    notes=f"Postura al momento de la toma: {position or 'no registrada'}. "
                          f"Estudio de reposo NASA, sujeto análogo.")
                n += 1
    return n


def load_sleep(mission_id, phases) -> int:
    source_id = catalog.get_data_source_id("NASA_LSDA")
    path = RAW / "BRSMAct_sleep.csv"
    if not path.exists():
        return 0
    n = 0
    specs = [("Sleep Latency (hours)", "SLEEP_LATENCY_MIN", "min", _hhmm_to_minutes),
             ("Sleep Duration (hours)", "SLEEP_DURATION_MIN", "min", _hhmm_to_minutes),
             ("Sleep Efficiency (%)", "SLEEP_EFFICIENCY", "pct", _f)]
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            phase = PHASE_MAP.get((row.get("Test_Phase") or "").strip())
            if phase is None:
                continue
            astro_id = _astronaut(row["Subject"].strip(), mission_id)
            br_day = _f(row.get("BR_Day"))
            day = int(br_day) if br_day is not None else None
            if day is not None and phase == "PRE_FLIGHT":
                day = -abs(day)
            for col, code, unit, conv in specs:
                value = conv(row.get(col))
                if value is None:
                    continue
                obs_model.record_observation(
                    indicator_id=catalog.get_indicator_id(code), mission_id=mission_id,
                    data_source_id=source_id, data_origin="REAL",
                    recorded_at=row.get("Date") or "unknown", unit=unit,
                    measurement_method="Actigrafía de muñeca",
                    astronaut_id=astro_id, mission_phase_id=phases[phase],
                    value_numeric=value, day_relative_to_launch=day,
                    notes="Estudio de reposo NASA, sujeto análogo.")
                n += 1
    return n


def load_echo(mission_id, phases) -> int:
    source_id = catalog.get_data_source_id("NASA_LSDA")
    path = RAW / "BRSMCF_echo.csv"
    if not path.exists():
        return 0
    n = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            test = (row.get("Test") or "").strip()
            if test not in ECHO_TESTS:
                continue
            phase = PHASE_MAP.get((row.get("Test_Phase") or "").strip())
            value = _f(row.get("Recorded_Value"))
            if phase is None or value is None:
                continue
            code, unit, _ = ECHO_TESTS[test]
            astro_id = _astronaut(row["Subject"].strip(), mission_id)
            br_day = _f(row.get("BR_Day"))
            day = int(br_day) if br_day is not None else None
            if day is not None and phase == "PRE_FLIGHT":
                day = -abs(day)
            obs_model.record_observation(
                indicator_id=catalog.get_indicator_id(code), mission_id=mission_id,
                data_source_id=source_id, data_origin="REAL",
                recorded_at=row.get("Date") or "unknown", unit=unit,
                measurement_method="Ecocardiografía en modo 2D",
                astronaut_id=astro_id, mission_phase_id=phases[phase],
                value_numeric=value, day_relative_to_launch=day, raw_sample_label=test,
                notes="Estudio de reposo NASA, sujeto análogo.")
            n += 1
    return n


def run():
    init_db(reset=False)
    seed_indicators()
    mission_id, phases = _setup_mission()
    a = load_anp_acth(mission_id, phases)
    s = load_sleep(mission_id, phases)
    e = load_echo(mission_id, phases)
    print(f"[NASA LSDA] ANP+ACTH: {a} | sueño: {s} | ecocardiografía: {e} | total {a+s+e} observaciones REAL")


if __name__ == "__main__":
    run()
