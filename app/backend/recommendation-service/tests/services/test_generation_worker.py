"""The generation worker against a real PostgreSQL: lifecycle, failure handling, caps, heartbeat, recovery,
and the real pipeline running under it. Deterministic: threads are synchronized with Events, not sleeps."""
import logging
import threading
from types import SimpleNamespace

import flask
import psycopg
import pytest
from services import generation, jobs, pipeline, recommendations as store
from services.context import ContextError
from services.inference_client import InferenceError
from services.movie_client import MovieCatalogError
from tests.services.pipeline_support import CONFIG, OTHER_USER, USER, World, context, script

CRITERIA = pipeline.normalize_criteria(None, None)


@pytest.fixture(autouse=True)
def empty_tables(url):
    with store.connect(url) as conn:
        conn.execute('DELETE FROM generation_jobs')
        conn.execute('DELETE FROM recommendations')


def queue(url, user=USER, source='user_requested', criteria=CRITERIA):
    return jobs.submit(url, user, source, criteria, 10)


def job_row(url, job_id):
    with store.connect(url) as conn:
        return conn.execute('SELECT * FROM generation_jobs WHERE id=%s', (job_id,)).fetchone()


def make_worker(url, **options):
    return generation.Worker({**CONFIG, 'DATABASE_URL': url}, poll_seconds=0.05, heartbeat_seconds=0.05, **options)


def fake_result(count=10, outcome='llm', attempts=1, used_fallback=False, reason=None, seconds=0.5):
    return SimpleNamespace(persisted_count=count, outcome=outcome, attempts=attempts, used_fallback=used_fallback,
                           fallback_reason=reason, duration_seconds=seconds)


def run_in_thread(target):
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


# --- lifecycle -------------------------------------------------------------------------------------------------------

def test_a_job_goes_queued_running_succeeded(url, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def fake(*args):
        entered.set()
        assert release.wait(20)
        return fake_result(count=7, outcome='llm_after_retry', attempts=2)
    monkeypatch.setattr(pipeline, 'generate_recommendations', fake)
    job = queue(url)
    assert job['status'] == 'queued'
    thread = run_in_thread(make_worker(url).run_once)
    assert entered.wait(20)
    running = job_row(url, job['id'])
    assert running['status'] == 'running' and running['started_at'] is not None and running['finished_at'] is None
    release.set()
    thread.join(20)
    done = job_row(url, job['id'])
    assert (done['status'], done['recommendation_count'], done['outcome'], done['attempts'], done['used_fallback']) == ('succeeded', 7, 'llm_after_retry', 2, False)
    assert done['finished_at'] is not None and done['error'] is None


def test_the_worker_calls_the_existing_pipeline_with_explicit_inputs(url, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, 'generate_recommendations', lambda *args: calls.append(args) or fake_result())
    criteria = pipeline.normalize_criteria({'genres': ['Action'], 'year_from': 1990, 'duration': 'medium'}, 15)
    queue(url, USER, 'user_requested', criteria)
    assert make_worker(url).run_once() is True
    [(config, user_id, source, filters)] = calls
    assert (user_id, source, filters) == (USER, 'user_requested', criteria) and filters['count'] == 15
    assert isinstance(config, dict) and config['DATABASE_URL'] == url and config['INFERENCE_SERVICE_URL'] == CONFIG['INFERENCE_SERVICE_URL']


def test_the_worker_snapshots_its_configuration(url):
    live = {**CONFIG, 'DATABASE_URL': url}
    worker = generation.Worker(live)
    live['DATABASE_URL'] = 'postgresql://changed.invalid/db'
    assert worker.config['DATABASE_URL'] == url and worker.config is not live


def test_no_flask_context_is_available_inside_the_job(url, monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, 'generate_recommendations',
                        lambda *a: seen.append((flask.has_app_context(), flask.has_request_context())) or fake_result())
    queue(url)
    app = flask.Flask('ctx')
    with app.app_context(), app.test_request_context():
        thread = run_in_thread(make_worker(url).run_once)      # the caller has a context; the job thread must not inherit it
        thread.join(20)
    assert seen == [(False, False)]


def test_a_started_worker_executes_jobs_off_the_calling_thread(url, monkeypatch):
    done, where = threading.Event(), []

    def fake(*args):
        where.append(threading.current_thread())
        done.set()
        return fake_result()
    monkeypatch.setattr(pipeline, 'generate_recommendations', fake)
    worker = make_worker(url)
    worker.start()
    try:
        job = queue(url)
        worker.wake()
        assert done.wait(20)
    finally:
        worker.stop()
    assert where[0] is not threading.main_thread() and where[0].name == 'generation-worker'
    assert job_row(url, job['id'])['status'] == 'succeeded'


def test_start_is_idempotent_and_bounded_to_two_threads(url):
    worker = make_worker(url)
    worker.start(), worker.start(), worker.start()
    try:
        assert len(worker._threads) == 2 and all(t.daemon for t in worker._threads)
    finally:
        worker.stop()
    assert not any(t.is_alive() for t in worker._threads)


def test_idle_worker_returns_false_without_calling_the_pipeline(url, monkeypatch):
    monkeypatch.setattr(pipeline, 'generate_recommendations', lambda *a: pytest.fail('nothing to run'))
    assert make_worker(url).run_once() is False


# --- failures ---------------------------------------------------------------------------------------------------------

FAILURES = [(ContextError(503, 'User context unavailable. Please retry.'), 'user_service_unavailable'),
            (ContextError(404, 'User not found.'), 'user_not_found'),
            (MovieCatalogError('http://internal-host:4206 SECRET'), 'movie_catalog_unavailable'),
            (ValueError('SECRET detail'), 'invalid_request'),
            (store.RecommendationInputError('SECRET detail'), 'invalid_request'),
            (psycopg.OperationalError('postgresql://user:pw-SECRET@host/db down'), 'database_error'),
            (RuntimeError('SECRET boom'), 'internal_error'), (KeyError('SECRET'), 'internal_error'),
            (InferenceError('SECRET'), 'internal_error')]


@pytest.mark.parametrize('error,category', FAILURES)
def test_failures_become_failed_jobs_with_a_safe_category(url, monkeypatch, caplog, error, category):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(pipeline, 'generate_recommendations', Mock_raising(error))
    job = queue(url)
    assert make_worker(url).run_once() is True
    failed = job_row(url, job['id'])
    assert (failed['status'], failed['error']) == ('failed', category) and failed['outcome'] is None
    assert 'SECRET' not in repr(dict(failed)) and 'SECRET' not in caplog.text and 'internal-host' not in caplog.text
    assert generation.classify_failure(error) == category


def Mock_raising(error):
    def fake(*args):
        raise error
    return fake


def test_a_failing_job_does_not_stop_later_jobs(url, monkeypatch):
    outcomes = [RuntimeError('boom'), fake_result()]

    def fake(*args):
        item = outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    monkeypatch.setattr(pipeline, 'generate_recommendations', fake)
    first, second = queue(url, USER), queue(url, OTHER_USER)
    worker = make_worker(url)
    assert worker.run_once() and worker.run_once()
    assert (job_row(url, first['id'])['status'], job_row(url, second['id'])['status']) == ('failed', 'succeeded')


def test_the_worker_loop_survives_an_infrastructure_error(url, monkeypatch):
    real_claim, done = jobs.claim_next, threading.Event()
    state = {'failed': False}

    def flaky(*args, **kwargs):
        if not state['failed']:
            state['failed'] = True
            raise psycopg.OperationalError('database restarting')
        return real_claim(*args, **kwargs)
    monkeypatch.setattr(jobs, 'claim_next', flaky)
    monkeypatch.setattr(pipeline, 'generate_recommendations', lambda *a: done.set() or fake_result())
    worker = make_worker(url)
    worker.start()
    try:
        job = queue(url)
        worker.wake()
        assert done.wait(20)
    finally:
        worker.stop()
    assert state['failed'] and job_row(url, job['id'])['status'] == 'succeeded'


def test_lifecycle_logs_are_concise_and_safe(url, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger='services.generation')
    monkeypatch.setattr(pipeline, 'generate_recommendations', lambda *a: fake_result(count=4, outcome='llm', seconds=1.25))
    queue(url)
    make_worker(url).run_once()
    monkeypatch.setattr(pipeline, 'generate_recommendations', Mock_raising(ContextError(503, 'SECRET')))
    queue(url, OTHER_USER)
    make_worker(url).run_once()
    started, succeeded, started2, failed = [r.getMessage() for r in caplog.records if r.name == 'services.generation']
    assert started.startswith('Generation job started (job=') and 'source=user_requested' in started
    assert 'outcome=llm' in succeeded and 'persisted=4' in succeeded and 'seconds=1.2' in succeeded
    assert 'category=user_service_unavailable' in failed and 'error=ContextError' in failed
    assert 'SECRET' not in caplog.text and USER not in caplog.text and OTHER_USER not in caplog.text


# --- capacity across workers, heartbeat and recovery ----------------------------------------------------------------------

def test_two_workers_never_run_more_jobs_than_the_global_cap(url, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def fake(*args):
        entered.set()
        assert release.wait(20)
        return fake_result()
    monkeypatch.setattr(pipeline, 'generate_recommendations', fake)
    first, second = queue(url, USER), queue(url, OTHER_USER)
    worker_a, worker_b = make_worker(url), make_worker(url)           # two "processes" sharing the database
    thread = run_in_thread(worker_a.run_once)
    assert entered.wait(20)
    assert worker_b.run_once() is False and job_row(url, second['id'])['status'] == 'queued'
    release.set()
    thread.join(20)
    assert worker_b.run_once() is True and job_row(url, second['id'])['status'] == 'succeeded'
    assert job_row(url, first['id'])['status'] == 'succeeded'


def test_a_running_job_is_kept_alive_by_the_heartbeat(url, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def fake(*args):
        entered.set()
        assert release.wait(20)
        return fake_result()
    monkeypatch.setattr(pipeline, 'generate_recommendations', fake)
    job = queue(url)
    worker = make_worker(url)
    worker.start()
    try:
        worker.wake()
        assert entered.wait(20)
        with store.connect(url) as conn:
            conn.execute("UPDATE generation_jobs SET heartbeat_at = now() - interval '5 minutes' WHERE id=%s", (job['id'],))
        refreshed = threading.Event()
        deadline = threading.Event()
        for _ in range(500):
            with store.connect(url) as conn:
                age = conn.execute("SELECT now() - heartbeat_at AS age FROM generation_jobs WHERE id=%s", (job['id'],)).fetchone()['age']
            if age.total_seconds() < 5:
                refreshed.set()
                break
            deadline.wait(0.02)
        assert refreshed.is_set()
        assert jobs.recover_stale(url) == 0 and job_row(url, job['id'])['status'] == 'running'
    finally:
        release.set()
        worker.stop()


def test_a_dead_process_job_is_failed_as_interrupted_and_does_not_block_the_queue(url, monkeypatch):
    monkeypatch.setattr(pipeline, 'generate_recommendations', lambda *a: fake_result())
    dead, waiting = queue(url, USER), queue(url, OTHER_USER)
    jobs.claim_next(url, 'process-that-died', 1)
    assert make_worker(url).run_once() is False                       # still within the heartbeat window: the cap is held
    with store.connect(url) as conn:
        conn.execute("UPDATE generation_jobs SET heartbeat_at = now() - interval '5 minutes' WHERE id=%s", (dead['id'],))
    assert make_worker(url).run_once() is True
    assert (job_row(url, dead['id'])['status'], job_row(url, dead['id'])['error']) == ('failed', 'interrupted')
    assert job_row(url, waiting['id'])['status'] == 'succeeded'


def test_jobs_queued_before_a_restart_are_picked_up_by_the_new_process(url, monkeypatch):
    monkeypatch.setattr(pipeline, 'generate_recommendations', lambda *a: fake_result())
    job = queue(url)                                                   # queued by "the previous process"
    assert make_worker(url).run_once() is True and job_row(url, job['id'])['status'] == 'succeeded'


def test_a_result_arriving_after_the_job_was_declared_interrupted_is_ignored(url, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger='services.generation')
    job = queue(url)

    def fake(*args):
        with store.connect(url) as conn:
            conn.execute("UPDATE generation_jobs SET heartbeat_at = now() - interval '5 minutes' WHERE id=%s", (job['id'],))
        jobs.recover_stale(url)
        return fake_result()
    monkeypatch.setattr(pipeline, 'generate_recommendations', fake)
    assert make_worker(url).run_once() is True
    assert (job_row(url, job['id'])['status'], job_row(url, job['id'])['error']) == ('failed', 'interrupted')
    assert 'no longer running' in caplog.text


# --- the real pipeline under the worker (only the three external services are faked) -------------------------------------------

@pytest.fixture
def world(monkeypatch, url):
    return World(monkeypatch, context(watched=[1, 2], watchlist=[3]), fake_persistence=False, config={**CONFIG, 'DATABASE_URL': url})


def run_job(world, url, source='user_requested', filters=None, count=None, user=USER):
    job = queue(url, user, source, pipeline.normalize_criteria(filters, count))
    assert generation.Worker(world.config).run_once() is True
    return job_row(url, job['id'])


def listed(url, user=USER, source='user_requested'):
    return [(i['movie_id'], i['reason'], i['score']) for i in store.listing(url, user, 0, 100, source)['items']]


def test_normal_llm_result_succeeds_and_persists(world, url):
    done = run_job(world, url)
    assert (done['status'], done['outcome'], done['attempts'], done['used_fallback'], done['recommendation_count']) == ('succeeded', 'llm', 1, False, 10)
    assert len(listed(url)) == 10 and world.llm.call_count == 1


def test_success_after_a_retry_is_a_succeeded_job(world, url):
    world.llm = script('not json')
    done = run_job(world, url)
    assert (done['status'], done['outcome'], done['attempts'], done['used_fallback']) == ('succeeded', 'llm_after_retry', 2, False)


def test_deterministic_fallback_is_a_succeeded_job_not_a_failed_one(world, url):
    run_job(world, url, count=10)
    old = listed(url)
    world.llm = script(InferenceError('down'))
    done = run_job(world, url, count=5)
    assert (done['status'], done['outcome'], done['used_fallback'], done['fallback_reason'], done['recommendation_count'], done['error']) == (
        'succeeded', 'fallback_inference_error', True, 'inference_error', 5, None)
    assert len(listed(url)) == 5 and listed(url) != old


def test_two_invalid_answers_also_succeed_through_the_fallback(world, url):
    world.llm = script('bad', 'bad')
    done = run_job(world, url)
    assert (done['status'], done['outcome'], done['attempts'], done['fallback_reason']) == ('succeeded', 'fallback_validation_error', 2, 'validation_error')


def test_no_candidates_is_succeeded_with_zero_recommendations_and_clears_only_the_targeted_set(world, url):
    run_job(world, url, 'user_requested')
    pipeline.generate_recommendations(world.config, USER, 'auto', None, 5)
    calls = world.llm.call_count
    done = run_job(world, url, 'user_requested', filters={'genres': ['Horror'], 'year_from': 1888, 'year_to': 1888})
    assert (done['status'], done['outcome'], done['recommendation_count'], done['attempts'], done['error']) == ('succeeded', 'no_candidates', 0, 0, None)
    assert world.llm.call_count == calls and listed(url, source='user_requested') == [] and len(listed(url, source='auto')) == 5


@pytest.mark.parametrize('failure,category', [
    ('context', 'user_service_unavailable'), ('catalog', 'movie_catalog_unavailable'), ('genre', 'invalid_request'),
    ('empty catalog', 'movie_catalog_unavailable'), ('llm bug', 'internal_error'), ('database', 'database_error')])
def test_failed_generation_marks_the_job_failed_and_preserves_the_old_set(world, url, monkeypatch, failure, category):
    pipeline.generate_recommendations(world.config, USER, 'user_requested', None, 10)
    before = listed(url)
    filters = None
    if failure == 'context':
        world.context_error = ContextError(503, 'User context unavailable. Please retry.')
    elif failure == 'catalog':
        world.catalog_error = MovieCatalogError('Movie catalog unavailable. Please retry.')
    elif failure == 'genre':
        filters = {'genres': ['CompletelyInvalidGenre']}
    elif failure == 'empty catalog':
        world.catalog = []
    elif failure == 'llm bug':
        world.llm = script(RuntimeError('programming error'))
    else:
        monkeypatch.setattr(pipeline, 'replace_set', Mock_raising(psycopg.OperationalError('database down')))
    done = run_job(world, url, filters=filters)
    assert (done['status'], done['error']) == ('failed', category) and done['outcome'] is None and done['recommendation_count'] is None
    assert listed(url) == before and len(before) == 10


def test_different_users_and_sources_stay_isolated(world, url):
    run_job(world, url, 'user_requested', user=USER)
    pipeline.generate_recommendations(world.config, USER, 'auto', None, 5)
    world.context = context(watched=[1, 2], watchlist=[3], user_id=OTHER_USER)
    run_job(world, url, 'user_requested', user=OTHER_USER, count=5)
    assert len(listed(url, USER, 'user_requested')) == 10 and len(listed(url, USER, 'auto')) == 5 and len(listed(url, OTHER_USER, 'user_requested')) == 5
    assert listed(url, OTHER_USER, 'auto') == []
