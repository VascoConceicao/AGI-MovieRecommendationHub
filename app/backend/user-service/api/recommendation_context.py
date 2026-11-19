"""Agent-only context endpoints. No browser access or account credentials returned."""
from helpers.context import authorize, private, unavailable
from uuid import UUID
import psycopg
from flask import Blueprint, current_app, jsonify, request
from services import recommendation_context as store

agent_context = Blueprint('agent_context', __name__, url_prefix='/internal')


agent_context.before_request(authorize)


agent_context.after_request(private)


agent_context.errorhandler(psycopg.Error)(unavailable)


@agent_context.get('/recommendation-users')
def users():
    try:
        after = str(UUID(request.args['after'])) if 'after' in request.args else None
        limit = int(request.args.get('limit', '100'))
        if not 1 <= limit <= 1000:
            raise ValueError()
    except ValueError:
        return jsonify(error='Use an after UUID and limit 1–1000.'), 400
    return jsonify(store.users(current_app.config['DATABASE_URL'], after, limit))


@agent_context.get('/recommendation-context/<user_id>')
def context(user_id):
    try:
        user_id = str(UUID(user_id))
        watched_offset = int(request.args.get('watched_offset', '0'))
        watchlist_offset = int(request.args.get('watchlist_offset', '0'))
        limit = int(request.args.get('limit', '100'))
        if not 0 <= watched_offset <= 1000000 or not 0 <= watchlist_offset <= 1000000 or not 1 <= limit <= 1000:
            raise ValueError()
    except ValueError:
        return jsonify(error='Use a user UUID, offsets 0–1000000 and limit 1–1000.'), 400
    result = store.context(current_app.config['DATABASE_URL'], user_id, watched_offset, watchlist_offset, limit)
    return (jsonify(result), 200) if result else (jsonify(error='User not found.'), 404)
