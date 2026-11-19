from unittest.mock import MagicMock
import pytest
from services import reset


def test_unknown_table_never_connects():
    with pytest.raises(ValueError):
        reset.clear_tables('not-a-database', 'arbitrary_table')


@pytest.mark.parametrize('table,expected', [('all', reset.TABLES), ('users', reset.TABLES),
                                          ('user_sessions', ('user_sessions',))])
def test_reset_counts_and_deletes_in_one_connection(monkeypatch, table, expected):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = {'count': 2}
    monkeypatch.setattr(reset, 'connect', lambda url: connection)
    result = reset.clear_tables('test-only', table)
    assert result == {'cleared_tables': list(expected), 'deleted_rows': {name: 2 for name in expected}}
    delete = connection.execute.call_args.args[0]
    sql = delete if isinstance(delete, str) else delete.as_string()
    assert sql == ('DELETE FROM users' if table in ('all', 'users') else 'DELETE FROM "user_sessions"')
