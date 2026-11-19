from unittest.mock import Mock

import psycopg
import pytest
from main import create_app
from api import recommendation_context as api

ID = '00000000-0000-0000-0000-000000000001'
HEADERS = {'Authorization': 'Bearer test'}


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True, DATABASE_URL='test-only', AGENT_CONTEXT_TOKEN='test')
    return app.test_client()


def test_authorization(client):
    assert client.get('/internal/recommendation-users').status_code == 401
    assert client.get('/internal/recommendation-users', headers={**HEADERS, 'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    client.application.config['AGENT_CONTEXT_TOKEN'] = ''
    response = client.get('/internal/recommendation-users')
    assert response.status_code == 404
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('query', ['after=bad', 'limit=no', 'limit=0', 'limit=1001'])
def test_invalid_users_query(client, query):
    assert client.get('/internal/recommendation-users?' + query, headers=HEADERS).status_code == 400


def test_users_and_db_error(client, monkeypatch):
    users = Mock(return_value={'user_ids': [ID], 'next_cursor': None})
    monkeypatch.setattr(api.store, 'users', users)
    assert client.get('/internal/recommendation-users', headers=HEADERS).json == users.return_value
    users.assert_called_with('test-only', None, 100)
    assert client.get('/internal/recommendation-users?after=' + ID + '&limit=1000', headers=HEADERS).status_code == 200
    users.assert_called_with('test-only', ID, 1000)
    users.side_effect = psycopg.OperationalError('offline')
    assert client.get('/internal/recommendation-users', headers=HEADERS).status_code == 503


@pytest.mark.parametrize('suffix', ['bad', ID + '?watched_offset=-1', ID + '?watched_offset=1000001',
    ID + '?watchlist_offset=-1', ID + '?watchlist_offset=1000001', ID + '?limit=0', ID + '?limit=1001', ID + '?limit=no'])
def test_invalid_context_query(client, suffix):
    assert client.get('/internal/recommendation-context/' + suffix, headers=HEADERS).status_code == 400


def test_context_and_missing_user(client, monkeypatch):
    context = Mock(return_value={'user_id': ID, 'watched': []})
    monkeypatch.setattr(api.store, 'context', context)
    assert client.get('/internal/recommendation-context/' + ID, headers=HEADERS).json == context.return_value
    context.assert_called_once_with('test-only', ID, 0, 0, 100)
    context.return_value = None
    assert client.get('/internal/recommendation-context/' + ID, headers=HEADERS).status_code == 404
