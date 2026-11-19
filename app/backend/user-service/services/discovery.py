"""Public profile reads. Account fields never leave this service's account API."""
from services.accounts import connect
from services import profiles


def search(url, query, offset, limit=25, seed=None):
    with connect(url) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        where = ('FROM users u JOIN user_profiles p ON p.user_id=u.id WHERE p.is_public AND '
                 '(position(lower(%s) in lower(u.username)) > 0 OR '
                 'position(lower(%s) in lower(p.display_name)) > 0)')
        total = conn.execute('SELECT count(*) AS n ' + where, (query, query)).fetchone()['n']
        order = 'md5(u.id::text || %s),u.id' if seed and not query else 'lower(u.username),u.id'
        params = (query, query, seed, limit, offset) if seed and not query else (query, query, limit, offset)
        rows = conn.execute('SELECT u.id, u.username, p.display_name, p.avatar_id ' + where +
                            ' ORDER BY ' + order + ' LIMIT %s OFFSET %s', params).fetchall()
    for row in rows:
        row['id'] = str(row['id'])
    return {'users': rows, 'total': total, 'offset': offset, 'limit': limit}


def public_profile(url, user_id, offset, section='watched', query='', movie_service_url=''):
    with connect(url) as conn:
        # Visibility, identity, and history are read from the same snapshot.
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        profile = conn.execute('SELECT u.id, u.username, p.display_name, p.avatar_id, p.bio '
                               'FROM users u JOIN user_profiles p ON p.user_id=u.id '
                               'WHERE u.id=%s AND p.is_public', (user_id,)).fetchone()
        if profile is None:
            return None
        watched_ids = [str(row['movie_id']) for row in conn.execute(
            'SELECT movie_id FROM watched_movies WHERE user_id=%s', (user_id,)).fetchall()]
        total = len(watched_ids)
        if section == 'watched':
            rows = conn.execute('SELECT movie_id, watched_at FROM watched_movies WHERE user_id=%s '
                                'ORDER BY recorded_at DESC,movie_id' + ('' if query else ' LIMIT 25 OFFSET %s'),
                                (user_id,) if query else (user_id, offset)).fetchall()
            collection_total = total
        elif section == 'watchlist':
            collection_total = conn.execute('SELECT count(*) AS n FROM watchlist_movies WHERE user_id=%s',
                                            (user_id,)).fetchone()['n']
            rows = conn.execute('SELECT movie_id, added_at FROM watchlist_movies WHERE user_id=%s '
                                'ORDER BY added_at DESC,movie_id' + ('' if query else ' LIMIT 25 OFFSET %s'),
                                (user_id,) if query else (user_id, offset)).fetchall()
        else:
            # Recommendation rows come from their owning service, after this visibility check.
            rows, collection_total = [], 0
    if query and section != 'recommendations':
        matches = profiles.search_ids(movie_service_url, [str(row['movie_id']) for row in rows], query)
        rows = [row for row in rows if str(row['movie_id']) in matches]
        collection_total = len(rows)
        rows = rows[offset:offset + 25]
    profile['id'] = str(profile['id'])
    for row in rows:
        row['movie_id'] = str(row['movie_id'])
        for key in ('watched_at', 'added_at'):
            if key in row:
                row[key] = row[key].isoformat() if row[key] else None
    collection = {'items': rows, 'total': collection_total, 'offset': offset, 'limit': 25}
    result = {'profile': profile, 'watched_total': total, 'collection': collection,
              'watch_minutes': profiles.watch_minutes(movie_service_url, watched_ids)}
    if section == 'watched':
        result['watched'] = collection
    return result


def is_public(url, user_id):
    with connect(url) as conn:
        return conn.execute('SELECT 1 FROM user_profiles WHERE user_id=%s AND is_public',
                            (user_id,)).fetchone() is not None
