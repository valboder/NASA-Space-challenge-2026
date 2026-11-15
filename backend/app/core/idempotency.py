"""Reintentos HTTP persistentes. Una operación interrumpida no se reejecuta a ciegas."""
import hashlib
import json

from flask import Response, g, jsonify, request
from app.core.db import session


def _fingerprint():
    data = request.get_json(silent=True)
    if request.mimetype == 'multipart/form-data':
        files = []
        for name, upload in request.files.items(multi=True):
            digest = hashlib.sha256()
            while chunk := upload.stream.read(65536):
                digest.update(chunk)
            upload.stream.seek(0)
            files.append((name, upload.filename, upload.content_type, digest.hexdigest()))
        body = {'form': sorted(request.form.lists()), 'files': sorted(files)}
    elif data is not None:
        body = data
    else:
        body = request.get_data().hex()
    payload = [request.method, request.path, sorted(request.args.lists()), body]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def register_idempotency(app):
    @app.before_request
    def reserve_operation():
        if request.method != 'POST' or not request.path.startswith('/api/'):
            return None
        key = request.headers.get('Idempotency-Key')
        if key is None:
            return None  # Compatibilidad: los clientes antiguos siguen funcionando.
        if not key.strip() or len(key) > 200:
            return jsonify(error='Idempotency-Key debe contener entre 1 y 200 caracteres'), 400
        fingerprint = _fingerprint()
        with session() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM api_operation WHERE operation_key=?', (key,)).fetchone()
            if row:
                if row['fingerprint'] != fingerprint:
                    return jsonify(error='idempotency_key_conflict'), 409
                if row['status_code'] is None:
                    return jsonify(error='operation_pending', message='Operación en curso o interrumpida; no repetir con otra clave sin comprobar sus efectos.'), 409
                response = Response(row['response_body'], status=row['status_code'], content_type=row['content_type'])
                response.headers['Idempotency-Replayed'] = 'true'
                return response
            conn.execute('INSERT INTO api_operation (operation_key,fingerprint) VALUES (?,?)', (key, fingerprint))
        g.operation_key = key

    @app.after_request
    def save_response(response):
        key = getattr(g, 'operation_key', None)
        if key is not None:
            with session() as conn:
                conn.execute('UPDATE api_operation SET status_code=?,response_body=?,content_type=? WHERE operation_key=?',
                             (response.status_code, response.get_data(), response.content_type, key))
        return response
