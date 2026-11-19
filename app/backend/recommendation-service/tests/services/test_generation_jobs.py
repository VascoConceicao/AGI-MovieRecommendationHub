"""Generation job state against a real PostgreSQL: uniqueness, capacity, the global running cap, races, recovery."""
import threading
from types import SimpleNamespace
from uuid import UUID

import psycopg
import pytest
from services import jobs, recommendations as store

USER_A, USER_B, USER_C = (str(UUID(int=n)) for n in (0xA, 0xB, 0xC))
CRITERIA = {'genres': [], 'languages': [], 'actors': [], 'directors': [], 'year_from': None, 'year_to': None, 'duration': 'any', 'count': 10}


@pytest.fixture(autouse=True)
def empty_tables(url):
    with store.connect(url) as conn:
        conn.execute('DELETE FROM generation_jobs')


def submit(url, user=USER_A, source='user_requested', max_queued=5, criteria=CRITERIA):
    return jobs.submit(url, user, source, criteria, max_queued)


def row(url, job_id):
    with store.connect(url) as conn:
        return conn.execute('SELECT * FROM generation_jobs WHERE id=%s', (job_id,)).fetchone()


def age(url, job_id, column='heartbeat_at', seconds=300):
    with store.connect(url) as conn:
        conn.execute(f"UPDATE generation_jobs SET {column} = now() - make_interval(secs => %s) WHERE id=%s", (seconds, job_id))


def result(count=10, outcome='llm', attempts=1, fallback=False, reason=None, seconds=1.5):
    return SimpleNamespace(persisted_count=count, outcome=outcome, attempts=attempts, used_fallback=fallback,
                           fallback_reason=reason, duration_seconds=seconds)


# --- submit / duplicates ------------------------------------------------------------------------------------------

def test_submit_creates_a_queued_job_with_the_normalized_criteria(url):
    job = submit(url)
    assert job['status'] == 'queued' and str(job['user_id']) == USER_A and job['source'] == 'user_requested'
    assert job['criteria'] == CRITERIA and job['started_at'] is None and job['finished_at'] is None and job['claimed_by'] is None


def test_a_second_active_job_for_the_same_user_and_source_is_rejected_with_the_active_job(url):
    first = submit(url)
    with pytest.raises(jobs.DuplicateJob) as duplicate:
        submit(url, criteria={**CRITERIA, 'count': 5})                   # different criteria: still a conflict, never silently reused
    assert duplicate.value.job['id'] == first['id'] and duplicate.value.job['status'] == 'queued'
    jobs.claim_next(url, 'w', 1)
    with pytest.raises(jobs.DuplicateJob) as running:
        submit(url)
    assert running.value.job['id'] == first['id'] and running.value.job['status'] == 'running'


def test_other_users_and_other_sources_are_independent(url):
    submit(url, USER_A, 'user_requested')
    submit(url, USER_B, 'user_requested')
    submit(url, USER_A, 'auto')
    with store.connect(url) as conn:
        assert conn.execute("SELECT count(*) AS n FROM generation_jobs WHERE status='queued'").fetchone()['n'] == 3


def test_a_new_job_is_accepted_after_the_previous_one_finished(url):
    first = submit(url)
    jobs.claim_next(url, 'w', 1)
    assert jobs.finish_success(url, first['id'], result())
    second = submit(url)
    assert second['id'] != first['id']
    jobs.claim_next(url, 'w', 1)
    assert jobs.finish_failure(url, second['id'], 'internal_error')
    assert submit(url)['status'] == 'queued'


def test_the_unique_index_guards_even_writers_that_bypass_the_submit_lock(url):
    submit(url)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with store.connect(url) as conn:
            conn.execute("INSERT INTO generation_jobs(user_id, source) VALUES (%s, 'user_requested')", (USER_A,))


def test_simultaneous_submissions_for_the_same_user_create_exactly_one_job(url):
    barrier, outcomes = threading.Barrier(8), []

    def attempt():
        barrier.wait()
        try:
            outcomes.append(('ok', submit(url)['id']))
        except jobs.DuplicateJob as duplicate:
            outcomes.append(('duplicate', duplicate.job['id']))
    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    accepted = [o for o in outcomes if o[0] == 'ok']
    assert len(outcomes) == 8 and len(accepted) == 1 and {o[1] for o in outcomes} == {accepted[0][1]}
    with store.connect(url) as conn:
        assert conn.execute("SELECT count(*) AS n FROM generation_jobs WHERE status IN ('queued','running')").fetchone()['n'] == 1


# --- capacity ---------------------------------------------------------------------------------------------------------

def test_the_queue_is_bounded_and_running_jobs_do_not_count_against_it(url):
    submit(url, USER_A, max_queued=2)
    submit(url, USER_B, max_queued=2)
    with pytest.raises(jobs.QueueFull):
        submit(url, USER_C, max_queued=2)
    jobs.claim_next(url, 'w', 1)                                           # one job moves to running: a queue slot frees up
    assert submit(url, USER_C, max_queued=2)['status'] == 'queued'
    with pytest.raises(jobs.QueueFull):
        submit(url, str(UUID(int=0xD)), max_queued=2)


def test_concurrent_submissions_never_exceed_the_queue_limit(url):
    barrier, outcomes = threading.Barrier(10), []

    def attempt(n):
        barrier.wait()
        try:
            jobs.submit(url, str(UUID(int=100 + n)), 'user_requested', CRITERIA, 3)
            outcomes.append('ok')
        except jobs.QueueFull:
            outcomes.append('full')
    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert outcomes.count('ok') == 3 and outcomes.count('full') == 7


# --- claiming / global running cap --------------------------------------------------------------------------------------

def test_claim_takes_the_oldest_queued_job_and_marks_it_running(url):
    first, second = submit(url, USER_A), submit(url, USER_B)
    claimed = jobs.claim_next(url, 'instance-1', 1)
    assert claimed['id'] == first['id'] and claimed['status'] == 'running' and claimed['claimed_by'] == 'instance-1'
    assert claimed['started_at'] is not None and claimed['heartbeat_at'] is not None
    assert row(url, second['id'])['status'] == 'queued'


def test_claim_returns_none_when_nothing_is_queued(url):
    assert jobs.claim_next(url, 'w', 1) is None


def test_the_global_running_cap_is_respected_across_workers(url):
    a, b = submit(url, USER_A), submit(url, USER_B)
    assert jobs.claim_next(url, 'worker-1', 1)['id'] == a['id']
    assert jobs.claim_next(url, 'worker-2', 1) is None                        # a second "process" may not start another job
    assert jobs.finish_success(url, a['id'], result())
    assert jobs.claim_next(url, 'worker-2', 1)['id'] == b['id']


def test_a_higher_configured_cap_allows_more_running_jobs(url):
    submit(url, USER_A), submit(url, USER_B), submit(url, USER_C)
    assert jobs.claim_next(url, 'w1', 2) and jobs.claim_next(url, 'w2', 2) and jobs.claim_next(url, 'w3', 2) is None


def test_concurrent_claims_never_exceed_the_cap(url):
    for n in range(6):
        submit(url, str(UUID(int=200 + n)), max_queued=10)
    barrier, claimed = threading.Barrier(6), []

    def attempt(n):
        barrier.wait()
        job = jobs.claim_next(url, 'w%d' % n, 2)
        if job:
            claimed.append(job['id'])
    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert len(claimed) == 2 and len(set(claimed)) == 2
    with store.connect(url) as conn:
        assert conn.execute("SELECT count(*) AS n FROM generation_jobs WHERE status='running'").fetchone()['n'] == 2


# --- finishing --------------------------------------------------------------------------------------------------------------

def test_finish_success_records_only_safe_metadata_and_only_from_running(url):
    job = submit(url)
    assert not jobs.finish_success(url, job['id'], result())                  # still queued
    jobs.claim_next(url, 'w', 1)
    assert jobs.finish_success(url, job['id'], result(count=7, outcome='fallback_inference_error', attempts=1, fallback=True,
                                                      reason='inference_error', seconds=2.5))
    done = row(url, job['id'])
    assert (done['status'], done['recommendation_count'], done['outcome'], done['attempts'], done['used_fallback'],
            done['fallback_reason'], done['duration_seconds'], done['error']) == ('succeeded', 7, 'fallback_inference_error', 1, True, 'inference_error', 2.5, None)
    assert done['finished_at'] is not None
    assert not jobs.finish_success(url, job['id'], result()) and not jobs.finish_failure(url, job['id'], 'x')      # terminal


def test_finish_failure_records_a_category_and_no_result(url):
    job = submit(url)
    jobs.claim_next(url, 'w', 1)
    assert jobs.finish_failure(url, job['id'], 'user_service_unavailable')
    failed = row(url, job['id'])
    assert (failed['status'], failed['error'], failed['outcome'], failed['recommendation_count']) == ('failed', 'user_service_unavailable', None, None)


def test_get_is_scoped_to_the_owner(url):
    job = submit(url)
    assert jobs.get(url, job['id'], USER_A)['id'] == job['id']
    assert jobs.get(url, job['id'], USER_B) is None
    assert jobs.get(url, str(UUID(int=999)), USER_A) is None


# --- heartbeat / recovery ----------------------------------------------------------------------------------------------------

def test_heartbeat_refreshes_running_jobs_only(url):
    running, queued = submit(url, USER_A), submit(url, USER_B)
    jobs.claim_next(url, 'w', 1)
    age(url, running['id'])
    before = row(url, running['id'])['heartbeat_at']
    jobs.heartbeat(url, [running['id'], queued['id']])
    assert row(url, running['id'])['heartbeat_at'] > before and row(url, queued['id'])['heartbeat_at'] is None


def test_a_job_without_heartbeat_is_declared_interrupted_and_never_left_running(url):
    job = submit(url)
    jobs.claim_next(url, 'dead-process', 1)
    assert jobs.recover_stale(url) == 0                                       # fresh heartbeat: still alive
    age(url, job['id'])
    assert jobs.recover_stale(url) == 1
    failed = row(url, job['id'])
    assert (failed['status'], failed['error']) == ('failed', jobs.INTERRUPTED) and failed['finished_at'] is not None
    assert jobs.recover_stale(url) == 0


def test_recovery_runs_when_claiming_so_a_dead_job_frees_the_global_cap(url):
    dead, waiting = submit(url, USER_A), submit(url, USER_B)
    jobs.claim_next(url, 'dead-process', 1)
    assert jobs.claim_next(url, 'alive', 1) is None                           # the cap is held by the (still fresh) dead job
    age(url, dead['id'])
    assert jobs.claim_next(url, 'alive', 1)['id'] == waiting['id']
    assert row(url, dead['id'])['error'] == jobs.INTERRUPTED


def test_recovery_runs_when_submitting_so_a_dead_job_does_not_block_new_requests(url):
    dead = submit(url)
    jobs.claim_next(url, 'dead-process', 1)
    with pytest.raises(jobs.DuplicateJob):
        submit(url)
    age(url, dead['id'])
    assert submit(url)['status'] == 'queued' and row(url, dead['id'])['status'] == 'failed'


def test_queued_jobs_are_never_declared_interrupted(url):
    job = submit(url)
    age(url, job['id'], 'created_at')
    assert jobs.recover_stale(url) == 0 and row(url, job['id'])['status'] == 'queued'


def test_a_late_result_for_an_interrupted_job_is_ignored(url):
    job = submit(url)
    jobs.claim_next(url, 'w', 1)
    age(url, job['id'])
    jobs.recover_stale(url)
    assert not jobs.finish_success(url, job['id'], result()) and row(url, job['id'])['status'] == 'failed'


def test_finished_jobs_are_purged_after_the_retention_period_but_active_ones_are_kept(url):
    old, recent, active = submit(url, USER_A), submit(url, USER_B), submit(url, USER_C)
    jobs.claim_next(url, 'w', 3), jobs.claim_next(url, 'w', 3)
    jobs.finish_success(url, old['id'], result()), jobs.finish_success(url, recent['id'], result())
    age(url, old['id'], 'finished_at', seconds=(jobs.RETENTION_DAYS + 1) * 86400)
    age(url, active['id'], 'created_at', seconds=(jobs.RETENTION_DAYS + 1) * 86400)
    jobs.recover_stale(url)
    assert row(url, old['id']) is None and row(url, recent['id']) and row(url, active['id'])


def test_migration_is_idempotent_and_the_constraints_hold(url):
    store.initialize(url)
    store.initialize(url)
    for bad in ("INSERT INTO generation_jobs(user_id, source) VALUES (gen_random_uuid(), 'everything')",
                "INSERT INTO generation_jobs(user_id, source, status) VALUES (gen_random_uuid(), 'auto', 'paused')",
                "INSERT INTO generation_jobs(user_id, source, recommendation_count) VALUES (gen_random_uuid(), 'auto', -1)"):
        with pytest.raises(psycopg.errors.CheckViolation):
            with store.connect(url) as conn:
                conn.execute(bad)


# --- priority: user-requested generations are claimed before automatic ones -------------------------------------------

def test_user_requested_jobs_are_claimed_before_older_automatic_jobs(url):
    auto_old = submit(url, USER_A, 'auto')
    auto_newer = submit(url, USER_B, 'auto')
    requested = submit(url, USER_C, 'user_requested')
    assert jobs.claim_next(url, 'w', 3)['id'] == requested['id']
    assert jobs.claim_next(url, 'w', 3)['id'] == auto_old['id']          # automatic jobs keep their FIFO order among themselves
    assert jobs.claim_next(url, 'w', 3)['id'] == auto_newer['id']


def test_user_requested_jobs_keep_fifo_order_and_a_running_auto_job_is_not_preempted(url):
    running_auto = submit(url, USER_A, 'auto')
    assert jobs.claim_next(url, 'w', 1)['id'] == running_auto['id']
    first, second = submit(url, USER_B, 'user_requested'), submit(url, USER_C, 'user_requested')
    assert jobs.claim_next(url, 'w', 1) is None and row(url, running_auto['id'])['status'] == 'running'
    jobs.finish_success(url, running_auto['id'], result())
    assert jobs.claim_next(url, 'w', 1)['id'] == first['id']
    jobs.finish_success(url, first['id'], result())
    assert jobs.claim_next(url, 'w', 1)['id'] == second['id']
