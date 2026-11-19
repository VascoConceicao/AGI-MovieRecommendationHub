"""HTTP layer of asynchronous generation with the job store mocked: validation, auth, status mapping."""
import threading
import time
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID

import psycopg
import pytest
from main import create_app
from services import generation, jobs, pipeline

USER = str(UUID(int=1))
JOB = str(UUID(int=2))
HEADERS = {'Authorization': 'Bearer test'}
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
CRITERIA = pipeline.normalize_criteria(None, None)


def job_row(status='queued', **changes):
    row = {'id': UUID(JOB), 'user_id': UUID(USER), 'source': 'user_requested', 'criteria': CRITERIA, 'status': status,
           'created_at': NOW, 'started_at': None, 'heartbeat_at': None, 'finished_at': None, 'claimed_by': 'instance-secret',
           'recommendation_count': None, 'outcome': None, 'attempts': None, 'used_fallback': None, 'fallback_reason': None,
           'duration_seconds': None, 'error': None}
    return {**row, **changes}


@pytest.fixture
def app():
    application = create_app()
    application.config.update(TESTING=True, DATABASE_URL='postgresql://user:pw-SECRET@db.internal/rec', RECOMMENDATION_API_TOKEN='test')
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def submit(monkeypatch):
    mock = Mock(return_value=job_row())
    monkeypatch.setattr(jobs, 'submit', mock)
    return mock


@pytest.fixture(autouse=True)
def pipeline_must_not_run_in_the_http_handler(monkeypatch):
    monkeypatch.setattr(pipeline, 'generate_recommendations', Mock(side_effect=AssertionError('the HTTP handler must not run the pipeline')))


def post(client, body, headers=HEADERS, **kwargs):
    return client.post('/recommendations/generate', json=body, headers=headers, **kwargs)


# --- authentication ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('headers,status', [({}, 401), ({'Authorization': 'Basic test'}, 401), ({'Authorization': 'Bearer wrong'}, 401),
                                            ({**HEADERS, 'Sec-Fetch-Site': 'cross-site'}, 403)])
def test_both_endpoints_keep_the_existing_service_authentication(client, submit, headers, status):
    assert post(client, {'user_id': USER}, headers).status_code == status
    assert client.get(f'/recommendations/generations/{JOB}?user_id={USER}', headers=headers).status_code == status
    submit.assert_not_called()


def test_endpoints_are_disabled_without_a_configured_token(app, submit):
    app.config['RECOMMENDATION_API_TOKEN'] = ''
    client = app.test_client()
    assert post(client, {'user_id': USER}).status_code == 404
    assert client.get(f'/recommendations/generations/{JOB}?user_id={USER}', headers=HEADERS).status_code == 404


# --- POST /recommendations/generate --------------------------------------------------------------------------------------

def test_accepted_request_returns_202_with_a_job_id_and_never_runs_the_pipeline(client, submit, monkeypatch):
    started = Mock()
    monkeypatch.setattr(generation, 'ensure_started', started)
    begun = time.monotonic()
    response = post(client, {'user_id': USER})
    assert response.status_code == 202 and time.monotonic() - begun < 2
    assert response.get_json() == {'job_id': JOB, 'status': 'queued'}
    assert response.headers['Location'] == f'/recommendations/generations/{JOB}' and response.headers['Cache-Control'] == 'no-store'
    submit.assert_called_once()
    started.assert_called_once()
    assert pipeline.generate_recommendations.call_count == 0


def test_the_request_is_not_blocked_even_if_the_pipeline_would_block(client, submit, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(pipeline, 'generate_recommendations', lambda *a: gate.wait(30))      # would hang the handler if it were called
    response = post(client, {'user_id': USER})
    assert response.status_code == 202 and not gate.is_set()


def test_validated_normalized_inputs_are_what_gets_queued(client, submit, app):
    post(client, {'user_id': USER.upper(), 'filters': {'genres': ['Drama', 'Drama'], 'actors': [' Name ']}, 'count': 15})
    url, user, source, criteria, max_queued = submit.call_args.args
    assert (url, user, source, max_queued) == (app.config['DATABASE_URL'], USER, 'user_requested', app.config['GENERATION_MAX_QUEUED'])
    assert criteria['genres'] == ['Drama'] and criteria['actors'] == ['Name'] and criteria['count'] == 15 and criteria['duration'] == 'any'


def test_defaults_are_the_published_ones(client, submit):
    post(client, {'user_id': USER})
    assert submit.call_args.args[3] == CRITERIA and CRITERIA['count'] == 10 and submit.call_args.args[2] == 'user_requested'
    post(client, {'user_id': USER, 'source': 'user_requested', 'filters': {}, 'count': 5})
    assert submit.call_args.args[3]['count'] == 5
    post(client, {'user_id': USER, 'filters': {'count': 20}})
    assert submit.call_args.args[3]['count'] == 20


@pytest.mark.parametrize('body', [
    None, [], 'text', 5, {}, {'filters': {}}, {'user_id': None}, {'user_id': 5}, {'user_id': 'not-a-uuid'}, {'user_id': ''}, {'user_id': [USER]},
    {'user_id': USER, 'extra': 1}, {'user_id': USER, 'source': 'auto'}, {'user_id': USER, 'source': 'all'}, {'user_id': USER, 'source': None},
    {'user_id': USER, 'count': 7}, {'user_id': USER, 'count': 0}, {'user_id': USER, 'count': True}, {'user_id': USER, 'count': '10'},
    {'user_id': USER, 'count': 25}, {'user_id': USER, 'count': -5},
    {'user_id': USER, 'filters': 'drama'}, {'user_id': USER, 'filters': [1]}, {'user_id': USER, 'filters': {'extra': 1}},
    {'user_id': USER, 'filters': {'genres': 'Drama'}}, {'user_id': USER, 'filters': {'genres': ['x'] * 11}}, {'user_id': USER, 'filters': {'duration': 'weird'}},
    {'user_id': USER, 'filters': {'year_from': 2000, 'year_to': 1999}}, {'user_id': USER, 'filters': {'year_from': True}},
    {'user_id': USER, 'filters': {'count': 7}}, {'user_id': USER, 'filters': {'count': 5}, 'count': 10}])
def test_malformed_requests_are_rejected_before_any_job_is_created(client, submit, body):
    response = post(client, body)
    assert response.status_code == 400 and 'error' in response.get_json()
    submit.assert_not_called()


@pytest.mark.parametrize('raw', [b'{not json', b'', b'null', b'\xff\xfe'])
def test_malformed_json_is_rejected(client, submit, raw):
    response = client.post('/recommendations/generate', data=raw, headers={**HEADERS, 'Content-Type': 'application/json'})
    assert response.status_code == 400
    submit.assert_not_called()


def test_a_non_json_body_is_rejected(client, submit):
    assert client.post('/recommendations/generate', data='user_id=1', headers=HEADERS).status_code == 400
    submit.assert_not_called()


def test_error_messages_are_fixed_and_safe(client, submit):
    for body in ({'user_id': 'nope'}, {'user_id': USER, 'count': 7}, {'user_id': USER, 'source': 'auto'}):
        message = post(client, body).get_json()['error']
        assert 'nope' not in message and 'Traceback' not in message and len(message) < 120


def test_a_duplicate_active_generation_returns_409_with_the_active_job(client, submit):
    submit.side_effect = jobs.DuplicateJob({'id': UUID(JOB), 'status': 'running'})
    response = post(client, {'user_id': USER, 'count': 5})
    assert response.status_code == 409
    assert response.get_json() == {'error': 'A generation is already queued or running for this user.', 'job_id': JOB, 'status': 'running'}


def test_a_full_queue_returns_503_with_retry_after(client, submit):
    submit.side_effect = jobs.QueueFull()
    response = post(client, {'user_id': USER})
    assert response.status_code == 503 and response.headers['Retry-After'] == '30'
    assert 'queue is full' in response.get_json()['error']


def test_a_database_failure_is_a_safe_503(client, submit):
    submit.side_effect = psycopg.OperationalError('connection to postgresql://user:pw-SECRET@db.internal failed')
    response = post(client, {'user_id': USER})
    assert response.status_code == 503 and response.get_json() == {'error': 'Recommendation database unavailable. Please retry.'}
    assert 'SECRET' not in response.get_data(as_text=True) and 'internal' not in response.get_data(as_text=True)


def test_the_worker_is_woken_after_queueing(client, submit, monkeypatch, app):
    worker = Mock()
    monkeypatch.setattr(generation, 'get_worker', lambda a: worker)
    post(client, {'user_id': USER})
    worker.wake.assert_called_once()


# --- GET /recommendations/generations/<job_id> -----------------------------------------------------------------------------

@pytest.fixture
def lookup(monkeypatch):
    mock = Mock(return_value=job_row())
    monkeypatch.setattr(jobs, 'get', mock)
    return mock


def status(client, job_id=JOB, user=USER):
    query = '' if user is None else f'?user_id={user}'
    return client.get(f'/recommendations/generations/{job_id}{query}', headers=HEADERS)


def test_a_queued_job_status(client, lookup, app):
    response = status(client)
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    assert response.get_json() == {'job_id': JOB, 'status': 'queued', 'source': 'user_requested', 'requested_count': 10,
                                   'created_at': NOW.isoformat(), 'started_at': None, 'finished_at': None}
    lookup.assert_called_once_with(app.config['DATABASE_URL'], JOB, USER)


def test_a_running_job_status(client, lookup):
    lookup.return_value = job_row('running', started_at=NOW)
    body = status(client).get_json()
    assert body['status'] == 'running' and body['started_at'] == NOW.isoformat() and 'outcome' not in body and 'error' not in body


def test_a_succeeded_job_exposes_only_safe_result_metadata(client, lookup):
    lookup.return_value = job_row('succeeded', started_at=NOW, finished_at=NOW, recommendation_count=10, outcome='llm', attempts=1,
                                  used_fallback=False, fallback_reason=None, duration_seconds=72.6)
    body = status(client).get_json()
    assert body['status'] == 'succeeded' and body['recommendation_count'] == 10 and body['outcome'] == 'llm' and body['attempts'] == 1
    assert body['used_fallback'] is False and body['fallback_reason'] is None and body['duration_seconds'] == 72.6
    assert not {'criteria', 'claimed_by', 'user_id', 'heartbeat_at', 'error'} & set(body)


@pytest.mark.parametrize('outcome,fallback,reason,count', [('fallback_inference_error', True, 'inference_error', 10),
                                                           ('no_candidates', False, None, 0), ('llm_after_retry', False, None, 10)])
def test_fallback_and_no_candidates_are_reported_as_succeeded(client, lookup, outcome, fallback, reason, count):
    lookup.return_value = job_row('succeeded', recommendation_count=count, outcome=outcome, attempts=1, used_fallback=fallback,
                                  fallback_reason=reason, duration_seconds=1.0)
    body = status(client).get_json()
    assert body['status'] == 'succeeded' and body['outcome'] == outcome and body['recommendation_count'] == count and 'error' not in body


def test_a_failed_job_exposes_only_a_safe_category(client, lookup):
    lookup.return_value = job_row('failed', finished_at=NOW, error='movie_catalog_unavailable')
    body = status(client).get_json()
    assert body['status'] == 'failed' and body['error'] == 'movie_catalog_unavailable' and 'outcome' not in body
    assert 'SECRET' not in repr(body) and 'instance' not in repr(body)


def test_unknown_jobs_and_other_users_jobs_are_404(client, lookup):
    lookup.return_value = None
    response = status(client)
    assert response.status_code == 404 and response.get_json() == {'error': 'Generation job not found.'}


@pytest.mark.parametrize('job_id,user', [('not-a-uuid', USER), (JOB, 'nope'), (JOB, None), (JOB, ''), ('', USER)])
def test_invalid_ids_are_rejected_without_a_lookup(client, lookup, job_id, user):
    assert status(client, job_id, user).status_code in (400, 404)
    lookup.assert_not_called()


def test_status_database_failure_is_a_safe_503(client, lookup):
    lookup.side_effect = psycopg.OperationalError('postgresql://user:pw-SECRET@db.internal down')
    response = status(client)
    assert response.status_code == 503 and 'SECRET' not in response.get_data(as_text=True)


# --- the existing endpoints keep working -----------------------------------------------------------------------------------------

def test_existing_recommendation_routes_are_unchanged_by_the_new_routes(client):
    rules = {(rule.rule, tuple(sorted(rule.methods - {'HEAD', 'OPTIONS'}))) for rule in client.application.url_map.iter_rules()}
    assert ('/recommendations', ('GET',)) in rules and ('/recommendations', ('POST',)) in rules
    assert ('/recommendations/<recommendation_id>', ('DELETE',)) in rules and ('/recommendation-filters', ('GET',)) in rules
    assert ('/recommendations/generate', ('POST',)) in rules and ('/recommendations/generations/<job_id>', ('GET',)) in rules
