"""Explicit allowlisted account-table resets, executed in one transaction."""
from psycopg import sql
from services.accounts import connect

TABLES = ('users', 'user_profiles', 'user_sessions', 'watched_movies', 'watchlist_movies')


def clear_tables(database_url, table):
    if table not in (*TABLES, 'all'):
        raise ValueError('Unsupported table selection.')
    # Deleting accounts also deletes their dependent profiles and sessions.
    affected = TABLES if table in ('all', 'users') else (table,)
    with connect(database_url) as connection:
        identifiers = sql.SQL(', ').join(sql.Identifier(name) for name in affected)
        connection.execute(sql.SQL('LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE').format(identifiers))
        counts = {
            name: connection.execute(
                sql.SQL('SELECT count(*) AS count FROM {}').format(sql.Identifier(name))
            ).fetchone()['count']
            for name in affected
        }
        if table in ('all', 'users'):
            connection.execute('DELETE FROM users')
        else:
            connection.execute(sql.SQL('DELETE FROM {}').format(sql.Identifier(table)))
    return {'cleared_tables': list(affected), 'deleted_rows': counts}
