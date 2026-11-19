"""HTTP helpers extracted from recommendation_context routes."""
from helpers.responses import no_cache as private
import secrets
from flask import current_app, jsonify, request


def authorize():
    token = current_app.config['AGENT_CONTEXT_TOKEN']
    if not token:
        return jsonify(error='Agent context is disabled.'), 404
    supplied = request.headers.get('Authorization', '')
    if not secrets.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
        return jsonify(error='A valid agent context token is required.'), 401
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        return jsonify(error='Cross-site requests are not allowed.'), 403


def unavailable(error):
    return jsonify(error='User context unavailable. Please retry.'), 503
