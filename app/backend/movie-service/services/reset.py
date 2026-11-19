"""Durable cleanup coordination; each service owns its own transaction."""
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen
from urllib.error import URLError
from psycopg.types.json import Jsonb
from services.catalog import connect, LOCK


class CleanupPending(Exception):
    pass


def clear(config):
    # Ingestion holds this same lock while downloading and inserting posters.
    # Also serialize reset requests so a late retry cannot delete new assets.
    with connect(config['DATABASE_URL']) as guard:
        if not guard.execute('SELECT pg_try_advisory_xact_lock(150005) AS acquired').fetchone()['acquired']:
            raise CleanupPending('Movie ingestion or reset is running. Retry after it finishes.')
        return _clear(config)


def clear_posters(directory):
    directory = Path(directory)
    try:
        entries = list(directory.iterdir())
    except FileNotFoundError:
        return
    for path in entries:
        if re.fullmatch(r'[a-f0-9]{64}\.jpg', path.name):
            path.unlink(missing_ok=True)


def _clear(config):
    if not config['USER_SERVICE_URL'] or not config['WATCHED_CLEANUP_TOKEN']:
        raise CleanupPending('Configure User Service cleanup before resetting movies.')
    with connect(config['DATABASE_URL']) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        job = conn.execute('SELECT * FROM catalog_resets WHERE NOT completed').fetchone()
        if job is None:
            ids = [str(row['id']) for row in conn.execute('DELETE FROM movies RETURNING id').fetchall()]
            job = conn.execute('INSERT INTO catalog_resets(movie_ids, deleted_count) VALUES (%s,%s) RETURNING *',
                               (Jsonb(ids), len(ids))).fetchone()
    # The deletion + pending job is durable before calling User Service. New creates
    # remain blocked until cleanup completes. Retrying uses the same operation ID.
    payload = json.dumps({'operation_id': str(job['id']), 'movie_ids': job['movie_ids']}).encode()
    req = Request(config['USER_SERVICE_URL'].rstrip('/') + '/internal/clear-watched', data=payload,
                  headers={'Content-Type': 'application/json',
                           'Authorization': 'Bearer ' + config['WATCHED_CLEANUP_TOKEN']}, method='POST')
    try:
        with urlopen(req, timeout=5) as response:
            result = json.load(response)
        if result.get('operation_id') != str(job['id']) or type(result.get('deleted_rows')) is not int:
            raise ValueError()
    except (URLError, TimeoutError, ValueError, OSError):
        raise CleanupPending('Movie deletion recorded; watched cleanup pending. Retry this reset.') from None
    with connect(config['DATABASE_URL']) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        try:
            clear_posters(config['MOVIE_MEDIA_DIR'])
        except OSError:
            raise CleanupPending('Movie deletion recorded; poster cleanup pending. Retry this reset.') from None
        conn.execute('UPDATE catalog_resets SET completed=true WHERE id=%s', (job['id'],))
    return {'cleared_tables': ['movies'], 'deleted_rows': {'movies': job['deleted_count']},
            'watched_deleted_rows': result['deleted_rows'], 'operation_id': str(job['id'])}
