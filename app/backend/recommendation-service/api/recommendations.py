"""Service-token API for a future agent; never expose its token to the browser."""
from helpers.http import authorize, protect, no_cache, unavailable, filter_options
import math
from uuid import UUID
from flask import Blueprint, current_app, jsonify, request
import psycopg
from urllib.error import URLError
from services import recommendations as store
from services import filters

recommendations = Blueprint('recommendations', __name__)


recommendations.before_request(protect)


recommendations.after_request(no_cache)


recommendations.errorhandler(psycopg.Error)(unavailable)


@recommendations.get('/recommendation-filters')
def available_filters():
    try:
        return jsonify(filter_options())
    except (URLError, OSError, ValueError):
        return jsonify(error='Movie filters unavailable. Please retry.'), 503


@recommendations.get('/recommendations')
def listing():
    try:
        user_id = str(UUID(request.args.get('user_id', '')))
        source = request.args.get('source', 'all')
        if source not in ('all', 'auto', 'user_requested'):
            raise ValueError()
        offset = int(request.args.get('offset', '0'))
        limit = int(request.args.get('limit', '25'))
        if not 0 <= offset <= 1000000 or not 1 <= limit <= 100:
            raise ValueError()
    except ValueError:
        return jsonify(error='Provide user_id UUID, offset 0–1000000, and limit 1–100.'), 400
    return jsonify(store.listing(current_app.config['DATABASE_URL'], user_id, offset, limit, None if source == 'all' else source))


@recommendations.post('/recommendations')
def save():
    data = request.get_json(silent=True)
    try:
        if not isinstance(data, dict) or set(data) - {'user_id', 'movie_id', 'reason', 'score', 'source'}:
            raise ValueError()
        user_id, movie_id = str(UUID(data['user_id'])), str(UUID(data['movie_id']))
        source = data['source']
        if source not in ('auto', 'user_requested'):
            raise ValueError()
        reason, score = data['reason'], data.get('score')
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 5000:
            raise ValueError()
        if score is not None and (type(score) not in (int, float) or not 0 <= score <= 1 or not math.isfinite(score)):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        return jsonify(error='Provide user_id/movie_id UUIDs, reason (1–5000 characters), optional score (0–1), and source auto or user_requested.'), 400
    return jsonify(recommendation=store.save(current_app.config['DATABASE_URL'], user_id, movie_id, reason.strip(), score, source))


@recommendations.delete('/recommendations/<recommendation_id>')
def remove(recommendation_id):
    try:
        recommendation_id = str(UUID(recommendation_id))
    except ValueError:
        return jsonify(error='Invalid recommendation UUID.'), 400
    return jsonify(store.remove(current_app.config['DATABASE_URL'], recommendation_id))


@recommendations.post('/admin/reset-recommendation-db')
def clear():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'table'} or data['table'] not in ('all', 'recommendations'):
        return jsonify(error='Provide table: all or recommendations.'), 400
    return jsonify(store.clear(current_app.config['DATABASE_URL']))
