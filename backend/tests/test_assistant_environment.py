"""
Pruebas de la adaptación por entorno del asistente de emergencia.

Verifican lo que pide explícitamente el brief del reto ("adapt to different
environments: spacecraft, space station, lunar surface base"): que el mismo
reporte produce pasos y mensaje distintos según el entorno, no solo rangos de
referencia distintos. Son pruebas puras de texto (no tocan la base de datos),
así que corren solas con:

    python -m tests.test_assistant_environment
"""
from __future__ import annotations

from app.services.assistant_service import _adapt_step_text, environment_context


def test_recostar_se_adapta_en_microgravedad():
    paso_original = "Si respira, recuéstala de lado y no la dejes sola."
    for destino in ("LEO", "MARS_TRANSIT", "DEEP_SPACE"):
        adaptado = _adapt_step_text(paso_original, destino)
        assert adaptado != paso_original, f"no se adaptó para {destino}"
        assert "SUJETARLA" in adaptado
    print("  OK   microgravedad reemplaza 'recostar' por 'sujetar'")


def test_recostar_no_cambia_con_gravedad_parcial():
    paso_original = "Si respira, recuéstala de lado y no la dejes sola."
    for destino in ("LUNAR_SURFACE", "MARS_SURFACE"):
        adaptado = _adapt_step_text(paso_original, destino)
        assert adaptado == paso_original, f"se adaptó sin deber hacerlo en {destino}"
    print("  OK   gravedad parcial deja el paso de recostar sin cambios")


def test_comunicacion_difiere_por_entorno():
    leo = environment_context("LEO")
    mars = environment_context("MARS_TRANSIT")
    assert leo["comm_delay"] == "near_real_time"
    assert mars["comm_delay"] == "long"
    assert leo["comm_note"] != mars["comm_note"]
    print("  OK   el retraso de comunicación y su texto difieren entre LEO y Marte")


def test_destino_desconocido_cae_a_leo():
    sin_destino = environment_context(None)
    assert sin_destino["label"] == environment_context("LEO")["label"]
    print("  OK   sin destino especificado, usa LEO como supuesto explícito")


def run_all():
    tests = [
        test_recostar_se_adapta_en_microgravedad,
        test_recostar_no_cambia_con_gravedad_parcial,
        test_comunicacion_difiere_por_entorno,
        test_destino_desconocido_cae_a_leo,
    ]
    for t in tests:
        print(f"{t.__name__}:")
        t()
    print("\nTodas las pruebas pasaron.")


if __name__ == "__main__":
    run_all()
