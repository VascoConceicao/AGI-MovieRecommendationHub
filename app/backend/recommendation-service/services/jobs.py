"""Generation job state in the Recommendation DB: submit, claim, heartbeat, finish, recover.

All coordination is in PostgreSQL so it holds across threads, processes and restarts: one active job per
(user_id, source) (unique index plus a submit lock), a bounded queue, and a global cap on running jobs.
A running job is considered dead when its heartbeat stops; that is failure detection, not a retry.
"""
import psycopg
from psycopg.types.json import Jsonb

from services.recommendations import connect

SUBMIT_LOCK = 150008            # advisory lock keys of this module (150006 and 150007 belong to recommendations.py)
CLAIM_LOCK = 150009
STALE_SECONDS = 60              # a running job without a heartbeat for this long is declared interrupted
RETENTION_DAYS = 7              # finished jobs are purged after this many days
INTERRUPTED = 'interrupted'


class DuplicateJob(Exception):
    """A job is already queued or running for this user and source; .job is its id and status."""

    def __init__(self, job):
        super().__init__('A generation is already active for this user and source.')
        self.job = job


class QueueFull(Exception):
    """The bounded queue has no free slot."""


def _recover(conn, stale_seconds):
    stale = conn.execute("UPDATE generation_jobs SET status='failed', error=%s, finished_at=now() "
                         "WHERE status='running' AND heartbeat_at < now() - make_interval(secs => %s)",
                         (INTERRUPTED, stale_seconds)).rowcount
    conn.execute("DELETE FROM generation_jobs WHERE status IN ('succeeded','failed') "
                 "AND finished_at < now() - make_interval(days => %s)", (RETENTION_DAYS,))
    return stale


def recover_stale(url, stale_seconds=STALE_SECONDS):
    """Mark running jobs whose heartbeat stopped as failed (interrupted); returns how many."""
    with connect(url) as conn:
        return _recover(conn, stale_seconds)


def _active(conn, user_id, source):
    return conn.execute("SELECT id, status FROM generation_jobs WHERE user_id=%s AND source=%s "
                        "AND status IN ('queued','running')", (user_id, source)).fetchone()


def submit(url, user_id, source, criteria, max_queued, stale_seconds=STALE_SECONDS):
    """Queue a job, or raise DuplicateJob / QueueFull. Submissions are serialized by an advisory lock."""
    try:
        with connect(url) as conn:
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (SUBMIT_LOCK,))
            _recover(conn, stale_seconds)
            active = _active(conn, user_id, source)
            if active:
                raise DuplicateJob(active)
            if conn.execute("SELECT count(*) AS n FROM generation_jobs WHERE status='queued'").fetchone()['n'] >= max_queued:
                raise QueueFull()
            return conn.execute('INSERT INTO generation_jobs(user_id, source, criteria) VALUES (%s,%s,%s) RETURNING *',
                                (user_id, source, Jsonb(criteria))).fetchone()
    except psycopg.errors.UniqueViolation:             # another writer bypassed the lock: the index still holds
        with connect(url) as conn:
            raise DuplicateJob(_active(conn, user_id, source) or {'id': None, 'status': 'queued'}) from None


def claim_next(url, instance, max_running, stale_seconds=STALE_SECONDS):
    """Move the oldest queued job to running, user-requested jobs before automatic ones, unless max_running jobs
    already run. Claims are serialized. A running automatic job is not preempted."""
    with connect(url) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (CLAIM_LOCK,))
        _recover(conn, stale_seconds)
        if conn.execute("SELECT count(*) AS n FROM generation_jobs WHERE status='running'").fetchone()['n'] >= max_running:
            return None
        return conn.execute("UPDATE generation_jobs SET status='running', started_at=now(), heartbeat_at=now(), claimed_by=%s "
                            "WHERE id = (SELECT id FROM generation_jobs WHERE status='queued' ORDER BY (source = 'auto'), created_at, id LIMIT 1) "
                            "RETURNING *", (instance,)).fetchone()


def heartbeat(url, job_ids):
    with connect(url) as conn:
        conn.execute("UPDATE generation_jobs SET heartbeat_at=now() WHERE id = ANY(%s::uuid[]) AND status='running'", (list(job_ids),))


def finish_success(url, job_id, result):
    """Record a pipeline result; False when the job is no longer running (e.g. it was declared interrupted)."""
    with connect(url) as conn:
        return bool(conn.execute(
            "UPDATE generation_jobs SET status='succeeded', finished_at=now(), recommendation_count=%s, outcome=%s, attempts=%s, "
            "used_fallback=%s, fallback_reason=%s, duration_seconds=%s WHERE id=%s AND status='running'",
            (result.persisted_count, result.outcome, result.attempts, result.used_fallback, result.fallback_reason,
             result.duration_seconds, job_id)).rowcount)


def finish_failure(url, job_id, category):
    with connect(url) as conn:
        return bool(conn.execute("UPDATE generation_jobs SET status='failed', error=%s, finished_at=now() "
                                 "WHERE id=%s AND status='running'", (category, job_id)).rowcount)


def get(url, job_id, user_id):
    """The job, only if it belongs to user_id (a job of another user is indistinguishable from a missing one)."""
    with connect(url) as conn:
        return conn.execute('SELECT * FROM generation_jobs WHERE id=%s AND user_id=%s', (job_id, user_id)).fetchone()
