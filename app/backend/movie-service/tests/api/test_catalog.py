from unittest.mock import Mock

import psycopg
import pytest
from main import create_app
from api import catalog as api
from tests.services.test_catalog import VALID

ID = '00000000-0000-0000-0000-000000000001'
HEADERS = {'Authorization': 'Bearer test'}


@pytest.fixture
def client(tmp_path):
    app = create_app()
    app.config.update(TESTING=True, DATABASE_URL='test-only', MOVIE_WRITE_TOKEN='test',
                      MOVIE_RESET_TOKEN='test', MOVIE_RESET_ENABLED=True, MOVIE_MEDIA_DIR=str(tmp_path))
    return app.test_client()


@pytest.mark.parametrize('headers,status', [({}, 401), ({'Authorization': 'Basic test'}, 401),
    ({'Authorization': 'Bearer wrong'}, 401), ({**HEADERS, 'Sec-Fetch-Site': 'cross-site'}, 403)])
def test_write_authorization(client, headers, status):
    response = client.post('/movies', json=VALID, headers=headers)
    assert response.status_code == status
    assert response.headers['Cache-Control'] == 'no-store'


def test_disabled_endpoints(client):
    client.application.config['MOVIE_WRITE_TOKEN'] = ''
    assert client.post('/movies', json=VALID).status_code == 404
    client.application.config['MOVIE_RESET_ENABLED'] = False
    assert client.post('/admin/reset-movie-db', headers=HEADERS).status_code == 404


@pytest.mark.parametrize('query', ['offset=no', 'offset=-1', 'offset=1000001', 'q=' + 'x' * 201,
    'ids=', 'ids=bad', 'ids=' + ','.join([ID] * 51)])
def test_invalid_get_query(client, query):
    assert client.get('/movies?' + query).status_code == 400


def test_browse_and_lookup(client, monkeypatch):
    browse = Mock(return_value={'movies': [], 'total': 0})
    lookup = Mock(return_value=[{'id': ID}])
    monkeypatch.setattr(api.catalog, 'browse', browse)
    monkeypatch.setattr(api.catalog, 'lookup', lookup)
    assert client.get('/movies?q=%20title%20&offset=25').json == browse.return_value
    browse.assert_called_once_with('test-only', 'title', 25)
    assert client.get('/movies?ids=,' + ID).json == {'movies': [{'id': ID}]}
    lookup.assert_called_once_with('test-only', [ID])
    browse.side_effect = psycopg.OperationalError('offline')
    assert client.get('/movies').status_code == 503


@pytest.mark.parametrize('created', [True, False])
def test_create_and_poster(client, monkeypatch, tmp_path, created):
    create = Mock(return_value=({'id': ID}, created))
    monkeypatch.setattr(api.catalog, 'create', create)
    response = client.post('/movies', json=VALID, headers=HEADERS)
    assert response.status_code == (201 if created else 200)
    assert response.json == {'movie': {'id': ID}, 'created': created}
    key = 'a' * 64 + '.jpg'
    payload = {**VALID, 'poster_key': key}
    assert client.post('/movies', json=payload, headers=HEADERS).status_code == 400
    (tmp_path / key).write_bytes(b'jpeg')
    assert client.post('/movies', json=payload, headers=HEADERS).status_code == (201 if created else 200)
    response = client.get('/posters/' + key)
    assert response.data == b'jpeg'
    assert response.mimetype == 'image/jpeg'
    assert client.get('/posters/invalid.jpg').status_code == 404
    create.side_effect = api.catalog.ResetPending()
    assert client.post('/movies', json=VALID, headers=HEADERS).status_code == 503


@pytest.mark.parametrize('data', [None, {}, {'table': 'bad'}, {'table': 'all', 'extra': 1}])
def test_invalid_reset(client, data):
    assert client.post('/admin/reset-movie-db', json=data, headers=HEADERS).status_code == 400


def test_reset_and_pending(client, monkeypatch):
    clear = Mock(return_value={'deleted_rows': {'movies': 2}})
    monkeypatch.setattr(api.reset, 'clear', clear)
    assert client.post('/admin/reset-movie-db', json={'table': 'all'}, headers=HEADERS).json == clear.return_value
    clear.assert_called_once_with(client.application.config)
    clear.side_effect = api.reset.CleanupPending('retry')
    response = client.post('/admin/reset-movie-db', json={'table': 'movies'}, headers=HEADERS)
    assert response.status_code == 503
    assert response.json == {'error': 'retry', 'cleanup_pending': True}


@pytest.mark.parametrize('data', [None, {}, {'ids': 'bad'}, {'ids': []}, {'ids': [ID] * 1001},
                                 {'ids': ['bad']}, {'ids': [None]}])
def test_invalid_duration(client, data):
    assert client.post('/movies/duration', json=data).status_code == 400


def test_duration_ids_and_filters(client, monkeypatch):
    duration = Mock(return_value={'total_minutes': 90, 'missing_count': 0})
    ids = Mock(return_value={'ids': [ID], 'next_cursor': None})
    options = Mock(return_value={'genres': [], 'languages': []})
    monkeypatch.setattr(api.catalog, 'duration_summary', duration)
    monkeypatch.setattr(api.catalog, 'movie_ids', ids)
    monkeypatch.setattr(api.catalog, 'filter_options', options)
    assert client.post('/movies/duration', json={'ids': [ID]}).json == duration.return_value
    duration.assert_called_once_with('test-only', [ID])
    assert client.get('/movies/ids').json == ids.return_value
    ids.assert_called_with('test-only', None)
    assert client.get('/movies/ids?after=' + ID).status_code == 200
    ids.assert_called_with('test-only', ID)
    assert client.get('/movies/ids?after=bad').status_code == 400
    assert client.get('/movies/filter-options').json == options.return_value


@pytest.mark.parametrize('data', [None, {'extra': 1}, {'offset': True}, {'offset': -1}, {'offset': 1000001},
    {'q': None}, {'q': 'x' * 201}, {'exclude_ids': 'bad'}, {'exclude_ids': [''] * 10001}, {'exclude_ids': ['bad']},
    {'exclude_ids': [None]}])
def test_invalid_post_browse(client, data):
    assert client.post('/movies/browse', json=data).status_code == 400


def test_post_browse(client, monkeypatch):
    browse = Mock(return_value={'movies': []})
    monkeypatch.setattr(api.catalog, 'browse', browse)
    assert client.post('/movies/browse', json={}).json == {'movies': []}
    browse.assert_called_with('test-only', '', 0, [])
    assert client.post('/movies/browse', json={'q': ' title ', 'offset': 25, 'exclude_ids': [ID]}).status_code == 200
    browse.assert_called_with('test-only', 'title', 25, [ID])


@pytest.mark.parametrize('query,seed,limit', [('seed='+ID, ID, 25), ('limit=1000', None, 1000)])
def test_browse_seed_and_limit(client, monkeypatch, query, seed, limit):
    browse = Mock(return_value={'movies': [], 'total': 0})
    monkeypatch.setattr(api.catalog, 'browse', browse)
    assert client.get('/movies?' + query).json == browse.return_value
    browse.assert_called_once_with('test-only', '', 0, seed=seed, limit=limit)
