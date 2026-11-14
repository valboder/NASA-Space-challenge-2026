"""Punto de entrada. Uso: python run.py  (desde backend/)"""
from app.app_factory import create_app
from app.core.db import init_db, DB_PATH
import os

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        init_db(reset=False)
    app = create_app()
    app.run(host="0.0.0.0", port=8000, debug=True)
