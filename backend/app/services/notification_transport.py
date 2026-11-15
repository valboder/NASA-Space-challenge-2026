"""Adaptador HTTP configurable; ningún destino externo está preconfigurado."""
import json
import os
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WebhookSender:
    def __init__(self):
        self.urls = {}
        self.tokens = {}
        for channel in ('CREW', 'EARTH'):
            url = os.environ.get(f'GUARDIAN_{channel}_WEBHOOK_URL')
            if not url:
                continue
            parsed = urlparse(url)
            if parsed.username or parsed.password or not parsed.hostname:
                raise ValueError(f'URL inválida para {channel}')
            if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')):
                raise ValueError('Se requiere HTTPS, excepto para pruebas locales')
            self.urls[channel] = url
            self.tokens[channel] = os.environ.get(f'GUARDIAN_{channel}_WEBHOOK_TOKEN')

    @property
    def channels(self):
        return set(self.urls)

    def __call__(self, channel, notification_id, payload):
        headers = {'Content-Type': 'application/json', 'Idempotency-Key': notification_id}
        if self.tokens[channel]:
            headers['Authorization'] = 'Bearer ' + self.tokens[channel]
        req = Request(self.urls[channel], data=json.dumps(payload).encode(), headers=headers, method='POST')
        with build_opener(NoRedirect).open(req, timeout=10) as response:
            return 200 <= response.status < 300
