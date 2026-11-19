from types import SimpleNamespace

import psycopg
import pytest

from api import auth
from main import create_app

HEADERS = {'X-G15-Request': '1'}
DETAILS = dict(username='reader', display_name='Reader', email='reader@example.test',
               password='read', password_confirmation='read')
USER = dict(id='test-id', username='reader', display_name='Reader', email='reader@example.test')


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'test-only')
    monkeypatch.setenv('AUTH_COOKIE_SECURE', 'false')
    return create_app()


@pytest.mark.parametrize('path', ['/auth/register', '/auth/login', '/auth/logout'])
def test_mutations_require_same_origin_json(app, path):
    assert app.test_client().post(path, json=DETAILS).status_code == 403
    assert app.test_client().post(path, data='raw', headers=HEADERS).status_code == 403
    assert app.test_client().post(path, json=DETAILS,
                                  headers=HEADERS | {'Sec-Fetch-Site': 'cross-site'}).status_code == 403


@pytest.mark.parametrize('changes,message', [
    ({'username': None}, 'Username is required.'),
    ({'username': ' '}, 'Username is required.'),
    ({'username': 'bad name'}, 'Username must be'),
    ({'email': 'bad'}, 'Enter a valid email'),
    ({'email': None}, 'Email and password'),
    ({'password': ''}, 'Password is required.'),
    ({'display_name': ''}, 'Display name must'),
    ({'password_confirmation': 'wrong'}, 'Your passwords do not match.'),
])
def test_invalid_registration_is_rejected(app, changes, message):
    response = app.test_client().post('/auth/register', json=DETAILS | changes, headers=HEADERS)
    assert response.status_code == 400
    assert message in response.json['error']


def test_non_object_payload_is_rejected(app):
    assert app.test_client().post('/auth/register', json=[], headers=HEADERS).status_code == 400


def test_registration_normalizes_identity_and_sets_cookie(app, monkeypatch):
    captured = {}
    def register(url, **kwargs):
        captured.update(kwargs)
        return USER, 'opaque-test-token'
    monkeypatch.setattr(auth.accounts, 'register', register)
    response = app.test_client().post('/auth/register', json=DETAILS | {
        'username': ' READER ', 'email': ' Reader@Example.Test ', 'display_name': ' Reader '
    }, headers=HEADERS)
    assert response.status_code == 201
    assert captured['username'] == 'reader'
    assert captured['email'] == 'reader@example.test'
    assert captured['display_name'] == 'Reader'
    assert response.json['user'] == USER
    assert 'HttpOnly' in response.headers['Set-Cookie']
    assert 'SameSite=Lax' in response.headers['Set-Cookie']
    assert 'Path=/api/user' in response.headers['Set-Cookie']
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('constraint,message', [('users_username_unique', 'Username already exists.'),
                                              ('users_email_unique', 'Email already exists.')])
def test_duplicate_identity_has_clear_message(app, monkeypatch, constraint, message):
    class Duplicate(psycopg.errors.UniqueViolation):
        @property
        def diag(self):
            return SimpleNamespace(constraint_name=constraint)
    def fail(*args, **kwargs):
        raise Duplicate()
    monkeypatch.setattr(auth.accounts, 'register', fail)
    response = app.test_client().post('/auth/register', json=DETAILS, headers=HEADERS)
    assert response.status_code == 409
    assert response.json['error'] == message


@pytest.mark.parametrize('result,status', [(None, 401), ((USER, 'token'), 200)])
def test_login_response(app, monkeypatch, result, status):
    monkeypatch.setattr(auth.accounts, 'login', lambda *args, **kwargs: result)
    assert app.test_client().post('/auth/login', json=DETAILS, headers=HEADERS).status_code == status


@pytest.mark.parametrize('result,status', [(None, 401), (USER, 200)])
def test_current_user_requires_session(app, monkeypatch, result, status):
    monkeypatch.setattr(auth.accounts, 'current_user', lambda *args: result)
    assert app.test_client().get('/auth/me').status_code == status


def test_logout_clears_cookie(app, monkeypatch):
    monkeypatch.setattr(auth.accounts, 'logout', lambda *args: None)
    response = app.test_client().post('/auth/logout', json={}, headers=HEADERS)
    assert response.status_code == 200
    assert 'Max-Age=0' in response.headers['Set-Cookie']


def test_database_failure_does_not_expose_details(app, monkeypatch):
    def fail(*args, **kwargs):
        raise psycopg.OperationalError('private database password')
    monkeypatch.setattr(auth.accounts, 'login', fail)
    response = app.test_client().post('/auth/login', json=DETAILS, headers=HEADERS)
    assert response.status_code == 503
    assert b'private database password' not in response.data


def test_invalid_login_credentials(app):
    response = app.test_client().post('/auth/login', json={'email': 'invalid', 'password': ''}, headers=HEADERS)
    assert response.status_code == 400
    assert 'error' in response.json
