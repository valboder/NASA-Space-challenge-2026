"""
Siembra toda la base de datos de GUARDIÁN en el orden correcto, de una sola vez.

Ejecutar: python -m data.seed.seed_all   (desde backend/, crea la BD desde cero)
"""
from __future__ import annotations

from app.core.db import init_db
from data.seed import (
    seed_catalog, seed_real_data, seed_nasa_analog, seed_ship,
    seed_emergency_episodes, seed_measurement_guides,
)


def run(reset: bool = True):
    init_db(reset=reset)
    seed_catalog.run()
    seed_real_data.run()
    seed_nasa_analog.run()
    seed_ship.run()
    seed_emergency_episodes.run()
    seed_measurement_guides.run()
    print("\nBase de datos de GUARDIÁN lista.")


if __name__ == "__main__":
    run()
