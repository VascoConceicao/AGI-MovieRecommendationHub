from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from services import recommendation_context as store


@pytest.fixture
def connection(monkeypatch):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr(store, 'connect', Mock(return_value=conn))
    return conn


@pytest.mark.parametrize('count', [0, 2, 3])
def test_user_cursor(connection, count):
    connection.execute.return_value.fetchall.return_value = [{'id': UUID(int=i)} for i in range(count)]
    result = store.users('db', None, 2)
    assert len(result['user_ids']) == min(count, 2)
    assert result['next_cursor'] == (str(UUID(int=1)) if count == 3 else None)
    assert connection.execute.call_args.args[1] == (None, None, 3)


def test_unknown_user(connection):
    connection.execute.return_value.fetchone.return_value = None
    assert store.context('db', 'user', 0, 0, 2) is None


def test_context_serializes_and_paginates(connection):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    connection.execute.return_value.fetchone.side_effect = [{'exists': 1}, {'at': now}, {'n': 4}, {'n': 1}]
    connection.execute.return_value.fetchall.side_effect = [
        [{'movie_id': UUID(int=1), 'watched_at': None, 'recorded_at': now}],
        [{'movie_id': UUID(int=2), 'added_at': now}]]
    result = store.context('db', 'user', 1, 0, 2)
    assert result['user_id'] == 'user'
    assert result['as_of'] == now.isoformat()
    assert result['watched'] == {'items': [{'movie_id': str(UUID(int=1)), 'watched_at': None, 'recorded_at': now.isoformat()}],
                                 'total': 4, 'offset': 1, 'limit': 2, 'next_offset': 3}
    assert result['watchlist']['next_offset'] is None
    assert result['watchlist']['items'] == [{'movie_id': str(UUID(int=2)), 'added_at': now.isoformat()}]
