"""Local catalog persistence. No external provider access in the running service."""
from datetime import date
from pathlib import Path
import re
import psycopg
from psycopg.rows import dict_row

LOCK = 150003
FIELDS = ('source', 'source_id', 'title', 'original_title', 'synopsis', 'release_date',
          'duration_minutes', 'movie_type', 'genres', 'actors', 'directors', 'languages', 'countries')


class ResetPending(Exception):
    pass


def connect(url):
    return psycopg.connect(url, connect_timeout=3, options='-c statement_timeout=10000', row_factory=dict_row)


def initialize(url):
    with connect(url) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        for path in sorted((Path(__file__).resolve().parents[1] / 'db/migrations').glob('*.sql')):
            conn.execute(path.read_text())


def validate(data):
    if not isinstance(data, dict) or set(data) - set(FIELDS) - {'poster_key'}:
        raise ValueError('Provide movie fields only; external image URLs are not accepted.')
    result = {}
    for field in FIELDS:
        value = data.get(field)
        if field not in ('source', 'source_id', 'title', 'synopsis', 'genres', 'actors', 'directors', 'duration_minutes') and (
            value is None or value == [] or (isinstance(value, str) and not value.strip())
        ):
            result[field] = None
            continue
        if field == 'duration_minutes':
            if type(value) is not int or not 1 <= value <= 10000:
                raise ValueError('duration_minutes must be an integer between 1 and 10000.')
        elif field in ('genres', 'actors', 'directors', 'languages', 'countries'):
            if not isinstance(value, list) or not 1 <= len(value) <= 200 or any(
                not isinstance(item, str) or not 1 <= len(item.strip()) <= 200 for item in value
            ):
                raise ValueError(f'{field} must contain 1–200 nonempty strings.')
            value = list(dict.fromkeys(item.strip() for item in value))
        else:
            limit = 10000 if field == 'synopsis' else 300
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
                raise ValueError(f'{field} is required (maximum {limit} characters).')
            value = value.strip()
        result[field] = value
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', result['source']):
        raise ValueError('source must be a lowercase provider identifier.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', result['source_id']):
        raise ValueError('source_id must be a stable provider ID.')
    if result['release_date'] is not None:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', result['release_date']):
            raise ValueError('release_date must be a valid YYYY-MM-DD date.')
        try:
            result['release_date'] = date.fromisoformat(result['release_date'])
        except ValueError:
            raise ValueError('release_date must be a valid YYYY-MM-DD date.') from None
    key = data.get('poster_key')
    if key is not None and (not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}\.jpg', key)):
        raise ValueError('poster_key must identify an already stored JPEG, or be null.')
    result['poster_key'] = key
    return result


def serialize(row):
    result = dict(row)
    result['id'] = str(result['id'])
    result['release_date'] = result['release_date'].isoformat() if result['release_date'] else None
    result['created_at'] = result['created_at'].isoformat()
    result['poster_url'] = '/api/movie/posters/' + result['poster_key'] if result['poster_key'] else None
    return result


def create(url, data):
    values = validate(data)
    with connect(url) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        if conn.execute('SELECT 1 FROM catalog_resets WHERE NOT completed').fetchone():
            raise ResetPending()
        fields = (*FIELDS, 'poster_key')
        row = conn.execute(
            'INSERT INTO movies (' + ','.join(fields) + ') VALUES (' + ','.join(['%s'] * len(fields)) + ') '
            'ON CONFLICT (source, source_id) DO NOTHING RETURNING *',
            tuple(values[field] for field in fields),
        ).fetchone()
        created = row is not None
        if row is None:
            row = conn.execute('SELECT * FROM movies WHERE source=%s AND source_id=%s',
                               (values['source'], values['source_id'])).fetchone()
    return serialize(row), created


def lookup(url, ids):
    with connect(url) as conn:
        rows = conn.execute('SELECT * FROM movies WHERE id = ANY(%s::uuid[])', (ids,)).fetchall()
    return [serialize(row) for row in rows]


def duration_summary(url, ids):
    with connect(url) as conn:
        row = conn.execute('SELECT COALESCE(sum(duration_minutes), 0) AS total_minutes, count(*) AS matched '
                           'FROM movies WHERE id = ANY(%s::uuid[])', (ids,)).fetchone()
    return {'total_minutes': row['total_minutes'], 'missing_count': len(set(ids)) - row['matched']}


def movie_ids(url, after=None):
    with connect(url) as conn:
        rows = conn.execute('SELECT id FROM movies WHERE (%s::uuid IS NULL OR id > %s::uuid) '
                            'ORDER BY id LIMIT 1001', (after, after)).fetchall()
    ids = [str(row['id']) for row in rows[:1000]]
    return {'ids': ids, 'next_cursor': ids[-1] if len(rows) > 1000 else None}


def filter_options(url):
    with connect(url) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return {field: [row['value'] for row in conn.execute(
            'SELECT DISTINCT unnest(' + field + ') AS value FROM movies ORDER BY value') if row['value']]
            for field in ('genres', 'languages')}


def browse(url, query, offset, exclude_ids=None, seed=None, limit=25):
    limit = max(1, min(int(limit), 1000))
    # Literal, case-insensitive substring search, including original titles.
    with connect(url) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        where = "(position(lower(%s) in lower(title)) > 0 OR position(lower(%s) in lower(coalesce(original_title,''))) > 0) AND NOT (id=ANY(%s::uuid[]))"
        total = conn.execute('SELECT count(*) AS n FROM movies WHERE ' + where, (query, query, exclude_ids or [])).fetchone()['n']
        order = 'md5(id::text || %s),id' if seed and not query else 'lower(title),id'
        params = (query, query, exclude_ids or [], seed, offset) if seed and not query else (query, query, exclude_ids or [], offset)
        rows = conn.execute('SELECT * FROM movies WHERE ' + where + ' ORDER BY ' + order + ' LIMIT ' + str(limit) + ' OFFSET %s',
                            params).fetchall()
    return {'movies': [serialize(row) for row in rows], 'total': total, 'offset': offset, 'limit': limit}
