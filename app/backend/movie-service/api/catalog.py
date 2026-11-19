"""Movie API: local reads and token-protected agent writes/reset."""
from helpers.http import authorize, no_cache, unavailable
from pathlib import Path
import re
from uuid import UUID
from flask import Blueprint, current_app, jsonify, request, send_from_directory
import psycopg
from services import catalog, reset

movies = Blueprint('movies', __name__)


movies.after_request(no_cache)


movies.errorhandler(psycopg.Error)(unavailable)


@movies.get('/movies')
def batch():
    if 'ids' not in request.args:
        try:
            offset = int(request.args.get('offset', '0'))
            query = request.args.get('q', '').strip()
            seed = str(UUID(request.args['seed'])) if 'seed' in request.args else None
            limit = int(request.args.get('limit', '25'))
            if not 0 <= offset <= 1000000 or len(query) > 200 or not 1 <= limit <= 1000:
                raise ValueError()
        except ValueError:
            return jsonify(error='Invalid search, offset, limit (1–1000), or seed UUID.'), 400
        if seed or limit != 25:
            return jsonify(catalog.browse(current_app.config['DATABASE_URL'], query, offset, seed=seed, limit=limit))
        return jsonify(catalog.browse(current_app.config['DATABASE_URL'], query, offset))
    raw = request.args.get('ids', '')
    try:
        ids = [str(UUID(value)) for value in raw.split(',') if value]
        if not 1 <= len(ids) <= 50:
            raise ValueError()
    except ValueError:
        return jsonify(error='Provide 1–50 comma-separated movie UUIDs in ids.'), 400
    return jsonify(movies=catalog.lookup(current_app.config['DATABASE_URL'], ids))


@movies.post('/movies')
def create():
    denied = authorize('MOVIE_WRITE_TOKEN')
    if denied:
        return denied
    try:
        data = request.get_json(silent=True)
        values = catalog.validate(data)
        if values['poster_key'] and not (Path(current_app.config['MOVIE_MEDIA_DIR']) / values['poster_key']).is_file():
            raise ValueError('poster_key does not exist in local poster storage.')
        movie, created = catalog.create(current_app.config['DATABASE_URL'], data)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except catalog.ResetPending:
        return jsonify(error='Catalog cleanup pending. Retry after reset completes.'), 503
    return jsonify(movie=movie, created=created), 201 if created else 200


@movies.get('/posters/<key>')
def poster(key):
    if not re.fullmatch(r'[a-f0-9]{64}\.jpg', key):
        return jsonify(error='Poster not found.'), 404
    return send_from_directory(current_app.config['MOVIE_MEDIA_DIR'], key, mimetype='image/jpeg')


@movies.post('/admin/reset-movie-db')
def clear():
    denied = authorize('MOVIE_RESET_TOKEN', current_app.config['MOVIE_RESET_ENABLED'])
    if denied:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'table'} or data['table'] not in ('all', 'movies'):
        return jsonify(error='Provide table: all or movies.'), 400
    try:
        return jsonify(reset.clear(current_app.config))
    except reset.CleanupPending as error:
        return jsonify(error=str(error), cleanup_pending=True), 503


@movies.post('/movies/duration')
def duration_summary():
    data = request.get_json(silent=True)
    try:
        if not isinstance(data, dict) or set(data) != {'ids'} or not isinstance(data['ids'], list) or not 1 <= len(data['ids']) <= 1000:
            raise ValueError()
        ids = [str(UUID(value)) for value in data['ids']]
    except (ValueError, TypeError, AttributeError):
        return jsonify(error='Provide ids: an array of 1–1000 movie UUIDs.'), 400
    return jsonify(catalog.duration_summary(current_app.config['DATABASE_URL'], ids))


@movies.get('/movies/ids')
def movie_ids():
    try:
        after = str(UUID(request.args['after'])) if 'after' in request.args else None
    except ValueError:
        return jsonify(error='after must be a movie UUID.'), 400
    return jsonify(catalog.movie_ids(current_app.config['DATABASE_URL'], after))


@movies.get('/movies/filter-options')
def filter_options():
    return jsonify(catalog.filter_options(current_app.config['DATABASE_URL']))


@movies.post('/movies/browse')
def browse_movies():
    data = request.get_json(silent=True)
    try:
        if not isinstance(data, dict) or set(data) - {'offset', 'q', 'exclude_ids'}:
            raise ValueError()
        offset = data.get('offset', 0)
        query = data.get('q', '')
        excluded = data.get('exclude_ids', [])
        if type(offset) is not int or not 0 <= offset <= 1000000 or not isinstance(query, str) or len(query) > 200 or not isinstance(excluded, list) or len(excluded) > 10000:
            raise ValueError()
        ids = [str(UUID(value)) for value in excluded]
    except (ValueError, TypeError, AttributeError):
        return jsonify(error='Invalid movie search parameters.'), 400
    return jsonify(catalog.browse(current_app.config['DATABASE_URL'], query.strip(), offset, ids))
