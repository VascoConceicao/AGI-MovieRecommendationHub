"""HTTP helpers extracted from profile routes."""
from helpers.responses import no_cache as private
from flask import current_app, jsonify, request, g
from helpers.auth import COOKIE
from services import accounts


def session():
    if request.method == 'POST' and (request.headers.get('X-G15-Request') != '1' or not request.is_json
                                    or request.headers.get('Sec-Fetch-Site') == 'cross-site'):
        return jsonify(error='A same-origin JSON request is required.'), 403
    g.user = accounts.current_user(current_app.config['DATABASE_URL'], request.cookies.get(COOKIE))
    if not g.user:
        return jsonify(error='Please sign in to continue.'), 401


def unavailable(exception):
    return jsonify(error='User database unavailable. Please retry.'), 503
