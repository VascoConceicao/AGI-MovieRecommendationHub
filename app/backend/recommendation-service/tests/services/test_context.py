import io
import json
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest
from services import context

CONFIG = {'AGENT_CONTEXT_TOKEN': 'test-token', 'USER_SERVICE_URL': 'http://user/'}


def test_context_auth_and_query(monkeypatch):
    fetch = Mock(return_value=io.BytesIO(b'{"user_ids":[]}'))
    monkeypatch.setattr(context, 'urlopen', fetch)
    assert context.fetch({**CONFIG, 'AGENT_CONTEXT_TOKEN': ''}, '/users', {})[1] == 503
    fetch.assert_not_called()
    assert context.fetch(CONFIG, '/users', {'limit': 2}) == ({'user_ids': []}, 200)
    req = fetch.call_args.args[0]
    assert req.full_url == 'http://user/users?limit=2'
    assert req.get_header('Authorization') == 'Bearer test-token'
    assert fetch.call_args.kwargs == {'timeout': 5}


@pytest.mark.parametrize('code,body,status', [(404, {'error': 'User not found.'}, 404), (404, {'error': 'other'}, 503),
    (404, [], 503), (404, 'invalid', 503), (500, {}, 503)])
def test_context_http_errors(monkeypatch, code, body, status):
    encoded = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    monkeypatch.setattr(context, 'urlopen', Mock(side_effect=HTTPError('http://test', code, 'failure', {}, io.BytesIO(encoded))))
    result, actual = context.fetch(CONFIG, '/users', {})
    assert actual == status
    assert result['error'] == ('User not found.' if status == 404 else 'User context unavailable. Please retry.')


@pytest.mark.parametrize('body', [b'[]', b'bad'])
def test_invalid_body(monkeypatch, body):
    monkeypatch.setattr(context, 'urlopen', Mock(return_value=io.BytesIO(body)))
    assert context.fetch(CONFIG, '/users', {})[1] == 503


def test_context_transport_failure(monkeypatch):
    monkeypatch.setattr(context, 'urlopen', Mock(side_effect=URLError('offline')))
    assert context.fetch(CONFIG, '/users', {})[1] == 503


def page(watched=(), watchlist=(), watched_next=None, watchlist_next=None):
    return {'user_id': 'u', 'as_of': '2026-10-09T16:00:00+00:00',
            'watched': {'items': list(watched), 'next_offset': watched_next},
            'watchlist': {'items': list(watchlist), 'next_offset': watchlist_next}}


def watched(movie, watched_at=None, recorded_at='2026-10-01T10:00:00+00:00'):
    return {'movie_id': movie, 'watched_at': watched_at, 'recorded_at': recorded_at}


def listed(movie, added_at='2026-10-02T10:00:00+00:00'):
    return {'movie_id': movie, 'added_at': added_at}


def serve(monkeypatch, *pages):
    calls = []
    responses = iter(pages)

    def fake(config, path, params):
        calls.append((path, dict(params)))
        result = next(responses)
        return result if isinstance(result, tuple) else (result, 200)
    monkeypatch.setattr(context, 'fetch', fake)
    return calls


def test_full_context_empty(monkeypatch):
    calls = serve(monkeypatch, page())
    result = context.fetch_full_context(CONFIG, 'user-1')
    assert result['watched'] == [] and result['watchlist'] == []
    assert result['user_id'] == 'user-1' and result['as_of'].year == 2026
    assert calls == [('/internal/recommendation-context/user-1', {'limit': 1000, 'watched_offset': 0, 'watchlist_offset': 0})]


def test_full_context_single_page_keeps_ids_and_timestamps(monkeypatch):
    serve(monkeypatch, page([watched('m1', '2026-09-01T20:00:00+00:00'), watched('m2')], [listed('m3')]))
    result = context.fetch_full_context(CONFIG, 'u')
    first, second = result['watched']
    assert (first['movie_id'], second['movie_id']) == ('m1', 'm2')
    assert first['watched_at'].day == 1 and first['effective_at'] == first['watched_at']
    assert second['watched_at'] is None and second['effective_at'] == second['recorded_at']
    assert first['recorded_at'].day == 1
    assert result['watchlist'] == [{'movie_id': 'm3', 'added_at': result['watchlist'][0]['added_at']}]
    assert result['watchlist'][0]['added_at'].day == 2


def test_full_context_pages_lists_independently(monkeypatch):
    calls = serve(monkeypatch,
                  page([watched('w1'), watched('w2')], [listed('l1')], watched_next=2, watchlist_next=1),
                  page([watched('w3')], [listed('l2')], watched_next=3, watchlist_next=None),
                  page([watched('w4')], [], watched_next=None))
    result = context.fetch_full_context(CONFIG, 'u')
    assert [row['movie_id'] for row in result['watched']] == ['w1', 'w2', 'w3', 'w4']
    assert [row['movie_id'] for row in result['watchlist']] == ['l1', 'l2']
    offsets = [(params['watched_offset'], params['watchlist_offset']) for _, params in calls]
    assert offsets == [(0, 0), (2, 1), (3, context.MAX_OFFSET)]


def test_full_context_ignores_items_repeated_across_pages(monkeypatch):
    serve(monkeypatch, page([watched('w1')], watched_next=1), page([watched('w1'), watched('w2')]))
    assert [row['movie_id'] for row in context.fetch_full_context(CONFIG, 'u')['watched']] == ['w1', 'w2']


@pytest.mark.parametrize('status,message', [(404, 'User not found.'), (503, 'User context unavailable. Please retry.')])
def test_full_context_errors(monkeypatch, status, message):
    serve(monkeypatch, ({'error': message}, status))
    with pytest.raises(context.ContextError) as error:
        context.fetch_full_context(CONFIG, 'u')
    assert error.value.status == status


def test_full_context_failure_on_later_page(monkeypatch):
    serve(monkeypatch, page([watched('w1')], watched_next=1), ({'error': 'User context unavailable. Please retry.'}, 503))
    with pytest.raises(context.ContextError) as error:
        context.fetch_full_context(CONFIG, 'u')
    assert error.value.status == 503


@pytest.mark.parametrize('bad', [
    {'as_of': 'x'},
    {'user_id': 'u', 'as_of': '2026-10-09T16:00:00+00:00', 'watched': {'items': [{'movie_id': 'm'}], 'next_offset': None},
     'watchlist': {'items': [], 'next_offset': None}},
    page(watched_next=0),
    page(watchlist_next='1'),
])
def test_full_context_rejects_malformed_or_stuck_pagination(monkeypatch, bad):
    serve(monkeypatch, bad)
    with pytest.raises(context.ContextError) as error:
        context.fetch_full_context(CONFIG, 'u')
    assert error.value.status == 503
