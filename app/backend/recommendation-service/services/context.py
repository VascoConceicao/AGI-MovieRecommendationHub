"""Read context over User Service HTTP API, never its database."""
import json
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def fetch(config, path, params):
    if not config['AGENT_CONTEXT_TOKEN']:
        return {'error': 'User context unavailable. Please retry.'}, 503
    req = Request(config['USER_SERVICE_URL'].rstrip('/') + path + '?' + urlencode(params),
                  headers={'Authorization': 'Bearer ' + config['AGENT_CONTEXT_TOKEN']})
    try:
        with urlopen(req, timeout=5) as response:
            body = json.load(response)
            if not isinstance(body, dict):
                raise ValueError()
            return body, 200
    except HTTPError as error:
        if error.code == 404:
            try:
                body = json.load(error)
                if body.get('error') == 'User not found.':
                    return body, 404
            except (ValueError, AttributeError):
                pass
    except (URLError, OSError, ValueError):
        pass
    return {'error': 'User context unavailable. Please retry.'}, 503


PAGE_LIMIT = 1000
MAX_OFFSET = 1000000  # User Service maximum; a finished list is parked here to return empty pages
RECOMMENDATION_CONTEXT_PATH = '/internal/recommendation-context/'


class ContextError(Exception):
    """User context could not be read; status is 404 (unknown user) or 503."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _timestamp(value):
    return datetime.fromisoformat(value) if value else None


def _next_offset(section, offset):
    following = section['next_offset']
    if following is None:
        return None
    if type(following) is not int or following <= offset:
        raise ValueError('Context pagination did not advance.')
    return following


def fetch_full_context(config, user_id):
    """Return the user's complete watched history and watchlist, all pages."""
    offsets = {'watched': 0, 'watchlist': 0}
    items = {'watched': {}, 'watchlist': {}}
    as_of = None
    while offsets:
        params = {'limit': PAGE_LIMIT, 'watched_offset': offsets.get('watched', MAX_OFFSET),
                  'watchlist_offset': offsets.get('watchlist', MAX_OFFSET)}
        body, status = fetch(config, RECOMMENDATION_CONTEXT_PATH + str(user_id), params)
        if status != 200:
            raise ContextError(status, body.get('error', 'User context unavailable. Please retry.'))
        try:
            as_of = as_of or _timestamp(body['as_of'])
            for key in list(offsets):
                section = body[key]
                for row in section['items']:
                    if row['movie_id'] in items[key]:
                        continue
                    if key == 'watched':
                        watched_at, recorded_at = _timestamp(row['watched_at']), _timestamp(row['recorded_at'])
                        items[key][row['movie_id']] = {'movie_id': row['movie_id'], 'watched_at': watched_at,
                            'recorded_at': recorded_at, 'effective_at': watched_at or recorded_at}
                    else:
                        items[key][row['movie_id']] = {'movie_id': row['movie_id'],
                                                       'added_at': _timestamp(row['added_at'])}
                following = _next_offset(section, offsets[key])
                if following is None:
                    del offsets[key]
                else:
                    offsets[key] = following
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ContextError(503, 'User context unavailable. Please retry.') from error
    return {'user_id': str(user_id), 'as_of': as_of,
            'watched': list(items['watched'].values()), 'watchlist': list(items['watchlist'].values())}
