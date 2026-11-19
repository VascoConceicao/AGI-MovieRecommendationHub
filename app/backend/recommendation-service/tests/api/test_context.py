from unittest.mock import Mock

import pytest
from main import create_app
from api import context as api

ID = '00000000-0000-0000-0000-000000000001'
HEADERS = {'Authorization': 'Bearer test'}


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True, RECOMMENDATION_API_TOKEN='test')
    return app.test_client()


@pytest.mark.parametrize('query', ['after=bad', 'limit=no', 'limit=0', 'limit=1001'])
def test_invalid_user_query(client, query):
    assert client.get('/context/users?' + query, headers=HEADERS).status_code == 400


def test_users_gateway_and_auth(client, monkeypatch):
    fetch = Mock(return_value=({'user_ids': [ID]}, 200))
    monkeypatch.setattr(api.service, 'fetch', fetch)
    assert client.get('/context/users').status_code == 401
    fetch.assert_not_called()
    response = client.get('/context/users', headers=HEADERS)
    assert response.json == {'user_ids': [ID]}
    assert response.headers['Cache-Control'] == 'no-store'
    assert fetch.call_args.args[1:] == ('/internal/recommendation-users', {'limit': 100})
    assert client.get('/context/users?after=' + ID + '&limit=2', headers=HEADERS).status_code == 200
    assert fetch.call_args.args[2] == {'limit': 2, 'after': ID}


@pytest.mark.parametrize('suffix', ['bad', ID + '?limit=no', ID + '?limit=0', ID + '?limit=1001',
    ID + '?watched_offset=-1', ID + '?watchlist_offset=1000001'])
def test_invalid_context_query(client, suffix):
    assert client.get('/context/users/' + suffix, headers=HEADERS).status_code == 400


def test_context_gateway_preserves_status(client, monkeypatch):
    fetch = Mock(return_value=({'error': 'User not found.'}, 404))
    monkeypatch.setattr(api.service, 'fetch', fetch)
    response = client.get('/context/users/' + ID + '?watched_offset=5&watchlist_offset=10&limit=20', headers=HEADERS)
    assert response.status_code == 404
    assert response.json == {'error': 'User not found.'}
    assert fetch.call_args.args[1:] == ('/internal/recommendation-context/' + ID,
                                      {'watched_offset': 5, 'watchlist_offset': 10, 'limit': 20})
