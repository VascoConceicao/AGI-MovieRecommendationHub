"""Private token guards for User Service mutations."""
import secrets
from flask import current_app, jsonify, request


def authorize_reset():
    expected = current_app.config['AUTH_RESET_TOKEN']
    if not current_app.config['AUTH_RESET_ENABLED'] or not expected:
        return jsonify(error='Reset endpoint is disabled.'), 404
    authorization = request.headers.get('Authorization', '')
    prefix = 'Bearer '
    supplied = authorization[len(prefix):] if authorization.startswith(prefix) else ''
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        return jsonify(error='A valid reset token is required.'), 401
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        return jsonify(error='Cross-site requests are not allowed.'), 403
    return None


def authorize_cleanup():
    expected = current_app.config['WATCHED_CLEANUP_TOKEN']
    if not expected:
        return jsonify(error='Cleanup disabled.'), 404
    authorization = request.headers.get('Authorization', '')
    supplied = authorization[7:] if authorization.startswith('Bearer ') else ''
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        return jsonify(error='A valid cleanup token is required.'), 401
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        return jsonify(error='Cross-site requests are not allowed.'), 403
    return None
