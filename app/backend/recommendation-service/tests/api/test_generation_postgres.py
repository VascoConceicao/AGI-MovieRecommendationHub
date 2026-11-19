"""Asynchronous generation over HTTP with a real PostgreSQL and the real pipeline, job store and worker.

Only the three external services are faked (User Service, Movie Service, inference). Jobs are driven either
deterministically through Worker.run_once() or by the real worker thread, synchronized with Events (no sleeps).
"""
import threading

import pytest
from main import create_app
from services import generation, jobs, pipeline, recommendations as store
from services.context import ContextError
from services.inference_client import InferenceError
from tests.services.pipeline_support import CONFIG, OTHER_USER, USER, World, context, script

HEADERS = {'Authorization': 'Bearer test'}


@pytest.fixture(autouse=True)
def empty_tables(url):
    with store.connect(url) as conn:
        conn.execute('DELETE FROM generation_jobs')
        conn.execute('DELETE FROM recommendations')


def make_app(url, **config):
    app = create_app()
    app.config.update(TESTING=True, DATABASE_URL=url, RECOMMENDATION_API_TOKEN='test', **config)
    return app


@pytest.fixture
def app(url):
    return make_app(url)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def world(monkeypatch, url):
    return World(monkeypatch, context(watched=[1, 2], watchlist=[3]), fake_persistence=False, config={**CONFIG, 'DATABASE_URL': url})


def post(client, body=None, **extra):
    return client.post('/recommendations/generate', json={'user_id': USER, **(body or {})}, headers=HEADERS, **extra)


def status(client, job_id, user=USER):
    return client.get(f'/recommendations/generations/{job_id}?user_id={user}', headers=HEADERS)


def listing(client, user=USER, source='user_requested'):
    body = client.get(f'/recommendations?user_id={user}&source={source}&limit=100', headers=HEADERS).get_json()
    return [(i['movie_id'], i['reason'], i['score'], i['source']) for i in body['items']]


def run_worker(app, world):
    """Run exactly one queued job on the app's worker, in this thread, with the world's faked services."""
    worker = generation.get_worker(app)
    worker.config.update(world.config)
    return worker.run_once()


# --- the full flow ------------------------------------------------------------------------------------------------------

def test_post_then_poll_then_read_the_persisted_recommendations(client, app, world):
    response = post(client, {'count': 10})
    assert response.status_code == 202
    job_id = response.get_json()['job_id']
    assert response.get_json()['status'] == 'queued' and status(client, job_id).get_json()['status'] == 'queued'
    assert listing(client) == []
    assert run_worker(app, world) is True
    done = status(client, job_id).get_json()
    assert (done['status'], done['outcome'], done['attempts'], done['used_fallback'], done['recommendation_count']) == ('succeeded', 'llm', 1, False, 10)
    stored = listing(client)
    assert len(stored) == 10 and {s[3] for s in stored} == {'user_requested'}
    assert [s[2] for s in stored] == pytest.approx([1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1])
    assert all(isinstance(s[1], str) and s[1] for s in stored)
    watched = {str(world.context['watched'][i]['movie_id']) for i in range(2)}
    assert not watched & {s[0] for s in stored}


def test_filters_and_count_travel_through_the_job_to_the_pipeline(client, app, world):
    job_id = post(client, {'filters': {'genres': ['Action', 'Drama'], 'duration': 'medium', 'year_from': 1990}, 'count': 5}).get_json()['job_id']
    run_worker(app, world)
    done = status(client, job_id).get_json()
    assert done['status'] == 'succeeded' and done['requested_count'] == 5 and done['recommendation_count'] == 5
    assert len(listing(client)) == 5


def test_old_recommendations_stay_visible_while_a_job_is_queued_and_running(client, app, world, url):
    pipeline.generate_recommendations(world.config, USER, 'user_requested', None, 10)
    old = listing(client)
    assert len(old) == 10
    world.gate, world.gate_entered = threading.Event(), threading.Event()
    job_id = post(client, {'count': 5}).get_json()['job_id']
    assert listing(client) == old                                         # queued: nothing was deleted
    thread = threading.Thread(target=lambda: run_worker(app, world), daemon=True)
    thread.start()
    assert world.gate_entered.wait(20)
    assert status(client, job_id).get_json()['status'] == 'running' and status(client, job_id).get_json()['started_at']
    assert listing(client) == old                                         # running: still the previous set
    world.gate.set()
    thread.join(30)
    assert status(client, job_id).get_json()['status'] == 'succeeded'
    assert len(listing(client)) == 5 and listing(client) != old


def test_the_real_worker_thread_processes_the_job_off_the_request_thread(url, world):
    app = make_app(url, GENERATION_WORKER=True)
    app.config.update(INFERENCE_SERVICE_URL=world.config['INFERENCE_SERVICE_URL'])
    worker = generation.get_worker(app)
    worker.config.update(world.config)
    worker.poll_seconds, worker.heartbeat_seconds = 0.05, 0.05
    finished, threads = threading.Event(), []
    real_finish = jobs.finish_success

    def finish(*args):
        threads.append(threading.current_thread().name)
        outcome = real_finish(*args)
        finished.set()
        return outcome
    jobs.finish_success = finish
    try:
        client = app.test_client()
        job_id = post(client).get_json()['job_id']                         # the first request also starts the worker
        assert finished.wait(30)
    finally:
        jobs.finish_success = real_finish
        worker.stop()
    assert threads == ['generation-worker'] and status(client, job_id).get_json()['status'] == 'succeeded'
    assert len(listing(client)) == 10


# --- outcomes -----------------------------------------------------------------------------------------------------------------

def test_deterministic_fallback_is_a_succeeded_job_and_persists_the_fallback(client, app, world):
    world.llm = script(InferenceError('down'))
    job_id = post(client).get_json()['job_id']
    run_worker(app, world)
    done = status(client, job_id).get_json()
    assert (done['status'], done['outcome'], done['used_fallback'], done['fallback_reason']) == ('succeeded', 'fallback_inference_error', True, 'inference_error')
    assert len(listing(client)) == 10 and 'error' not in done


def test_retry_success_and_double_invalid_fallback(client, app, world):
    world.llm = script('not json')
    first = post(client).get_json()['job_id']
    run_worker(app, world)
    assert status(client, first).get_json()['outcome'] == 'llm_after_retry'
    world.llm = script('bad', 'bad')
    second = post(client).get_json()['job_id']
    run_worker(app, world)
    done = status(client, second).get_json()
    assert (done['status'], done['outcome'], done['attempts']) == ('succeeded', 'fallback_validation_error', 2)


def test_no_candidates_is_succeeded_and_clears_only_the_targeted_set(client, app, world):
    pipeline.generate_recommendations(world.config, USER, 'user_requested', None, 10)
    pipeline.generate_recommendations(world.config, USER, 'auto', None, 5)
    calls = world.llm.call_count
    job_id = post(client, {'filters': {'genres': ['Horror'], 'year_from': 1888, 'year_to': 1888}}).get_json()['job_id']
    run_worker(app, world)
    done = status(client, job_id).get_json()
    assert (done['status'], done['outcome'], done['recommendation_count']) == ('succeeded', 'no_candidates', 0)
    assert listing(client) == [] and len(listing(client, source='auto')) == 5 and world.llm.call_count == calls


@pytest.mark.parametrize('failure,category', [('context', 'user_service_unavailable'), ('catalog', 'movie_catalog_unavailable'),
                                              ('genre', 'invalid_request'), ('llm bug', 'internal_error')])
def test_a_failed_generation_is_a_failed_job_and_keeps_the_old_recommendations(client, app, world, failure, category):
    pipeline.generate_recommendations(world.config, USER, 'user_requested', None, 10)
    before = listing(client)
    body = {}
    if failure == 'context':
        world.context_error = ContextError(503, 'User context unavailable. Please retry.')
    elif failure == 'catalog':
        world.catalog = []
    elif failure == 'genre':
        body = {'filters': {'genres': ['CompletelyInvalidGenre']}}                 # passes the structural check; fails against the catalog
    else:
        world.llm = script(RuntimeError('SECRET programming error'))
    job_id = post(client, body).get_json()['job_id']
    run_worker(app, world)
    failed = status(client, job_id)
    assert failed.status_code == 200
    assert (failed.get_json()['status'], failed.get_json()['error']) == ('failed', category)
    assert 'SECRET' not in failed.get_data(as_text=True) and 'outcome' not in failed.get_json()
    assert listing(client) == before and len(before) == 10


def test_different_users_and_sources_are_isolated(client, app, world):
    post(client)
    run_worker(app, world)
    pipeline.generate_recommendations(world.config, USER, 'auto', None, 5)
    world.context = context(watched=[1, 2], watchlist=[3], user_id=OTHER_USER)
    other = client.post('/recommendations/generate', json={'user_id': OTHER_USER, 'count': 5}, headers=HEADERS).get_json()['job_id']
    run_worker(app, world)
    assert status(client, other, OTHER_USER).get_json()['status'] == 'succeeded'
    assert len(listing(client, USER)) == 10 and len(listing(client, USER, 'auto')) == 5
    assert len(listing(client, OTHER_USER)) == 5 and listing(client, OTHER_USER, 'auto') == []


def test_a_job_is_visible_only_to_its_own_user(client, app, world):
    job_id = post(client).get_json()['job_id']
    assert status(client, job_id, USER).status_code == 200
    assert status(client, job_id, OTHER_USER).status_code == 404
    assert status(client, '00000000-0000-0000-0000-0000000000ff').status_code == 404


# --- duplicates and capacity -----------------------------------------------------------------------------------------------------

def test_repeated_requests_for_the_same_user_and_source_conflict_until_the_job_finishes(client, app, world):
    first = post(client, {'count': 10})
    assert first.status_code == 202
    for body in ({'count': 10}, {'count': 5}, {'filters': {'genres': ['Action']}}):
        duplicate = post(client, body)
        assert duplicate.status_code == 409 and duplicate.get_json()['job_id'] == first.get_json()['job_id']
        assert duplicate.get_json()['status'] == 'queued'
    run_worker(app, world)
    assert post(client).status_code == 202                                   # a new generation is allowed afterwards


def test_a_conflict_is_reported_while_the_job_is_running(client, app, world):
    world.gate, world.gate_entered = threading.Event(), threading.Event()
    job_id = post(client).get_json()['job_id']
    thread = threading.Thread(target=lambda: run_worker(app, world), daemon=True)
    thread.start()
    assert world.gate_entered.wait(20)
    duplicate = post(client)
    assert duplicate.status_code == 409 and duplicate.get_json() == {
        'error': 'A generation is already queued or running for this user.', 'job_id': job_id, 'status': 'running'}
    world.gate.set()
    thread.join(30)


def test_simultaneous_duplicate_posts_create_exactly_one_job(app, url):
    barrier, responses = threading.Barrier(8), []

    def attempt():
        client = app.test_client()
        barrier.wait()
        responses.append(post(client))
    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    codes = sorted(r.status_code for r in responses)
    assert codes == [202] + [409] * 7
    accepted = next(r for r in responses if r.status_code == 202).get_json()['job_id']
    assert {r.get_json()['job_id'] for r in responses if r.status_code == 409} == {accepted}
    with store.connect(url) as conn:
        assert conn.execute("SELECT count(*) AS n FROM generation_jobs WHERE status IN ('queued','running')").fetchone()['n'] == 1


def test_the_queue_is_bounded_and_rejects_excess_requests_with_503(url):
    app = make_app(url, GENERATION_MAX_QUEUED=2)
    client = app.test_client()
    users = [str(__import__('uuid').UUID(int=0x100 + n)) for n in range(4)]
    codes = [client.post('/recommendations/generate', json={'user_id': u}, headers=HEADERS) for u in users]
    assert [r.status_code for r in codes] == [202, 202, 503, 503] and codes[2].headers['Retry-After'] == '30'
    with store.connect(url) as conn:
        assert conn.execute("SELECT count(*) AS n FROM generation_jobs").fetchone()['n'] == 2


def test_a_queue_slot_frees_when_a_job_starts_running(url):
    app = make_app(url, GENERATION_MAX_QUEUED=1)
    client = app.test_client()
    first = client.post('/recommendations/generate', json={'user_id': USER}, headers=HEADERS)
    assert first.status_code == 202
    assert client.post('/recommendations/generate', json={'user_id': OTHER_USER}, headers=HEADERS).status_code == 503
    jobs.claim_next(url, 'someone', 1)
    assert client.post('/recommendations/generate', json={'user_id': OTHER_USER}, headers=HEADERS).status_code == 202


def test_no_more_than_the_configured_number_of_jobs_run_at_once(url, world):
    app_a, app_b = make_app(url), make_app(url)                                # two "processes" sharing the database
    client = app_a.test_client()
    first = post(client).get_json()['job_id']
    second = client.post('/recommendations/generate', json={'user_id': OTHER_USER}, headers=HEADERS).get_json()['job_id']
    world.gate, world.gate_entered = threading.Event(), threading.Event()
    thread = threading.Thread(target=lambda: run_worker(app_a, world), daemon=True)
    thread.start()
    assert world.gate_entered.wait(20)
    assert generation.get_worker(app_b).run_once() is False                  # the global cap holds across workers
    assert status(client, second, OTHER_USER).get_json()['status'] == 'queued'
    world.gate.set()
    thread.join(30)
    assert status(client, first).get_json()['status'] == 'succeeded'


# --- process safety ---------------------------------------------------------------------------------------------------------------------

def test_job_state_is_shared_between_independent_app_instances(url, world):
    app_a, app_b = make_app(url), make_app(url)
    client_a, client_b = app_a.test_client(), app_b.test_client()
    job_id = post(client_a).get_json()['job_id']
    assert status(client_b, job_id).get_json()['status'] == 'queued'          # queued through A, visible through B
    assert post(client_b).status_code == 409                                   # duplicate detection spans instances
    assert run_worker(app_b, world) is True                                    # executed by B's worker
    assert status(client_a, job_id).get_json()['status'] == 'succeeded' and len(listing(client_a)) == 10


def test_a_job_left_running_by_a_dead_process_is_failed_and_does_not_block_the_user(client, url):
    job_id = post(client).get_json()['job_id']
    jobs.claim_next(url, 'process-that-died', 1)
    assert post(client).status_code == 409                                     # looks alive: its heartbeat is fresh
    with store.connect(url) as conn:
        conn.execute("UPDATE generation_jobs SET heartbeat_at = now() - interval '5 minutes' WHERE id=%s", (job_id,))
    assert status(client, job_id).get_json()['status'] == 'running'            # status is read-only; recovery happens on submit/claim
    assert post(client).status_code == 202
    interrupted = status(client, job_id).get_json()
    assert (interrupted['status'], interrupted['error']) == ('failed', 'interrupted')


def test_jobs_queued_before_a_restart_are_executed_by_the_new_process(url, world):
    job_id = post(make_app(url).test_client()).get_json()['job_id']            # the "old process" queues and dies
    restarted = make_app(url)
    assert run_worker(restarted, world) is True
    assert status(restarted.test_client(), job_id).get_json()['status'] == 'succeeded'


# --- the existing endpoints still work --------------------------------------------------------------------------------------------------------

def test_existing_listing_save_and_delete_endpoints_still_work(client):
    movie = '00000000-0000-0000-0000-000000000abc'
    saved = client.post('/recommendations', json={'user_id': USER, 'movie_id': movie, 'reason': 'why', 'score': 0.5, 'source': 'auto'}, headers=HEADERS)
    assert saved.status_code == 200
    assert [r[0] for r in listing(client, source='auto')] == [movie]
    assert client.delete(f"/recommendations/{saved.get_json()['recommendation']['id']}", headers=HEADERS).get_json() == {'removed': True}
    assert listing(client, source='auto') == []
