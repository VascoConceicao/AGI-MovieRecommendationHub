import io
import json
from datetime import date
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest
from services import movie_client

URL = 'http://movie/'
ID1, ID2, ID3 = ('00000000-0000-4000-8000-00000000000%d' % n for n in (1, 2, 3))


def row(movie_id, **changes):
    return {'id': movie_id, 'title': 'Title ' + movie_id[-1], 'original_title': 'Original', 'synopsis': 'Plot',
            'release_date': '2014-11-05', 'duration_minutes': 169, 'movie_type': 'movie',
            'genres': ['Drama'], 'actors': ['A'], 'directors': ['D'], 'languages': ['en'], 'countries': ['US'],
            'poster_key': None, 'poster_url': None, 'created_at': '2026-10-01T00:00:00+00:00', **changes}


def serve(monkeypatch, *bodies):
    responses = iter(bodies)

    def fake(url, timeout):
        body = next(responses)
        if isinstance(body, Exception):
            raise body
        return io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode())
    mock = Mock(side_effect=fake)
    monkeypatch.setattr(movie_client, 'urlopen', mock)
    return mock


def page(rows, total):
    return {'movies': rows, 'total': total, 'offset': 0, 'limit': 1000}


def test_empty_catalog(monkeypatch):
    fetch = serve(monkeypatch, page([], 0))
    assert movie_client.fetch_catalog(URL) == []
    assert fetch.call_args.args[0] == 'http://movie/movies?limit=1000&offset=0'
    assert fetch.call_args.kwargs == {'timeout': 10}


def test_single_page_keeps_uuid_and_metadata(monkeypatch):
    serve(monkeypatch, page([row(ID1)], 1))
    [movie] = movie_client.fetch_catalog(URL)
    assert movie == {'id': ID1, 'title': 'Title 1', 'original_title': 'Original', 'synopsis': 'Plot',
                     'release_date': date(2014, 11, 5), 'year': 2014, 'duration_minutes': 169,
                     'genres': ['Drama'], 'actors': ['A'], 'directors': ['D'], 'languages': ['en'],
                     'countries': ['US']}


def test_multi_page_catalog_requests_following_offsets(monkeypatch):
    fetch = serve(monkeypatch, page([row(ID1), row(ID2)], 3), page([row(ID3)], 3))
    assert [movie['id'] for movie in movie_client.fetch_catalog(URL)] == [ID1, ID2, ID3]
    assert [call.args[0] for call in fetch.call_args_list] == [
        'http://movie/movies?limit=1000&offset=0', 'http://movie/movies?limit=1000&offset=2']


def test_ignores_movie_repeated_across_pages(monkeypatch):
    serve(monkeypatch, page([row(ID1)], 3), page([row(ID1), row(ID2)], 3))
    assert [movie['id'] for movie in movie_client.fetch_catalog(URL)] == [ID1, ID2]


def test_empty_page_before_total_fails_instead_of_returning_partial_catalog(monkeypatch):
    fetch = serve(monkeypatch, page([row(ID1)], 5), page([], 5))
    with pytest.raises(movie_client.MovieCatalogError):
        movie_client.fetch_catalog(URL)
    assert fetch.call_count == 2


def test_legacy_rows_with_missing_metadata(monkeypatch):
    serve(monkeypatch, page([row(ID1, release_date=None, duration_minutes=None, genres=None, actors=None,
                                 directors=None, languages=None, countries=None, synopsis=None, original_title=None)], 1))
    [movie] = movie_client.fetch_catalog(URL)
    assert movie['year'] is None and movie['release_date'] is None and movie['duration_minutes'] is None
    assert movie['genres'] == movie['actors'] == movie['languages'] == [] and movie['synopsis'] is None


@pytest.mark.parametrize('bad', [
    {'movies': [row(ID1)]}, {'movies': 'x', 'total': 1}, page([row(ID1)], '1'), page([row(ID1)], -1),
    page([row('not-a-uuid')], 1), page([{k: v for k, v in row(ID1).items() if k != 'id'}], 1),
    page([row(ID1, title='  ')], 1), page([row(ID1, title=None)], 1), page(['text'], 1),
    page([row(ID1, genres='Drama')], 1), page([row(ID1, actors=[1])], 1),
    page([row(ID1, release_date='not-a-date')], 1), page([row(ID1, duration_minutes=0)], 1),
    page([row(ID1, duration_minutes='90')], 1), [], b'bad',
])
def test_malformed_response(monkeypatch, bad):
    serve(monkeypatch, bad)
    with pytest.raises(movie_client.MovieCatalogError):
        movie_client.fetch_catalog(URL)


@pytest.mark.parametrize('failure', [URLError('offline'), TimeoutError(),
                                     HTTPError('http://movie', 500, 'failure', {}, io.BytesIO(b'{}'))])
def test_transport_failure(monkeypatch, failure):
    serve(monkeypatch, failure)
    with pytest.raises(movie_client.MovieCatalogError):
        movie_client.fetch_catalog(URL)


def test_failure_on_later_page_discards_partial_catalog(monkeypatch):
    serve(monkeypatch, page([row(ID1)], 2), URLError('offline'))
    with pytest.raises(movie_client.MovieCatalogError):
        movie_client.fetch_catalog(URL)
