import io
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock
from urllib.error import URLError
from uuid import UUID

import pytest
from services import profiles


@pytest.fixture
def connection(monkeypatch):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr(profiles, 'connect', Mock(return_value=conn))
    return conn


def test_profile_and_avatar(connection):
    row = {'display_name': 'Name', 'bio': '', 'avatar_id': 2}
    connection.execute.return_value.fetchone.return_value = row
    assert profiles.profile('db', 'user') == row
    assert connection.execute.call_args.args[1] == ('user',)
    assert profiles.avatar('db', 'user', 2) == row
    assert connection.execute.call_args.args[1] == (2, 'user')


def test_duration_batches_and_empty_history(monkeypatch):
    fetch = Mock(side_effect=[io.BytesIO(b'{"missing_count":0,"total_minutes":100}'),
                              io.BytesIO(b'{"missing_count":0,"total_minutes":2}')])
    monkeypatch.setattr(profiles, 'urlopen', fetch)
    assert profiles.watch_minutes('http://movie', []) == 0
    fetch.assert_not_called()
    assert profiles.watch_minutes('http://movie/', ['id'] * 1001) == 102
    assert [len(json.loads(c.args[0].data)['ids']) for c in fetch.call_args_list] == [1000, 1]


@pytest.mark.parametrize('body', [{'missing_count': 1, 'total_minutes': 1}, {'missing_count': 0, 'total_minutes': True},
                                  {'missing_count': 0, 'total_minutes': -1}, None])
def test_invalid_duration_is_unknown(monkeypatch, body):
    monkeypatch.setattr(profiles, 'urlopen', Mock(return_value=io.BytesIO(json.dumps(body).encode())))
    assert profiles.watch_minutes('http://movie', ['id']) is None


def test_duration_transport_failure(monkeypatch):
    monkeypatch.setattr(profiles, 'urlopen', Mock(side_effect=URLError('offline')))
    assert profiles.watch_minutes('http://movie', ['id']) is None


def test_search_matches_original_and_translated_titles(monkeypatch):
    body = {'movies': [{'id': '1', 'title': 'TITLE'}, {'id': '2', 'title': None, 'original_title': 'Title'},
                       {'id': '3', 'title': 'Other', 'original_title': None}]}
    fetch = Mock(side_effect=lambda *a, **kw: io.BytesIO(json.dumps(body).encode()))
    monkeypatch.setattr(profiles, 'urlopen', fetch)
    assert profiles.search_ids('http://movie/', ['id'] * 51, 'title') == {'1', '2'}
    assert fetch.call_count == 2
    fetch.side_effect = URLError('offline')
    with pytest.raises(profiles.SearchUnavailable):
        profiles.search_ids('http://movie', ['id'], 'title')


@pytest.mark.parametrize('query', ['', 'title'])
def test_history_pagination_and_serialization(connection, monkeypatch, query):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [{'movie_id': UUID(int=1), 'watched_at': None, 'recorded_at': now},
            {'movie_id': UUID(int=2), 'watched_at': now, 'recorded_at': now}]
    connection.execute.return_value.fetchall.side_effect = [rows, [{'movie_id': UUID(int=i)} for i in [1, 2]]]
    monkeypatch.setattr(profiles, 'watch_minutes', Mock(return_value=180))
    monkeypatch.setattr(profiles, 'search_ids', Mock(return_value={str(UUID(int=1))}))
    result = profiles.history('db', 'user', 0, 'http://movie', query)
    assert result['total'] == 2
    assert result['matched_total'] == (1 if query else 2)
    assert result['watch_minutes'] == 180
    assert result['items'][0] == {'movie_id': str(UUID(int=1)), 'watched_at': None, 'recorded_at': now.isoformat()}
    assert len(result['items']) == (1 if query else 2)


@pytest.mark.parametrize('count', [0, 1])
def test_mark_unwatched(connection, count):
    connection.execute.return_value.rowcount = count
    assert profiles.mark_unwatched('db', 'user', 'movie') == {'removed': bool(count)}
    assert connection.execute.call_args.args[1] == ('user', 'movie')


@pytest.mark.parametrize('previous', [None, {'deleted_rows': 4}])
def test_cleanup_is_idempotent(connection, previous):
    connection.execute.return_value.fetchone.return_value = previous
    connection.execute.return_value.rowcount = 3
    assert profiles.cleanup('db', 'operation', ['movie']) == (4 if previous else 3)
    statements = [c.args[0] for c in connection.execute.call_args_list]
    assert any('DELETE FROM watched_movies' in sql for sql in statements) is (previous is None)
    if previous is None:
        assert 'DELETE FROM watchlist_movies' in statements
        assert connection.execute.call_args.args[1] == ('operation', 3)


def test_watchlist(connection):
    connection.execute.return_value.fetchall.side_effect = [[{'movie_id': UUID(int=1)}], [{'movie_id': UUID(int=2)}]]
    assert profiles.watchlist('db', 'user') == {'ids': [str(UUID(int=1))], 'watched_ids': [str(UUID(int=2))]}


@pytest.mark.parametrize('add', [True, False])
def test_update_watchlist(connection, monkeypatch, add):
    require = Mock()
    monkeypatch.setattr(profiles, 'require_movie', require)
    connection.execute.return_value.fetchone.return_value = None
    assert profiles.update_watchlist('db', 'user', 'movie', add, 'http://movie') == {'in_watchlist': add}
    assert require.call_count == add
    assert connection.execute.call_args.args[1] == ('user', 'movie')
    assert ('INSERT' if add else 'DELETE') in connection.execute.call_args.args[0]


def test_watched_cannot_be_watchlisted(connection, monkeypatch):
    monkeypatch.setattr(profiles, 'require_movie', Mock())
    connection.execute.return_value.fetchone.return_value = {'exists': 1}
    with pytest.raises(profiles.AlreadyWatched):
        profiles.update_watchlist('db', 'user', 'movie', True, 'http://movie')
    assert not any('INSERT' in c.args[0] for c in connection.execute.call_args_list)


@pytest.mark.parametrize('movies,exists', [([], False), ([{'id': 'other'}, {'id': 'movie'}], True)])
def test_require_movie(monkeypatch, movies, exists):
    monkeypatch.setattr(profiles, 'urlopen', Mock(return_value=io.BytesIO(json.dumps({'movies': movies}).encode())))
    if exists:
        assert profiles.require_movie('http://movie/', 'movie') is None
    else:
        with pytest.raises(ValueError, match='not found'):
            profiles.require_movie('http://movie', 'movie')


def test_require_movie_transport_failure(monkeypatch):
    monkeypatch.setattr(profiles, 'urlopen', Mock(side_effect=URLError('offline')))
    with pytest.raises(profiles.SearchUnavailable):
        profiles.require_movie('http://movie', 'movie')


def test_mark_watched(connection, monkeypatch):
    require = Mock()
    monkeypatch.setattr(profiles, 'require_movie', require)
    assert profiles.mark_watched('db', 'user', 'movie', 'http://movie') == {'watched': True}
    require.assert_called_once_with('http://movie', 'movie')
    assert connection.execute.call_args.args[1] == ('user', 'movie')
    assert 'ON CONFLICT DO NOTHING' in connection.execute.call_args.args[0]


def test_move_to_watchlist(connection, monkeypatch):
    require = Mock()
    monkeypatch.setattr(profiles, 'require_movie', require)
    assert profiles.move_to_watchlist('db', 'user', 'movie', 'http://movie') == {'watched': False, 'in_watchlist': True}
    require.assert_called_once_with('http://movie', 'movie')
    calls = connection.execute.call_args_list
    assert 'DELETE FROM watched_movies' in calls[-2].args[0]
    assert 'INSERT INTO watchlist_movies' in calls[-1].args[0]
    assert calls[-2].args[1] == calls[-1].args[1] == ('user', 'movie')


@pytest.mark.parametrize('public', [True, False])
def test_visibility(connection, public):
    connection.execute.return_value.fetchone.return_value = {'is_public': public}
    assert profiles.visibility('db', 'user', public) == {'is_public': public}
    assert connection.execute.call_args.args[1] == (public, 'user')


@pytest.mark.parametrize('query', ['', 'title'])
def test_search_watchlist(connection, monkeypatch, query):
    ids = [str(UUID(int=i)) for i in range(1, 31)]
    connection.execute.return_value.fetchall.return_value = [{'movie_id': UUID(value)} for value in ids]
    search = Mock(return_value=set(ids[1:]))
    monkeypatch.setattr(profiles, 'search_ids', search)
    result = profiles.search_watchlist('db', 'user', query, 25, 'http://movie')
    expected = ids[1:] if query else ids
    assert result == {'items': [{'movie_id': value} for value in expected[25:]], 'total': len(expected), 'offset': 25, 'limit': 25}
    assert search.call_count == bool(query)
