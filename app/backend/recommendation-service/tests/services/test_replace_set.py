"""Unit tests for replace_set with a mocked connection: statement order, parameters and validation.

Atomicity, isolation and locking are NOT proven here (a mock cannot prove them); see
test_replace_set_postgres.py, which runs against a real PostgreSQL.
"""
import copy
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock
from uuid import UUID

import psycopg
import pytest
from services import candidates, recommendations as store
from services.assembly import FinalRecommendation, ordering_score

USER = str(UUID(int=900))


def movie(n):
    return {'id': str(UUID(int=n)), 'title': 'Title %d' % n}


def rec(n, score, reason='Because.', deterministic_score=0.5):
    return FinalRecommendation(candidates.Candidate(movie(n), deterministic_score, {}), score, reason)


def make_set(*numbers):
    return tuple(rec(n, ordering_score(rank, len(numbers)), 'Reason %d' % n) for rank, n in enumerate(numbers, 1))


@pytest.fixture
def conn(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.__exit__.return_value = False             # never swallow exceptions
    connect = Mock(return_value=connection)
    monkeypatch.setattr(store, 'connect', connect)
    connection.connect = connect
    return connection


def statements(conn):
    return [(call.args[0], call.args[1] if len(call.args) > 1 else None) for call in conn.execute.call_args_list]


def test_statement_order_lock_then_delete_then_inserts(conn):
    assert store.replace_set('db', USER, 'auto', make_set(1, 2, 3)) == 3
    sql = statements(conn)
    assert [text.split()[0] for text, _ in sql] == ['SELECT', 'DELETE', 'INSERT', 'INSERT', 'INSERT']
    assert 'pg_advisory_xact_lock' in sql[0][0] and 'hashtextextended' in sql[0][0]
    assert sql[1] == ('DELETE FROM recommendations WHERE user_id=%s AND source=%s', (USER, 'auto'))
    assert [params for _, params in sql[2:]] == [
        (USER, str(UUID(int=1)), 'Reason 1', 1.0, 'auto'), (USER, str(UUID(int=2)), 'Reason 2', pytest.approx(2 / 3), 'auto'),
        (USER, str(UUID(int=3)), 'Reason 3', pytest.approx(1 / 3), 'auto')]
    conn.connect.assert_called_once_with('db')


def test_everything_happens_inside_one_connection_context(conn):
    store.replace_set('db', USER, 'auto', make_set(1, 2))
    conn.__enter__.assert_called_once()
    conn.__exit__.assert_called_once_with(None, None, None)           # clean exit: psycopg commits here
    conn.commit.assert_not_called()                                    # no manual commit between delete and inserts


def test_persisted_values_are_exactly_the_given_score_and_reason(conn):
    item = rec(1, 0.37, '  Exactly this, kept as given.  ', deterministic_score=0.99)
    store.replace_set('db', USER, 'user_requested', [item])
    _, movie_id, reason, score, source = statements(conn)[2][1]
    assert (reason, score, source) == ('  Exactly this, kept as given.  ', 0.37, 'user_requested')
    assert score != item.candidate.score                              # not the deterministic candidate score


def test_lock_key_is_per_user_and_source(conn):
    keys = []
    for user, source in ((USER, 'auto'), (USER, 'auto'), (USER, 'user_requested'), (str(UUID(int=901)), 'auto')):
        conn.execute.reset_mock()
        store.replace_set('db', user, source, [])
        keys.append(statements(conn)[0][1])
    assert keys[0] == keys[1] and len({keys[0], keys[2], keys[3]}) == 3
    assert keys[0][1] == store.SET_LOCK_SEED


def test_empty_set_locks_and_deletes_only(conn):
    assert store.replace_set('db', USER, 'auto', []) == 0 and store.replace_set('db', USER, 'auto', ()) == 0
    sql = statements(conn)
    assert [text.split()[0] for text, _ in sql] == ['SELECT', 'DELETE', 'SELECT', 'DELETE']


def test_uuid_inputs_are_normalized_and_uuid_objects_accepted(conn):
    store.replace_set('db', str(UUID(int=900)).upper(), 'auto', [rec(1, 1.0)])
    assert statements(conn)[2][1][:2] == (USER, str(UUID(int=1)))
    conn.execute.reset_mock()
    item = FinalRecommendation(candidates.Candidate({'id': UUID(int=7)}, 0.1, {}), 1.0, 'r')
    store.replace_set('db', UUID(int=900), 'auto', [item])
    assert statements(conn)[2][1][:2] == (USER, str(UUID(int=7)))


def test_integer_one_and_zero_scores_are_accepted(conn):
    store.replace_set('db', USER, 'auto', [rec(1, 1), rec(2, 0)])
    assert [params[3] for _, params in statements(conn)[2:]] == [1, 0]


def test_reason_of_exactly_the_database_maximum_is_accepted(conn):
    store.replace_set('db', USER, 'auto', [rec(1, 1.0, 'x' * store.MAX_REASON_CHARS)])
    store.replace_set('db', USER, 'auto', [rec(1, 1.0, ' ' * 9 + 'x' * store.MAX_REASON_CHARS + ' ' * 9)])   # Postgres trim() only strips spaces


BAD_USERS = [None, 5, '', 'not-a-uuid', ['x'], object()]
BAD_SOURCES = [None, '', 'all', 'AUTO', 'Auto', 'background', 'normal', 5]
BAD_SETS = {
    'string': 'abc', 'dict': {'a': 1}, 'none': None, 'generator': (r for r in make_set(1)), 'set': {1},
    'plain tuple item': [(1, 2, 3)], 'dict item': [{'movie_id': 'x'}], 'none item': [None], 'mock item': [Mock()],
    'no candidate': [FinalRecommendation(None, 1.0, 'r')], 'candidate without movie': [FinalRecommendation(Mock(spec=[]), 1.0, 'r')],
    'movie without id': [FinalRecommendation(candidates.Candidate({'title': 'x'}, 0.1, {}), 1.0, 'r')],
    'movie id none': [FinalRecommendation(candidates.Candidate({'id': None}, 0.1, {}), 1.0, 'r')],
    'bad movie uuid': [FinalRecommendation(candidates.Candidate({'id': 'nope'}, 0.1, {}), 1.0, 'r')],
    'int movie id': [FinalRecommendation(candidates.Candidate({'id': 5}, 0.1, {}), 1.0, 'r')],
    'duplicate movie': [rec(1, 1.0), rec(1, 0.5)],
    'duplicate movie different case': [rec(1, 1.0), FinalRecommendation(candidates.Candidate({'id': str(UUID(int=1)).upper()}, 0.1, {}), 0.5, 'r')],
    'empty reason': [rec(1, 1.0, '')], 'blank reason': [rec(1, 1.0, '   \n\t ')], 'none reason': [rec(1, 1.0, None)],
    'int reason': [rec(1, 1.0, 5)], 'list reason': [rec(1, 1.0, ['r'])], 'nul in reason': [rec(1, 1.0, 'a\x00b')],
    'overlong reason': [rec(1, 1.0, 'x' * (store.MAX_REASON_CHARS + 1))],
    'negative score': [rec(1, -0.1)], 'score above one': [rec(1, 1.01)], 'nan': [rec(1, float('nan'))],
    'inf': [rec(1, float('inf'))], 'minus inf': [rec(1, float('-inf'))], 'bool true': [rec(1, True)], 'bool false': [rec(1, False)],
    'string score': [rec(1, '0.5')], 'none score': [rec(1, None)], 'list score': [rec(1, [0.5])],
    'equal scores': [rec(1, 0.5), rec(2, 0.5)], 'increasing scores': [rec(1, 0.4), rec(2, 0.5)],
    'bad second item': [rec(1, 1.0), rec(2, float('nan'))],
}


@pytest.mark.parametrize('user', BAD_USERS)
def test_invalid_user_is_rejected_before_any_database_access(conn, user):
    with pytest.raises(store.RecommendationInputError):
        store.replace_set('db', user, 'auto', make_set(1))
    conn.connect.assert_not_called()


@pytest.mark.parametrize('source', BAD_SOURCES)
def test_invalid_source_is_rejected_before_any_database_access(conn, source):
    with pytest.raises(store.RecommendationInputError):
        store.replace_set('db', USER, source, make_set(1))
    conn.connect.assert_not_called()


@pytest.mark.parametrize('name', list(BAD_SETS))
def test_invalid_sets_are_rejected_before_any_database_access(conn, name):
    with pytest.raises(store.RecommendationInputError):
        store.replace_set('db', USER, 'auto', BAD_SETS[name])
    conn.connect.assert_not_called()
    conn.execute.assert_not_called()


def test_one_bad_item_rejects_the_whole_set_so_nothing_is_written(conn):
    with pytest.raises(store.RecommendationInputError, match='Recommendation 3'):
        store.replace_set('db', USER, 'auto', [rec(1, 1.0), rec(2, 0.5), rec(3, 0.7)])
    conn.connect.assert_not_called()


def test_validation_error_is_a_value_error_and_not_a_database_error():
    assert issubclass(store.RecommendationInputError, ValueError) and not issubclass(store.RecommendationInputError, psycopg.Error)


def test_database_errors_are_propagated_and_the_context_manager_sees_them(conn):
    error = psycopg.errors.CheckViolation('score out of range')
    conn.execute.side_effect = [None, None, None, error]
    with pytest.raises(psycopg.errors.CheckViolation):
        store.replace_set('db', USER, 'auto', make_set(1, 2, 3))
    assert conn.__exit__.call_args.args[0] is psycopg.errors.CheckViolation        # psycopg rolls back on this path
    conn.commit.assert_not_called()


@pytest.mark.parametrize('failing_call', [0, 1, 2])
def test_failure_at_lock_delete_or_first_insert_is_not_swallowed(conn, failing_call):
    side_effect = [None, None, None]
    side_effect[failing_call] = psycopg.OperationalError('boom')
    conn.execute.side_effect = side_effect
    with pytest.raises(psycopg.OperationalError):
        store.replace_set('db', USER, 'auto', make_set(1, 2))


def test_connection_failure_is_propagated(monkeypatch):
    monkeypatch.setattr(store, 'connect', Mock(side_effect=psycopg.OperationalError('down')))
    with pytest.raises(psycopg.OperationalError):
        store.replace_set('db', USER, 'auto', make_set(1))


def test_inputs_are_not_mutated(conn):
    items = list(make_set(1, 2, 3))
    snapshot = copy.deepcopy(items)
    store.replace_set('db', USER, 'auto', items)
    assert items == snapshot


def test_validate_set_returns_canonical_values_in_the_given_order():
    user, source, rows = store.validate_set(str(UUID(int=900)).upper(), 'auto', make_set(3, 1, 2))
    assert (user, source) == (USER, 'auto')
    assert [row[0] for row in rows] == [str(UUID(int=n)) for n in (3, 1, 2)]
    assert [row[2] for row in rows] == pytest.approx([1.0, 2 / 3, 1 / 3])


def test_existing_persistence_functions_are_untouched(conn):
    conn.execute.return_value.fetchone.return_value = {'id': UUID(int=1), 'user_id': UUID(int=1), 'movie_id': UUID(int=1),
                                                      'created_at': datetime(2026, 1, 1, tzinfo=timezone.utc),
                                                      'updated_at': datetime(2026, 1, 1, tzinfo=timezone.utc), 'reason': 'r', 'score': None}
    assert store.save_batch('db', 'user', [], 'auto') == []
    store.save_batch('db', 'u', [{'movie_id': 'm', 'reason': 'r', 'score': 0.5}], 'auto')
    assert 'ON CONFLICT (user_id,movie_id,source) DO UPDATE' in conn.execute.call_args.args[0]
