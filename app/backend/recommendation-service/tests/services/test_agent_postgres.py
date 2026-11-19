"""One agent scan against a real PostgreSQL: scheduling decisions, capacity, concurrency, isolation.

The User Service is faked; the job queue, freshness queries and locks are real. The last tests also run the real
worker and pipeline (with the three external services faked) to show the queued automatic jobs complete.
"""
import logging
import threading
from datetime import datetime, timezone
from uuid import UUID

import pytest
from services import agent, generation, inference_client, jobs, pipeline, recommendations as store, selection
from tests.services.pipeline_support import CONFIG as PIPELINE_CONFIG, OTHER_USER, USER, World, context

FAKE_USER_SERVICE_TOKEN = 'tok-SECRET'


def uid(n):
    return str(UUID(int=n))


@pytest.fixture(autouse=True)
def empty_tables(url):
    with store.connect(url) as conn:
        conn.execute('DELETE FROM generation_jobs')
        conn.execute('DELETE FROM recommendations')


@pytest.fixture
def config(url):
    return {'DATABASE_URL': url, 'USER_SERVICE_URL': 'http://user.test', 'AGENT_CONTEXT_TOKEN': FAKE_USER_SERVICE_TOKEN,
            'AGENT_REFRESH_HOURS': 24, 'AGENT_RETRY_COOLDOWN_MINUTES': 60, 'AGENT_MAX_QUEUED': 5}


def users_are(monkeypatch, *ids, page=2):
    ordered = sorted(ids)

    def fake(cfg, path, params):
        start = 0 if 'after' not in params else ordered.index(params['after']) + 1
        chunk = ordered[start:start + page]
        return {'user_ids': chunk, 'next_cursor': chunk[-1] if start + len(chunk) < len(ordered) else None}, 200
    monkeypatch.setattr(agent.user_context, 'fetch', fake)


def add_job(url, user, status, hours_ago=0.0, source='auto', outcome=None):
    finished = status in ('succeeded', 'failed')
    with store.connect(url) as conn:
        conn.execute("INSERT INTO generation_jobs(user_id, source, status, created_at, finished_at, outcome, recommendation_count, started_at, heartbeat_at) "
                     "VALUES (%s, %s, %s, now() - make_interval(secs => %s), "
                     "CASE WHEN %s THEN now() - make_interval(secs => %s) END, %s, CASE WHEN %s THEN 0 END, now(), now())",
                     (user, source, status, hours_ago * 3600, finished, hours_ago * 3600, outcome, outcome == 'no_candidates'))


def add_recommendation(url, user, source, hours_ago):
    with store.connect(url) as conn:
        conn.execute("INSERT INTO recommendations(user_id, movie_id, reason, score, source, updated_at) "
                     "VALUES (%s, %s, 'r', 0.5, %s, now() - make_interval(secs => %s))", (user, uid(900), source, hours_ago * 3600))


def queued(url, source=None):
    with store.connect(url) as conn:
        return conn.execute("SELECT user_id::text AS user_id, source, criteria, status FROM generation_jobs "
                            "WHERE status IN ('queued','running') AND (%s::text IS NULL OR source=%s) ORDER BY created_at, id", (source, source)).fetchall()


def all_jobs(url):
    with store.connect(url) as conn:
        return conn.execute('SELECT * FROM generation_jobs').fetchall()


# --- scheduling --------------------------------------------------------------------------------------------------------

def test_a_scan_queues_automatic_jobs_for_users_without_any_recommendations(url, config, monkeypatch):
    users_are(monkeypatch, uid(1), uid(2), uid(3), uid(4), uid(5))                 # five users over three pages
    summary = agent.scan(config)
    assert (summary.users, summary.scheduled, summary.errors, summary.skipped_scan) == (5, 5, 0, False)
    rows = queued(url)
    assert sorted(r['user_id'] for r in rows) == [uid(n) for n in range(1, 6)]
    assert {(r['source'], r['status'], r['criteria']['count']) for r in rows} == {('auto', 'queued', 10)}
    assert summary.describe() == 'users=5 scheduled=5 fresh=0 cooldown=0 active=0 deferred=0 errors=0'


def test_a_new_user_with_only_user_requested_history_still_gets_an_automatic_set(url, config, monkeypatch):
    add_job(url, uid(1), 'succeeded', hours_ago=0.1, source='user_requested')
    add_recommendation(url, uid(1), 'user_requested', hours_ago=0.1)
    users_are(monkeypatch, uid(1))
    assert agent.scan(config).scheduled == 1 and [r['source'] for r in queued(url)] == ['auto']


def test_users_with_a_recent_automatic_set_are_not_scheduled(url, config, monkeypatch):
    add_job(url, uid(1), 'succeeded', hours_ago=1)                                  # fresh by job history
    add_recommendation(url, uid(2), 'auto', hours_ago=3)                            # fresh by stored rows (no job record)
    users_are(monkeypatch, uid(1), uid(2), uid(3))
    summary = agent.scan(config)
    assert (summary.skipped_fresh, summary.scheduled) == (2, 1) and [r['user_id'] for r in queued(url)] == [uid(3)]


def test_users_whose_automatic_set_is_stale_are_refreshed(url, config, monkeypatch):
    add_job(url, uid(1), 'succeeded', hours_ago=30)
    add_recommendation(url, uid(2), 'auto', hours_ago=40)
    users_are(monkeypatch, uid(1), uid(2))
    summary = agent.scan(config)
    assert (summary.skipped_fresh, summary.scheduled) == (0, 2)


def test_user_requested_activity_never_makes_the_automatic_set_fresh(url, config, monkeypatch):
    add_job(url, uid(1), 'succeeded', hours_ago=0.5, source='user_requested')
    add_recommendation(url, uid(1), 'user_requested', hours_ago=0.5)
    users_are(monkeypatch, uid(1))
    assert agent.scan(config).skipped_fresh == 0


def test_a_successful_no_candidates_generation_is_recent_and_not_rescheduled(url, config, monkeypatch):
    add_job(url, uid(1), 'succeeded', hours_ago=2, outcome='no_candidates')          # zero stored rows, but a successful generation
    users_are(monkeypatch, uid(1))
    for _ in range(3):
        summary = agent.scan(config)
        assert (summary.skipped_fresh, summary.scheduled) == (1, 0)
    assert queued(url) == []


def test_recent_failures_cool_down_and_old_failures_retry(url, config, monkeypatch):
    add_job(url, uid(1), 'failed', hours_ago=10 / 60)
    add_job(url, uid(2), 'failed', hours_ago=3)
    add_job(url, uid(3), 'failed', hours_ago=5 / 60)
    add_job(url, uid(3), 'succeeded', hours_ago=2)                                  # ...but uid(3) also has a recent success
    users_are(monkeypatch, uid(1), uid(2), uid(3))
    summary = agent.scan(config)
    assert (summary.skipped_cooldown, summary.skipped_fresh, summary.scheduled) == (1, 1, 1)
    assert [r['user_id'] for r in queued(url)] == [uid(2)]


def test_users_with_an_active_job_are_skipped_without_creating_duplicates(url, config, monkeypatch):
    add_job(url, uid(1), 'queued')
    add_job(url, uid(2), 'running')
    users_are(monkeypatch, uid(1), uid(2), uid(3))
    summary = agent.scan(config)
    assert (summary.skipped_active, summary.scheduled) == (2, 1)
    assert len(queued(url)) == 3 and len({r['user_id'] for r in queued(url)}) == 3


def test_repeated_scans_are_idempotent(url, config, monkeypatch):
    users_are(monkeypatch, uid(1), uid(2), uid(3))
    first, second, third = agent.scan(config), agent.scan(config), agent.scan(config)
    assert (first.scheduled, second.scheduled, third.scheduled) == (3, 0, 0)
    assert (second.skipped_active, third.skipped_active) == (3, 3) and len(all_jobs(url)) == 3
    for job in queued(url):
        jobs.claim_next(url, 'w', 10)
    with store.connect(url) as conn:
        conn.execute("UPDATE generation_jobs SET status='succeeded', finished_at=now()")
    fourth = agent.scan(config)
    assert (fourth.scheduled, fourth.skipped_fresh) == (0, 3) and len(all_jobs(url)) == 3


def test_a_later_scan_refreshes_a_user_once_the_interval_has_passed(url, config, monkeypatch):
    users_are(monkeypatch, uid(1))
    agent.scan(config)
    with store.connect(url) as conn:
        conn.execute("UPDATE generation_jobs SET status='succeeded', started_at=now(), finished_at=now() - interval '25 hours'")
    assert agent.scan(config).scheduled == 1 and len(all_jobs(url)) == 2


# --- capacity and priority ---------------------------------------------------------------------------------------------

def test_the_agent_stops_at_its_queue_limit_and_defers_the_rest(url, config, monkeypatch):
    config['AGENT_MAX_QUEUED'] = 2
    users_are(monkeypatch, *[uid(n) for n in range(1, 6)])
    summary = agent.scan(config)
    assert (summary.scheduled, summary.deferred, summary.errors) == (2, 3, 0) and len(queued(url)) == 2
    again = agent.scan(config)                                                       # still full: nothing new, nothing blocked
    assert (again.scheduled, again.deferred, again.skipped_active) == (0, 3, 2)


def test_deferred_users_are_scheduled_by_later_scans_as_capacity_frees(url, config, monkeypatch):
    config['AGENT_MAX_QUEUED'] = 2
    users_are(monkeypatch, *[uid(n) for n in range(1, 6)])
    seen = set()
    for _ in range(4):
        agent.scan(config)
        while (claimed := jobs.claim_next(url, 'w', 10)):
            seen.add(str(claimed['user_id']))
            jobs.finish_success(url, claimed['id'], type('R', (), {'persisted_count': 1, 'outcome': 'llm', 'attempts': 1,
                                                                    'used_fallback': False, 'fallback_reason': None, 'duration_seconds': 1.0}))
    assert seen == {uid(n) for n in range(1, 6)}


def test_users_most_in_need_are_scheduled_first(url, config, monkeypatch):
    add_job(url, uid(1), 'succeeded', hours_ago=30)
    add_job(url, uid(3), 'succeeded', hours_ago=50)
    add_job(url, uid(5), 'succeeded', hours_ago=26)
    users_are(monkeypatch, *[uid(n) for n in range(1, 6)])                           # uid(2), uid(4) have never been generated
    config['AGENT_MAX_QUEUED'] = 4
    summary = agent.scan(config)
    assert [r['user_id'] for r in queued(url)] == [uid(2), uid(4), uid(3), uid(1)] and (summary.scheduled, summary.deferred) == (4, 1)


def test_the_agent_cannot_take_the_slots_reserved_for_user_requests(url, config, monkeypatch):
    config['AGENT_MAX_QUEUED'] = 2
    users_are(monkeypatch, *[uid(n) for n in range(1, 8)])
    agent.scan(config)
    assert len(queued(url, 'auto')) == 2
    for n in range(3):                                                               # GENERATION_MAX_QUEUED (5) minus the agent's 2
        assert jobs.submit(url, uid(100 + n), 'user_requested', {'count': 10}, 5)['status'] == 'queued'
    with pytest.raises(jobs.QueueFull):
        jobs.submit(url, uid(200), 'user_requested', {'count': 10}, 5)


def test_queued_user_requests_count_against_the_agent_limit(url, config, monkeypatch):
    config['AGENT_MAX_QUEUED'] = 2
    jobs.submit(url, uid(100), 'user_requested', {'count': 10}, 5)
    jobs.submit(url, uid(101), 'user_requested', {'count': 10}, 5)
    users_are(monkeypatch, uid(1), uid(2))
    summary = agent.scan(config)
    assert (summary.scheduled, summary.deferred) == (0, 2)


# --- concurrency ---------------------------------------------------------------------------------------------------------

def test_a_scan_that_finds_another_scan_running_does_nothing(url, config, monkeypatch):
    users_are(monkeypatch, uid(1), uid(2))
    with store.connect(url) as holder:
        holder.execute('SELECT pg_advisory_xact_lock(%s)', (agent.AGENT_LOCK,))
        summary = agent.scan(config)
    assert summary.skipped_scan and summary.scheduled == 0 and all_jobs(url) == []
    assert agent.scan(config).scheduled == 2                                          # the lock was released with the transaction


def test_concurrent_scans_never_create_duplicate_active_jobs(url, config, monkeypatch):
    config['AGENT_MAX_QUEUED'] = 10
    users_are(monkeypatch, *[uid(n) for n in range(1, 7)])
    barrier, summaries = threading.Barrier(6), []

    def scan():
        barrier.wait()
        summaries.append(agent.scan(config))
    threads = [threading.Thread(target=scan) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert len(summaries) == 6 and sum(s.scheduled for s in summaries) == 6
    rows = queued(url)
    assert len(rows) == 6 and len({r['user_id'] for r in rows}) == 6 and {r['source'] for r in rows} == {'auto'}


# --- failures and safety -------------------------------------------------------------------------------------------------

def test_a_user_service_failure_schedules_nothing(url, config, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger='services.agent')
    monkeypatch.setattr(agent.user_context, 'fetch', lambda *a: ({'error': 'User context unavailable. Please retry.'}, 503))
    summary = agent.scan(config)
    assert (summary.discovery_failed, summary.errors, summary.scheduled, summary.users) == (True, 1, 0, 0)
    assert all_jobs(url) == [] and 'aborted' in caplog.text and 'SECRET' not in caplog.text


def test_a_failure_on_a_later_page_does_not_schedule_a_partial_list(url, config, monkeypatch):
    pages = iter([({'user_ids': [uid(1), uid(2)], 'next_cursor': uid(2)}, 200), ({'error': 'x'}, 503)])
    monkeypatch.setattr(agent.user_context, 'fetch', lambda *a: next(pages))
    summary = agent.scan(config)
    assert summary.discovery_failed and all_jobs(url) == []


def test_malformed_user_ids_are_counted_and_valid_users_still_scheduled(url, config, monkeypatch):
    monkeypatch.setattr(agent.user_context, 'fetch', lambda *a: ({'user_ids': [uid(1), 'garbage', uid(2)], 'next_cursor': None}, 200))
    summary = agent.scan(config)
    assert (summary.users, summary.scheduled, summary.errors, summary.discovery_failed) == (2, 2, 1, False)


def test_the_agent_never_runs_the_pipeline_or_calls_inference_or_starts_a_worker(url, config, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('the agent must only queue jobs')
    monkeypatch.setattr(pipeline, 'generate_recommendations', forbidden)
    monkeypatch.setattr(selection, 'request_rerank', forbidden)
    monkeypatch.setattr(inference_client, 'urlopen', forbidden)
    monkeypatch.setattr(generation.Worker, 'start', forbidden)
    users_are(monkeypatch, uid(1), uid(2))
    assert agent.scan(config).scheduled == 2
    assert not any(t.name.startswith('generation') for t in threading.enumerate())


def test_scan_logs_one_summary_line_without_user_data_or_tokens(url, config, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    add_job(url, uid(1), 'succeeded', hours_ago=1)
    users_are(monkeypatch, uid(1), uid(2), uid(3))
    agent.scan(config)
    lines = [r.getMessage() for r in caplog.records if r.name == 'services.agent']
    assert lines == ['Agent scan finished (users=3 scheduled=2 fresh=1 cooldown=0 active=0 deferred=0 errors=0)']
    assert FAKE_USER_SERVICE_TOKEN not in caplog.text and uid(1) not in caplog.text and 'postgresql' not in caplog.text


# --- the queued jobs really complete through the existing worker and pipeline ----------------------------------------------------

@pytest.fixture
def world(monkeypatch, url):
    return World(monkeypatch, context(watched=[1, 2], watchlist=[3]), fake_persistence=False, config={**PIPELINE_CONFIG, 'DATABASE_URL': url})


def listed(url, user, source):
    return [(i['movie_id'], i['reason'], i['score']) for i in store.listing(url, user, 0, 100, source)['items']]


def test_automatic_jobs_complete_through_the_same_worker_and_only_replace_the_auto_set(url, config, world, monkeypatch):
    pipeline.generate_recommendations(world.config, USER, 'user_requested', None, 5)         # an existing user-requested set
    before = listed(url, USER, 'user_requested')
    users_are(monkeypatch, USER)
    assert agent.scan(config).scheduled == 1
    [job] = queued(url)
    assert job['source'] == 'auto' and job['user_id'] == USER
    assert generation.Worker(world.config).run_once() is True
    done = [j for j in all_jobs(url) if j['source'] == 'auto'][0]
    assert (done['status'], done['outcome'], done['recommendation_count']) == ('succeeded', 'llm', 10)
    assert len(listed(url, USER, 'auto')) == 10 and listed(url, USER, 'user_requested') == before and len(before) == 5
    again = agent.scan(config)
    assert (again.scheduled, again.skipped_fresh) == (0, 1)                                    # the fresh result is not scheduled again


def test_a_failed_automatic_generation_keeps_the_previous_auto_set_and_cools_down(url, config, world, monkeypatch):
    pipeline.generate_recommendations(world.config, USER, 'auto', None, 5)
    before = listed(url, USER, 'auto')
    with store.connect(url) as conn:                                                            # make that set stale, then fail the refresh
        conn.execute("UPDATE recommendations SET updated_at = now() - interval '30 hours' WHERE source='auto'")
    users_are(monkeypatch, USER)
    assert agent.scan(config).scheduled == 1
    world.catalog = []                                                                          # empty catalog: the job will fail
    generation.Worker(world.config).run_once()
    assert [j['status'] for j in all_jobs(url)] == ['failed'] and listed(url, USER, 'auto') == before
    summary = agent.scan(config)
    assert (summary.skipped_cooldown, summary.scheduled) == (1, 0)                              # no retry storm
