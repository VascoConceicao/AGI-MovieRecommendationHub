"""Recommendation-owned persistence; no cross-service database access."""
import math
from pathlib import Path
from uuid import UUID
import psycopg
from psycopg.rows import dict_row

from services.assembly import FinalRecommendation

SOURCES = ('auto', 'user_requested')
MAX_REASON_CHARS = 5000        # recommendations.reason CHECK: length(trim(reason)) BETWEEN 1 AND 5000
SET_LOCK_SEED = 150007         # seed of the per-(user, source) replace_set advisory lock key


def connect(url):
    return psycopg.connect(url, connect_timeout=3, options='-c statement_timeout=10000', row_factory=dict_row)


def initialize(url):
    with connect(url) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(150006)')
        for migration in sorted((Path(__file__).resolve().parents[1] / 'db/migrations').glob('*.sql')):
            conn.execute(migration.read_text())


def serialize(row):
    return {key: str(value) if key in ('id', 'user_id', 'movie_id') else
            value.isoformat() if key in ('created_at', 'updated_at') else value for key, value in row.items()}


def save(url, user_id, movie_id, reason, score, source):
    return save_batch(url, user_id, [{'movie_id': movie_id, 'reason': reason, 'score': score}], source)[0]


# Rows of one user visible for a source. Without a source (the "All" view) each movie appears once; when both
# sources recommend it the user_requested row wins, so its reason is shown. Read-only: nothing is deleted or changed.
_VISIBLE = {
    True: 'SELECT * FROM recommendations WHERE user_id=%s AND source=%s',
    False: 'SELECT DISTINCT ON (movie_id) * FROM recommendations WHERE user_id=%s AND %s::text IS NULL '
           "ORDER BY movie_id, (source='user_requested') DESC, created_at DESC, id",
}


def listing(url, user_id, offset, limit, source=None):
    visible = _VISIBLE[source is not None]
    with connect(url) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        total = conn.execute(f'WITH visible AS ({visible}) SELECT count(*) AS n FROM visible', (user_id, source)).fetchone()['n']
        rows = conn.execute(f'WITH visible AS ({visible}) SELECT * FROM visible ORDER BY score DESC NULLS LAST, '
                            'created_at DESC, id LIMIT %s OFFSET %s', (user_id, source, limit, offset)).fetchall()
    return {'items': [serialize(row) for row in rows], 'total': total, 'offset': offset, 'limit': limit}


def remove(url, recommendation_id):
    with connect(url) as conn:
        count = conn.execute('DELETE FROM recommendations WHERE id=%s', (recommendation_id,)).rowcount
    return {'removed': bool(count)}


def clear(url):
    with connect(url) as conn:
        count = conn.execute('DELETE FROM recommendations').rowcount
        deleted = {'recommendations': count}
        # Existing development installs may still contain the retired request table.
        if conn.execute("SELECT to_regclass('recommendation_requests') AS name").fetchone()['name']:
            deleted['recommendation_requests'] = conn.execute('DELETE FROM recommendation_requests').rowcount
    return {'cleared_tables': list(deleted), 'deleted_rows': deleted}



def save_batch(url, user_id, items, source):
    with connect(url) as conn:
        rows = []
        for item in items:
            row = conn.execute('INSERT INTO recommendations(user_id,movie_id,reason,score,source) '
                'VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_id,movie_id,source) DO UPDATE SET '
                'reason=EXCLUDED.reason,score=EXCLUDED.score,updated_at=now() RETURNING *',
                (user_id,item['movie_id'],item['reason'],item['score'],source)).fetchone()
            rows.append(serialize(row))
    return rows


class RecommendationInputError(ValueError):
    """The recommendation set to persist is invalid; nothing was written."""


def _uuid(value, name):
    if isinstance(value, UUID):
        return str(value)
    try:
        if not isinstance(value, str):
            raise ValueError()
        return str(UUID(value))
    except ValueError:
        raise RecommendationInputError(f'Invalid {name}.') from None


def validate_set(user_id, source, recommendations):
    """Validate a whole set before any DB access; returns (user_id, source, [(movie_id, reason, score), ...]).

    Nothing is clamped, truncated, deduplicated or defaulted. The stored score only orders the list (the DB
    has no rank column), so scores must be strictly decreasing in the given order.
    """
    user_id = _uuid(user_id, 'user_id')
    if source not in SOURCES:
        raise RecommendationInputError('source must be auto or user_requested.')
    if not isinstance(recommendations, (list, tuple)):
        raise RecommendationInputError('recommendations must be a list or tuple.')
    rows, seen, previous = [], set(), None
    for position, item in enumerate(recommendations, 1):
        where = f'Recommendation {position}'
        if not isinstance(item, FinalRecommendation):
            raise RecommendationInputError(f'{where}: not a FinalRecommendation.')
        try:
            raw_movie_id = item.candidate.movie['id']
        except (AttributeError, KeyError, TypeError):
            raise RecommendationInputError(f'{where}: missing movie id.') from None
        movie_id = _uuid(raw_movie_id, f'{where} movie id')
        if movie_id in seen:
            raise RecommendationInputError(f'{where}: duplicate movie.')
        score, reason = item.score, item.reason
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise RecommendationInputError(f'{where}: score must be a finite number from 0 to 1.')
        if previous is not None and score >= previous:
            raise RecommendationInputError(f'{where}: scores must be strictly decreasing.')
        if not isinstance(reason, str) or not reason.strip() or '\x00' in reason:
            raise RecommendationInputError(f'{where}: reason must be a non-empty string.')
        if len(reason.strip(' ')) > MAX_REASON_CHARS:
            raise RecommendationInputError(f'{where}: reason longer than {MAX_REASON_CHARS} characters.')
        seen.add(movie_id)
        previous = score
        rows.append((movie_id, reason, score))
    return user_id, source, rows


def _lock_set(conn, user_id, source):
    """Serialize replacements of one (user_id, source); released automatically at commit or rollback.

    Takes the lock before any other statement: under READ COMMITTED the following DELETE then gets a fresh
    snapshot that includes whatever the previous holder committed.
    """
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, %s))', (f'{user_id}:{source}', SET_LOCK_SEED))


def replace_set(url, user_id, source, recommendations):
    """Atomically replace the (user_id, source) recommendation set; returns the number of rows inserted.

    All or nothing in one transaction: the old set stays visible until the commit and survives any failure,
    which is propagated. An empty list is an intentionally empty set and just removes the old one. Other
    sources and other users are never touched. The stored score and reason are exactly the given ones.
    """
    user_id, source, rows = validate_set(user_id, source, recommendations)
    with connect(url) as conn:
        _lock_set(conn, user_id, source)
        conn.execute('DELETE FROM recommendations WHERE user_id=%s AND source=%s', (user_id, source))
        for movie_id, reason, score in rows:
            conn.execute('INSERT INTO recommendations(user_id,movie_id,reason,score,source) VALUES (%s,%s,%s,%s,%s)',
                         (user_id, movie_id, reason, score, source))
    return len(rows)
