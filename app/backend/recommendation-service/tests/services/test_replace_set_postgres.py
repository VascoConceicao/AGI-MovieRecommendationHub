"""replace_set against a real PostgreSQL: transactions, rollback, source/user isolation and locking.

The `url` fixture (tests/services/conftest.py) creates a throwaway database on the server named by
DATABASE_URL and drops it afterwards; the configured database is never touched. Skipped when DATABASE_URL is
unset or the server is unreachable. To run them:
    set -a; . ./.env; set +a; .venv/bin/python -m pytest tests/services/test_replace_set_postgres.py
"""
import threading
import time
from datetime import datetime, timezone
from uuid import UUID

import psycopg
import pytest
from services import assembly, candidates, recommendations as store
from services.assembly import FinalRecommendation, ordering_score

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
USER_A, USER_B = str(UUID(int=0xA)), str(UUID(int=0xB))


@pytest.fixture(autouse=True)
def empty_table(url):
    with store.connect(url) as conn:
        conn.execute('DELETE FROM recommendations')


def mid(n):
    return str(UUID(int=n))


def make_set(*numbers, prefix='Reason'):
    return tuple(FinalRecommendation(candidates.Candidate({'id': mid(n)}, 0.5, {}), ordering_score(rank, len(numbers)),
                                     f'{prefix} {n}') for rank, n in enumerate(numbers, 1))


def stored(url, user, source=None):
    """(movie_id, reason, score, source) in the order the existing listing (score DESC) returns them."""
    items = store.listing(url, user, 0, 100, source)['items']
    return [(i['movie_id'], i['reason'], i['score'], i['source']) for i in items]


def movies(url, user, source=None):
    return [row[0] for row in stored(url, user, source)]


def total_rows(url):
    with store.connect(url) as conn:
        return conn.execute('SELECT count(*) AS n FROM recommendations').fetchone()['n']


# --- success ------------------------------------------------------------------------------------------------

def test_insert_a_complete_set_with_exact_scores_and_reasons(url):
    assert store.replace_set(url, USER_A, 'auto', make_set(1, 2, 3, 4)) == 4
    rows = stored(url, USER_A, 'auto')
    assert [r[0] for r in rows] == [mid(n) for n in (1, 2, 3, 4)]
    assert [r[1] for r in rows] == ['Reason %d' % n for n in (1, 2, 3, 4)]
    assert [r[2] for r in rows] == [1.0, 0.75, 0.5, 0.25] and {r[3] for r in rows} == {'auto'}


def test_listing_order_matches_assemble_order(url):
    profile = candidates.build_profile({'as_of': NOW, 'watched': [], 'watchlist': []}, [])
    pool = [candidates.score_movie({'id': mid(n), 'title': 't', 'genres': ['Drama'], 'directors': [], 'actors': [], 'languages': [],
                                    'year': 1990 + n, 'duration_minutes': 100}, profile) for n in (7, 3, 9, 1, 5)]
    result = assembly.assemble(pool, profile)
    store.replace_set(url, USER_A, 'auto', result)
    assert movies(url, USER_A, 'auto') == [item.candidate.movie['id'] for item in result]
    assert [r[2] for r in stored(url, USER_A, 'auto')] == pytest.approx([item.score for item in result])
    assert [r[1] for r in stored(url, USER_A, 'auto')] == [item.reason for item in result]


def test_replace_an_existing_set_removes_the_old_one(url):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2, 3))
    store.replace_set(url, USER_A, 'auto', make_set(4, 5, 6, prefix='New'))
    assert movies(url, USER_A, 'auto') == [mid(n) for n in (4, 5, 6)]
    assert {r[1][:3] for r in stored(url, USER_A, 'auto')} == {'New'} and total_rows(url) == 3


def test_replace_with_fewer_and_with_more_recommendations(url):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2, 3, 4, 5))
    store.replace_set(url, USER_A, 'auto', make_set(2, 9))
    assert movies(url, USER_A, 'auto') == [mid(2), mid(9)]
    store.replace_set(url, USER_A, 'auto', make_set(*range(10, 30)))
    assert movies(url, USER_A, 'auto') == [mid(n) for n in range(10, 30)] and total_rows(url) == 20


def test_replacing_with_an_overlapping_set_keeps_no_stale_values(url):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2, 3, prefix='Old'))
    store.replace_set(url, USER_A, 'auto', make_set(3, 1, prefix='Fresh'))
    assert [(r[0], r[1], r[2]) for r in stored(url, USER_A, 'auto')] == [(mid(3), 'Fresh 3', 1.0), (mid(1), 'Fresh 1', 0.5)]


def test_same_movie_can_live_in_both_sources(url):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2))
    store.replace_set(url, USER_A, 'user_requested', make_set(2, 1))
    assert movies(url, USER_A, 'auto') == [mid(1), mid(2)] and movies(url, USER_A, 'user_requested') == [mid(2), mid(1)]


# --- isolation ----------------------------------------------------------------------------------------------

def seed_four(url):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2, 3, prefix='AAuto'))
    store.replace_set(url, USER_A, 'user_requested', make_set(4, 5, 6, prefix='AReq'))
    store.replace_set(url, USER_B, 'auto', make_set(7, 8, prefix='BAuto'))
    store.replace_set(url, USER_B, 'user_requested', make_set(9, prefix='BReq'))


def snapshot(url):
    return {(u, s): stored(url, u, s) for u in (USER_A, USER_B) for s in ('auto', 'user_requested')}


def test_replacing_auto_preserves_user_requested_and_other_users(url):
    seed_four(url)
    before = snapshot(url)
    store.replace_set(url, USER_A, 'auto', make_set(20, 21, prefix='NewAuto'))
    after = snapshot(url)
    assert after[(USER_A, 'auto')] != before[(USER_A, 'auto')] and movies(url, USER_A, 'auto') == [mid(20), mid(21)]
    for key in before:
        if key != (USER_A, 'auto'):
            assert after[key] == before[key]


def test_replacing_user_requested_preserves_auto_and_other_users(url):
    seed_four(url)
    before = snapshot(url)
    store.replace_set(url, USER_A, 'user_requested', make_set(30, prefix='NewReq'))
    after = snapshot(url)
    assert movies(url, USER_A, 'user_requested') == [mid(30)]
    for key in before:
        if key != (USER_A, 'user_requested'):
            assert after[key] == before[key]


def test_replacing_user_a_preserves_user_b(url):
    seed_four(url)
    before = snapshot(url)
    store.replace_set(url, USER_A, 'auto', make_set(40))
    store.replace_set(url, USER_A, 'user_requested', make_set(41))
    after = snapshot(url)
    assert after[(USER_B, 'auto')] == before[(USER_B, 'auto')] and after[(USER_B, 'user_requested')] == before[(USER_B, 'user_requested')]


# --- empty set ------------------------------------------------------------------------------------------------

def test_empty_replacement_clears_only_the_targeted_set(url):
    seed_four(url)
    before = snapshot(url)
    assert store.replace_set(url, USER_A, 'auto', []) == 0
    after = snapshot(url)
    assert after[(USER_A, 'auto')] == []
    for key in before:
        if key != (USER_A, 'auto'):
            assert after[key] == before[key]
    assert store.replace_set(url, USER_A, 'auto', ()) == 0 and total_rows(url) == 6


def test_empty_replacement_for_a_pair_with_no_rows_is_a_noop(url):
    store.replace_set(url, USER_A, 'auto', make_set(1))
    assert store.replace_set(url, USER_B, 'auto', []) == 0 and movies(url, USER_A, 'auto') == [mid(1)]


# --- validation ----------------------------------------------------------------------------------------------

def test_invalid_input_modifies_nothing_and_never_opens_a_connection(url, monkeypatch):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2, 3))
    before = snapshot(url)
    opened = []
    real = store.connect
    monkeypatch.setattr(store, 'connect', lambda u: opened.append(u) or real(u))
    bad = [make_set(4, 5) + (FinalRecommendation(candidates.Candidate({'id': mid(6)}, 0.5, {}), 0.1, ''),),
           make_set(4, 4), make_set(4, 5)[::-1], 'nonsense']
    for recommendations in bad:
        with pytest.raises(store.RecommendationInputError):
            store.replace_set(url, USER_A, 'auto', recommendations)
    with pytest.raises(store.RecommendationInputError):
        store.replace_set(url, USER_A, 'everything', make_set(4))
    with pytest.raises(store.RecommendationInputError):
        store.replace_set(url, 'not-a-uuid', 'auto', make_set(4))
    assert opened == [] and snapshot(url) == before


# --- atomicity --------------------------------------------------------------------------------------------------

class FailingConnection:
    """Delegates to a real PostgreSQL connection, raising on the Nth INSERT or on the DELETE."""

    def __init__(self, real, fail_on_insert=None, fail_on_delete=False):
        self.real, self.fail_on_insert, self.fail_on_delete, self.inserts = real, fail_on_insert, fail_on_delete, 0

    def __enter__(self):
        self.real.__enter__()
        return self

    def __exit__(self, *exc):
        return self.real.__exit__(*exc)

    def execute(self, query, params=None):
        if query.startswith('DELETE') and self.fail_on_delete:
            raise psycopg.OperationalError('injected failure on delete')
        if query.startswith('INSERT'):
            self.inserts += 1
            if self.inserts == self.fail_on_insert:
                raise psycopg.OperationalError('injected failure on insert')
        return self.real.execute(query, params)


def inject(monkeypatch, **options):
    real = store.connect
    monkeypatch.setattr(store, 'connect', lambda u: FailingConnection(real(u), **options))


def test_failure_on_the_last_insert_rolls_everything_back(url, monkeypatch):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2, 3, prefix='Old'))
    before = stored(url, USER_A, 'auto')
    inject(monkeypatch, fail_on_insert=3)                   # D and E are inserted, F fails
    with pytest.raises(psycopg.OperationalError, match='injected'):
        store.replace_set(url, USER_A, 'auto', make_set(4, 5, 6, prefix='New'))
    monkeypatch.undo()
    assert stored(url, USER_A, 'auto') == before            # exactly the old set: not [D, E], not [A, B, C, D, E]
    assert total_rows(url) == 3


@pytest.mark.parametrize('failing_insert', [1, 2])
def test_failure_on_any_earlier_insert_leaves_the_old_set(url, monkeypatch, failing_insert):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2, 3))
    before = stored(url, USER_A, 'auto')
    inject(monkeypatch, fail_on_insert=failing_insert)
    with pytest.raises(psycopg.OperationalError):
        store.replace_set(url, USER_A, 'auto', make_set(4, 5, 6))
    monkeypatch.undo()
    assert stored(url, USER_A, 'auto') == before


def test_failure_on_the_delete_leaves_the_old_set(url, monkeypatch):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2, 3))
    before = stored(url, USER_A, 'auto')
    inject(monkeypatch, fail_on_delete=True)
    with pytest.raises(psycopg.OperationalError):
        store.replace_set(url, USER_A, 'auto', make_set(4, 5))
    monkeypatch.undo()
    assert stored(url, USER_A, 'auto') == before


def test_a_real_database_constraint_violation_rolls_the_whole_set_back(url, monkeypatch):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2, 3, prefix='Old'))
    before = stored(url, USER_A, 'auto')
    rows = [(mid(4), 'ok', 1.0), (mid(5), 'ok', 0.5), (mid(6), 'violates the score CHECK', 5.0)]
    monkeypatch.setattr(store, 'validate_set', lambda u, s, r: (USER_A, 'auto', rows))        # bypass validation on purpose
    with pytest.raises(psycopg.errors.CheckViolation):
        store.replace_set(url, USER_A, 'auto', make_set(4, 5, 6))
    monkeypatch.undo()
    assert stored(url, USER_A, 'auto') == before and total_rows(url) == 3


def test_a_failed_replacement_of_one_source_does_not_affect_the_other(url, monkeypatch):
    seed_four(url)
    before = snapshot(url)
    inject(monkeypatch, fail_on_insert=2)
    with pytest.raises(psycopg.OperationalError):
        store.replace_set(url, USER_A, 'auto', make_set(20, 21, 22))
    monkeypatch.undo()
    assert snapshot(url) == before


def test_no_partial_set_is_visible_to_readers_while_the_transaction_is_open(url):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2, 3, prefix='Old'))
    before = stored(url, USER_A, 'auto')
    writer = store.connect(url)
    try:
        store._lock_set(writer, USER_A, 'auto')
        writer.execute('DELETE FROM recommendations WHERE user_id=%s AND source=%s', (USER_A, 'auto'))
        writer.execute('INSERT INTO recommendations(user_id,movie_id,reason,score,source) VALUES (%s,%s,%s,%s,%s)',
                       (USER_A, mid(9), 'uncommitted', 1.0, 'auto'))
        assert stored(url, USER_A, 'auto') == before            # readers still see the complete old set
        writer.rollback()
    finally:
        writer.close()
    assert stored(url, USER_A, 'auto') == before


# --- concurrency -------------------------------------------------------------------------------------------------

def run_in_thread(target):
    outcome = {}

    def work():
        try:
            outcome['value'] = target()
        except BaseException as error:               # noqa: BLE001 - reported to the test thread
            outcome['error'] = error
    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread, outcome


def test_same_set_waits_for_the_lock_while_other_pairs_proceed(url):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2, 3, prefix='Old'))
    before = stored(url, USER_A, 'auto')
    holder = store.connect(url)
    try:
        store._lock_set(holder, USER_A, 'auto')                  # an in-flight replacement of (A, auto)
        blocked, outcome = run_in_thread(lambda: store.replace_set(url, USER_A, 'auto', make_set(7, 8, prefix='Waiting')))
        blocked.join(0.8)
        assert blocked.is_alive()                                # serialized behind the lock holder
        started = time.monotonic()
        store.replace_set(url, USER_B, 'auto', make_set(11, 12))                    # other user: not blocked
        store.replace_set(url, USER_A, 'user_requested', make_set(13, 14))          # other source: not blocked
        assert time.monotonic() - started < 3
        assert stored(url, USER_A, 'auto') == before            # nothing of the waiting writer is visible yet
        holder.commit()                                          # releases the transaction-scoped lock
        blocked.join(10)
        assert not blocked.is_alive() and 'error' not in outcome
        assert movies(url, USER_A, 'auto') == [mid(7), mid(8)]
    finally:
        holder.close()


def test_the_lock_is_released_after_a_rollback(url, monkeypatch):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2))
    inject(monkeypatch, fail_on_insert=1)
    with pytest.raises(psycopg.OperationalError):
        store.replace_set(url, USER_A, 'auto', make_set(3, 4))
    monkeypatch.undo()
    thread, outcome = run_in_thread(lambda: store.replace_set(url, USER_A, 'auto', make_set(5, 6)))
    thread.join(10)
    assert not thread.is_alive() and 'error' not in outcome and movies(url, USER_A, 'auto') == [mid(5), mid(6)]


@pytest.mark.parametrize('writers', [2, 3])
def test_concurrent_replacements_never_produce_a_mixed_set(url, writers):
    candidate_sets = [make_set(*range(100 * w + 1, 100 * w + 5 + w), prefix='W%d' % w) for w in range(writers)]
    expected = [[mid(n) for n in range(100 * w + 1, 100 * w + 5 + w)] for w in range(writers)]
    for round_number in range(25):
        barrier = threading.Barrier(writers)

        def replace(items):
            barrier.wait()
            return store.replace_set(url, USER_A, 'auto', items)
        threads = [run_in_thread(lambda items=items: replace(items)) for items in candidate_sets]
        for thread, _ in threads:
            thread.join(30)
        errors = [outcome['error'] for _, outcome in threads if 'error' in outcome]
        assert errors == [], f'round {round_number}: {errors}'
        final = movies(url, USER_A, 'auto')
        assert final in expected, f'round {round_number}: mixed or partial set {final}'
        assert {r[1].split()[0] for r in stored(url, USER_A, 'auto')} == {'W%d' % expected.index(final)}


def test_concurrent_replacements_of_independent_pairs_stay_isolated(url):
    pairs = [(USER_A, 'auto'), (USER_A, 'user_requested'), (USER_B, 'auto'), (USER_B, 'user_requested')]
    barrier = threading.Barrier(len(pairs))

    def replace(index, user, source):
        barrier.wait()
        for repeat in range(10):
            store.replace_set(url, user, source, make_set(*range(index * 100 + 1, index * 100 + 4 + repeat % 3)))
    threads = [run_in_thread(lambda i=i, p=p: replace(i, *p)) for i, p in enumerate(pairs)]
    for thread, outcome in threads:
        thread.join(60)
        assert 'error' not in outcome
    for index, (user, source) in enumerate(pairs):
        assert set(movies(url, user, source)) <= {mid(n) for n in range(index * 100 + 1, index * 100 + 7)} and movies(url, user, source)


# --- compatibility with the existing persistence ----------------------------------------------------------------

def test_existing_save_batch_and_listing_still_work_and_are_replaced_by_replace_set(url):
    saved = store.save_batch(url, USER_A, [{'movie_id': mid(1), 'reason': 'first', 'score': 0.4},
                                           {'movie_id': mid(2), 'reason': 'second', 'score': 0.9}], 'auto')
    assert [row['reason'] for row in saved] == ['first', 'second']
    store.save_batch(url, USER_A, [{'movie_id': mid(1), 'reason': 'upserted', 'score': 0.4}], 'auto')       # upsert semantics intact
    assert [(r[0], r[1]) for r in stored(url, USER_A, 'auto')] == [(mid(2), 'second'), (mid(1), 'upserted')]
    store.replace_set(url, USER_A, 'auto', make_set(5))
    assert movies(url, USER_A, 'auto') == [mid(5)]
    store.save_batch(url, USER_A, [{'movie_id': mid(6), 'reason': 'appended', 'score': 0.1}], 'auto')       # append/upsert is distinct
    assert movies(url, USER_A, 'auto') == [mid(5), mid(6)]


def test_listing_pagination_and_remove_still_work_on_replaced_sets(url):
    store.replace_set(url, USER_A, 'auto', make_set(1, 2, 3, 4, 5))
    page = store.listing(url, USER_A, 2, 2, 'auto')
    assert page['total'] == 5 and [i['movie_id'] for i in page['items']] == [mid(3), mid(4)]
    assert store.remove(url, page['items'][0]['id']) == {'removed': True} and len(movies(url, USER_A, 'auto')) == 4
