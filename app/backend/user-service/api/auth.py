"""Same-origin JSON authentication API; cookies contain only opaque tokens."""
from helpers.auth import COOKIE, COOKIE_PATH
from helpers.auth import error, protect_mutations, private_response, database_error, credentials, signed_in

from flask import Blueprint, current_app, jsonify, request
import psycopg
from services import accounts

auth = Blueprint('auth', __name__, url_prefix='/auth')


auth.before_request(protect_mutations)


auth.after_request(private_response)


auth.errorhandler(psycopg.Error)(database_error)


@auth.post('/register')
def register():
    data, message = credentials(registering=True)
    if message:
        return error(message, 400)
    try:
        result = accounts.register(current_app.config['DATABASE_URL'], **data,
                                   previous_token=request.cookies.get(COOKIE))
    except psycopg.errors.UniqueViolation as exception:
        if exception.diag.constraint_name == 'users_username_unique':
            return error('Username already exists.', 409)
        return error('Email already exists.', 409)
    return signed_in(result, 201)


@auth.post('/login')
def login():
    data, message = credentials()
    if message:
        return error(message, 400)
    result = accounts.login(current_app.config['DATABASE_URL'], **data,
                            previous_token=request.cookies.get(COOKIE))
    if result is None:
        return error('Email or password is incorrect.', 401)
    return signed_in(result)


@auth.get('/me')
def me():
    user = accounts.current_user(current_app.config['DATABASE_URL'], request.cookies.get(COOKIE))
    if not user:
        return error('Please sign in to continue.', 401)
    return jsonify(user=user)


@auth.post('/logout')
def logout():
    accounts.logout(current_app.config['DATABASE_URL'], request.cookies.get(COOKIE))
    response = jsonify(message='Signed out.')
    response.delete_cookie(COOKIE, path=COOKIE_PATH,
                           secure=current_app.config['AUTH_COOKIE_SECURE'],
                           httponly=True, samesite='Lax')
    return response
