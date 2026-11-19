from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from services import discovery

ID = UUID(int=1)


@pytest.fixture
def connection(monkeypatch):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr(discovery, 'connect', Mock(return_value=conn))
    return conn


@pytest.mark.parametrize('query,seed', [('', None), ('', 'seed'), ('alice', 'seed')])
def test_search_public_users(connection, query, seed):
    connection.execute.return_value.fetchone.return_value = {'n': 1}
    connection.execute.return_value.fetchall.return_value = [{'id': ID, 'username': 'alice'}]
    assert discovery.search('db', query, 25, 10, seed) == {
        'users': [{'id': str(ID), 'username': 'alice'}], 'total': 1, 'offset': 25, 'limit': 10}
    sql, params = connection.execute.call_args.args
    assert 'p.is_public' in sql
    assert params == ((query, query, seed, 10, 25) if seed and not query else (query, query, 10, 25))
    assert ('md5' in sql) == bool(seed and not query)


def test_empty_search(connection):
    connection.execute.return_value.fetchone.return_value = {'n': 0}
    connection.execute.return_value.fetchall.return_value = []
    assert discovery.search('db', '', 0)['users'] == []


def test_private_profile(connection, monkeypatch):
    connection.execute.return_value.fetchone.return_value = None
    duration = Mock()
    monkeypatch.setattr(discovery.profiles, 'watch_minutes', duration)
    assert discovery.public_profile('db', str(ID), 0) is None
    duration.assert_not_called()


@pytest.mark.parametrize('section', ['watched', 'watchlist', 'recommendations'])
@pytest.mark.parametrize('query', ['', 'match'])
def test_public_collections(connection, monkeypatch, section, query):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    connection.execute.return_value.fetchone.side_effect = [{'id': ID, 'username': 'alice'}, {'n': 2}]
    key = 'watched_at' if section == 'watched' else 'added_at'
    rows = [{'movie_id': UUID(int=2), key: now}, {'movie_id': UUID(int=3), key: None}]
    connection.execute.return_value.fetchall.side_effect = [[{'movie_id': UUID(int=2)}], rows]
    search = Mock(return_value={str(UUID(int=3))})
    duration = Mock(return_value=120)
    monkeypatch.setattr(discovery.profiles, 'search_ids', search)
    monkeypatch.setattr(discovery.profiles, 'watch_minutes', duration)
    result = discovery.public_profile('db', str(ID), 0, section, query, 'http://movie')
    assert result['profile'] == {'id': str(ID), 'username': 'alice'}
    assert result['watched_total'] == 1
    assert result['watch_minutes'] == 120
    duration.assert_called_once_with('http://movie', [str(UUID(int=2))])
    expected = [] if section == 'recommendations' else ([{'movie_id': str(UUID(int=3)), key: None}] if query else [
        {'movie_id': str(UUID(int=2)), key: now.isoformat()}, {'movie_id': str(UUID(int=3)), key: None}])
    assert result['collection']['items'] == expected
    assert ('watched' in result) == (section == 'watched')
    if query and section != 'recommendations':
        search.assert_called_once_with('http://movie', [str(UUID(int=2)), str(UUID(int=3))], query)
        assert result['collection']['total'] == 1
    else:
        search.assert_not_called()


@pytest.mark.parametrize('row,expected', [(None, False), ({'exists': 1}, True)])
def test_visibility(connection, row, expected):
    connection.execute.return_value.fetchone.return_value = row
    assert discovery.is_public('db', ID) is expected
    assert connection.execute.call_args.args[1] == (ID,)


def test_title_filter_runs_before_pagination(connection, monkeypatch):
    ids = [UUID(int=i) for i in range(1, 32)]
    connection.execute.return_value.fetchone.return_value = {'id': ID}
    connection.execute.return_value.fetchall.side_effect = [
        [{'movie_id': value} for value in ids],
        [{'movie_id': value, 'watched_at': None} for value in ids],
    ]
    monkeypatch.setattr(discovery.profiles, 'search_ids', Mock(return_value={str(value) for value in ids[1:]}))
    monkeypatch.setattr(discovery.profiles, 'watch_minutes', Mock(return_value=None))
    result = discovery.public_profile('db', ID, 25, 'watched', 'title', 'http://movie')
    assert result['watched_total'] == 31
    assert result['watch_minutes'] is None
    assert result['collection'] == {
        'items': [{'movie_id': str(value), 'watched_at': None} for value in ids[26:]],
        'total': 30, 'offset': 25, 'limit': 25,
    }
