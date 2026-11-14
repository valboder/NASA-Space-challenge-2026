"""
Detector por LÍNEA BASE PERSONAL — el núcleo real de GUARDIÁN.

Por qué este diseño y no un modelo poblacional
----------------------------------------------
Medimos si las variables de los estudios análogos de la NASA separan el estado
de reposo prolongado del estado basal, y NO lo hacen (ver docs/VALIDACION.md):
ANP AUC=0.487, ACTH AUC=0.513, calcio sérico AUC=0.357 — todos en el nivel del
azar, con 10 a 16 sujetos. Entrenar un clasificador poblacional sobre eso sería
ajustar ruido.

Pero la pregunta clínica real no es poblacional. Es:
    "¿este tripulante se está saliendo de SU propio normal?"
Eso se responde con n=1 por persona, que es exactamente la situación de una
tripulación de 4. Es también cómo trabaja la medicina espacial: la NASA usa las
mediciones pre-vuelo de cada tripulante como su referencia individual.

Tres señales independientes, de más confiable a menos:
  1. Desviación contra la línea base PERSONAL (z-score robusto con mediana/MAD)
  2. Salida del rango de referencia clínico (de indicator_range, fuente NASA OSDR)
  3. Tendencia sostenida intra-sujeto (Theil-Sen sobre los días recientes)

Ninguna requiere etiquetas inventadas. La #1 y la #3 usan solo los datos del
propio tripulante; la #2 usa rangos publicados con cita.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, asdict, field

from app.models import catalog, observation as obs_model

# Mínimo para calcular una mediana basal. Con 3-4 puntos el z es inestable, así
# que se marca baseline_confidence='low' y el roll-up no escala a rojo solo por eso.
MIN_BASELINE_N = 3
BASELINE_N_ADEQUATE = 5

# Umbrales de z robusto. 3.5 es el criterio clásico de Iglewicz-Hoaglin para
# atípicos con MAD; 2.5 lo usamos como aviso temprano.
Z_WARN = 2.5
Z_ALERT = 3.5

# Una tendencia se reporta solo si su efecto proyectado supera el ruido propio
# de la serie (slope * días > TREND_SNR * MAD). Evita alarmar por deriva de sensor.
TREND_MIN_POINTS = 10
TREND_SNR = 2.0


@dataclass
class IndicatorVerdict:
    indicator_code: str
    value: float | None
    unit: str | None
    status: str                      # OK | WARN | ALERT | NOT_EVALUABLE | NO_DATA
    reason: str
    # cuáles de las 3 señales pudieron calcularse
    signals_used: list[str] = field(default_factory=list)
    baseline_n: int = 0
    baseline_median: float | None = None
    baseline_confidence: str | None = None   # low | adequate
    robust_z: float | None = None
    reference_min: float | None = None
    reference_max: float | None = None
    outside_reference: bool | None = None
    trend_per_day: float | None = None
    trend_days: int = 0
    trend_is_material: bool | None = None
    caveat: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _scale_floor(baseline_median: float, ref_min: float | None, ref_max: float | None) -> float:
    """Piso para la escala de dispersión, para no inventar desviaciones gigantes.

    Con 3 basales casi idénticos (p.ej. albúmina 5.0, 5.0, 4.9) el MAD cae a 0 y
    cualquier cambio mínimo da un z absurdo: medimos un caso real donde pasar de
    5.0 a 4.6 g/dL —clínicamente trivial, dentro del rango normal— salía como
    8.5 desviaciones. El piso evita eso.

    Anclaje: un rango de referencia clínico abarca aproximadamente ±3 desviaciones
    de la población sana, así que ancho/6 es del orden de 1 desviación poblacional.
    Nunca afirmamos una desviación más extrema que eso. Sin rango de referencia,
    usamos 5% de la mediana basal como precisión relativa genérica.
    """
    if ref_min is not None and ref_max is not None and ref_max > ref_min:
        return (ref_max - ref_min) / 6.0
    return abs(baseline_median) * 0.05 or 1e-6


def _robust_z(value: float, baseline: list[float],
               ref_min: float | None = None, ref_max: float | None = None) -> float | None:
    """z basado en mediana y MAD, con piso de escala.

    Mediana/MAD en lugar de media/desviación porque no se desploma con un solo
    valor extremo, que es lo que importa con líneas base de 3-10 puntos.
    """
    if len(baseline) < 2:
        return None
    med = statistics.median(baseline)
    mad = statistics.median([abs(x - med) for x in baseline])
    escala = 1.4826 * mad if mad > 0 else statistics.pstdev(baseline)
    escala = max(escala, _scale_floor(med, ref_min, ref_max))
    if escala <= 0:
        return 0.0
    return (value - med) / escala


def _theil_sen_slope(points: list[tuple[float, float]]) -> float | None:
    """Pendiente de Theil-Sen (mediana de pendientes por pares). Robusta a
    atípicos, apropiada para series cortas y ruidosas de sensores."""
    if len(points) < 4:
        return None
    slopes = []
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            dx = points[j][0] - points[i][0]
            if dx != 0:
                slopes.append((points[j][1] - points[i][1]) / dx)
    return statistics.median(slopes) if slopes else None


def evaluate_indicator(astronaut_id: int, indicator_code: str,
                        context_destination: str | None = None) -> IndicatorVerdict:
    """Evalúa un indicador para un tripulante contra sus propios datos."""
    series = obs_model.series_for_indicator(astronaut_id, indicator_code)
    indicators = {i["code"]: i for i in catalog.list_indicators()}
    meta = indicators.get(indicator_code, {})
    caveat = meta.get("measurement_caveat")
    unit = meta.get("default_unit")

    if not series:
        return IndicatorVerdict(indicator_code, None, unit, "NO_DATA",
                                 "Sin observaciones para este tripulante.", caveat=caveat)

    baseline = [r["value_numeric"] for r in series
                if r.get("phase_type") == "PRE_FLIGHT" and r["value_numeric"] is not None]
    current_row = series[-1]
    value = current_row["value_numeric"]

    ranges = catalog.get_ranges_for_indicator(indicator_code, context_destination)
    ref_min = ref_max = None
    outside_ref = None
    if ranges:
        ref_min, ref_max = ranges[0].get("min_value"), ranges[0].get("max_value")
        if ref_min is not None and ref_max is not None and value is not None:
            outside_ref = value < ref_min or value > ref_max

    # Tendencia: solo sobre la fase actual (no mezclar antes/durante el vuelo)
    current_phase = current_row.get("phase_type")
    trend_points = [(float(r["day_relative_to_launch"]), float(r["value_numeric"]))
                    for r in series
                    if r.get("phase_type") == current_phase
                    and r.get("day_relative_to_launch") is not None
                    and r["value_numeric"] is not None]
    slope = _theil_sen_slope(trend_points)

    # ---- Las tres señales se evalúan por separado; cada una puede faltar ----
    signals: list[str] = []
    hallazgos: list[tuple[str, str]] = []   # (nivel, explicación)

    # Señal 1: desviación contra la línea base personal
    z = med = None
    baseline_conf = None
    if len(baseline) >= MIN_BASELINE_N:
        z = _robust_z(value, baseline, ref_min, ref_max)
        med = statistics.median(baseline)
        if z is not None:
            baseline_conf = "adequate" if len(baseline) >= BASELINE_N_ADEQUATE else "low"
            signals.append("linea_base_personal")
            # Con línea base débil no se permite llegar a rojo por esta señal sola
            tope_alerta = "ALERT" if baseline_conf == "adequate" else "WARN"
            # Y si el valor sigue dentro del rango clínico normal, tampoco:
            # "se movió respecto de sí mismo pero sigue sano" es un aviso, no una
            # emergencia. Sin esta guarda el sistema alertaría en rojo por cambios
            # clínicamente irrelevantes.
            if outside_ref is False:
                tope_alerta = "WARN"
            if abs(z) >= Z_ALERT:
                hallazgos.append((tope_alerta,
                    f"se desvía {abs(z):.1f} desviaciones robustas de su propio basal "
                    f"(mediana {med:.2f} {unit or ''}, {len(baseline)} mediciones)"
                    + ("" if baseline_conf == "adequate" else " — línea base débil, no escala a rojo")))
            elif abs(z) >= Z_WARN:
                hallazgos.append(("WARN",
                    f"se desvía {abs(z):.1f} desviaciones robustas de su propio basal "
                    f"(mediana {med:.2f} {unit or ''})"))
            else:
                hallazgos.append(("OK", f"dentro de su rango habitual (z={z:+.1f})"))

    # Señal 2: rango de referencia clínico publicado
    if outside_ref is not None:
        signals.append("rango_referencia_nasa")
        if outside_ref:
            hallazgos.append(("ALERT",
                f"fuera del rango de referencia clínico ({ref_min}–{ref_max} {unit or ''})"))
        else:
            hallazgos.append(("OK", f"dentro del rango de referencia ({ref_min}–{ref_max} {unit or ''})"))

    # Señal 3: tendencia sostenida intra-sujeto, solo si supera el ruido de la serie
    trend_material = None
    if slope is not None and len(trend_points) >= TREND_MIN_POINTS:
        signals.append("tendencia_intra_sujeto")
        serie = [p[1] for p in trend_points]
        med_serie = statistics.median(serie)
        mad_serie = statistics.median([abs(x - med_serie) for x in serie]) or 1e-9
        span_dias = max(p[0] for p in trend_points) - min(p[0] for p in trend_points)
        efecto = abs(slope) * span_dias
        trend_material = efecto > TREND_SNR * mad_serie
        if trend_material:
            direccion = "baja" if slope < 0 else "sube"
            hallazgos.append(("WARN",
                f"tendencia sostenida: {direccion} {abs(slope):.3f} {unit or ''}/día "
                f"sobre {len(trend_points)} días (efecto acumulado {efecto:.1f}, "
                f"ruido de la serie {mad_serie:.1f})"))
        else:
            hallazgos.append(("OK",
                f"sin tendencia relevante sobre {len(trend_points)} días "
                f"(efecto {efecto:.1f} por debajo del ruido {mad_serie:.1f})"))

    # ---- Resolución: gana el hallazgo más severo ----
    if not hallazgos:
        return IndicatorVerdict(
            indicator_code, value, current_row.get("unit") or unit, "NOT_EVALUABLE",
            f"Hay {len(series)} medición(es) pero ninguna señal es calculable: "
            f"{len(baseline)} basales (se necesitan {MIN_BASELINE_N}), "
            f"{'sin' if ref_min is None else 'con'} rango de referencia, "
            f"{len(trend_points)} puntos de tendencia (se necesitan {TREND_MIN_POINTS}).",
            signals_used=[], baseline_n=len(baseline), reference_min=ref_min, reference_max=ref_max,
            outside_reference=outside_ref, trend_per_day=slope, trend_days=len(trend_points),
            caveat=caveat)

    rank = {"OK": 1, "WARN": 2, "ALERT": 3}
    nivel, _ = max(hallazgos, key=lambda h: rank[h[0]])
    motivos = [txt for lvl, txt in hallazgos if lvl == nivel]
    reason = f"{indicator_code}: " + "; ".join(motivos) + "."

    return IndicatorVerdict(
        indicator_code, value, current_row.get("unit") or unit, nivel, reason,
        signals_used=signals, baseline_n=len(baseline), baseline_median=med,
        baseline_confidence=baseline_conf, robust_z=z,
        reference_min=ref_min, reference_max=ref_max, outside_reference=outside_ref,
        trend_per_day=slope, trend_days=len(trend_points), trend_is_material=trend_material,
        caveat=caveat)


def project_to_day(astronaut_id: int, indicator_code: str, target_day: int,
                    context_destination: str | None = None) -> dict:
    """Proyección lineal de un indicador a un día futuro de misión.

    Esto es la proyección al "Día 500" del pitch, hecha honestamente: es una
    extrapolación lineal de la tendencia observada, NO una predicción del
    modelo. Se devuelve junto con las advertencias que la limitan, porque
    extrapolar 500 días desde 60 días de datos es una suposición fuerte: asume
    que la tendencia se mantiene lineal, cosa que la fisiología rara vez hace
    (suele estabilizarse por adaptación).
    """
    v = evaluate_indicator(astronaut_id, indicator_code, context_destination)
    if v.trend_per_day is None or v.value is None:
        return {"indicator_code": indicator_code, "projectable": False,
                "reason": "Sin tendencia calculable (se necesitan al menos 4 puntos en la fase actual)."}

    series = obs_model.series_for_indicator(astronaut_id, indicator_code)
    dias = [r["day_relative_to_launch"] for r in series if r.get("day_relative_to_launch") is not None]
    dia_actual = max(dias) if dias else 0
    dias_adelante = target_day - dia_actual

    proyectado = v.value + v.trend_per_day * dias_adelante
    fuera_de_rango = None
    if v.reference_min is not None and v.reference_max is not None:
        fuera_de_rango = proyectado < v.reference_min or proyectado > v.reference_max

    advertencias = [
        f"Extrapolación lineal desde {v.trend_days} días de datos hacia {dias_adelante} días adelante.",
        "Asume que la tendencia se mantiene lineal; la fisiología suele estabilizarse por adaptación.",
    ]
    if not v.trend_is_material:
        advertencias.append("La tendencia observada no supera el ruido de la serie: proyección poco confiable.")
    if dias_adelante > 4 * max(v.trend_days, 1):
        advertencias.append(
            f"Se proyecta {dias_adelante / max(v.trend_days, 1):.0f} veces más allá del rango observado.")
    if v.caveat:
        advertencias.append(v.caveat)

    return {
        "indicator_code": indicator_code,
        "projectable": True,
        "current_value": v.value,
        "current_day": dia_actual,
        "target_day": target_day,
        "trend_per_day": v.trend_per_day,
        "projected_value": round(proyectado, 2),
        "unit": v.unit,
        "projected_outside_reference": fuera_de_rango,
        "reference_min": v.reference_min,
        "reference_max": v.reference_max,
        "trend_is_material": v.trend_is_material,
        "warnings": advertencias,
    }


def evaluate_hazard(astronaut_id: int, hazard_code: str,
                     context_destination: str | None = None) -> dict:
    """Evalúa todos los indicadores de un hazard y resume el peor estado."""
    indicators = catalog.list_indicators(hazard_code=hazard_code)
    verdicts = [evaluate_indicator(astronaut_id, i["code"], context_destination) for i in indicators]

    rank = {"ALERT": 3, "WARN": 2, "OK": 1}
    evaluables = [v for v in verdicts if v.status in rank]
    peor = max(evaluables, key=lambda v: rank[v.status]) if evaluables else None

    nivel = {"ALERT": "RED", "WARN": "YELLOW", "OK": "GREEN"}[peor.status] if peor else "UNKNOWN"

    return {
        "astronaut_id": astronaut_id,
        "hazard_code": hazard_code,
        "alert_level": nivel,
        "driver": peor.indicator_code if peor else None,
        "reason": peor.reason if peor else (
            "Sin indicadores evaluables para este hazard: no hay suficientes mediciones "
            "basales, ni rango de referencia, ni serie para detectar tendencia."),
        "indicators_evaluated": len(evaluables),
        "indicators_not_evaluable": sum(1 for v in verdicts if v.status == "NOT_EVALUABLE"),
        "indicators_without_data": sum(1 for v in verdicts if v.status == "NO_DATA"),
        "detail": [v.to_dict() for v in verdicts],
    }
