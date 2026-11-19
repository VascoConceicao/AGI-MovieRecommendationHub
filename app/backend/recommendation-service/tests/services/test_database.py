from unittest.mock import MagicMock
import psycopg
import pytest
from services import database


def test_empty_database_url_is_not_ready():
    assert database.database_is_ready('') is False


@pytest.mark.parametrize('row,expected', [((1,), True), ((0,), False)])
def test_database_readiness_query(monkeypatch, row, expected):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    monkeypatch.setattr(database.psycopg, 'connect', lambda *args, **kwargs: connection)
    assert database.database_is_ready('test-only') is expected
    cursor.execute.assert_called_once()


def test_database_connection_failure_is_not_ready(monkeypatch):
    def fail(*args, **kwargs):
        raise psycopg.OperationalError('test error')
    monkeypatch.setattr(database.psycopg, 'connect', fail)
    assert database.database_is_ready('test-only') is False
