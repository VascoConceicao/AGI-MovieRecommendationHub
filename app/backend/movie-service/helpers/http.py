"""HTTP helpers extracted from catalog routes."""
from helpers.responses import no_cache
from flask import current_app, jsonify, request
import secrets


def authorize(key, enabled=True):
    expected = current_app.config[key]
    if not enabled or not expected:
        return jsonify(error='Endpoint is disabled.'), 404
    authorization = request.headers.get('Authorization', '')
    supplied = authorization[7:] if authorization.startswith('Bearer ') else ''
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        return jsonify(error='A valid service token is required.'), 401
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        return jsonify(error='Cross-site requests are not allowed.'), 403
    return None


def unavailable(exception):
    return jsonify(error='Movie database unavailable. Retry shortly.'), 503
