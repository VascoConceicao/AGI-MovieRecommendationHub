"""HTTP helpers extracted from auth routes."""
from helpers.responses import no_cache as private_response
import re
from flask import current_app, jsonify, request
from services import accounts

COOKIE = 'g15_session'
COOKIE_PATH = '/api/user'


def error(message, status):
    return jsonify(error=message), status


def protect_mutations():
    if request.method == 'POST':
        # A foreign site cannot set this header without a CORS preflight.
        # This service deliberately grants no cross-origin access.
        if request.headers.get('X-G15-Request') != '1' or not request.is_json:
            return error('A same-origin JSON request is required.', 403)
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            return error('Cross-site requests are not allowed.', 403)
    return None


def database_error(exception):
    # Never return SQL, credentials or database exception strings to the browser.
    return error('Account service is unavailable. Please try again shortly.', 503)


def credentials(registering=False):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, 'Please provide your account details.'
    email, password = data.get('email'), data.get('password')
    if not isinstance(email, str) or not isinstance(password, str):
        return None, 'Email and password are required.'
    email = email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return None, 'Enter a valid email address.'
    if not password:
        return None, 'Password is required.'
    result = {'email': email, 'password': password}
    if registering:
        username = data.get('username')
        if username is None or (isinstance(username, str) and not username.strip()):
            return None, 'Username is required.'
        if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', username.strip()):
            return None, 'Username must be 1–80 letters, numbers, dots, underscores or hyphens.'
        result['username'] = username.strip().lower()
        name = data.get('display_name')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            return None, 'Display name must contain between 1 and 80 characters.'
        if data.get('password_confirmation') != password:
            return None, 'Your passwords do not match.'
        result['display_name'] = name.strip()
    return result, None


def signed_in(result, status=200):
    user, token = result
    response = jsonify(user=user)
    response.status_code = status
    response.set_cookie(COOKIE, token, max_age=accounts.SESSION_SECONDS,
                        httponly=True, secure=current_app.config['AUTH_COOKIE_SECURE'],
                        samesite='Lax', path=COOKIE_PATH)
    return response
