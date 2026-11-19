"""The real pipeline against a real PostgreSQL (throwaway database from the `url` fixture).

Only the external services are faked (User Service, Movie Service, inference); profile, filtering, scoring,
selection, assembly and replace_set are the real implementations.
"""
import psycopg
import pytest
from services import pipeline, recommendations as store
from services.context import ContextError
from services.inference_client import InferenceError
from services.movie_client import MovieCatalogError
from tests.services.pipeline_support import CONFIG, OTHER_USER, USER, World, context, mid, script
from tests.services.test_replace_set_postgres import FailingConnection


@pytest.fixture(autouse=True)
def empty_table(url):
    with store.connect(url) as conn:
        conn.execute('DELETE FROM recommendations')


@pytest.fixture
def world(monkeypatch, url):
    return World(monkeypatch, context(watched=[1, 2], watchlist=[3]), fake_persistence=False, config={**CONFIG, 'DATABASE_URL': url})


def rows(url, user=USER, source=None):
    return [(i['movie_id'], i['reason'], i['score'], i['source']) for i in store.listing(url, user, 0, 100, source)['items']]


def expected(result):
    return [(item.candidate.movie['id'], item.reason, item.score, result.source) for item in result.recommendations]


def total(url):
    with store.connect(url) as conn:
        return conn.execute('SELECT count(*) AS n FROM recommendations').fetchone()['n']


def test_generated_set_is_persisted_exactly_and_listed_in_final_order(world, url):
    result = world.run('user_requested')
    assert result.persisted_count == 10 and rows(url) == expected(result)
    scores = [r[2] for r in rows(url)]
    assert scores == pytest.approx([1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1])
    assert not {mid(1), mid(2)} & {r[0] for r in rows(url)}


def test_a_new_generation_atomically_replaces_the_previous_one(world, url):
    first = world.run('auto', count=10)
    ids_before = {i['id'] for i in store.listing(url, USER, 0, 100, 'auto')['items']}
    second = world.run('auto', count=5)
    assert len(rows(url, source='auto')) == 5 and rows(url, source='auto') == expected(second)
    assert not ids_before & {i['id'] for i in store.listing(url, USER, 0, 100, 'auto')['items']}
    assert first.persisted_count == 10 and total(url) == 5


def test_sources_and_users_are_isolated(world, url):
    auto = world.run('auto')
    requested = world.run('user_requested', filters={'genres': ['Horror']})
    other = world.run('auto', user_id=OTHER_USER)
    assert rows(url, source='auto') == expected(auto) and rows(url, source='user_requested') == expected(requested)
    assert rows(url, OTHER_USER, 'auto') == expected(other) and rows(url, OTHER_USER, 'user_requested') == []
    world.run('user_requested', count=5)
    assert rows(url, source='auto') == expected(auto) and rows(url, OTHER_USER, 'auto') == expected(other)
    assert len(rows(url, source='user_requested')) == 5


def test_fallback_generation_is_persisted_and_replaces_the_previous_set(world, url):
    world.run('auto')
    world.llm = script(InferenceError('down'))
    result = world.run('auto', count=5)
    assert result.outcome == 'fallback_inference_error' and rows(url, source='auto') == expected(result) and total(url) == 5


@pytest.mark.parametrize('failure', ['context', 'catalog'])
def test_upstream_failure_preserves_the_previous_set_and_never_writes_an_empty_one(world, url, failure):
    world.run('auto')
    before = rows(url, source='auto')
    if failure == 'context':
        world.context_error = ContextError(503, 'User context unavailable. Please retry.')
    else:
        world.catalog_error = MovieCatalogError('Movie catalog unavailable. Please retry.')
    with pytest.raises((ContextError, MovieCatalogError)):
        world.run('auto')
    assert rows(url, source='auto') == before and len(before) == 10


def test_unexpected_selection_error_preserves_the_previous_set(world, url, monkeypatch):
    world.run('auto')
    before = rows(url, source='auto')
    world.llm = script(RuntimeError('bug'))
    with pytest.raises(RuntimeError):
        world.run('auto')
    assert rows(url, source='auto') == before


def test_invalid_input_preserves_the_previous_set(world, url):
    world.run('auto')
    before = rows(url, source='auto')
    for kwargs in ({'filters': {'duration': 'weird'}}, {'count': 7}, {'source': 'everything'}):
        with pytest.raises(ValueError):
            world.run(**{'source': 'auto', **kwargs})
    assert rows(url, source='auto') == before


def test_zero_eligible_movies_replaces_only_the_targeted_set_with_an_empty_one(world, url):
    world.run('auto')
    world.run('user_requested')
    llm_calls = world.llm.call_count
    result = world.run('user_requested', filters={'year_from': 1888, 'year_to': 1888})
    assert result.outcome == 'no_candidates' and result.persisted_count == 0 and world.llm.call_count == llm_calls
    assert rows(url, source='user_requested') == [] and len(rows(url, source='auto')) == 10


def test_a_persistence_failure_midway_rolls_back_and_propagates(world, url, monkeypatch):
    world.run('auto')
    before = rows(url, source='auto')
    real = store.connect
    monkeypatch.setattr(store, 'connect', lambda u: FailingConnection(real(u), fail_on_insert=4))
    with pytest.raises(psycopg.OperationalError, match='injected'):
        world.run('auto', count=5)
    monkeypatch.undo()
    assert rows(url, source='auto') == before and len(before) == 10


def test_a_database_that_is_down_propagates_after_inference_and_changes_nothing(world, url, monkeypatch):
    world.run('auto')
    before = rows(url, source='auto')
    monkeypatch.setattr(store, 'connect', lambda u: (_ for _ in ()).throw(psycopg.OperationalError('database down')))
    with pytest.raises(psycopg.OperationalError):
        world.run('auto')
    monkeypatch.undo()
    assert rows(url, source='auto') == before


def test_pipeline_uses_replace_set_not_the_upsert_path(world, url, monkeypatch):
    saved = []
    monkeypatch.setattr(store, 'save_batch', lambda *a, **k: saved.append(a))
    world.run('auto')
    assert saved == [] and not hasattr(pipeline, 'save_batch') and len(rows(url, source='auto')) == 10


@pytest.mark.parametrize('source', ['auto', 'user_requested'])
def test_unsupported_genre_or_language_preserves_the_previous_set_and_writes_nothing(world, url, source):
    world.run('auto')
    world.run('user_requested')
    before = {s: rows(url, source=s) for s in ('auto', 'user_requested')}
    for filters in ({'genres': ['CompletelyInvalidGenre']}, {'languages': ['xx']}):
        with pytest.raises(ValueError):
            world.run(source, filters=filters)
    assert {s: rows(url, source=s) for s in ('auto', 'user_requested')} == before and total(url) == 20


def test_valid_filters_matching_nothing_still_clear_only_the_targeted_set(world, url):
    world.run('auto')
    world.run('user_requested')
    result = world.run('user_requested', filters={'genres': ['Horror'], 'year_from': 1888, 'year_to': 1888})
    assert result.outcome == 'no_candidates' and rows(url, source='user_requested') == [] and len(rows(url, source='auto')) == 10


@pytest.mark.parametrize('source', ['auto', 'user_requested'])
def test_an_empty_catalog_preserves_the_previous_set(monkeypatch, url, source):
    world = World(monkeypatch, context(watched=[1, 2]), fake_persistence=False, config={**CONFIG, 'DATABASE_URL': url})
    world.run(source)
    before = rows(url, source=source)
    world.catalog = []
    with pytest.raises(MovieCatalogError, match='empty'):
        world.run(source)
    assert rows(url, source=source) == before and len(before) == 10


def test_all_movies_watched_is_a_valid_empty_result_unlike_an_empty_catalog(world, url):
    world.run('auto')
    world.context = context(watched=list(range(1, 61)))
    result = world.run('auto')
    assert result.outcome == 'no_candidates' and rows(url, source='auto') == []
