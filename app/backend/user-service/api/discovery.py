"""Session-authenticated discovery of public profiles."""
from uuid import UUID
from urllib.parse import urlencode
from flask import Blueprint, current_app, jsonify, request
import psycopg
from helpers.profile import session, private, unavailable
from services import discovery, recommendations, profiles

users = Blueprint('users', __name__, url_prefix='/users')
users.before_request(session)
users.after_request(private)
users.errorhandler(psycopg.Error)(unavailable)


def offset():
    value = int(request.args.get('offset', '0'))
    if not 0 <= value <= 1000000:
        raise ValueError()
    return value


@users.get('')
def search():
    try:
        start = offset()
        query = request.args.get('q', '').strip()
        limit = int(request.args.get('limit', '25'))
        seed = str(UUID(request.args['seed'])) if 'seed' in request.args else None
        if len(query) > 200 or not 1 <= limit <= 1000:
            raise ValueError()
    except ValueError:
        return jsonify(error='Invalid search, offset, limit (1–1000), or seed UUID.'), 400
    return jsonify(discovery.search(current_app.config['DATABASE_URL'], query, start, limit, seed))


@users.get('/<user_id>')
def public_profile(user_id):
    try:
        user_id = str(UUID(user_id))
    except ValueError:
        return jsonify(error='Profile not found.'), 404
    try:
        start = offset()
    except ValueError:
        return jsonify(error='offset must be between 0 and 1000000.'), 400
    section = request.args.get('section', 'watched')
    if section not in ('watchlist', 'watched', 'recommendations'):
        return jsonify(error='section must be watchlist, watched, or recommendations.'), 400
    search = request.args.get('q', '').strip()
    if len(search) > 200:
        return jsonify(error='Search must be 200 characters or fewer.'), 400
    try:
        result = discovery.public_profile(current_app.config['DATABASE_URL'], user_id, start, section,
                                          search, current_app.config['MOVIE_SERVICE_URL'])
    except profiles.SearchUnavailable:
        return jsonify(error='Movie search unavailable. Please retry.'), 503
    # Recheck visibility after movie duration/search requests finish.
    if result is None or not discovery.is_public(current_app.config['DATABASE_URL'], user_id):
        return jsonify(error='Profile not found.'), 404
    if section == 'recommendations':
        query = urlencode({'user_id': user_id, 'source': 'all', 'offset': start, 'limit': 25})
        body, status = (recommendations.search(current_app.config, user_id, 'all', start, search) if search
                        else recommendations.call(current_app.config, '/recommendations?' + query))
        # A profile can become private while the other service is responding.
        if not discovery.is_public(current_app.config['DATABASE_URL'], user_id):
            return jsonify(error='Profile not found.'), 404
        if status != 200:
            return jsonify(body), status
        result['collection'] = {
            'items': [{key: item.get(key) for key in ('id', 'movie_id', 'reason', 'source')}
                      for item in body['items']],
            'total': body['total'], 'offset': start, 'limit': 25,
        }
    return jsonify(result)
