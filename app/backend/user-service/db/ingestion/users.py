"""Add realistic sample accounts and profiles, without login sessions."""
import argparse
import csv
import json
import os
from pathlib import Path
import random
from uuid import UUID
from urllib.request import urlopen
from urllib.error import URLError

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
import psycopg

ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path(__file__).with_name('assets')


def load_templates():
    return {name: json.loads((ASSETS / f'{name}.json').read_text())
            for name in ('first_names', 'last_names', 'usernames', 'email_domains', 'passwords')}


def sample_user(number, templates):
    # Repeatable choices let reruns find the same accounts.
    rng = random.Random(f'g15-sample-user-{number}')
    first = rng.choice(templates['first_names'])
    last = rng.choice(templates['last_names'])
    username = rng.choice(templates['usernames']).format(
        first=first.lower(), last=last.lower(), initial=first[0].lower(), number=number)
    email = f"{username}@{rng.choice(templates['email_domains'])}"
    password = (rng.choice(templates['passwords']['words'])
                + rng.choice(templates['passwords']['words'])
                + str(rng.randint(100, 9999))
                + rng.choice(templates['passwords']['symbols']))
    return {'display_name': f'{first} {last}', 'username': username,
            'email': email, 'password': password}


def load_movie_ids(base_url):
    ids = []
    cursor = None
    while True:
        suffix = '?after=' + cursor if cursor else ''
        with urlopen(base_url.rstrip('/') + '/movies/ids' + suffix, timeout=5) as response:
            page = json.load(response)
        batch = [str(UUID(value)) for value in page['ids']]
        ids.extend(batch)
        next_cursor = page['next_cursor']
        if next_cursor is None:
            return sorted(set(ids))
        next_cursor = str(UUID(next_cursor))
        if not batch or next_cursor != batch[-1] or (cursor and next_cursor <= cursor):
            raise ValueError('Invalid catalog cursor')
        cursor = next_cursor


def seed_watched(connection, user_id, number, movie_ids, maximum):
    rng = random.Random(f'g15-watched-{number}')
    target = rng.randint(0, min(maximum, len(movie_ids)))
    existing = {str(row[0]) for row in connection.execute(
        'SELECT movie_id FROM watched_movies WHERE user_id=%s', (user_id,)).fetchall()}
    count = max(0, target - len(existing))
    choices = rng.sample([mid for mid in movie_ids if mid not in existing], count)
    for movie_id in choices:
        connection.execute('INSERT INTO watched_movies(user_id,movie_id) VALUES (%s,%s) '
                           'ON CONFLICT DO NOTHING', (user_id, movie_id))
    return len(choices)


def seed_watchlist(connection, user_id, number, movie_ids, maximum):
    rng = random.Random(f'g15-watchlist-{number}')
    watched = {str(row[0]) for row in connection.execute('SELECT movie_id FROM watched_movies WHERE user_id=%s', (user_id,))}
    existing = {str(row[0]) for row in connection.execute('SELECT movie_id FROM watchlist_movies WHERE user_id=%s', (user_id,))}
    eligible = [mid for mid in movie_ids if mid not in watched]
    target = rng.randint(0, min(maximum, len(eligible)))
    choices = rng.sample([mid for mid in eligible if mid not in existing], max(0, target - len(existing)))
    for movie_id in choices:
        connection.execute('INSERT INTO watchlist_movies(user_id,movie_id) VALUES (%s,%s) ON CONFLICT DO NOTHING', (user_id, movie_id))
    return len(choices)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=1000,
                        help='Number of sample users, plus admin (default: 1000).')
    parser.add_argument('--max-watched', type=int, default=10,
                        help='Maximum random watched movies per sample user/admin (default: 10; 0 disables).')
    parser.add_argument('--max-watchlist', type=int, default=10, help='Maximum random watchlist movies per user (0 disables).')
    args = parser.parse_args()
    if args.count < 1:
        parser.error('Count must be positive.')
    if args.max_watchlist < 0:
        parser.error('Maximum watchlist movies must be zero or positive.')
    if args.max_watched < 0:
        parser.error('Maximum watched movies must be zero or positive.')
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        parser.error('DATABASE_URL is missing. Run users.sh to load the service .env.')
    try:
        movie_ids = load_movie_ids(os.environ.get('MOVIE_SERVICE_URL', 'http://127.0.0.1:4206')) if args.max_watched or args.max_watchlist else []
    except (URLError, OSError, ValueError, KeyError, TypeError, AttributeError):
        parser.exit(1, 'Cannot read Movie Service catalog. Start Movie Service or use --max-watched 0 --max-watchlist 0. No users changed.\n')
    templates = load_templates()
    passwords = PasswordHasher()
    created = updated = skipped = watched_added = watchlist_added = 0
    credentials = [{'display_name': 'Admin', 'username': 'admin',
                    'email': 'admin@admin.com', 'password': 'admin'}]
    try:
        with psycopg.connect(database_url, connect_timeout=5) as connection:
            # Serialize ingestion runs so they cannot create the same seed concurrently.
            connection.execute('SELECT pg_advisory_xact_lock(150003)')
            # Coordinate with catalog cleanup; never recreate retired references.
            connection.execute('SELECT pg_advisory_xact_lock_shared(150004)')
            retired = {str(row[0]) for row in connection.execute(
                'SELECT movie_id FROM retired_movie_ids WHERE movie_id=ANY(%s::uuid[])', (movie_ids,)).fetchall()}
            movie_ids = [mid for mid in movie_ids if mid not in retired]
            admin = connection.execute(
                'SELECT id, password_hash FROM users WHERE lower(email) = %s',
                ('admin@admin.com',),
            ).fetchone()
            if admin:
                try:
                    passwords.verify(admin[1], 'admin')
                except (VerificationError, InvalidHashError):
                    connection.execute(
                        'UPDATE users SET password_hash = %s, updated_at = now() WHERE id = %s',
                        (passwords.hash('admin'), admin[0]),
                    )
                admin_id = admin[0]
            else:
                admin_id = connection.execute(
                    'INSERT INTO users (email, password_hash, username) VALUES (%s, %s, %s) RETURNING id',
                    ('admin@admin.com', passwords.hash('admin'), 'admin'),
                ).fetchone()[0]
            connection.execute(
                'INSERT INTO user_profiles (user_id, display_name, avatar_id) VALUES (%s, %s, %s) '
                'ON CONFLICT (user_id) DO NOTHING', (admin_id, 'Admin', random.randint(1, 10)),
            )
            watched_added += seed_watched(connection, admin_id, 'admin', movie_ids, args.max_watched)
            watchlist_added += seed_watchlist(connection, admin_id, 'admin', movie_ids, args.max_watchlist)
            for number in range(1, args.count + 1):
                record = sample_user(number, templates)
                credentials.append(record)
                existing = connection.execute(
                    'SELECT id FROM users WHERE lower(email) = %s', (record['email'],)
                ).fetchone()
                if existing:
                    watched_added += seed_watched(connection, existing[0], number, movie_ids, args.max_watched)
                    watchlist_added += seed_watchlist(connection, existing[0], number, movie_ids, args.max_watchlist)
                    skipped += 1
                    continue
                # Convert only the old samples created by this script.
                legacy = connection.execute(
                    'SELECT u.id FROM users u JOIN user_profiles p ON p.user_id = u.id '
                    'WHERE lower(u.email) = %s AND p.display_name = %s',
                    (f'sample{number:04d}@example.test', f'Sample User {number:04d}'),
                ).fetchone()
                password_hash = passwords.hash(record['password'])
                if legacy:
                    user_id = legacy[0]
                    connection.execute(
                        'UPDATE users SET email = %s, password_hash = %s, username = %s, updated_at = now() '
                        'WHERE id = %s', (record['email'], password_hash, record['username'], user_id),
                    )
                    connection.execute(
                        'UPDATE user_profiles SET display_name = %s, updated_at = now() '
                        'WHERE user_id = %s', (record['display_name'], user_id),
                    )
                    updated += 1
                else:
                    user_id = connection.execute(
                        'INSERT INTO users (email, password_hash, username) VALUES (%s, %s, %s) RETURNING id',
                        (record['email'], password_hash, record['username']),
                    ).fetchone()[0]
                    connection.execute(
                        'INSERT INTO user_profiles (user_id, display_name, avatar_id) VALUES (%s, %s, %s)',
                        (user_id, record['display_name'], random.randint(1, 10)),
                    )
                    created += 1
                watched_added += seed_watched(connection, user_id, number, movie_ids, args.max_watched)
                watchlist_added += seed_watchlist(connection, user_id, number, movie_ids, args.max_watchlist)
                if number % 100 == 0:
                    print(f'Prepared {number}/{args.count} sample users...', flush=True)
    except psycopg.Error:
        parser.exit(1, 'Ingestion failed. Changes rolled back. Check the DB and service .env.\n')

    report = ROOT / '.run/ingestion-users.csv'
    report.parent.mkdir(exist_ok=True)
    fd = os.open(report, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=list(credentials[0]))
        writer.writeheader()
        writer.writerows(credentials)
    print(f'Created {created}, updated {updated} old samples, skipped {skipped}. '
          'Admin ensured separately. No sessions created.', flush=True)
    print(f'Added {watched_added} watched records from {len(movie_ids)} existing movies (maximum {args.max_watched} per user).', flush=True)
    print(f'Added {watchlist_added} watchlist records (maximum {args.max_watchlist} per user).', flush=True)
    print(f'Sample login details: {report}', flush=True)


if __name__ == '__main__':
    main()
