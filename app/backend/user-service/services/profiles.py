"""Private profiles, history, and idempotent catalog cleanup."""
import json
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import URLError
from services.accounts import connect


def profile(url, user_id):
    with connect(url) as conn:
        row = conn.execute('SELECT display_name, bio, avatar_id, is_public FROM user_profiles WHERE user_id=%s', (user_id,)).fetchone()
    return row


def avatar(url, user_id, avatar_id):
    with connect(url) as conn:
        return conn.execute('UPDATE user_profiles SET avatar_id=%s, updated_at=now() WHERE user_id=%s '
                            'RETURNING display_name, bio, avatar_id, is_public', (avatar_id, user_id)).fetchone()


def watch_minutes(movie_service_url, ids):
    if not ids:
        return 0
    total = 0
    try:
        for start in range(0, len(ids), 1000):
            request = Request(movie_service_url.rstrip('/') + '/movies/duration',
                              data=json.dumps({'ids': ids[start:start + 1000]}).encode(),
                              headers={'Content-Type': 'application/json'}, method='POST')
            with urlopen(request, timeout=3) as response:
                result = json.load(response)
            if result.get('missing_count') != 0 or type(result.get('total_minutes')) is not int or result['total_minutes'] < 0:
                return None
            total += result['total_minutes']
    except (URLError, OSError, ValueError, TypeError, AttributeError):
        return None
    return total


class SearchUnavailable(Exception):
    pass


def search_ids(movie_service_url, ids, query):
    matches = set()
    try:
        for start in range(0, len(ids), 50):
            url = movie_service_url.rstrip('/') + '/movies?' + urlencode({'ids': ','.join(ids[start:start + 50])})
            with urlopen(url, timeout=3) as response:
                movies = json.load(response)['movies']
            for movie in movies:
                if any(query.casefold() in (movie.get(field) or '').casefold() for field in ('title', 'original_title')):
                    matches.add(movie['id'])
    except (URLError, OSError, ValueError, KeyError, TypeError):
        raise SearchUnavailable() from None
    return matches


def history(url, user_id, offset, movie_service_url, query=''):
    with connect(url) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if query:
            rows = conn.execute('SELECT movie_id, watched_at, recorded_at FROM watched_movies WHERE user_id=%s '
                                'ORDER BY recorded_at DESC, movie_id', (user_id,)).fetchall()
        else:
            rows = conn.execute('SELECT movie_id, watched_at, recorded_at FROM watched_movies WHERE user_id=%s '
                                'ORDER BY recorded_at DESC, movie_id LIMIT 25 OFFSET %s', (user_id, offset)).fetchall()
        ids = [str(row['movie_id']) for row in conn.execute('SELECT movie_id FROM watched_movies WHERE user_id=%s', (user_id,)).fetchall()]
    matched_total = len(ids)
    if query:
        matches = search_ids(movie_service_url, ids, query)
        rows = [row for row in rows if str(row['movie_id']) in matches]
        matched_total = len(rows)
        rows = rows[offset:offset + 25]
    for row in rows:
        row['movie_id'] = str(row['movie_id'])
        for key in ('watched_at', 'recorded_at'):
            row[key] = row[key].isoformat() if row[key] else None
    return {'items': rows, 'total': len(ids), 'matched_total': matched_total, 'offset': offset, 'limit': 25,
            'watch_minutes': watch_minutes(movie_service_url, ids)}


def mark_unwatched(url, user_id, movie_id):
    with connect(url) as conn:
        deleted = conn.execute('DELETE FROM watched_movies WHERE user_id=%s AND movie_id=%s',
                               (user_id, movie_id)).rowcount
    return {'removed': bool(deleted)}


def move_to_watchlist(url, user_id, movie_id, movie_service_url):
    require_movie(movie_service_url, movie_id)
    with connect(url) as conn:
        conn.execute('SELECT pg_advisory_xact_lock_shared(150004)')
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,42))', (str(user_id),))
        conn.execute('DELETE FROM watched_movies WHERE user_id=%s AND movie_id=%s', (user_id, movie_id))
        conn.execute('INSERT INTO watchlist_movies(user_id,movie_id) VALUES (%s,%s) ON CONFLICT DO NOTHING',
                     (user_id, movie_id))
    return {'watched': False, 'in_watchlist': True}


def cleanup(url, operation_id, movie_ids):
    with connect(url) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(150004)')
        previous = conn.execute('SELECT deleted_rows FROM watched_cleanup_operations WHERE operation_id=%s',
                                (operation_id,)).fetchone()
        if previous:
            return previous['deleted_rows']
        # Retire catalog IDs as well as any orphan history from a previous catalog.
        conn.execute('INSERT INTO retired_movie_ids SELECT DISTINCT movie_id FROM watched_movies ON CONFLICT DO NOTHING')
        conn.execute('INSERT INTO retired_movie_ids SELECT unnest(%s::uuid[]) ON CONFLICT DO NOTHING', (movie_ids,))
        conn.execute('INSERT INTO retired_movie_ids SELECT DISTINCT movie_id FROM watchlist_movies ON CONFLICT DO NOTHING')
        conn.execute('DELETE FROM watchlist_movies')
        count = conn.execute('DELETE FROM watched_movies').rowcount
        conn.execute('INSERT INTO watched_cleanup_operations(operation_id, deleted_rows) VALUES (%s,%s)',
                     (operation_id, count))
    return count


def watchlist(url, user_id):
    with connect(url) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        rows = conn.execute('SELECT movie_id FROM watchlist_movies WHERE user_id=%s '
                            'ORDER BY added_at DESC,movie_id', (user_id,)).fetchall()
        watched = conn.execute('SELECT movie_id FROM watched_movies WHERE user_id=%s', (user_id,)).fetchall()
    return {'ids': [str(row['movie_id']) for row in rows], 'watched_ids': [str(row['movie_id']) for row in watched]}


def update_watchlist(url, user_id, movie_id, add, movie_service_url):
    if add:
        require_movie(movie_service_url, movie_id)
    with connect(url) as conn:
        if add:
            conn.execute('SELECT pg_advisory_xact_lock_shared(150004)')
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,42))', (str(user_id),))
            if conn.execute('SELECT 1 FROM watched_movies WHERE user_id=%s AND movie_id=%s', (user_id, movie_id)).fetchone():
                raise AlreadyWatched()
            conn.execute('INSERT INTO watchlist_movies(user_id,movie_id) VALUES (%s,%s) ON CONFLICT DO NOTHING',
                         (user_id, movie_id))
        else:
            conn.execute('DELETE FROM watchlist_movies WHERE user_id=%s AND movie_id=%s', (user_id, movie_id))
    return {'in_watchlist': add}


class AlreadyWatched(Exception):
    pass


def require_movie(movie_service_url, movie_id):
    try:
        with urlopen(movie_service_url.rstrip('/') + '/movies?' + urlencode({'ids': movie_id}), timeout=3) as response:
            movies = json.load(response)['movies']
        if not any(movie['id'] == movie_id for movie in movies):
            raise ValueError('Movie not found.')
    except (URLError, OSError, KeyError, TypeError):
        raise SearchUnavailable() from None


def mark_watched(url, user_id, movie_id, movie_service_url):
    require_movie(movie_service_url, movie_id)
    with connect(url) as conn:
        conn.execute('SELECT pg_advisory_xact_lock_shared(150004)')
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,42))', (str(user_id),))
        conn.execute('INSERT INTO watched_movies(user_id,movie_id,watched_at) VALUES (%s,%s,now()) '
                     'ON CONFLICT DO NOTHING', (user_id, movie_id))
    return {'watched': True}


def visibility(url, user_id, is_public):
    with connect(url) as conn:
        return conn.execute('UPDATE user_profiles SET is_public=%s, updated_at=now() WHERE user_id=%s '
                            'RETURNING display_name, bio, avatar_id, is_public', (is_public, user_id)).fetchone()


def search_watchlist(url, user_id, query, offset, movie_service_url):
    with connect(url) as conn:
        rows = conn.execute('SELECT movie_id FROM watchlist_movies WHERE user_id=%s '
                            'ORDER BY added_at DESC,movie_id', (user_id,)).fetchall()
    ids = [str(row['movie_id']) for row in rows]
    matches = search_ids(movie_service_url, ids, query) if query else set(ids)
    ids = [movie_id for movie_id in ids if movie_id in matches]
    return {'items': [{'movie_id': movie_id} for movie_id in ids[offset:offset + 25]],
            'total': len(ids), 'offset': offset, 'limit': 25}
