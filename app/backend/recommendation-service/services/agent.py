"""Proactive background agent: one scan queues automatic generations (source='auto') for users that need them.

The agent never runs the pipeline or calls inference: it only submits jobs to the existing generation queue, and the
same worker that serves user requests executes them. It is meant to run periodically and externally (cron or a
Kubernetes CronJob) as `flask agent-scan`, so no scheduler thread lives in any web worker or replica. A scan is short
and holds an advisory lock, so overlapping scans cannot run at the same time.

Policy: a user is fresh when their latest successful auto generation (a no_candidates success counts) finished, or
their auto recommendations were last written, within AGENT_REFRESH_HOURS. A user whose latest auto job failed
within AGENT_RETRY_COOLDOWN_MINUTES is skipped. Everyone else is due, never-generated users first, then the stalest.
Freshness is time-based only: new watch activity does not trigger an earlier refresh. user_requested sets are never
considered or touched. Queue capacity: the agent stops when AGENT_MAX_QUEUED jobs are already queued, and one scan never
submits more than AGENT_MAX_QUEUED jobs in total, even if the worker drains the queue while it runs.
"""
import logging
from datetime import timedelta
from typing import NamedTuple
from uuid import UUID

from services import context as user_context
from services import jobs, pipeline
from services.recommendations import connect

logger = logging.getLogger(__name__)

SOURCE = 'auto'
USERS_PATH = '/internal/recommendation-users'
PAGE_LIMIT = 1000                   # the User Service maximum
AGENT_LOCK = 150010                 # advisory lock key: one scan at a time
DEFAULT_REFRESH_HOURS = 24.0
DEFAULT_COOLDOWN_MINUTES = 60.0
DEFAULT_MAX_QUEUED = 2              # leaves the rest of GENERATION_MAX_QUEUED to user-requested generations

FRESH, COOLDOWN, DUE = 'fresh', 'cooldown', 'due'


class UserDiscoveryError(Exception):
    """The User Service could not list users completely; nothing is scheduled."""


class ScanSummary(NamedTuple):
    skipped_scan: bool = False          # another scan held the lock
    discovery_failed: bool = False
    users: int = 0
    scheduled: int = 0
    skipped_fresh: int = 0
    skipped_cooldown: int = 0
    skipped_active: int = 0
    deferred: int = 0                   # due users left for the next scan because the queue was full
    errors: int = 0                     # discovery failure or malformed user ids

    def describe(self):
        return ('users=%d scheduled=%d fresh=%d cooldown=%d active=%d deferred=%d errors=%d' % (
            self.users, self.scheduled, self.skipped_fresh, self.skipped_cooldown, self.skipped_active, self.deferred, self.errors))


def discover_users(config):
    """All user ids from the User Service API, paginated; returns (ids, malformed_count). Raises UserDiscoveryError."""
    users, malformed, after, seen = [], 0, None, set()
    while True:
        body, status = user_context.fetch(config, USERS_PATH, {'limit': PAGE_LIMIT, **({'after': after} if after else {})})
        ids, cursor = body.get('user_ids') if status == 200 else None, body.get('next_cursor')
        if status != 200 or not isinstance(ids, list) or (cursor is not None and (not isinstance(cursor, str) or cursor == after)):
            raise UserDiscoveryError('User listing failed.')
        for raw in ids:
            try:
                user = str(UUID(raw))
            except (ValueError, TypeError, AttributeError):
                malformed += 1
                continue
            if user not in seen:
                seen.add(user)
                users.append(user)
        if cursor is None:
            return users, malformed
        after = cursor


def auto_history(url, user_ids):
    """Per user: the latest auto job, the latest auto success and the last auto write, plus the database clock."""
    if not user_ids:
        return {}
    with connect(url) as conn:
        rows = conn.execute(
            "SELECT ids.id::text AS user_id, now() AS db_now, j.status AS last_status, j.finished_at AS last_finished, "
            "(SELECT max(finished_at) FROM generation_jobs s WHERE s.user_id=ids.id AND s.source=%s AND s.status='succeeded') AS last_success, "
            "(SELECT max(updated_at) FROM recommendations r WHERE r.user_id=ids.id AND r.source=%s) AS last_stored "
            "FROM unnest(%s::uuid[]) AS ids(id) "
            "LEFT JOIN LATERAL (SELECT status, finished_at FROM generation_jobs WHERE user_id=ids.id AND source=%s "
            "ORDER BY created_at DESC LIMIT 1) j ON true", (SOURCE, SOURCE, user_ids, SOURCE)).fetchall()
    return {row['user_id']: row for row in rows}


def last_fresh(row):
    times = [t for t in (row['last_success'], row['last_stored']) if t is not None]
    return max(times) if times else None


def decide(row, refresh, cooldown):
    """fresh, cooldown or due for one user's history row."""
    fresh_at = last_fresh(row)
    if fresh_at is not None and row['db_now'] - fresh_at < refresh:
        return FRESH
    if row['last_status'] == 'failed' and row['last_finished'] is not None and row['db_now'] - row['last_finished'] < cooldown:
        return COOLDOWN
    return DUE


def _settings(config):
    return (timedelta(hours=float(config.get('AGENT_REFRESH_HOURS', DEFAULT_REFRESH_HOURS))),
            timedelta(minutes=float(config.get('AGENT_RETRY_COOLDOWN_MINUTES', DEFAULT_COOLDOWN_MINUTES))),
            int(config.get('AGENT_MAX_QUEUED', DEFAULT_MAX_QUEUED)))


def scan(config):
    """Run one scan: queue auto generations for due users (most in need first) until the queue limit is reached."""
    url = config['DATABASE_URL']
    refresh, cooldown, max_queued = _settings(config)
    with connect(url) as guard:
        if not guard.execute('SELECT pg_try_advisory_xact_lock(%s) AS acquired', (AGENT_LOCK,)).fetchone()['acquired']:
            logger.info('Agent scan skipped: another scan is running')
            return ScanSummary(skipped_scan=True)
        try:
            users, malformed = discover_users(config)
        except UserDiscoveryError:
            logger.error('Agent scan aborted: user discovery failed, nothing scheduled')
            return ScanSummary(discovery_failed=True, errors=1)
        history = auto_history(url, users)
        counts = {FRESH: 0, COOLDOWN: 0}
        due = []
        for user in users:
            verdict = decide(history[user], refresh, cooldown)
            if verdict == DUE:
                due.append(user)
            else:
                counts[verdict] += 1
        epoch = max((r['db_now'] for r in history.values()), default=None)
        due.sort(key=lambda u: (last_fresh(history[u]) is not None, last_fresh(history[u]) or epoch, u))
        criteria = pipeline.normalize_criteria(None, None)
        scheduled = active = 0
        for position, user in enumerate(due):
            if scheduled >= max_queued:         # strict per-scan cap: the worker may drain the queue while we submit
                deferred = len(due) - position
                break
            try:
                jobs.submit(url, user, SOURCE, criteria, max_queued)
            except jobs.DuplicateJob:
                active += 1
            except jobs.QueueFull:
                deferred = len(due) - position
                break
            else:
                scheduled += 1
        else:
            deferred = 0
    summary = ScanSummary(users=len(users), scheduled=scheduled, skipped_fresh=counts[FRESH], skipped_cooldown=counts[COOLDOWN],
                          skipped_active=active, deferred=deferred, errors=malformed)
    logger.info('Agent scan finished (%s)', summary.describe())
    return summary
