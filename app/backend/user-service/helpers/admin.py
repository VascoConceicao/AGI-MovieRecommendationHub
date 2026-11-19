"""HTTP helpers extracted from admin routes."""
from helpers.responses import no_cache
from flask import jsonify


def database_error(exception):
    return jsonify(error='User database is unavailable. No reset was committed.'), 503
