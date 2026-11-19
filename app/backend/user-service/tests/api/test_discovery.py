from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
import psycopg
from main import create_app
from api import discovery as api
from services import accounts

ID = '00000000-0000-0000-0000-000000000001'


@pytest.fixture
def client(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True, DATABASE_URL='test-only', MOVIE_SERVICE_URL='http://movie')
    monkeypatch.setattr(accounts, 'current_user', Mock(return_value={'id': ID}))
    monkeypatch.setattr(api.discovery, 'search', Mock(return_value={'users': []}))
    monkeypatch.setattr(api.discovery, 'public_profile', Mock(return_value={'profile': {'id': ID}}))
    monkeypatch.setattr(api.discovery, 'is_public', Mock(return_value=True))
    return app.test_client()


@pytest.mark.parametrize('query', ['offset=no', 'offset=-1', 'offset=1000001', 'limit=0', 'limit=1001', 'seed=bad', 'q=' + 'a'*201])
def test_invalid_search(client, query):
    assert client.get('/users?' + query).status_code == 400
    api.discovery.search.assert_not_called()


def test_search(client):
    assert client.get('/users').json == {'users': []}
    api.discovery.search.assert_called_with('test-only', '', 0, 25, None)
    assert client.get('/users', query_string={'q': ' alice ', 'offset': 1000000, 'limit': 1000, 'seed': ID}).status_code == 200
    api.discovery.search.assert_called_with('test-only', 'alice', 1000000, 1000, ID)


@pytest.mark.parametrize('path,status', [('bad', 404), (ID+'?offset=bad', 400), (ID+'?section=bad', 400), (ID+'?q='+'a'*201, 400)])
def test_invalid_profile(client, path, status):
    assert client.get('/users/' + path).status_code == status
    api.discovery.public_profile.assert_not_called()


def test_public_profile(client):
    response = client.get('/users/' + ID)
    assert response.json == {'profile': {'id': ID}}
    assert response.headers['Cache-Control'] == 'no-store'
    api.discovery.public_profile.assert_called_once_with('test-only', ID, 0, 'watched', '', 'http://movie')


@pytest.mark.parametrize('missing', [True, False])
def test_hidden_profile(client, missing):
    if missing:
        api.discovery.public_profile.return_value = None
    else:
        api.discovery.is_public.return_value = False
    assert client.get('/users/' + ID).status_code == 404


def test_unavailable(client):
    api.discovery.public_profile.side_effect = api.profiles.SearchUnavailable()
    assert client.get('/users/' + ID).status_code == 503
    api.discovery.public_profile.side_effect = psycopg.OperationalError('secret')
    response = client.get('/users/' + ID)
    assert response.status_code == 503
    assert b'secret' not in response.data
    accounts.current_user.return_value = None
    assert client.get('/users').status_code == 401


@pytest.mark.parametrize('query', ['', 'title'])
@pytest.mark.parametrize('status,visible', [(200, True), (503, True), (200, False)])
def test_recommendations(client, monkeypatch, query, status, visible):
    body = {'items': [{'id': 'rec', 'movie_id': 'movie', 'reason': 'why', 'source': 'auto', 'private': 'secret'}], 'total': 1} if status == 200 else {'error': 'unavailable'}
    call = Mock(return_value=(body, status))
    search = Mock(return_value=(body, status))
    monkeypatch.setattr(api.recommendations, 'call', call)
    monkeypatch.setattr(api.recommendations, 'search', search)
    api.discovery.is_public.side_effect = [True, visible]
    response = client.get('/users/' + ID, query_string={'section': 'recommendations', 'offset': 25, 'q': query})
    assert response.status_code == (status if visible else 404)
    if query:
        search.assert_called_once_with(client.application.config, ID, 'all', 25, query)
        call.assert_not_called()
    else:
        assert parse_qs(urlsplit(call.call_args.args[1]).query) == {'user_id': [ID], 'source': ['all'], 'offset': ['25'], 'limit': ['25']}
    if visible and status == 200:
        assert response.json['collection'] == {'items': [{'id': 'rec', 'movie_id': 'movie', 'reason': 'why', 'source': 'auto'}], 'total': 1, 'offset': 25, 'limit': 25}
    elif visible:
        assert response.json == body
