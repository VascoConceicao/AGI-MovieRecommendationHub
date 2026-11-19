from unittest.mock import Mock
from urllib.error import URLError

import psycopg
import pytest
from main import create_app
from api import recommendations as api
from api import context as context_api

ID = '00000000-0000-0000-0000-000000000001'
HEADERS = {'Authorization': 'Bearer test'}


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True, DATABASE_URL='test-only', RECOMMENDATION_API_TOKEN='test',
                      RECOMMENDATION_RESET_ENABLED=True, RECOMMENDATION_RESET_TOKEN='test')
    return app.test_client()


@pytest.mark.parametrize('headers,status', [({}, 401), ({'Authorization': 'Basic test'}, 401),
    ({'Authorization': 'Bearer wrong'}, 401), ({**HEADERS, 'Sec-Fetch-Site': 'cross-site'}, 403)])
def test_authorization(client, headers, status):
    response = client.get('/recommendations', headers=headers)
    assert response.status_code == status
    assert response.headers['Cache-Control'] == 'no-store'


def test_disabled_endpoints(client):
    client.application.config['RECOMMENDATION_API_TOKEN'] = ''
    assert client.get('/recommendations').status_code == 404
    client.application.config['RECOMMENDATION_RESET_ENABLED'] = False
    assert client.post('/admin/reset-recommendation-db', headers=HEADERS).status_code == 404


def test_filter_options_and_failure(client, monkeypatch):
    options = Mock(return_value={'version': 1})
    monkeypatch.setattr(api.filters, 'options', options)
    assert client.get('/recommendation-filters', headers=HEADERS).json == {'version': 1, 'generation_available': False}
    client.application.config['AGENT_SUBMIT_URL'] = 'http://agent'
    assert client.get('/recommendation-filters', headers=HEADERS).json['generation_available'] is False
    options.side_effect = URLError('offline')
    assert client.get('/recommendation-filters', headers=HEADERS).status_code == 503


@pytest.mark.parametrize('query', ['', '?user_id=bad', f'?user_id={ID}&source=bad',
    f'?user_id={ID}&offset=-1', f'?user_id={ID}&offset=1000001', f'?user_id={ID}&offset=no',
    f'?user_id={ID}&limit=0', f'?user_id={ID}&limit=101'])
def test_invalid_listing(client, query):
    assert client.get('/recommendations' + query, headers=HEADERS).status_code == 400


@pytest.mark.parametrize('source', ['all', 'auto', 'user_requested'])
def test_listing_and_database_failure(client, monkeypatch, source):
    listing = Mock(return_value={'items': [], 'total': 0})
    monkeypatch.setattr(api.store, 'listing', listing)
    response = client.get(f'/recommendations?user_id={ID}&source={source}&offset=1000000&limit=100', headers=HEADERS)
    assert response.json == {'items': [], 'total': 0}
    listing.assert_called_once_with('test-only', ID, 1000000, 100, None if source == 'all' else source)
    listing.side_effect = psycopg.OperationalError('offline')
    assert client.get(f'/recommendations?user_id={ID}', headers=HEADERS).status_code == 503


@pytest.mark.parametrize('data', [None, [], {}, {'user_id': 'bad', 'filters': {}}, {'user_id': None, 'filters': {}}])
def test_invalid_request(client, data):
    assert client.post('/context/recommendation-requests', json=data, headers=HEADERS).status_code == 400


def test_request_handoff_errors_and_success(client, monkeypatch):
    options = Mock(side_effect=ValueError('bad catalog'))
    monkeypatch.setattr(context_api, 'filter_options', options)
    payload = {'user_id': ID, 'filters': {}}
    assert client.post('/context/recommendation-requests', json=payload, headers=HEADERS).status_code == 503
    options.side_effect = None
    options.return_value = {'version': 1}
    validate = Mock(side_effect=ValueError('invalid filters'))
    monkeypatch.setattr(context_api.filters, 'validate', validate)
    response = client.post('/context/recommendation-requests', json=payload, headers=HEADERS)
    assert response.status_code == 400
    assert response.json['error'] == 'invalid filters'
    validate.side_effect = None
    validate.return_value = {'count': 5}
    response = client.post('/context/recommendation-requests', json=payload, headers=HEADERS)
    assert response.status_code == 200
    assert response.json == {'user_id': ID, 'source': 'user_requested',
                             'filters': {'count': 5}, 'generation_available': False}



VALID = {'user_id': ID, 'movie_id': ID, 'reason': ' why ', 'source': 'auto'}


@pytest.mark.parametrize('data', [None, [], {}, {**VALID, 'extra': 1}, {**VALID, 'source': 'bad'},
    {**VALID, 'movie_id': None}, *[{**VALID, 'reason': value} for value in [None, '', 'x' * 5001]],
    *[{**VALID, 'score': value} for value in [True, -1, 2, float('nan')]]])
def test_invalid_save(client, data):
    assert client.post('/recommendations', json=data, headers=HEADERS).status_code == 400


@pytest.mark.parametrize('score', [None, 0, 1, 0.5])
def test_save(client, monkeypatch, score):
    save = Mock(return_value={'id': ID})
    monkeypatch.setattr(api.store, 'save', save)
    response = client.post('/recommendations', json={**VALID, 'score': score}, headers=HEADERS)
    assert response.json == {'recommendation': {'id': ID}}
    save.assert_called_once_with('test-only', ID, ID, 'why', score, 'auto')


def test_remove(client, monkeypatch):
    remove = Mock(return_value={'removed': False})
    monkeypatch.setattr(api.store, 'remove', remove)
    assert client.delete('/recommendations/bad', headers=HEADERS).status_code == 400
    remove.assert_not_called()
    assert client.delete('/recommendations/' + ID, headers=HEADERS).json == {'removed': False}
    remove.assert_called_once_with('test-only', ID)


@pytest.mark.parametrize('data', [None, {}, {'table': 'bad'}, {'table': 'all', 'extra': 1}])
def test_invalid_reset(client, data):
    assert client.post('/admin/reset-recommendation-db', json=data, headers=HEADERS).status_code == 400


@pytest.mark.parametrize('table', ['all', 'recommendations'])
def test_reset(client, monkeypatch, table):
    clear = Mock(return_value={'deleted_rows': {'recommendations': 2}})
    monkeypatch.setattr(api.store, 'clear', clear)
    response = client.post('/admin/reset-recommendation-db', json={'table': table}, headers=HEADERS)
    assert response.json == clear.return_value
    clear.assert_called_once_with('test-only')
