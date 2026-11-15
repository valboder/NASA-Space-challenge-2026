"""Seguimiento de atención y confirmaciones de transporte (son conceptos distintos)."""
import hmac
import os
from flask import Blueprint, jsonify, request
from app.models.emergency_session import CaseError
from app.controllers.button_controller import json_body, positive_id
from app.services import escalation_service as service

bp = Blueprint('escalation', __name__, url_prefix='/api')


@bp.errorhandler(CaseError)
def error(exc):
    return jsonify(error=str(exc)), exc.status


@bp.post('/missions/<int:mission_id>/escalation-policy')
def policy(mission_id):
    return jsonify(service.configure_policy(mission_id, json_body().get('response_timeout_seconds')))


@bp.get('/emergency/sessions/<int:session_id>/escalation')
def status(session_id):
    result = service.session_status(session_id)
    result['channels'] = {channel: {'configured': bool(os.environ.get(f'GUARDIAN_{channel}_WEBHOOK_URL'))}
                          for channel in ('CREW', 'EARTH')}
    return jsonify(result)


@bp.post('/emergency/sessions/<int:session_id>/acknowledge')
def acknowledge(session_id):
    return jsonify(service.acknowledge(session_id, positive_id(json_body(), 'operator_id')))


@bp.post('/notifications/<notification_id>/queue')
def queue(notification_id):
    return jsonify(service.queue_report(notification_id, positive_id(json_body(), 'operator_id')))


@bp.post('/notifications/<notification_id>/confirm')
def confirm(notification_id):
    # El receptor confirma recepción; esto no equivale a atención al paciente.
    token = os.environ.get('GUARDIAN_DELIVERY_CONFIRM_TOKEN')
    if not token:
        return jsonify(error='confirmation_channel_not_configured'), 503
    if not hmac.compare_digest(request.headers.get('Authorization', ''), f'Bearer {token}'):
        return jsonify(error='unauthorized'), 401
    return jsonify(service.confirm_delivery(notification_id))
