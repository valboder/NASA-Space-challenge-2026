"""Proceso independiente: python escalation_worker.py --retry-seconds N [--once]."""
import argparse
import logging
import signal
import threading

from app.core.db import init_db
from app.services.escalation_service import prepare_notifications, dispatch_notifications
from app.services.notification_transport import WebhookSender


def run_once(sender, retry_seconds):
    prepare_notifications()
    return dispatch_notifications(sender, sender.channels, retry_seconds)


def run_forever(sender, retry_seconds, poll_seconds, stop):
    while not stop.is_set():
        try:
            run_once(sender, retry_seconds)
        except Exception:
            # No volcar datos de salud ni credenciales a logs.
            logging.error('Ciclo de escalamiento fallido; se reintentará en el siguiente ciclo')
        stop.wait(poll_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retry-seconds', type=float, required=True)
    parser.add_argument('--poll-seconds', type=float, default=1, help='Frecuencia técnica de consulta; no es plazo médico')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if args.retry_seconds <= 0 or args.poll_seconds <= 0:
        parser.error('Los intervalos deben ser positivos')
    init_db()
    sender = WebhookSender()
    if not sender.channels:
        logging.warning('Sin canales configurados: solo se preparan notificaciones, no se envían')
    if args.once:
        run_once(sender, args.retry_seconds)
        return
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    run_forever(sender, args.retry_seconds, args.poll_seconds, stop)


if __name__ == '__main__':
    main()
