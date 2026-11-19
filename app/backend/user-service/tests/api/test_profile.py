from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import psycopg
import pytest
from main import create_app
from api import profile as api

ID = '00000000-0000-0000-0000-000000000001'
HEADERS = {'X-G15-Request': '1'}
TOKEN = {'Authorization': 'Bearer test'}


@pytest.fixture
def client(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True, DATABASE_URL='test-only', MOVIE_SERVICE_URL='http://movie', WATCHED_CLEANUP_TOKEN='test')
    monkeypatch.setattr(api.accounts, 'current_user', Mock(return_value={'id': ID}))
    return app.test_client()


def test_session_and_csrf(client):
    assert client.post('/profile/avatar', json={}).status_code == 403
    assert client.post('/profile/avatar', data='raw', headers=HEADERS).status_code == 403
    assert client.post('/profile/avatar', json={}, headers={**HEADERS, 'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    api.accounts.current_user.return_value = None
    assert client.get('/profile').status_code == 401
    api.accounts.current_user.side_effect = psycopg.OperationalError('private')
    response = client.get('/profile')
    assert response.status_code == 503
    assert b'private' not in response.data
    assert response.headers['Cache-Control'] == 'no-store'


def test_profile_and_avatar(client, monkeypatch):
    profile = Mock(return_value={'avatar_id': 1})
    avatar = Mock(return_value={'avatar_id': 10})
    monkeypatch.setattr(api.profiles, 'profile', profile)
    monkeypatch.setattr(api.profiles, 'avatar', avatar)
    assert client.get('/profile').json == {'profile': {'avatar_id': 1}}
    profile.assert_called_once_with('test-only', ID)
    assert client.post('/profile/avatar', json={'avatar_id': 10}, headers=HEADERS).json == {'profile': {'avatar_id': 10}}
    avatar.assert_called_once_with('test-only', ID, 10)


@pytest.mark.parametrize('data', [[], {}, {'avatar_id': True}, {'avatar_id': 0}, {'avatar_id': 11}, {'avatar_id': 1, 'extra': 1}])
def test_invalid_avatar(client, data):
    assert client.post('/profile/avatar', json=data, headers=HEADERS).status_code == 400


def test_recommendation_gateway(client, monkeypatch):
    call = Mock(return_value=({'items': []}, 200))
    monkeypatch.setattr(api.recommendations, 'call', call)
    assert client.get('/profile/recommendation-filters').json == {'items': []}
    assert call.call_args.args[1] == '/recommendation-filters'
    assert client.get('/profile/recommendations?source=auto&offset=25').status_code == 200
    assert parse_qs(urlsplit(call.call_args.args[1]).query) == {'user_id': [ID], 'source': ['auto'], 'offset': ['25'], 'limit': ['25']}
    assert client.post('/profile/recommendation-requests', json={'filters': {}}, headers=HEADERS).status_code == 200
    assert call.call_args.args[1:] == ('/context/recommendation-requests', {'user_id': ID, 'filters': {}})


@pytest.mark.parametrize('data', [[], {}, {'filters': {}, 'user_id': ID}])
def test_request_cannot_override_identity(client, data):
    assert client.post('/profile/recommendation-requests', json=data, headers=HEADERS).status_code == 400


@pytest.mark.parametrize('query', ['offset=no', 'offset=-1', 'offset=1000001', 'q=' + 'x' * 201])
def test_invalid_history_query(client, query):
    assert client.get('/profile/watched?' + query).status_code == 400


def test_history(client, monkeypatch):
    history = Mock(return_value={'items': [], 'total': 0})
    monkeypatch.setattr(api.profiles, 'history', history)
    assert client.get('/profile/watched?q=%20title%20&offset=25').json == history.return_value
    history.assert_called_once_with('test-only', ID, 25, 'http://movie', 'title')
    history.side_effect = api.profiles.SearchUnavailable()
    assert client.get('/profile/watched').status_code == 503


@pytest.mark.parametrize('path', ['/watched/add', '/watched/remove'])
@pytest.mark.parametrize('data', [[], {}, {'movie_id': None}, {'movie_id': 'bad'}, {'movie_id': ID, 'extra': 1}])
def test_invalid_movie_mutations(client, path, data):
    assert client.post('/profile' + path, json=data, headers=HEADERS).status_code == 400


def test_add_remove_watched(client, monkeypatch):
    remove = Mock(return_value={'removed': True})
    add = Mock(return_value={'watched': True})
    monkeypatch.setattr(api.profiles, 'mark_unwatched', remove)
    monkeypatch.setattr(api.profiles, 'mark_watched', add)
    assert client.post('/profile/watched/remove', json={'movie_id': ID}, headers=HEADERS).json == {'removed': True}
    remove.assert_called_once_with('test-only', ID, ID)
    assert client.post('/profile/watched/add', json={'movie_id': ID}, headers=HEADERS).json == {'watched': True}
    add.assert_called_once_with('test-only', ID, ID, 'http://movie')
    for error, status in [(api.profiles.SearchUnavailable(), 503), (ValueError('missing'), 404)]:
        add.side_effect = error
        assert client.post('/profile/watched/add', json={'movie_id': ID}, headers=HEADERS).status_code == status


def test_cleanup_authorization(client):
    assert client.post('/internal/clear-watched').status_code == 401
    assert client.post('/internal/clear-watched', headers={'Authorization': 'Basic test'}).status_code == 401
    assert client.post('/internal/clear-watched', headers={**TOKEN, 'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    client.application.config['WATCHED_CLEANUP_TOKEN'] = ''
    assert client.post('/internal/clear-watched').status_code == 404


@pytest.mark.parametrize('data', [None, {}, {'operation_id': ID, 'movie_ids': 'bad'},
    {'operation_id': None, 'movie_ids': []}, {'operation_id': ID, 'movie_ids': [None]},
    {'operation_id': ID, 'movie_ids': ['bad']}])
def test_invalid_cleanup(client, data):
    assert client.post('/internal/clear-watched', json=data, headers=TOKEN).status_code == 400


def test_cleanup(client, monkeypatch):
    cleanup = Mock(return_value=3)
    monkeypatch.setattr(api.profiles, 'cleanup', cleanup)
    assert client.post('/internal/clear-watched', json={'operation_id': ID, 'movie_ids': [ID]}, headers=TOKEN).json == {
        'operation_id': ID, 'deleted_rows': 3}
    cleanup.assert_called_once_with('test-only', ID, [ID])


def test_events_close_and_busy(client, monkeypatch):
    close = Mock()
    subscribe = Mock(return_value=(iter(['event: ready\ndata: {}\n\n']), close))
    monkeypatch.setattr(api.history_events, 'subscribe', subscribe)
    response = client.get('/profile/events')
    assert response.mimetype == 'text/event-stream'
    assert response.headers['X-Accel-Buffering'] == 'no'
    assert b'event: ready' in response.data
    response.close()
    close.assert_called_once()
    subscribe.side_effect = api.history_events.StreamBusy()
    assert client.get('/profile/events').status_code == 503


@pytest.mark.parametrize('data', [[], {}, {'movie_id': ID, 'add': 1}, {'movie_id': None, 'add': True},
                                 {'movie_id': 'bad', 'add': False}])
def test_invalid_watchlist(client, data):
    assert client.post('/profile/watchlist', json=data, headers=HEADERS).status_code == 400


def test_watchlist(client, monkeypatch):
    listing = Mock(return_value={'ids': [ID], 'watched_ids': []})
    update = Mock(return_value={'in_watchlist': True})
    monkeypatch.setattr(api.profiles, 'watchlist', listing)
    monkeypatch.setattr(api.profiles, 'update_watchlist', update)
    assert client.get('/profile/watchlist').json == listing.return_value
    listing.assert_called_once_with('test-only', ID)
    assert client.post('/profile/watchlist', json={'movie_id': ID, 'add': True}, headers=HEADERS).json == {'in_watchlist': True}
    update.assert_called_once_with('test-only', ID, ID, True, 'http://movie')
    for error, status in [(api.profiles.AlreadyWatched(), 409), (api.profiles.SearchUnavailable(), 503), (ValueError('missing'), 404)]:
        update.side_effect = error
        assert client.post('/profile/watchlist', json={'movie_id': ID, 'add': True}, headers=HEADERS).status_code == status


@pytest.mark.parametrize('query', ['q='+'x'*201, 'q=x&offset=no', 'q=x&offset=-1', 'q=x&offset=1000001', 'q=x&source=bad'])
def test_invalid_recommendation_search(client, query):
    assert client.get('/profile/recommendations?' + query).status_code == 400


def test_recommendation_search(client, monkeypatch):
    search = Mock(return_value=({'items': [], 'total': 0}, 200))
    monkeypatch.setattr(api.recommendations, 'search', search)
    assert client.get('/profile/recommendations?q=%20title%20&offset=25&source=auto').json == {'items': [], 'total': 0}
    search.assert_called_once_with(client.application.config, ID, 'auto', 25, 'title')


@pytest.mark.parametrize('data', [[], {}, {'movie_id': None}, {'movie_id': 'bad'}, {'movie_id': ID, 'extra': 1}])
def test_invalid_move_to_list(client, data):
    assert client.post('/profile/watched/move-to-list', json=data, headers=HEADERS).status_code == 400


def test_move_to_list(client, monkeypatch):
    move = Mock(return_value={'watched': False, 'in_watchlist': True})
    monkeypatch.setattr(api.profiles, 'move_to_watchlist', move)
    assert client.post('/profile/watched/move-to-list', json={'movie_id': ID}, headers=HEADERS).json == move.return_value
    move.assert_called_once_with('test-only', ID, ID, 'http://movie')
    for error, status in [(api.profiles.SearchUnavailable(), 503), (ValueError('missing'), 404)]:
        move.side_effect = error
        assert client.post('/profile/watched/move-to-list', json={'movie_id': ID}, headers=HEADERS).status_code == status


@pytest.mark.parametrize('data', [[], {}, {'is_public': 1}, {'is_public': None}, {'is_public': True, 'extra': 1}])
def test_invalid_visibility(client, data):
    assert client.post('/profile/visibility', json=data, headers=HEADERS).status_code == 400


@pytest.mark.parametrize('public', [True, False])
def test_visibility(client, monkeypatch, public):
    change = Mock(return_value={'is_public': public})
    monkeypatch.setattr(api.profiles, 'visibility', change)
    assert client.post('/profile/visibility', json={'is_public': public}, headers=HEADERS).json == {'profile': {'is_public': public}}
    change.assert_called_once_with('test-only', ID, public)


@pytest.mark.parametrize('query', ['offset=no', 'offset=-1', 'offset=1000001', 'q='+'x'*201])
def test_invalid_watchlist_search(client, query):
    assert client.get('/profile/watchlist/search?' + query).status_code == 400


def test_watchlist_search(client, monkeypatch):
    search = Mock(return_value={'items': [], 'total': 0})
    monkeypatch.setattr(api.profiles, 'search_watchlist', search)
    assert client.get('/profile/watchlist/search?q=%20title%20&offset=25').json == search.return_value
    search.assert_called_once_with('test-only', ID, 'title', 25, 'http://movie')
    search.side_effect = api.profiles.SearchUnavailable()
    assert client.get('/profile/watchlist/search').status_code == 503


# --- asynchronous generation gateway ---------------------------------------------------------------------------------------

JOB = '11111111-1111-4111-8111-111111111111'
OTHER = '99999999-9999-4999-8999-999999999999'
FILTERS = {'genres': ['Drama'], 'languages': [], 'actors': [], 'directors': [], 'year_from': None, 'year_to': None, 'duration': 'any', 'count': 10}


@pytest.fixture
def generation(client, monkeypatch):
    client.application.config.update(RECOMMENDATION_API_TOKEN='internal-secret-token', RECOMMENDATION_SERVICE_URL='http://recommendation')
    call = Mock(return_value=({'job_id': JOB, 'status': 'queued'}, 202, {}))
    monkeypatch.setattr(api.recommendations, 'generation_call', call)
    return call


def test_generation_requires_a_session_and_the_same_origin_json_header(client, generation):
    assert client.post('/profile/recommendation-generations', json={'filters': {}}).status_code == 403
    assert client.post('/profile/recommendation-generations', data='raw', headers=HEADERS).status_code == 403
    assert client.post('/profile/recommendation-generations', json={'filters': {}}, headers={**HEADERS, 'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    api.accounts.current_user.return_value = None
    assert client.post('/profile/recommendation-generations', json={'filters': {}}, headers=HEADERS).status_code == 401
    assert client.get(f'/profile/recommendation-generations/{JOB}').status_code == 401
    generation.assert_not_called()


def test_generation_forwards_filters_with_the_user_from_the_session(client, generation):
    response = client.post('/profile/recommendation-generations', json={'filters': FILTERS}, headers=HEADERS)
    assert response.status_code == 202 and response.json == {'job_id': JOB, 'status': 'queued'}
    config, path, payload = generation.call_args.args
    assert path == '/recommendations/generate' and payload == {'user_id': ID, 'filters': FILTERS}
    assert response.headers['Cache-Control'] == 'no-store'
    assert 'source' not in payload                                       # the browser can only ever request user_requested


@pytest.mark.parametrize('data', [[], {}, {'user_id': OTHER, 'filters': {}}, {'filters': {}, 'user_id': OTHER}, {'filters': {}, 'source': 'auto'},
                                  {'filters': {}, 'count': 5}, {'count': 5}])
def test_generation_rejects_anything_but_filters_and_never_trusts_a_browser_user_id(client, generation, data):
    assert client.post('/profile/recommendation-generations', json=data, headers=HEADERS).status_code == 400
    generation.assert_not_called()


def test_the_internal_token_never_reaches_the_browser(client, generation):
    responses = [client.post('/profile/recommendation-generations', json={'filters': {}}, headers=HEADERS),
                 client.get(f'/profile/recommendation-generations/{JOB}')]
    generation.return_value = ({'error': 'Recommendations unavailable. Please retry.'}, 503, {})
    responses.append(client.post('/profile/recommendation-generations', json={'filters': {}}, headers=HEADERS))
    for response in responses:
        assert b'internal-secret-token' not in response.data and 'internal-secret-token' not in str(response.headers)
    assert 'internal-secret-token' not in str(generation.call_args_list) or generation.call_args.args[0]['RECOMMENDATION_API_TOKEN'] == 'internal-secret-token'


def test_a_conflict_is_forwarded_with_the_active_job(client, generation):
    generation.return_value = ({'error': 'A generation is already queued or running for this user.', 'job_id': JOB, 'status': 'running'}, 409, {})
    response = client.post('/profile/recommendation-generations', json={'filters': FILTERS}, headers=HEADERS)
    assert response.status_code == 409 and response.json['job_id'] == JOB and response.json['status'] == 'running'


def test_a_full_queue_is_forwarded_with_retry_after(client, generation):
    generation.return_value = ({'error': 'Generation queue is full. Please retry later.'}, 503, {'Retry-After': '30'})
    response = client.post('/profile/recommendation-generations', json={'filters': FILTERS}, headers=HEADERS)
    assert response.status_code == 503 and response.headers['Retry-After'] == '30' and 'queue is full' in response.json['error']


@pytest.mark.parametrize('status,body', [(400, {'error': 'Select an available duration.'}), (404, {'error': 'Generation job not found.'}),
                                         (503, {'error': 'Recommendations unavailable. Please retry.'})])
def test_other_meaningful_errors_keep_their_status_and_message(client, generation, status, body):
    generation.return_value = (body, status, {})
    assert client.post('/profile/recommendation-generations', json={'filters': {}}, headers=HEADERS).json == body
    assert client.get(f'/profile/recommendation-generations/{JOB}').status_code == status


def test_non_object_filters_are_left_to_the_recommendation_service_validation(client, generation):
    generation.return_value = ({'error': 'Provide predefined filters only.'}, 400, {})
    response = client.post('/profile/recommendation-generations', json={'filters': 'drama'}, headers=HEADERS)
    assert response.status_code == 400 and generation.call_args.args[2]['filters'] == 'drama'


def test_job_status_is_always_asked_for_the_session_user(client, generation):
    generation.return_value = ({'job_id': JOB, 'status': 'running'}, 200, {})
    response = client.get(f'/profile/recommendation-generations/{JOB.upper()}?user_id={OTHER}')      # a browser-supplied user_id is ignored
    assert response.status_code == 200 and response.json == {'job_id': JOB, 'status': 'running'}
    path = generation.call_args.args[1]
    parts = urlsplit(path)
    assert parts.path == f'/recommendations/generations/{JOB}' and parse_qs(parts.query) == {'user_id': [ID]}
    assert response.headers['Cache-Control'] == 'no-store'


def test_another_users_job_looks_like_an_unknown_job(client, generation):
    generation.return_value = ({'error': 'Generation job not found.'}, 404, {})
    response = client.get(f'/profile/recommendation-generations/{JOB}')
    assert response.status_code == 404 and response.json == {'error': 'Generation job not found.'}
    assert parse_qs(urlsplit(generation.call_args.args[1]).query) == {'user_id': [ID]}


@pytest.mark.parametrize('job_id', ['not-a-uuid', '123', 'x' * 40, '%00'])
def test_an_invalid_job_id_is_rejected_without_calling_the_service(client, generation, job_id):
    assert client.get(f'/profile/recommendation-generations/{job_id}').status_code in (400, 404)
    generation.assert_not_called()


def test_the_existing_recommendation_routes_still_work(client, monkeypatch, generation):
    call = Mock(return_value=({'items': [], 'total': 0}, 200))
    monkeypatch.setattr(api.recommendations, 'call', call)
    assert client.get('/profile/recommendations?source=auto&offset=0').status_code == 200
    assert parse_qs(urlsplit(call.call_args.args[1]).query)['source'] == ['auto']
    assert client.get('/profile/recommendation-filters').status_code == 200
    assert client.post('/profile/recommendation-requests', json={'filters': {}}, headers=HEADERS).status_code == 200
    assert call.call_args.args[1] == '/context/recommendation-requests'
    generation.assert_not_called()
