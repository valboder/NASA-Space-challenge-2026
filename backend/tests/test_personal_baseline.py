"""
Pruebas del detector por línea base personal.

Lo que se verifica aquí no es "que el modelo acierte mucho" (eso ya nos engañó
una vez con el 99.6%), sino que el detector se comporte correctamente en los
casos borde donde este tipo de sistema suele fallar en silencio:

  1. Detecta un valor clínicamente anormal  -> si no, el sistema es inútil
  2. No alarma por variación normal          -> si no, el astronauta lo ignora
  3. No explota cuando la línea base tiene varianza casi nula (el caso que
     producía z=8.5 por un cambio trivial de albúmina)
  4. Detecta una tendencia sostenida real y no una serie plana con ruido
  5. Se declara NO EVALUABLE en vez de adivinar cuando no hay datos

Ejecutar:  python -m tests.test_personal_baseline   (desde backend/)
"""
from __future__ import annotations

import sys

from app.ml.personal_baseline import _robust_z, _theil_sen_slope, _scale_floor, _kendall_tau

ALBUMIN_REF = (3.6, 5.1)          # rango de referencia real de NASA OSDR LSDS-8
fallos: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    if condicion:
        print(f"  OK   {nombre}")
    else:
        print(f"  FALLA {nombre}  {detalle}")
        fallos.append(nombre)


def test_detecta_valor_anormal():
    """Albúmina de 2.5 g/dL está muy por debajo del piso de referencia (3.6):
    debe dar un z claramente alto."""
    baseline = [4.8, 5.0, 4.9, 4.7, 5.1]
    z = _robust_z(2.5, baseline, *ALBUMIN_REF)
    check("detecta hipoalbuminemia marcada", z is not None and abs(z) >= 3.5, f"z={z}")


def test_no_alarma_por_variacion_normal():
    """Pasar de 5.0 a 4.6 g/dL es irrelevante clínicamente (sigue dentro de
    3.6-5.1). Este es el caso real que antes daba z=8.5."""
    baseline = [5.0, 5.0, 4.9]
    z = _robust_z(4.6, baseline, *ALBUMIN_REF)
    check("no infla z con variacion trivial", z is not None and abs(z) < 2.5, f"z={z}")


def test_piso_de_escala_con_varianza_cero():
    """Línea base idéntica: MAD=0 y desviación=0. Sin piso, el z sería infinito."""
    baseline = [4.6, 4.6, 4.6]
    z = _robust_z(4.3, baseline, *ALBUMIN_REF)
    check("maneja varianza basal cero", z is not None and abs(z) < 2.0, f"z={z}")
    piso = _scale_floor(4.6, *ALBUMIN_REF)
    esperado = (5.1 - 3.6) / 6.0
    check("piso de escala anclado al rango de referencia", abs(piso - esperado) < 1e-9,
          f"piso={piso} esperado={esperado}")


def test_piso_sin_rango_de_referencia():
    """Sin rango publicado cae a 5% de la mediana, no a cero."""
    piso = _scale_floor(80.0, None, None)
    check("piso relativo sin rango de referencia", abs(piso - 4.0) < 1e-9, f"piso={piso}")


def test_detecta_tendencia_sostenida():
    """Serie que baja 0.14/día durante 60 días (el caso real del sujeto
    C1G0001 del estudio de reposo: eficiencia de sueño degradándose)."""
    puntos = [(float(d), 92.0 - 0.14 * d) for d in range(60)]
    slope = _theil_sen_slope(puntos)
    check("recupera la pendiente real", slope is not None and abs(slope - (-0.14)) < 0.01,
          f"slope={slope}")


def test_ignora_serie_plana_con_ruido():
    """Serie sin tendencia real: la pendiente debe quedar cerca de cero."""
    ruido = [0.8, -1.2, 0.3, 1.1, -0.7, 0.5, -0.4, 0.9, -1.0, 0.2, 0.6, -0.8]
    puntos = [(float(i), 85.0 + ruido[i % len(ruido)]) for i in range(40)]
    slope = _theil_sen_slope(puntos)
    check("no inventa tendencia en serie plana", slope is not None and abs(slope) < 0.05,
          f"slope={slope}")


def test_tau_distingue_tendencia_de_ruido():
    """Kendall tau: alto en serie monótona, cerca de 0 en serie casi plana.
    Esta es la condición que descarta la pendiente espuria del span largo."""
    monotona = [(float(d), 92.0 - 0.14 * d) for d in range(60)]
    casi_plana = [(float(i * 30), v) for i, v in enumerate(
        [9.7, 9.72, 9.68, 9.75, 9.71, 9.69, 9.73, 9.7, 9.74, 9.71])]
    tau_m = _kendall_tau(monotona)
    tau_p = _kendall_tau(casi_plana)
    check("tau alto en tendencia real", abs(tau_m) >= 0.9, f"tau={tau_m}")
    check("tau bajo en serie casi plana", abs(tau_p) < 0.2, f"tau={tau_p}")


def test_se_niega_sin_datos_suficientes():
    """Con menos de 2 puntos no se puede estimar dispersión: debe devolver None,
    no un número inventado."""
    check("devuelve None con 1 solo basal", _robust_z(4.6, [5.0], *ALBUMIN_REF) is None)
    check("devuelve None sin basales", _robust_z(4.6, [], *ALBUMIN_REF) is None)


def test_direccion_del_z():
    """El signo debe reflejar la dirección del cambio."""
    baseline = [70.0, 72.0, 68.0, 71.0, 69.0]
    z_alto = _robust_z(95.0, baseline, 65.0, 99.0)
    z_bajo = _robust_z(45.0, baseline, 65.0, 99.0)
    check("z positivo cuando el valor sube", z_alto is not None and z_alto > 0, f"z={z_alto}")
    check("z negativo cuando el valor baja", z_bajo is not None and z_bajo < 0, f"z={z_bajo}")


if __name__ == "__main__":
    print("Pruebas del detector por linea base personal\n")
    for fn in (test_detecta_valor_anormal, test_no_alarma_por_variacion_normal,
               test_piso_de_escala_con_varianza_cero, test_piso_sin_rango_de_referencia,
               test_detecta_tendencia_sostenida, test_ignora_serie_plana_con_ruido,
               test_tau_distingue_tendencia_de_ruido,
               test_se_niega_sin_datos_suficientes, test_direccion_del_z):
        print(f"{fn.__name__}:")
        fn()
    print()
    if fallos:
        print(f"FALLARON {len(fallos)}: {', '.join(fallos)}")
        sys.exit(1)
    print("Todas las pruebas pasaron.")
