"""Asynchronous generation API: queue a job, poll its status. The existing /recommendations listing returns results."""
import logging
from uuid import UUID

import psycopg
from flask import Blueprint, current_app, jsonify, request

from helpers.http import protect, no_cache, unavailable
from services import generation, jobs, pipeline

logger = logging.getLogger(__name__)

generation_api = Blueprint('generation', __name__)
generation_api.before_request(protect)
generation_api.after_request(no_cache)
generation_api.errorhandler(psycopg.Error)(unavailable)

PUBLIC_SOURCES = ('user_requested',)     # 'auto' is reserved for the background agent, which does not use this route
REQUEST_FIELDS = {'user_id', 'source', 'filters', 'count'}
RETRY_AFTER_SECONDS = '30'


def _serialize(job):
    result = {'job_id': str(job['id']), 'status': job['status'], 'source': job['source'],
              'requested_count': job['criteria'].get('count'),
              'created_at': job['created_at'].isoformat(),
              'started_at': job['started_at'].isoformat() if job['started_at'] else None,
              'finished_at': job['finished_at'].isoformat() if job['finished_at'] else None}
    if job['status'] == 'succeeded':
        result.update(recommendation_count=job['recommendation_count'], outcome=job['outcome'], attempts=job['attempts'],
                      used_fallback=job['used_fallback'], fallback_reason=job['fallback_reason'],
                      duration_seconds=job['duration_seconds'])
    elif job['status'] == 'failed':
        result['error'] = job['error']
    return result


@generation_api.post('/recommendations/generate')
def generate():
    data = request.get_json(silent=True)
    try:
        if not isinstance(data, dict) or set(data) - REQUEST_FIELDS:
            raise ValueError('Provide user_id, and optionally filters, count and source.')
        try:
            user_id = str(UUID(data['user_id']))
        except (KeyError, TypeError, AttributeError, ValueError):
            raise ValueError('Provide a valid user_id UUID.') from None
        if data.get('source', 'user_requested') not in PUBLIC_SOURCES:
            raise ValueError('source must be user_requested.')
        criteria = pipeline.normalize_criteria(data.get('filters'), data.get('count'))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    try:
        job = jobs.submit(current_app.config['DATABASE_URL'], user_id, 'user_requested', criteria,
                          current_app.config['GENERATION_MAX_QUEUED'])
    except jobs.DuplicateJob as duplicate:
        return jsonify(error='A generation is already queued or running for this user.',
                       job_id=str(duplicate.job['id']), status=duplicate.job['status']), 409
    except jobs.QueueFull:
        response = jsonify(error='Generation queue is full. Please retry later.')
        response.headers['Retry-After'] = RETRY_AFTER_SECONDS
        return response, 503
    logger.info('Generation job queued (job=%s, source=user_requested)', str(job['id'])[:8])
    generation.get_worker(current_app._get_current_object()).wake()      # already started by the app's before_request hook
    response = jsonify(job_id=str(job['id']), status='queued')
    response.headers['Location'] = '/recommendations/generations/' + str(job['id'])
    return response, 202


@generation_api.get('/recommendations/generations/<job_id>')
def generation_status(job_id):
    try:
        job_id, user_id = str(UUID(job_id)), str(UUID(request.args.get('user_id', '')))
    except ValueError:
        return jsonify(error='Provide a job UUID and a user_id UUID.'), 400
    job = jobs.get(current_app.config['DATABASE_URL'], job_id, user_id)
    if job is None:
        return jsonify(error='Generation job not found.'), 404
    return jsonify(_serialize(job))
