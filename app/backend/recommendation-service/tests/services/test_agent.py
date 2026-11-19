"""Agent logic without a database: freshness decisions, user discovery and pagination."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import UUID

import pytest
from services import agent

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
REFRESH, COOLDOWN = timedelta(hours=24), timedelta(minutes=60)
CONFIG = {'USER_SERVICE_URL': 'http://user.test', 'AGENT_CONTEXT_TOKEN': 'tok-SECRET'}


def uid(n):
    return str(UUID(int=n))


def row(success=None, stored=None, status=None, finished=None):
    ago = lambda delta: None if delta is None else NOW - delta
    return {'db_now': NOW, 'last_status': status, 'last_finished': ago(finished), 'last_success': ago(success), 'last_stored': ago(stored)}


# --- freshness policy -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('history,expected', [
    (row(), agent.DUE),                                                             # never generated (cold start included)
    (row(success=timedelta(hours=1), status='succeeded', finished=timedelta(hours=1)), agent.FRESH),
    (row(success=timedelta(hours=23, minutes=59)), agent.FRESH),
    (row(success=timedelta(hours=24)), agent.DUE),                                  # exactly at the interval: refresh
    (row(success=timedelta(hours=30), status='succeeded', finished=timedelta(hours=30)), agent.DUE),
    (row(stored=timedelta(hours=2)), agent.FRESH),                                  # auto rows written outside the job queue
    (row(stored=timedelta(hours=40)), agent.DUE),
    (row(success=timedelta(hours=30), stored=timedelta(hours=1)), agent.FRESH),     # the newest of the two counts
    (row(status='failed', finished=timedelta(minutes=10)), agent.COOLDOWN),
    (row(status='failed', finished=timedelta(minutes=59)), agent.COOLDOWN),
    (row(status='failed', finished=timedelta(minutes=60)), agent.DUE),
    (row(status='failed', finished=timedelta(hours=3)), agent.DUE),
    (row(success=timedelta(hours=30), status='failed', finished=timedelta(minutes=5)), agent.COOLDOWN),
    (row(success=timedelta(hours=2), status='failed', finished=timedelta(minutes=5)), agent.FRESH),   # a recent success wins
    (row(status='queued'), agent.DUE), (row(status='running'), agent.DUE),         # active jobs are caught by the queue itself
])
def test_decide(history, expected):
    assert agent.decide(history, REFRESH, COOLDOWN) == expected


def test_a_successful_no_candidates_generation_counts_as_a_recent_success():
    history = row(success=timedelta(hours=1), status='succeeded', finished=timedelta(hours=1))      # no recommendation rows exist
    assert history['last_stored'] is None and agent.decide(history, REFRESH, COOLDOWN) == agent.FRESH


def test_policy_is_configurable():
    config = {'AGENT_REFRESH_HOURS': '1', 'AGENT_RETRY_COOLDOWN_MINUTES': '5', 'AGENT_MAX_QUEUED': '3'}
    refresh, cooldown, max_queued = agent._settings(config)
    assert (refresh, cooldown, max_queued) == (timedelta(hours=1), timedelta(minutes=5), 3)
    assert agent.decide(row(success=timedelta(minutes=90)), refresh, cooldown) == agent.DUE
    assert agent._settings({}) == (timedelta(hours=24), timedelta(minutes=60), 2)


# --- user discovery ----------------------------------------------------------------------------------------------------

def serve(monkeypatch, ids, page=2, fail_after=None, status=200):
    ordered, calls = sorted(ids), []

    def fake(config, path, params):
        calls.append((path, dict(params)))
        if fail_after is not None and len(calls) > fail_after:
            return {'error': 'User context unavailable. Please retry.'}, 503
        start = 0 if 'after' not in params else ordered.index(params['after']) + 1
        chunk = ordered[start:start + min(page, params['limit'])]
        more = start + len(chunk) < len(ordered)
        return {'user_ids': chunk, 'next_cursor': chunk[-1] if more else None}, status
    monkeypatch.setattr(agent.user_context, 'fetch', fake)
    return calls


def test_discovery_follows_the_cursor_across_pages(monkeypatch):
    ids = [uid(n) for n in range(1, 8)]
    calls = serve(monkeypatch, ids, page=3)
    users, malformed = agent.discover_users(CONFIG)
    assert users == ids and malformed == 0
    assert [c[0] for c in calls] == [agent.USERS_PATH] * 3
    assert calls[0][1] == {'limit': 1000} and calls[1][1] == {'limit': 1000, 'after': ids[2]} and calls[2][1]['after'] == ids[5]


def test_single_page_and_empty_user_lists(monkeypatch):
    serve(monkeypatch, [uid(1)], page=100)
    assert agent.discover_users(CONFIG) == ([uid(1)], 0)
    serve(monkeypatch, [])
    assert agent.discover_users(CONFIG) == ([], 0)


def test_users_without_any_history_are_just_ids_and_are_kept(monkeypatch):
    serve(monkeypatch, [uid(5)])
    assert agent.discover_users(CONFIG)[0] == [uid(5)]        # the agent never inspects history, so cold start is not excluded


@pytest.mark.parametrize('fail_after', [0, 1, 2])
def test_a_failure_on_any_page_aborts_discovery(monkeypatch, fail_after):
    serve(monkeypatch, [uid(n) for n in range(1, 9)], page=2, fail_after=fail_after)
    with pytest.raises(agent.UserDiscoveryError) as error:
        agent.discover_users(CONFIG)
    assert 'SECRET' not in str(error.value)


@pytest.mark.parametrize('body,status', [({'error': 'x'}, 503), ({'user_ids': 'nope'}, 200), ({}, 200), ({'user_ids': None}, 200),
                                         ({'user_ids': [], 'next_cursor': 5}, 200)])
def test_malformed_user_service_responses_abort_discovery(monkeypatch, body, status):
    monkeypatch.setattr(agent.user_context, 'fetch', lambda *a: (body, status))
    with pytest.raises(agent.UserDiscoveryError):
        agent.discover_users(CONFIG)


def test_a_cursor_that_does_not_advance_cannot_loop_forever(monkeypatch):
    calls = []

    def stuck(config, path, params):
        calls.append(params)
        return {'user_ids': [uid(1)], 'next_cursor': uid(1)}, 200
    monkeypatch.setattr(agent.user_context, 'fetch', stuck)
    with pytest.raises(agent.UserDiscoveryError):
        agent.discover_users(CONFIG)
    assert len(calls) == 2


def test_malformed_and_duplicate_ids_are_skipped_and_counted(monkeypatch):
    pages = iter([({'user_ids': [uid(1), 'not-a-uuid', None, 5, uid(1).upper()], 'next_cursor': uid(1)}, 200),
                  ({'user_ids': [uid(1), uid(2)], 'next_cursor': None}, 200)])
    monkeypatch.setattr(agent.user_context, 'fetch', lambda *a: next(pages))
    users, malformed = agent.discover_users(CONFIG)
    assert users == [uid(1), uid(2)] and malformed == 3


def test_the_agent_uses_the_authenticated_user_service_client_not_a_database(monkeypatch):
    seen = Mock(return_value=({'user_ids': [], 'next_cursor': None}, 200))
    monkeypatch.setattr(agent.user_context, 'fetch', seen)
    agent.discover_users(CONFIG)
    assert seen.call_args.args[0] is CONFIG and seen.call_args.args[1] == '/internal/recommendation-users'


def test_the_agent_module_has_no_inference_or_worker_dependencies():
    assert not any(hasattr(agent, name) for name in ('request_rerank', 'select_recommendations', 'Worker', 'generate_recommendations'))
    assert agent.SOURCE == 'auto'


def test_summary_describes_every_counter_without_user_data():
    summary = agent.ScanSummary(users=5, scheduled=2, skipped_fresh=1, skipped_cooldown=1, skipped_active=1, deferred=0, errors=0)
    assert summary.describe() == 'users=5 scheduled=2 fresh=1 cooldown=1 active=1 deferred=0 errors=0'


# --- strict per-scan submission cap (no database: discovery, history and the queue are faked) ---------------------------

class FakeGuard:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args):
        return Mock(fetchone=Mock(return_value={'acquired': True}))


def scan_with(monkeypatch, users, submit, max_queued=4):
    monkeypatch.setattr(agent, 'connect', lambda url: FakeGuard())
    monkeypatch.setattr(agent, 'discover_users', lambda config: (list(users), 0))
    monkeypatch.setattr(agent, 'auto_history', lambda url, ids: {user: row() for user in ids})
    monkeypatch.setattr(agent.jobs, 'submit', submit)
    return agent.scan({'DATABASE_URL': 'postgresql://unused', 'AGENT_MAX_QUEUED': max_queued})


def test_a_scan_submits_at_most_max_queued_jobs_even_if_the_queue_never_fills(monkeypatch):
    submit = Mock()                                                                 # never raises QueueFull: the worker "drains" it
    summary = scan_with(monkeypatch, [uid(n) for n in range(1, 11)], submit)
    assert submit.call_count == 4 and summary.scheduled == 4 and summary.deferred == 6
    assert [call.args[1] for call in submit.call_args_list] == [uid(n) for n in range(1, 5)]       # same order as before


def test_duplicate_jobs_do_not_count_as_submissions(monkeypatch):
    def submit(url, user, source, criteria, max_queued):
        if user in (uid(1), uid(3)):
            raise agent.jobs.DuplicateJob({'id': None, 'status': 'queued'})
    summary = scan_with(monkeypatch, [uid(n) for n in range(1, 11)], Mock(side_effect=submit))
    assert summary.skipped_active == 2 and summary.scheduled == 4 and summary.deferred == 4        # users 2, 4, 5, 6 scheduled; 7-10 deferred
    assert summary.skipped_active + summary.scheduled + summary.deferred == 10


def test_a_full_queue_still_stops_the_scan_early(monkeypatch):
    calls = []

    def submit(url, user, source, criteria, max_queued):
        calls.append(user)
        if len(calls) > 2:
            raise agent.jobs.QueueFull()
    summary = scan_with(monkeypatch, [uid(n) for n in range(1, 11)], submit)
    assert summary.scheduled == 2 and summary.deferred == 8 and len(calls) == 3


def test_fewer_due_users_than_the_cap_defers_nothing(monkeypatch):
    summary = scan_with(monkeypatch, [uid(1), uid(2)], Mock())
    assert summary.scheduled == 2 and summary.deferred == 0


def test_exactly_max_queued_due_users_are_all_scheduled_and_none_deferred(monkeypatch):
    summary = scan_with(monkeypatch, [uid(n) for n in range(1, 5)], Mock())
    assert summary.scheduled == 4 and summary.deferred == 0
