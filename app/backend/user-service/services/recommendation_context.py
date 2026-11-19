"""Read-only user context for the external recommendation agent."""
from services.accounts import connect


def users(url, after, limit):
    with connect(url) as conn:
        rows = conn.execute('SELECT id FROM users WHERE (%s::uuid IS NULL OR id>%s::uuid) ORDER BY id LIMIT %s',
                            (after, after, limit + 1)).fetchall()
    ids = [str(row['id']) for row in rows[:limit]]
    return {'user_ids': ids, 'next_cursor': ids[-1] if len(rows) > limit else None}


def context(url, user_id, watched_offset, watchlist_offset, limit):
    with connect(url) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if not conn.execute('SELECT 1 FROM users WHERE id=%s', (user_id,)).fetchone():
            return None
        result = {'user_id': user_id, 'as_of': conn.execute('SELECT now() AS at').fetchone()['at'].isoformat()}
        for key, table, columns, order, offset in (
            ('watched', 'watched_movies', 'movie_id,watched_at,recorded_at', 'coalesce(watched_at,recorded_at)', watched_offset),
            ('watchlist', 'watchlist_movies', 'movie_id,added_at', 'added_at', watchlist_offset),
        ):
            count = conn.execute('SELECT count(*) AS n FROM ' + table + ' WHERE user_id=%s', (user_id,)).fetchone()['n']
            rows = conn.execute('SELECT ' + columns + ' FROM ' + table + ' WHERE user_id=%s ORDER BY ' + order +
                                ' DESC,movie_id LIMIT %s OFFSET %s', (user_id, limit, offset)).fetchall()
            items = [{name: str(value) if name == 'movie_id' else value.isoformat() if value else None
                      for name, value in row.items()} for row in rows]
            result[key] = {'items': items, 'total': count, 'offset': offset, 'limit': limit,
                           'next_offset': offset + limit if offset + limit < count else None}
    return result
