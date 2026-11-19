"""Current-user profile, privacy, and movie lists."""
from helpers.profile import session, private, unavailable
from uuid import UUID
from helpers.security import authorize_cleanup
from flask import Blueprint, current_app, jsonify, request, g, Response
import psycopg
from helpers.auth import COOKIE
from services import accounts, profiles, history_events
from services import recommendations

profile = Blueprint('profile', __name__, url_prefix='/profile')
internal = Blueprint('internal', __name__, url_prefix='/internal')


profile.before_request(session)


profile.after_request(private)
internal.after_request(private)


profile.errorhandler(psycopg.Error)(unavailable)
internal.errorhandler(psycopg.Error)(unavailable)


@profile.get('')
def get_profile():
    return jsonify(profile=profiles.profile(current_app.config['DATABASE_URL'], g.user['id']))


@profile.get('/recommendation-filters')
def recommendation_filters():
    body, status = recommendations.call(current_app.config, '/recommendation-filters')
    return jsonify(body), status


@profile.post('/recommendation-requests')
def request_recommendations():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'filters'}:
        return jsonify(error='Provide filters only.'), 400
    body, status = recommendations.call(current_app.config, '/context/recommendation-requests',
                                        {'user_id': str(g.user['id']), 'filters': data['filters']})
    return jsonify(body), status


@profile.post('/recommendation-generations')
def start_generation():
    """Queue a real user-requested generation. The user comes from the session, never from the request."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'filters'}:
        return jsonify(error='Provide filters only.'), 400
    body, status, headers = recommendations.generation_call(
        current_app.config, '/recommendations/generate', {'user_id': str(g.user['id']), 'filters': data['filters']})
    return jsonify(body), status, headers


@profile.get('/recommendation-generations/<job_id>')
def generation_status(job_id):
    """Status of a generation job; the Recommendation Service only answers for the session user's own jobs."""
    from urllib.parse import urlencode
    try:
        job_id = str(UUID(job_id))
    except ValueError:
        return jsonify(error='Invalid generation id.'), 400
    body, status, headers = recommendations.generation_call(
        current_app.config, f"/recommendations/generations/{job_id}?" + urlencode({'user_id': str(g.user['id'])}))
    return jsonify(body), status, headers


@profile.get('/recommendations')
def saved_recommendations():
    from urllib.parse import urlencode
    search = request.args.get('q', '').strip()
    if len(search) > 200:
        return jsonify(error='Search must be 200 characters or fewer.'), 400
    if search:
        try:
            offset = int(request.args.get('offset', '0'))
            source = request.args.get('source', 'all')
            if not 0 <= offset <= 1000000 or source not in ('all', 'auto', 'user_requested'):
                raise ValueError()
        except ValueError:
            return jsonify(error='Invalid offset or recommendation source.'), 400
        body, status = recommendations.search(current_app.config, g.user['id'], source, offset, search)
        return jsonify(body), status
    query = urlencode({'user_id': str(g.user['id']), 'source': request.args.get('source', 'all'),
                       'offset': request.args.get('offset', '0'), 'limit': '25'})
    body, status = recommendations.call(current_app.config, '/recommendations?' + query)
    return jsonify(body), status


@profile.post('/avatar')
def set_avatar():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'avatar_id'} or type(data['avatar_id']) is not int or not 1 <= data['avatar_id'] <= 10:
        return jsonify(error='avatar_id must be an integer from 1 to 10.'), 400
    return jsonify(profile=profiles.avatar(current_app.config['DATABASE_URL'], g.user['id'], data['avatar_id']))


@profile.get('/watched')
def watched():
    try:
        offset = int(request.args.get('offset', '0'))
        if not 0 <= offset <= 1000000:
            raise ValueError()
    except ValueError:
        return jsonify(error='offset must be between 0 and 1000000.'), 400
    query = request.args.get('q', '').strip()
    if len(query) > 200:
        return jsonify(error='Search must be 200 characters or fewer.'), 400
    try:
        return jsonify(profiles.history(current_app.config['DATABASE_URL'], g.user['id'], offset, current_app.config['MOVIE_SERVICE_URL'], query))
    except profiles.SearchUnavailable:
        return jsonify(error='Movie search unavailable. Please retry.'), 503


@profile.post('/watched/remove')
def remove_watched():
    data = request.get_json(silent=True)
    try:
        if not isinstance(data, dict) or set(data) != {'movie_id'} or not isinstance(data['movie_id'], str):
            raise ValueError()
        movie_id = str(UUID(data['movie_id']))
    except ValueError:
        return jsonify(error='Provide movie_id as a UUID.'), 400
    return jsonify(profiles.mark_unwatched(current_app.config['DATABASE_URL'], g.user['id'], movie_id))


@profile.post('/watched/move-to-list')
def move_watched_to_list():
    data = request.get_json(silent=True)
    try:
        if not isinstance(data, dict) or set(data) != {'movie_id'} or not isinstance(data['movie_id'], str):
            raise ValueError()
        movie_id = str(UUID(data['movie_id']))
    except ValueError:
        return jsonify(error='Provide movie_id as a UUID.'), 400
    try:
        return jsonify(profiles.move_to_watchlist(current_app.config['DATABASE_URL'], g.user['id'], movie_id,
                                                  current_app.config['MOVIE_SERVICE_URL']))
    except profiles.SearchUnavailable:
        return jsonify(error='Movie service unavailable. Please retry.'), 503
    except ValueError as error:
        return jsonify(error=str(error)), 404


@internal.post('/clear-watched')
def clear_watched():
    request.max_content_length = 8 * 1024 * 1024
    denied = authorize_cleanup()
    if denied:
        return denied
    data = request.get_json(silent=True)
    try:
        if not isinstance(data, dict) or set(data) != {'operation_id', 'movie_ids'} or not isinstance(data['movie_ids'], list):
            raise ValueError()
        operation_id = str(UUID(data['operation_id']))
        ids = [str(UUID(value)) for value in data['movie_ids']]
    except (ValueError, TypeError, AttributeError):
        return jsonify(error='Provide operation_id UUID and movie_ids UUID array.'), 400
    count = profiles.cleanup(current_app.config['DATABASE_URL'], operation_id, ids)
    return jsonify(operation_id=operation_id, deleted_rows=count)


@profile.get('/events')
def events():
    try:
        stream, close = history_events.subscribe(current_app.config['DATABASE_URL'], g.user['id'], request.cookies.get(COOKIE))
    except history_events.StreamBusy:
        return jsonify(error='Live update capacity reached. Reconnecting shortly.'), 503
    response = Response(stream, mimetype='text/event-stream', headers={'X-Accel-Buffering': 'no'})
    response.call_on_close(close)
    return response


@profile.get('/watchlist')
def get_watchlist():
    return jsonify(profiles.watchlist(current_app.config['DATABASE_URL'], g.user['id']))


@profile.post('/watchlist')
def set_watchlist():
    data = request.get_json(silent=True)
    try:
        if not isinstance(data, dict) or set(data) != {'movie_id', 'add'} or type(data['add']) is not bool or not isinstance(data['movie_id'], str):
            raise ValueError()
        movie_id = str(UUID(data['movie_id']))
    except ValueError:
        return jsonify(error='Provide movie_id UUID and add boolean.'), 400
    try:
        return jsonify(profiles.update_watchlist(current_app.config['DATABASE_URL'], g.user['id'], movie_id,
                       data['add'], current_app.config['MOVIE_SERVICE_URL']))
    except profiles.AlreadyWatched:
        return jsonify(error='Movie is already watched.'), 409
    except profiles.SearchUnavailable:
        return jsonify(error='Movie service unavailable. Please retry.'), 503
    except ValueError as error:
        return jsonify(error=str(error)), 404


@profile.post('/watched/add')
def add_watched():
    data = request.get_json(silent=True)
    try:
        if not isinstance(data, dict) or set(data) != {'movie_id'} or not isinstance(data['movie_id'], str):
            raise ValueError()
        movie_id = str(UUID(data['movie_id']))
    except ValueError:
        return jsonify(error='Provide movie_id as a UUID.'), 400
    try:
        return jsonify(profiles.mark_watched(current_app.config['DATABASE_URL'], g.user['id'], movie_id,
                                            current_app.config['MOVIE_SERVICE_URL']))
    except profiles.SearchUnavailable:
        return jsonify(error='Movie service unavailable. Please retry.'), 503
    except ValueError as error:
        return jsonify(error=str(error)), 404


@profile.post('/visibility')
def set_visibility():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'is_public'} or type(data['is_public']) is not bool:
        return jsonify(error='Provide is_public as a boolean.'), 400
    return jsonify(profile=profiles.visibility(current_app.config['DATABASE_URL'], g.user['id'], data['is_public']))


@profile.get('/watchlist/search')
def search_watchlist():
    try:
        offset = int(request.args.get('offset', '0'))
        query = request.args.get('q', '').strip()
        if not 0 <= offset <= 1000000 or len(query) > 200:
            raise ValueError()
    except ValueError:
        return jsonify(error='Invalid offset or search (maximum 200 characters).'), 400
    try:
        return jsonify(profiles.search_watchlist(current_app.config['DATABASE_URL'], g.user['id'], query,
                                                offset, current_app.config['MOVIE_SERVICE_URL']))
    except profiles.SearchUnavailable:
        return jsonify(error='Movie search unavailable. Please retry.'), 503
