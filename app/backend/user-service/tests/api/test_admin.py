import pytest

from api import admin
from main import create_app


@pytest.fixture
def app():
    app = create_app()
    app.config.update(AUTH_RESET_ENABLED=True, AUTH_RESET_TOKEN='test-reset-token')
    return app


def test_reset_disabled_by_default(app):
    app.config['AUTH_RESET_ENABLED'] = False
    assert app.test_client().post('/admin/reset-user-db', json={'table': 'all'}).status_code == 404


def test_reset_requires_token(app):
    assert app.test_client().post('/admin/reset-user-db', json={'table': 'all'}).status_code == 401


@pytest.mark.parametrize('body', [{}, {'table': 'unknown'}, {'table': 1}, {'table': 'all', 'extra': 1}, []])
def test_invalid_reset_payload_is_rejected(app, body):
    response = app.test_client().post('/admin/reset-user-db', json=body,
                                      headers={'Authorization': 'Bearer test-reset-token'})
    assert response.status_code == 400


@pytest.mark.parametrize('table', ['all', 'users', 'user_profiles', 'user_sessions'])
def test_reset_calls_only_selected_table(app, monkeypatch, table):
    calls = []
    def clear(url, selection):
        calls.append(selection)
        return {'cleared_tables': [selection], 'deleted_rows': {selection: 2}}
    monkeypatch.setattr(admin, 'clear_tables', clear)
    response = app.test_client().post('/admin/reset-user-db', json={'table': table},
                                      headers={'Authorization': 'Bearer test-reset-token'})
    assert response.status_code == 200
    assert calls == [table]
    assert response.headers['Cache-Control'] == 'no-store'


def test_cross_site_reset_is_rejected(app):
    response = app.test_client().post('/admin/reset-user-db', json={'table': 'all'},
        headers={'Authorization': 'Bearer test-reset-token', 'Sec-Fetch-Site': 'cross-site'})
    assert response.status_code == 403


def test_reset_requires_json(app):
    assert app.test_client().post('/admin/reset-user-db', data='raw',
        headers={'Authorization': 'Bearer test-reset-token'}).status_code == 400


def test_database_error_does_not_expose_details(app, monkeypatch):
    from unittest.mock import Mock
    import psycopg
    monkeypatch.setattr(admin, 'clear_tables', Mock(side_effect=psycopg.OperationalError('private')))
    response = app.test_client().post('/admin/reset-user-db', json={'table': 'all'},
                                      headers={'Authorization': 'Bearer test-reset-token'})
    assert response.status_code == 503
    assert b'private' not in response.data
