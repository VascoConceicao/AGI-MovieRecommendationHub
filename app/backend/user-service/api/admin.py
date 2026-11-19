"""Opt-in reset API for local account-data management."""
from helpers.admin import no_cache, database_error

from helpers.security import authorize_reset
from flask import Blueprint, current_app, jsonify, request
import psycopg
from services.reset import TABLES, clear_tables

admin = Blueprint('admin', __name__, url_prefix='/admin')


admin.after_request(no_cache)


admin.errorhandler(psycopg.Error)(database_error)


@admin.post('/reset-user-db')
def reset_user_db():
    denied = authorize_reset()
    if denied:
        return denied
    if not request.is_json:
        return jsonify(error='Use Content-Type: application/json.'), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'table'} or not isinstance(data['table'], str):
        return jsonify(error='Provide exactly one field: table.'), 400
    table = data['table']
    if table not in (*TABLES, 'all'):
        return jsonify(error='table must be all, users, user_profiles, user_sessions, watched_movies, or watchlist_movies.'), 400
    return jsonify(clear_tables(current_app.config['DATABASE_URL'], table))
