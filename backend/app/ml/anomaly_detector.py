"""
Capa ML: IsolationForest por contexto de misión (orbit/lunar/mars/deep_space),
tal como pide la guía de mentoría ("un modelo de machine learning detecta
anomalías según el contexto de la misión"). Un modelo por `context_destination`
porque los rangos normales no son los mismos en LEO que en Marte.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from app.models import anomaly as anomaly_model, observation as obs_model, catalog

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "data" / "models"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

# Qué indicadores alimentan el modelo por hazard activo. Expandible: agregar
# un indicador aquí no requiere tocar el esquema, solo re-entrenar.
HAZARD_FEATURES = {
    "DISTANCE": ["DISTANCE_EARTH_KM", "ONE_WAY_LIGHT_TIME_S"],
    "ISOLATION": ["SLEEP_EFFICIENCY", "DAILY_STRESS_SCORE", "STAI_ANXIETY", "PANAS_NEGATIVE"],
    "GRAVITY": ["URINARY_CALCIUM_MGDL", "URINARY_CALCIUM_MG24H", "SERUM_CALCIUM", "SERUM_ALBUMIN"],
}


def _feature_matrix(astronaut_id: int | None, habitat_id: int | None, indicator_codes: list[str]) -> np.ndarray:
    """Construye una matriz (n_muestras, n_indicadores) tomando la última serie
    disponible por indicador; faltantes se imputan con la mediana de la columna."""
    columns = []
    for code in indicator_codes:
        if astronaut_id is not None:
            series = obs_model.series_for_indicator(astronaut_id, code)
        else:
            series = []  # las lecturas de hábitat se consultan directo en el servicio de alertas
        values = [row["value_numeric"] for row in series if row["value_numeric"] is not None]
        columns.append(values)
    max_len = max((len(c) for c in columns), default=0)
    if max_len == 0:
        return np.empty((0, len(indicator_codes)))
    matrix = np.full((max_len, len(indicator_codes)), np.nan)
    for j, col in enumerate(columns):
        for i, v in enumerate(col):
            matrix[i, j] = v
    # imputación simple por mediana de columna (si toda la columna es NaN, usa 0)
    for j in range(matrix.shape[1]):
        col = matrix[:, j]
        med = np.nanmedian(col) if not np.all(np.isnan(col)) else 0.0
        col[np.isnan(col)] = med
        matrix[:, j] = col
    return matrix


def train_model_for_context(context_destination: str, hazard_code: str, astronaut_ids: list[int]) -> int:
    """Entrena un IsolationForest para un hazard dentro de un contexto de misión,
    usando todas las observaciones disponibles de los astronautas dados."""
    indicator_codes = HAZARD_FEATURES[hazard_code]
    rows = []
    for aid in astronaut_ids:
        m = _feature_matrix(aid, None, indicator_codes)
        if m.shape[0] > 0:
            rows.append(m)
    if not rows:
        raise ValueError("No hay observaciones suficientes para entrenar.")
    X = np.vstack(rows)

    clf = IsolationForest(n_estimators=150, contamination="auto", random_state=42)
    clf.fit(X)

    version = f"{context_destination}_{hazard_code}_v1"
    artifact_path = ARTIFACT_DIR / f"{version}.joblib"
    joblib.dump({"model": clf, "indicator_codes": indicator_codes}, artifact_path)

    model_id = anomaly_model.register_model(
        context_destination=context_destination, version=version,
        params_json=json.dumps({"indicator_codes": indicator_codes, "n_samples": int(X.shape[0])}),
        artifact_path=str(artifact_path),
    )
    return model_id


def score_astronaut(astronaut_id: int, context_destination: str, hazard_code: str) -> dict:
    """Corre el modelo más reciente para ese contexto+hazard sobre la última
    observación disponible del astronauta. Devuelve score + nivel de alerta."""
    model_row = anomaly_model.latest_model_for_context_hazard(context_destination, hazard_code)
    indicator_codes = HAZARD_FEATURES[hazard_code]

    artifact = None
    if model_row and model_row.get("artifact_path") and os.path.exists(model_row["artifact_path"]):
        artifact = joblib.load(model_row["artifact_path"])

    X = _feature_matrix(astronaut_id, None, indicator_codes)
    if X.shape[0] == 0:
        return {"status": "NO_DATA", "indicator_codes": indicator_codes}

    last_row = X[-1:, :]
    if artifact is not None:
        clf: IsolationForest = artifact["model"]
        raw_score = float(clf.decision_function(last_row)[0])   # más negativo = más anómalo
        is_outlier = bool(clf.predict(last_row)[0] == -1)
    else:
        # fallback sin modelo entrenado: z-score simple contra rangos NASA conocidos
        raw_score, is_outlier = _rule_based_fallback(last_row[0], indicator_codes, context_destination)

    level = _score_to_level(raw_score, is_outlier)
    return {
        "status": "OK", "astronaut_id": astronaut_id, "hazard_code": hazard_code,
        "indicator_codes": indicator_codes, "anomaly_score": raw_score,
        "is_outlier": is_outlier, "alert_level": level,
        "model_used": model_row["version"] if model_row else "rule_based_fallback",
    }


def _rule_based_fallback(values: np.ndarray, indicator_codes: list[str], context_destination: str) -> tuple[float, bool]:
    """Sin modelo entrenado todavía (p.ej. demo en frío): usa los rangos NASA
    de indicator_range para dar un score interpretable (desviaciones fuera de rango)."""
    deviations = []
    for code, val in zip(indicator_codes, values):
        ranges = catalog.get_ranges_for_indicator(code, context_destination)
        if not ranges:
            continue
        r = ranges[0]
        lo, hi = r.get("min_value"), r.get("max_value")
        if lo is not None and hi is not None and hi > lo:
            mid, span = (hi + lo) / 2, (hi - lo) / 2
            deviations.append(abs(val - mid) / span)
    if not deviations:
        return 0.0, False
    avg_dev = float(np.mean(deviations))
    return -avg_dev, avg_dev > 1.3


def _score_to_level(raw_score: float, is_outlier: bool) -> str:
    if not is_outlier:
        return "GREEN"
    if raw_score > -0.15:
        return "YELLOW"
    if raw_score > -0.30:
        return "ORANGE"
    return "RED"
