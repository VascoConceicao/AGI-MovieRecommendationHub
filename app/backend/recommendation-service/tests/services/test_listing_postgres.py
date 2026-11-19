"""The "All" listing against a real PostgreSQL: each movie once, user_requested preferred, read-only.

Uses the throwaway-database `url` fixture (tests/services/conftest.py); skipped when DATABASE_URL is unset.
"""
from uuid import UUID

import pytest
from services import recommendations as store

USER, OTHER = str(UUID(int=0xA)), str(UUID(int=0xB))


def mid(n):
    return str(UUID(int=n))


@pytest.fixture(autouse=True)
def empty_table(url):
    with store.connect(url) as conn:
        conn.execute('DELETE FROM recommendations')


def add(url, user, movie, source, score, reason=None):
    with store.connect(url) as conn:
        conn.execute('INSERT INTO recommendations(user_id,movie_id,reason,score,source) VALUES (%s,%s,%s,%s,%s)',
                     (user, mid(movie), reason or f'{source} {movie}', score, source))


def rows(url):
    with store.connect(url) as conn:
        return conn.execute('SELECT user_id, movie_id, reason, score, source FROM recommendations ORDER BY id').fetchall()


def seed(url):
    # movies 1-2 only auto, 3-4 in both sources, 5 only user_requested
    for movie, score in ((1, 1.0), (2, 0.9), (3, 0.8), (4, 0.7)):
        add(url, USER, movie, 'auto', score)
    for movie, score in ((3, 1.0), (4, 0.9), (5, 0.8)):
        add(url, USER, movie, 'user_requested', score)
    add(url, OTHER, 3, 'auto', 1.0)


def test_all_shows_each_movie_once_and_prefers_user_requested(url):
    seed(url)
    listing = store.listing(url, USER, 0, 25)
    by_movie = {item['movie_id']: item for item in listing['items']}
    assert listing['total'] == 5 and len(listing['items']) == 5 and len(by_movie) == 5
    assert {m: (i['source'], i['reason']) for m, i in by_movie.items() if m in (mid(3), mid(4))} == {
        mid(3): ('user_requested', 'user_requested 3'), mid(4): ('user_requested', 'user_requested 4')}
    assert by_movie[mid(1)]['source'] == 'auto' and by_movie[mid(5)]['source'] == 'user_requested'


def test_all_keeps_score_ordering_of_the_chosen_rows(url):
    seed(url)
    ordered = [(i['movie_id'], i['source'], i['score']) for i in store.listing(url, USER, 0, 25)['items']]
    # Ties are broken by the newer row first, so the user_requested row leads its auto twin.
    assert ordered == [(mid(3), 'user_requested', 1.0), (mid(1), 'auto', 1.0), (mid(4), 'user_requested', 0.9),
                       (mid(2), 'auto', 0.9), (mid(5), 'user_requested', 0.8)]


def test_pagination_and_total_follow_the_deduplicated_list(url):
    seed(url)
    pages = [store.listing(url, USER, offset, 2) for offset in (0, 2, 4)]
    assert [page['total'] for page in pages] == [5, 5, 5]
    movies = [item['movie_id'] for page in pages for item in page['items']]
    assert len(movies) == 5 and len(set(movies)) == 5
    assert store.listing(url, USER, 5, 2)['items'] == []


def test_single_source_views_are_unchanged(url):
    seed(url)
    assert [i['movie_id'] for i in store.listing(url, USER, 0, 25, 'auto')['items']] == [mid(1), mid(2), mid(3), mid(4)]
    assert store.listing(url, USER, 0, 25, 'auto')['total'] == 4
    assert [i['movie_id'] for i in store.listing(url, USER, 0, 25, 'user_requested')['items']] == [mid(3), mid(4), mid(5)]
    assert store.listing(url, USER, 0, 25, 'user_requested')['total'] == 3


def test_users_are_isolated_and_nothing_is_modified(url):
    seed(url)
    before = rows(url)
    store.listing(url, USER, 0, 25)
    store.listing(url, OTHER, 0, 25)
    assert rows(url) == before and len(before) == 8
    assert [i['movie_id'] for i in store.listing(url, OTHER, 0, 25)['items']] == [mid(3)]


def test_a_user_without_recommendations_gets_an_empty_list(url):
    assert store.listing(url, USER, 0, 25) == {'items': [], 'total': 0, 'offset': 0, 'limit': 25}
