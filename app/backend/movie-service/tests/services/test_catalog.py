from datetime import date, datetime, timezone
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from services import catalog

VALID = {'source': 'tmdb', 'source_id': '1', 'title': ' Title ', 'synopsis': ' Plot ',
         'duration_minutes': 90, 'genres': ['Drama', 'Drama'], 'actors': ['Actor'], 'directors': ['Director']}


@pytest.fixture
def connection(monkeypatch):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr(catalog, 'connect', Mock(return_value=conn))
    return conn


@pytest.fixture
def row():
    return {**catalog.validate(VALID), 'id': UUID(int=1), 'created_at': datetime(2026, 1, 1, tzinfo=timezone.utc)}


def test_normalize_optional_fields():
    result = catalog.validate(VALID)
    assert result['title'] == 'Title'
    assert result['genres'] == ['Drama']
    assert result['poster_key'] is None
    for empty in [None, [], ' ']:
        assert catalog.validate({**VALID, 'original_title': empty})['original_title'] is None
    result = catalog.validate({**VALID, 'release_date': '2024-02-29', 'poster_key': 'a' * 64 + '.jpg',
                               'languages': ['en'], 'countries': ['PT']})
    assert result['release_date'] == date(2024, 2, 29)
    assert result['languages'] == ['en']


@pytest.mark.parametrize('data', [None, {'extra': 1},
    *[{**VALID, 'duration_minutes': x} for x in [None, True, 0, 10001]],
    *[{**VALID, 'genres': x} for x in [None, [], ['x'] * 201, [1], [''], ['x' * 201]]],
    *[{**VALID, 'title': x} for x in [None, '', 'x' * 301]],
    {**VALID, 'synopsis': 'x' * 10001}, {**VALID, 'source': 'TMDB'}, {**VALID, 'source_id': 'with space'},
    {**VALID, 'release_date': '2024-1-1'}, {**VALID, 'release_date': '2024-02-30'},
    {**VALID, 'poster_key': 2}, {**VALID, 'poster_key': '../poster.jpg'}])
def test_invalid_metadata(data):
    with pytest.raises(ValueError):
        catalog.validate(data)


def test_connect_and_initialize(monkeypatch, connection):
    catalog.initialize('db')
    assert connection.execute.call_args_list[0].args == ('SELECT pg_advisory_xact_lock(%s)', (catalog.LOCK,))
    assert any('CREATE TABLE' in c.args[0] for c in connection.execute.call_args_list)
    monkeypatch.undo()
    connect = Mock()
    monkeypatch.setattr(catalog.psycopg, 'connect', connect)
    assert catalog.connect('db') is connect.return_value
    connect.assert_called_once_with('db', connect_timeout=3, options='-c statement_timeout=10000', row_factory=catalog.dict_row)


def test_serialize(row):
    result = catalog.serialize(row)
    assert result['id'] == str(row['id'])
    assert result['poster_url'] is None
    assert result['release_date'] is None
    row.update(release_date=date(2024, 1, 1), poster_key='a' * 64 + '.jpg')
    result = catalog.serialize(row)
    assert result['release_date'] == '2024-01-01'
    assert result['poster_url'] == '/api/movie/posters/' + row['poster_key']


@pytest.mark.parametrize('created', [True, False])
def test_create_is_idempotent(connection, row, created):
    connection.execute.return_value.fetchone.side_effect = [None, row if created else None, row]
    result, is_new = catalog.create('db', VALID)
    assert result == catalog.serialize(row)
    assert is_new is created
    insert = connection.execute.call_args_list[2]
    assert 'ON CONFLICT' in insert.args[0]
    assert insert.args[1][2] == 'Title'


def test_create_blocks_pending_cleanup(connection):
    connection.execute.return_value.fetchone.return_value = {'pending': 1}
    with pytest.raises(catalog.ResetPending):
        catalog.create('db', VALID)
    assert not any('INSERT' in c.args[0] for c in connection.execute.call_args_list)


def test_lookup_and_duration(connection, row):
    connection.execute.return_value.fetchall.return_value = [row]
    assert catalog.lookup('db', ['id']) == [catalog.serialize(row)]
    assert connection.execute.call_args.args[1] == (['id'],)
    connection.execute.return_value.fetchone.return_value = {'total_minutes': 90, 'matched': 1}
    assert catalog.duration_summary('db', ['a', 'a', 'b']) == {'total_minutes': 90, 'missing_count': 1}


@pytest.mark.parametrize('count', [0, 1000, 1001])
def test_id_pagination(connection, count):
    connection.execute.return_value.fetchall.return_value = [{'id': UUID(int=i)} for i in range(count)]
    result = catalog.movie_ids('db', 'cursor')
    assert len(result['ids']) == min(count, 1000)
    assert result['next_cursor'] == (str(UUID(int=999)) if count > 1000 else None)
    assert connection.execute.call_args.args[1] == ('cursor', 'cursor')


def test_filter_options(connection):
    connection.execute.return_value.__iter__.return_value = [{'value': ''}, {'value': None}, {'value': 'choice'}]
    assert catalog.filter_options('db') == {'genres': ['choice'], 'languages': ['choice']}


@pytest.mark.parametrize('excluded', [None, ['id']])
def test_browse_uses_literal_query_and_exclusions(connection, row, excluded):
    connection.execute.return_value.fetchone.return_value = {'n': 1}
    connection.execute.return_value.fetchall.return_value = [row]
    result = catalog.browse('db', '%_', 25, excluded)
    assert result == {'movies': [catalog.serialize(row)], 'total': 1, 'offset': 25, 'limit': 25}
    assert connection.execute.call_args.args[1] == ('%_', '%_', excluded or [], 25)
