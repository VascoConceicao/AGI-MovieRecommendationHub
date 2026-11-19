"""HTTP helpers extracted from recommendations routes."""
from helpers.responses import no_cache
from flask import current_app, jsonify, request
import secrets
from services import filters


def authorize(key, enabled=True):
    expected = current_app.config[key]
    if not enabled or not expected:
        return jsonify(error='Endpoint is disabled.'), 404
    header = request.headers.get('Authorization', '')
    supplied = header[7:] if header.startswith('Bearer ') else ''
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        return jsonify(error='A valid service token is required.'), 401
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        return jsonify(error='Cross-site requests are not allowed.'), 403
    return None


def protect():
    if request.path.startswith('/admin/'):
        return authorize('RECOMMENDATION_RESET_TOKEN', current_app.config['RECOMMENDATION_RESET_ENABLED'])
    return authorize('RECOMMENDATION_API_TOKEN')


def unavailable(error):
    return jsonify(error='Recommendation database unavailable. Please retry.'), 503


def filter_options():
    options = filters.options(current_app.config['MOVIE_SERVICE_URL'])
    options['generation_available'] = False
    return options
