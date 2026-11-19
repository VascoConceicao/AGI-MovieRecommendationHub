"""Authenticated profile gateway; Recommendation Service owns results."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def call(config, path, payload=None):
    if not config['RECOMMENDATION_API_TOKEN']:
        return {'error': 'Recommendations unavailable. Please retry.'}, 503
    request = Request(config['RECOMMENDATION_SERVICE_URL'].rstrip('/') + path,
                      data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Authorization': 'Bearer ' + config['RECOMMENDATION_API_TOKEN'],
                               'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response), response.status
    except HTTPError as error:
        if error.code in (400, 404, 503):
            try:
                return {'error': json.load(error)['error']}, error.code
            except (ValueError, KeyError, TypeError):
                pass
    except (URLError, OSError, ValueError):
        pass
    return {'error': 'Recommendations unavailable. Please retry.'}, 503


def generation_call(config, path, payload=None):
    """Gateway call for the asynchronous generation API; returns (body, status, headers).

    Unlike call(), it keeps what the frontend needs to react correctly: the 202/200 body, a safe error message for
    400/404/409/503, the active job's id and status on 409, and Retry-After on 503. Anything else (including a
    rejected service token) becomes a generic retryable 503, so no internal detail reaches the browser.
    """
    generic = {'error': 'Recommendations unavailable. Please retry.'}
    if not config['RECOMMENDATION_API_TOKEN']:
        return generic, 503, {}
    request = Request(config['RECOMMENDATION_SERVICE_URL'].rstrip('/') + path,
                      data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Authorization': 'Bearer ' + config['RECOMMENDATION_API_TOKEN'],
                               'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response), response.status, {}
    except HTTPError as error:
        try:
            body = json.load(error)
        except (ValueError, TypeError):
            body = None
        if error.code in (400, 404, 409, 503) and isinstance(body, dict) and isinstance(body.get('error'), str):
            safe = {'error': body['error']}
            if error.code == 409:
                safe.update({key: body[key] for key in ('job_id', 'status') if isinstance(body.get(key), str)})
            retry_after = error.headers.get('Retry-After') if error.code == 503 else None
            return safe, error.code, {'Retry-After': retry_after} if retry_after and retry_after.isdigit() else {}
    except (URLError, OSError, ValueError):
        pass
    return generic, 503, {}


def search(config, user_id, source, offset, query):
    """Filter all saved recommendations by local movie titles before pagination."""
    from urllib.parse import urlencode
    from services import profiles
    items, start = [], 0
    while True:
        params = urlencode({'user_id': str(user_id), 'source': source, 'offset': start, 'limit': 100})
        body, status = call(config, '/recommendations?' + params)
        if status != 200:
            return body, status
        items.extend(body['items'])
        start += len(body['items'])
        if not body['items'] or start >= body['total']:
            break
    try:
        ids = list(dict.fromkeys(item['movie_id'] for item in items))
        matches = profiles.search_ids(config['MOVIE_SERVICE_URL'], ids, query)
    except profiles.SearchUnavailable:
        return {'error': 'Movie search unavailable. Please retry.'}, 503
    matched = [item for item in items if item['movie_id'] in matches]
    return {'items': matched[offset:offset + 25], 'total': len(matched), 'offset': offset, 'limit': 25}, 200
