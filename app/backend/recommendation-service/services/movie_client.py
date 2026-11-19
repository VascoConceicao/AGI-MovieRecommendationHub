"""Read the closed movie catalog over Movie Service HTTP API, never its database."""
from datetime import date
import json
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import UUID

PAGE_LIMIT = 1000
LISTS = ('genres', 'actors', 'directors', 'languages', 'countries')


class MovieCatalogError(Exception):
    """The catalog could not be read completely; callers should treat it as 503."""


def _text(value, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError('Invalid catalog text field.')
    return value


def _list(value):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError('Invalid catalog list field.')
    return value


def _movie(row):
    released = row.get('release_date')
    released = date.fromisoformat(released) if released else None
    duration = row.get('duration_minutes')
    if duration is not None and (type(duration) is not int or duration < 1):
        raise ValueError('Invalid catalog duration.')
    return {'id': str(UUID(row['id'])), 'title': _text(row.get('title'), required=True),
            'original_title': _text(row.get('original_title')), 'synopsis': _text(row.get('synopsis')),
            'release_date': released, 'year': released.year if released else None, 'duration_minutes': duration,
            **{key: _list(row.get(key)) for key in LISTS}}


def fetch_catalog(movie_url):
    """Return every movie in the Movie Service catalog, all pages, in catalog order."""
    movies, offset = {}, 0
    while True:
        url = movie_url.rstrip('/') + '/movies?' + urlencode({'limit': PAGE_LIMIT, 'offset': offset})
        try:
            with urlopen(url, timeout=10) as response:
                body = json.load(response)
            page, total = body['movies'], body['total']
            if not isinstance(page, list) or type(total) is not int or total < 0:
                raise ValueError('Invalid catalog page.')
            for row in page:
                movie = _movie(row)
                movies.setdefault(movie['id'], movie)
        except (URLError, OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise MovieCatalogError('Movie catalog unavailable. Please retry.') from error
        offset += len(page)
        if offset >= total:
            return list(movies.values())
        if not page:
            raise MovieCatalogError('Movie catalog ended before its reported total.')
