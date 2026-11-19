"""Add N new real movies. External requests exist only in this ingestion module."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services import catalog


def download(url, token='', limit=4 * 1024 * 1024):
    headers = {'Accept': 'application/json' if token else 'image/jpeg'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    attempt = 0
    while True:
        try:
            with urlopen(Request(url, headers=headers), timeout=20) as response:
                data = response.read(limit + 1)
                if len(data) > limit:
                    raise ValueError('Provider response exceeds size limit.')
                return data
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            time.sleep(min(10, 2 ** attempt))
            attempt += 1


def tmdb_genre_candidates(token, genre_id):
    for page in range(1, 501):
        result = json.loads(download(
            f'https://api.themoviedb.org/3/discover/movie?language=en-US&sort_by=popularity.desc'
            f'&with_genres={genre_id}&page={page}', token))
        for movie in result['results']:
            yield str(movie['id'])
        if not result['results'] or page >= result['total_pages']:
            break


def tmdb_candidates(token):
    """Interleave genre feeds, avoiding repeated detail requests across genres."""
    genres = json.loads(download('https://api.themoviedb.org/3/genre/movie/list?language=en', token))['genres']
    feeds = [iter(tmdb_genre_candidates(token, genre['id'])) for genre in genres]
    seen = set()
    while feeds:
        remaining = []
        for feed in feeds:
            for movie_id in feed:
                if movie_id not in seen:
                    seen.add(movie_id)
                    yield movie_id
                    remaining.append(feed)
                    break
        feeds = remaining


def tmdb_movie(source_id, token, media):
    data = json.loads(download(f'https://api.themoviedb.org/3/movie/{source_id}?append_to_response=credits&language=en-US', token))
    movie = dict(source='tmdb', source_id=source_id, title=data['title'], original_title=data.get('original_title'),
                 synopsis=data.get('overview'), release_date=data.get('release_date'), duration_minutes=data.get('runtime') or None,
                 movie_type='movie', genres=[item['name'] for item in (data.get('genres') or [])],
                 actors=[item['name'] for item in ((data.get('credits') or {}).get('cast') or [])[:100]],
                 directors=[item['name'] for item in ((data.get('credits') or {}).get('crew') or []) if item['job'] == 'Director'],
                 languages=[item['iso_639_1'] for item in (data.get('spoken_languages') or []) if item['iso_639_1']],
                 countries=[item['iso_3166_1'] for item in (data.get('production_countries') or [])], poster_key=None)
    catalog.validate(movie)
    poster = data.get('poster_path')
    if poster and re.fullmatch(r'/[A-Za-z0-9]+\.jpg', poster):
        try:
            image = download('https://image.tmdb.org/t/p/w500' + poster)
            if not image.startswith(b'\xff\xd8\xff'):
                raise ValueError('Poster is not a JPEG.')
            key = sha256(image).hexdigest() + '.jpg'
            media.mkdir(parents=True, exist_ok=True)
            temp = media / (key + '.tmp')
            temp.write_bytes(image)
            temp.replace(media / key)
            movie['poster_key'] = key
        except (URLError, OSError, ValueError):
            print(f'Poster unavailable for tmdb:{source_id}; local placeholder will be used.', file=sys.stderr)
    return movie


def main():
    parser = argparse.ArgumentParser(description='Add COUNT additional movies; never replace existing rows.')
    parser.add_argument('--count', type=int, default=100)
    parser.add_argument('--file', type=Path, help='Offline JSON array in the agent movie payload format; no external requests.')
    args = parser.parse_args()
    if not 1 <= args.count <= 10000:
        parser.error('--count must be between 1 and 10000')
    url = os.environ.get('DATABASE_URL')
    if not url:
        parser.error('Set DATABASE_URL in Movie Service .env')
    token = os.environ.get('TMDB_READ_TOKEN', '')
    if not args.file and not token:
        parser.error('Set ingestion-only TMDB_READ_TOKEN, or supply --file for an offline import')
    records = json.loads(args.file.read_text()) if args.file else None
    if records is not None and not isinstance(records, list):
        parser.error('--file must contain a JSON array')
    media = Path(os.environ.get('MOVIE_MEDIA_DIR', str(ROOT / 'assets/posters'))).resolve()
    catalog.initialize(url)
    counts = dict(requested=args.count, added=0, skipped=0, failed=0)
    # One ingestion session at a time; commits still happen per movie.
    with catalog.connect(url) as guard:
        if not guard.execute('SELECT pg_try_advisory_lock(150005) AS acquired').fetchone()['acquired']:
            parser.error('Another movie ingestion is running; retry after it finishes')
        known = {(row['source'], row['source_id']) for row in guard.execute('SELECT source, source_id FROM movies')}
        candidates = records if records is not None else tmdb_candidates(token)
        for candidate in candidates:
            try:
                identity = (candidate['source'], candidate['source_id']) if records is not None else ('tmdb', candidate)
                if identity in known:
                    counts['skipped'] += 1
                    continue
                movie = candidate if records is not None else tmdb_movie(candidate, token, media)
                validated = catalog.validate(movie)
                if validated['poster_key'] and not (media / validated['poster_key']).is_file():
                    raise ValueError('Local poster is missing')
                _, created = catalog.create(url, movie)
                known.add(identity)
                counts['added' if created else 'skipped'] += 1
                if created:
                    print(f'Saved {counts["added"]}/{args.count} new movies.', flush=True)
            except (ValueError, KeyError, TypeError, URLError, OSError) as error:
                counts['failed'] += 1
                reason = str(error) if isinstance(error, ValueError) else type(error).__name__
                print(f'Skipped movie: {reason}', file=sys.stderr)
            if counts['added'] == args.count:
                break
    counts['complete'] = counts['added'] == args.count
    if not counts['complete']:
        print('Source exhausted before the requested number of new movies was saved.', file=sys.stderr)
    print(json.dumps(counts))
    return 0 if counts['complete'] else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (catalog.psycopg.Error, catalog.ResetPending, URLError, OSError, ValueError, KeyError):
        print('Ingestion stopped. Check database, source, or pending reset. Earlier inserts remain saved.', file=sys.stderr)
        raise SystemExit(1)
