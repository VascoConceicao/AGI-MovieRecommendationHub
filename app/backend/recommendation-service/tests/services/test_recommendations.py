from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from services import recommendations as store


@pytest.fixture
def connection(monkeypatch):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr(store, 'connect', Mock(return_value=conn))
    return conn


def test_connection_options(monkeypatch):
    connect = Mock()
    monkeypatch.setattr(store.psycopg, 'connect', connect)
    assert store.connect('db') is connect.return_value
    connect.assert_called_once_with('db', connect_timeout=3, options='-c statement_timeout=10000', row_factory=store.dict_row)


def test_initialize_migrations(connection):
    store.initialize('db')
    statements = [call.args[0] for call in connection.execute.call_args_list]
    assert statements[0] == 'SELECT pg_advisory_xact_lock(150006)'
    assert any('CREATE TABLE' in sql for sql in statements[1:])


def test_save_and_serialize(connection):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    identifier = UUID(int=1)
    connection.execute.return_value.fetchone.return_value = {'id': identifier, 'user_id': identifier,
        'movie_id': identifier, 'created_at': now, 'updated_at': now, 'reason': 'why', 'score': None}
    saved = store.save('db', 'user', 'movie', 'why', None, 'auto')
    assert saved == {'id': str(identifier), 'user_id': str(identifier), 'movie_id': str(identifier),
                     'created_at': now.isoformat(), 'updated_at': now.isoformat(), 'reason': 'why', 'score': None}
    assert connection.execute.call_args.args[1] == ('user', 'movie', 'why', None, 'auto')
    assert store.save_batch('db', 'user', [], 'auto') == []


def test_listing(connection):
    connection.execute.return_value.fetchone.return_value = {'n': 1}
    connection.execute.return_value.fetchall.return_value = [{'id': UUID(int=1), 'reason': 'why'}]
    assert store.listing('db', 'user', 5, 10, 'auto') == {
        'items': [{'id': str(UUID(int=1)), 'reason': 'why'}], 'total': 1, 'offset': 5, 'limit': 10}
    assert connection.execute.call_args.args[1] == ('user', 'auto', 10, 5)


def test_listing_all_deduplicates_by_movie_preferring_user_requested(connection):
    connection.execute.return_value.fetchone.return_value = {'n': 0}
    connection.execute.return_value.fetchall.return_value = []
    store.listing('db', 'user', 0, 25)
    statements = [call.args[0] for call in connection.execute.call_args_list]
    assert all('DISTINCT ON (movie_id)' in sql and "(source='user_requested') DESC" in sql for sql in statements[1:])
    assert connection.execute.call_args.args[1] == ('user', None, 25, 0)
    store.listing('db', 'user', 0, 25, 'auto')
    assert 'DISTINCT' not in connection.execute.call_args.args[0]


@pytest.mark.parametrize('count', [0, 2])
def test_remove(connection, count):
    connection.execute.return_value.rowcount = count
    assert store.remove('db', 'id') == {'removed': bool(count)}
    assert connection.execute.call_args.args[1] == ('id',)


@pytest.mark.parametrize('legacy', [None, 'recommendation_requests'])
def test_clear_legacy_table_when_present(connection, legacy):
    connection.execute.return_value.rowcount = 3
    connection.execute.return_value.fetchone.return_value = {'name': legacy}
    expected = {'recommendations': 3}
    if legacy:
        expected['recommendation_requests'] = 3
    assert store.clear('db')['deleted_rows'] == expected
    assert any(c.args[0] == 'DELETE FROM recommendation_requests' for c in connection.execute.call_args_list) == bool(legacy)
