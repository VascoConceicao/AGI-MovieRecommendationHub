"""Executes queued generation jobs: a bounded in-process worker over the shared job table.

The worker only coordinates: it claims a job (jobs.py enforces the global running cap), calls the existing
pipeline.generate_recommendations with explicit inputs, and records the outcome. It never touches Flask's
request context. Guarantees and limits:
  * One worker thread per process; the cap on concurrently running jobs is global and enforced in PostgreSQL.
  * While a job runs, a heartbeat keeps it alive. If the process dies, the heartbeat stops and the job is marked
    failed ('interrupted') within about STALE_SECONDS by any process. It is not retried.
  * Shutdown does not wait for a job in flight; the same interruption rule applies.
  * 'interrupted' means the outcome is unknown, not that nothing changed: replace_set() commits before the job is
    marked succeeded, so a crash in that window (or a heartbeat stall that gets a live job declared interrupted, whose
    late result is then ignored) can leave the new set stored while the job reads failed. A failure with another
    category normally happened before persistence (replace_set rolls back on its own errors) and left the previous set
    unchanged; only a bug after the commit would break that.
"""
import logging
import threading
import uuid

import psycopg

from services import jobs, pipeline
from services.context import ContextError
from services.movie_client import MovieCatalogError

logger = logging.getLogger(__name__)

POLL_SECONDS = 2.0
HEARTBEAT_SECONDS = 15.0


def classify_failure(error):
    """A fixed, safe category for a failed job; never the exception text."""
    if isinstance(error, ContextError):
        return 'user_not_found' if error.status == 404 else 'user_service_unavailable'
    if isinstance(error, MovieCatalogError):
        return 'movie_catalog_unavailable'
    if isinstance(error, ValueError):
        return 'invalid_request'
    if isinstance(error, psycopg.Error):
        return 'database_error'
    return 'internal_error'


class Worker:
    def __init__(self, config, max_running=1, poll_seconds=POLL_SECONDS, heartbeat_seconds=HEARTBEAT_SECONDS,
                 stale_seconds=jobs.STALE_SECONDS):
        self.config = dict(config)                       # an explicit snapshot: no Flask objects reach the worker
        self.url = self.config['DATABASE_URL']
        self.instance = uuid.uuid4().hex
        self.max_running, self.poll_seconds = max_running, poll_seconds
        self.heartbeat_seconds, self.stale_seconds = heartbeat_seconds, stale_seconds
        self._wake, self._stop = threading.Event(), threading.Event()
        self._lock, self._active, self._threads = threading.Lock(), set(), []

    # -- lifecycle ---------------------------------------------------------------------------------------------
    def start(self):
        if self._threads:
            return
        with self._lock:
            if self._threads:
                return
            self._threads = [threading.Thread(target=self._loop, name='generation-worker', daemon=True),
                             threading.Thread(target=self._heartbeat_loop, name='generation-heartbeat', daemon=True)]
            for thread in self._threads:
                thread.start()

    def stop(self, timeout=5):
        self._stop.set()
        self._wake.set()
        for thread in self._threads:
            thread.join(timeout)

    def wake(self):
        self._wake.set()

    # -- execution ---------------------------------------------------------------------------------------------
    def run_once(self):
        """Claim and execute one job; False when nothing could be claimed."""
        job = jobs.claim_next(self.url, self.instance, self.max_running, self.stale_seconds)
        if job is None:
            return False
        self._execute(job)
        return True

    def _execute(self, job):
        job_id, user_id = str(job['id']), str(job['user_id'])
        logger.info('Generation job started (job=%s, source=%s)', job_id[:8], job['source'])
        with self._lock:
            self._active.add(job_id)
        try:
            try:
                result = pipeline.generate_recommendations(self.config, user_id, job['source'], job['criteria'])
            except Exception as error:      # the single boundary: a failing job is recorded, it never stops the worker
                category = classify_failure(error)
                logger.error('Generation job failed (job=%s, category=%s, error=%s)', job_id[:8], category, type(error).__name__)
                recorded = jobs.finish_failure(self.url, job_id, category)
            else:
                recorded = jobs.finish_success(self.url, job_id, result)
                logger.info('Generation job succeeded (job=%s, outcome=%s, persisted=%d, seconds=%.1f)',
                            job_id[:8], result.outcome, result.persisted_count, result.duration_seconds)
            if not recorded:
                logger.warning('Generation job result not recorded: the job is no longer running (job=%s)', job_id[:8])
        finally:
            with self._lock:
                self._active.discard(job_id)

    def _loop(self):
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except Exception as error:      # e.g. the database is briefly unavailable: keep serving later jobs
                logger.error('Generation worker iteration failed (error=%s)', type(error).__name__)
                worked = False
            if not worked:
                self._wake.wait(self.poll_seconds)
                self._wake.clear()

    def _heartbeat_loop(self):
        while not self._stop.wait(self.heartbeat_seconds):
            with self._lock:
                active = list(self._active)
            if active:
                try:
                    jobs.heartbeat(self.url, active)
                except Exception as error:
                    logger.warning('Generation heartbeat failed (error=%s)', type(error).__name__)


_REGISTRY_LOCK = threading.Lock()


def get_worker(app):
    """The app's Worker (created on first use from the current config, not started)."""
    worker = app.extensions.get('generation_worker')
    if worker is None:
        with _REGISTRY_LOCK:
            worker = app.extensions.get('generation_worker')
            if worker is None:
                worker = app.extensions['generation_worker'] = Worker(
                    app.config, max_running=app.config['GENERATION_MAX_RUNNING'])
    return worker


def ensure_started(app):
    """Start the worker in a serving process (first request); never in CLI commands or when disabled."""
    if app.config['GENERATION_WORKER']:
        get_worker(app).start()
