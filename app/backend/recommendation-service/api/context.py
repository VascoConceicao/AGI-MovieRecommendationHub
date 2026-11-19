"""Agent-facing context API. User Service owns the underlying records."""
from helpers.context import protect, private
from uuid import UUID
from urllib.error import URLError
from helpers.http import filter_options
from services import filters
from flask import Blueprint, current_app, jsonify, request
from services import context as service

context = Blueprint('context', __name__, url_prefix='/context')


context.before_request(protect)


context.after_request(private)


@context.get('/users')
def users():
    try:
        after = str(UUID(request.args['after'])) if 'after' in request.args else None
        limit = int(request.args.get('limit', '100'))
        if not 1 <= limit <= 1000:
            raise ValueError()
    except ValueError:
        return jsonify(error='Use an after UUID and limit 1–1000.'), 400
    params = {'limit': limit}
    if after:
        params['after'] = after
    body, status = service.fetch(current_app.config, '/internal/recommendation-users', params)
    return jsonify(body), status


@context.get('/users/<user_id>')
def user_context(user_id):
    try:
        user_id = str(UUID(user_id))
        params = {'watched_offset': int(request.args.get('watched_offset', '0')),
                  'watchlist_offset': int(request.args.get('watchlist_offset', '0')),
                  'limit': int(request.args.get('limit', '100'))}
        if not 1 <= params['limit'] <= 1000 or any(not 0 <= params[key] <= 1000000
                for key in ('watched_offset', 'watchlist_offset')):
            raise ValueError()
    except ValueError:
        return jsonify(error='Use a user UUID, offsets 0–1000000 and limit 1–1000.'), 400
    body, status = service.fetch(current_app.config, '/internal/recommendation-context/' + user_id, params)
    return jsonify(body), status


@context.post('/recommendation-requests')
def create_request():
    data = request.get_json(silent=True)
    try:
        if not isinstance(data, dict) or set(data) != {'user_id', 'filters'}:
            raise ValueError()
        user_id = str(UUID(data['user_id']))
    except (ValueError, TypeError, AttributeError):
        return jsonify(error='Provide user_id UUID and filters.'), 400
    try:
        available = filter_options()
    except (URLError, OSError, ValueError):
        return jsonify(error='Movie filters unavailable. Please retry.'), 503
    try:
        selected = filters.validate(data['filters'], available)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(user_id=user_id, source='user_requested', filters=selected, generation_available=False), 200
