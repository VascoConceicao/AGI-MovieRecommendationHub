import io
import json
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest
from services import recommendations

CONFIG = {'RECOMMENDATION_API_TOKEN': 'secret', 'RECOMMENDATION_SERVICE_URL': 'http://recommendation/'}


def test_disabled_gateway(monkeypatch):
    fetch = Mock()
    monkeypatch.setattr(recommendations, 'urlopen', fetch)
    assert recommendations.call({**CONFIG, 'RECOMMENDATION_API_TOKEN': ''}, '/path')[1] == 503
    fetch.assert_not_called()


@pytest.mark.parametrize('payload', [None, {'filters': {}}])
def test_gateway_request(monkeypatch, payload):
    response = io.BytesIO(b'{"items":[]}')
    response.status = 200
    fetch = Mock(return_value=response)
    monkeypatch.setattr(recommendations, 'urlopen', fetch)
    assert recommendations.call(CONFIG, '/path', payload) == ({'items': []}, 200)
    req = fetch.call_args.args[0]
    assert req.full_url == 'http://recommendation/path'
    assert req.get_header('Authorization') == 'Bearer secret'
    assert req.get_method() == ('GET' if payload is None else 'POST')
    if payload is not None:
        assert json.loads(req.data) == payload


@pytest.mark.parametrize('status,body,expected', [(400, b'{"error":"bad"}', 400), (404, b'{"error":"gone"}', 404),
    (503, b'{"error":"offline"}', 503), (500, b'private details', 503), (400, b'invalid', 503),
    (400, b'{}', 503), (400, b'[]', 503)])
def test_gateway_http_errors(monkeypatch, status, body, expected):
    monkeypatch.setattr(recommendations, 'urlopen', Mock(side_effect=HTTPError('http://test', status, 'error', {}, io.BytesIO(body))))
    result, code = recommendations.call(CONFIG, '/path')
    assert code == expected
    assert 'error' in result
    assert 'private details' not in result['error']


@pytest.mark.parametrize('error', [URLError('offline'), OSError('offline'), ValueError('invalid')])
def test_gateway_failures(monkeypatch, error):
    monkeypatch.setattr(recommendations, 'urlopen', Mock(side_effect=error))
    assert recommendations.call(CONFIG, '/path')[1] == 503


def test_search_paginates_filters_then_slices(monkeypatch):
    from services import profiles
    from urllib.parse import parse_qs, urlsplit
    items = [{'movie_id': str(i)} for i in range(30)] + [{'movie_id': '1'}]
    call = Mock(side_effect=[({'items': items[:20], 'total': 31}, 200), ({'items': items[20:], 'total': 31}, 200)])
    search = Mock(return_value={str(i) for i in range(1, 30)})
    monkeypatch.setattr(recommendations, 'call', call)
    monkeypatch.setattr(profiles, 'search_ids', search)
    body, status = recommendations.search({'MOVIE_SERVICE_URL': 'http://movie'}, 'user', 'auto', 25, 'title')
    assert status == 200
    assert body == {'items': items[26:], 'total': 30, 'offset': 25, 'limit': 25}
    assert [parse_qs(urlsplit(c.args[1]).query)['offset'] for c in call.call_args_list] == [['0'], ['20']]
    search.assert_called_once_with('http://movie', [str(i) for i in range(30)], 'title')


def test_search_empty_and_failures(monkeypatch):
    from services import profiles
    call = Mock(return_value=({'error': 'offline'}, 503))
    search = Mock(return_value=set())
    monkeypatch.setattr(recommendations, 'call', call)
    monkeypatch.setattr(profiles, 'search_ids', search)
    config = {'MOVIE_SERVICE_URL': 'http://movie'}
    assert recommendations.search(config, 'user', 'all', 0, 'title') == ({'error': 'offline'}, 503)
    search.assert_not_called()
    call.return_value = ({'items': [], 'total': 10}, 200)
    assert recommendations.search(config, 'user', 'all', 0, 'title') == ({'items': [], 'total': 0, 'offset': 0, 'limit': 25}, 200)
    search.side_effect = profiles.SearchUnavailable()
    assert recommendations.search(config, 'user', 'all', 0, 'title')[1] == 503


# --- generation_call: the asynchronous generation gateway ---------------------------------------------------------------

def reply(status, body, headers=None):
    return HTTPError('http://test', status, 'error', headers or {}, io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode()))


def test_generation_gateway_is_disabled_without_a_token(monkeypatch):
    fetch = Mock()
    monkeypatch.setattr(recommendations, 'urlopen', fetch)
    body, status, headers = recommendations.generation_call({**CONFIG, 'RECOMMENDATION_API_TOKEN': ''}, '/recommendations/generate', {})
    assert (status, headers) == (503, {}) and body == {'error': 'Recommendations unavailable. Please retry.'}
    fetch.assert_not_called()


@pytest.mark.parametrize('payload,method,status', [({'user_id': 'u', 'filters': {}}, 'POST', 202), (None, 'GET', 200)])
def test_generation_request_and_success_are_forwarded_unchanged(monkeypatch, payload, method, status):
    response = io.BytesIO(b'{"job_id":"j","status":"queued"}')
    response.status = status
    fetch = Mock(return_value=response)
    monkeypatch.setattr(recommendations, 'urlopen', fetch)
    assert recommendations.generation_call(CONFIG, '/recommendations/generate', payload) == ({'job_id': 'j', 'status': 'queued'}, status, {})
    req = fetch.call_args.args[0]
    assert req.full_url == 'http://recommendation/recommendations/generate' and req.get_method() == method
    assert req.get_header('Authorization') == 'Bearer secret' and fetch.call_args.kwargs == {'timeout': 10}
    if payload is not None:
        assert json.loads(req.data) == payload


@pytest.mark.parametrize('status', [400, 404, 503])
def test_meaningful_errors_keep_their_status_and_a_safe_message(monkeypatch, status):
    monkeypatch.setattr(recommendations, 'urlopen', Mock(side_effect=reply(status, {'error': 'Safe message.', 'internal': 'private details'})))
    body, code, headers = recommendations.generation_call(CONFIG, '/x')
    assert code == status and body == {'error': 'Safe message.'} and headers == {}


def test_a_conflict_keeps_its_status_and_the_active_job(monkeypatch):
    monkeypatch.setattr(recommendations, 'urlopen', Mock(side_effect=reply(
        409, {'error': 'A generation is already queued or running for this user.', 'job_id': 'abc', 'status': 'running', 'internal': 'x'})))
    body, code, headers = recommendations.generation_call(CONFIG, '/x', {})
    assert code == 409 and headers == {}
    assert body == {'error': 'A generation is already queued or running for this user.', 'job_id': 'abc', 'status': 'running'}


def test_a_conflict_without_job_details_still_stays_a_conflict(monkeypatch):
    monkeypatch.setattr(recommendations, 'urlopen', Mock(side_effect=reply(409, {'error': 'Busy.', 'job_id': 5})))
    assert recommendations.generation_call(CONFIG, '/x', {})[:2] == ({'error': 'Busy.'}, 409)


@pytest.mark.parametrize('retry,expected', [('30', {'Retry-After': '30'}), ('soon', {}), ('', {}), ('-5', {}), ('1 2', {})])
def test_retry_after_is_forwarded_for_503_only_when_numeric(monkeypatch, retry, expected):
    monkeypatch.setattr(recommendations, 'urlopen', Mock(side_effect=reply(503, {'error': 'Generation queue is full. Please retry later.'}, {'Retry-After': retry})))
    body, code, headers = recommendations.generation_call(CONFIG, '/x', {})
    assert code == 503 and headers == expected and 'queue is full' in body['error']


def test_retry_after_is_not_forwarded_on_other_statuses(monkeypatch):
    monkeypatch.setattr(recommendations, 'urlopen', Mock(side_effect=reply(409, {'error': 'Busy.', 'job_id': 'j'}, {'Retry-After': '30'})))
    assert recommendations.generation_call(CONFIG, '/x', {})[2] == {}


@pytest.mark.parametrize('status', [401, 403, 405, 500, 502])
def test_other_http_errors_become_a_generic_retryable_503(monkeypatch, status):
    monkeypatch.setattr(recommendations, 'urlopen', Mock(side_effect=reply(status, {'error': 'A valid service token is required. private details'})))
    body, code, headers = recommendations.generation_call(CONFIG, '/x', {})
    assert (code, headers) == (503, {}) and body == {'error': 'Recommendations unavailable. Please retry.'}


@pytest.mark.parametrize('body', [b'private details', b'{}', b'[]', b'{"error": 5}', b'null'])
def test_unusable_error_bodies_become_a_generic_503(monkeypatch, body):
    monkeypatch.setattr(recommendations, 'urlopen', Mock(side_effect=reply(400, body)))
    result, code, headers = recommendations.generation_call(CONFIG, '/x', {})
    assert code == 503 and 'private' not in json.dumps(result)


@pytest.mark.parametrize('error', [URLError('offline'), OSError('offline'), ValueError('invalid')])
def test_transport_failures_become_a_generic_503(monkeypatch, error):
    monkeypatch.setattr(recommendations, 'urlopen', Mock(side_effect=error))
    body, code, headers = recommendations.generation_call(CONFIG, '/x', {})
    assert (code, headers) == (503, {}) and 'secret' not in json.dumps(body)


def test_an_invalid_success_body_becomes_a_generic_503(monkeypatch):
    response = io.BytesIO(b'not json')
    response.status = 202
    monkeypatch.setattr(recommendations, 'urlopen', Mock(return_value=response))
    assert recommendations.generation_call(CONFIG, '/x', {})[1] == 503


def test_the_existing_call_function_is_unchanged_for_conflicts(monkeypatch):
    monkeypatch.setattr(recommendations, 'urlopen', Mock(side_effect=reply(409, {'error': 'Busy.', 'job_id': 'j'})))
    assert recommendations.call(CONFIG, '/x', {}) == ({'error': 'Recommendations unavailable. Please retry.'}, 503)
