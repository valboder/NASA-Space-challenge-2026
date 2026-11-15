"""
Ensamblado de la app (equivalente al "front controller" de MVC): registra
todos los blueprints (controladores) y expone un healthcheck. No hay nada de
HTML/plantillas aquí a propósito — el frontend todavía no está definido.
"""
from flask import Flask, jsonify

from app.controllers import (
    catalog_controller,
    mission_controller,
    observation_controller,
    voice_controller,
    emergency_controller,
    button_controller,
    ship_controller,
    escalation_controller,
)


def create_app() -> Flask:
    from app.core.db import init_db
    init_db()  # CREATE IF NOT EXISTS: añade tablas nuevas sin borrar datos existentes.
    app = Flask(__name__)
    from app.core.idempotency import register_idempotency
    register_idempotency(app)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "GUARDIAN backend"})

    app.register_blueprint(catalog_controller.bp)
    app.register_blueprint(mission_controller.bp)
    app.register_blueprint(observation_controller.bp)
    app.register_blueprint(voice_controller.bp)
    app.register_blueprint(emergency_controller.bp)
    app.register_blueprint(button_controller.bp)
    app.register_blueprint(ship_controller.bp)
    app.register_blueprint(escalation_controller.bp)

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "not_found"}), 404

    return app
