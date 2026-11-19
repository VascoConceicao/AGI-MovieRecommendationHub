"""Account persistence and opaque sessions owned by the User Service."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
import psycopg
from psycopg.rows import dict_row

PASSWORDS = PasswordHasher()
# Unknown accounts perform the same expensive verification as existing ones.
_DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
SESSION_SECONDS = 7 * 24 * 60 * 60


def connect(database_url):
    return psycopg.connect(database_url, connect_timeout=3,
                           options="-c statement_timeout=5000", row_factory=dict_row)


def initialize(database_url):
    migrations = Path(__file__).resolve().parents[1] / "db/migrations"
    with connect(database_url) as connection:
        # Serialize concurrent initializers; creation remains transactional.
        connection.execute("SELECT pg_advisory_xact_lock(150002)")
        for migration in sorted(migrations.glob('*.sql')):
            connection.execute(migration.read_text())


def token_hash(token):
    return sha256(token.encode()).hexdigest()


def _session(connection, user_id, previous_token=None):
    if previous_token:
        connection.execute("DELETE FROM user_sessions WHERE token_hash = %s",
                           (token_hash(previous_token),))
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS)
    connection.execute(
        "INSERT INTO user_sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
        (token_hash(token), user_id, expires),
    )
    return token


def register(database_url, email, password, display_name, username, previous_token=None):
    password_hash = PASSWORDS.hash(password)
    with connect(database_url) as connection:
        user = connection.execute(
            "INSERT INTO users (email, password_hash, username) VALUES (%s, %s, %s) RETURNING id, email",
            (email, password_hash, username),
        ).fetchone()
        profile = connection.execute(
            "INSERT INTO user_profiles (user_id, display_name) VALUES (%s, %s) RETURNING avatar_id",
            (user['id'], display_name),
        ).fetchone()
        token = _session(connection, user['id'], previous_token)
    return {"id": str(user['id']), "email": email, "username": username, "display_name": display_name,
            "avatar_id": profile['avatar_id']}, token


def login(database_url, email, password, previous_token=None):
    with connect(database_url) as connection:
        user = connection.execute(
            "SELECT u.id, u.email, u.username, u.password_hash, p.display_name, p.avatar_id FROM users u "
            "JOIN user_profiles p ON p.user_id = u.id WHERE lower(u.email) = %s",
            (email,),
        ).fetchone()
        try:
            PASSWORDS.verify(user['password_hash'] if user else _DUMMY_HASH, password)
        except (VerificationError, InvalidHashError):
            return None
        if not user:
            return None
        if PASSWORDS.check_needs_rehash(user['password_hash']):
            connection.execute(
                "UPDATE users SET password_hash = %s, updated_at = now() WHERE id = %s",
                (PASSWORDS.hash(password), user['id']),
            )
        token = _session(connection, user['id'], previous_token)
    return {"id": str(user['id']), "email": user['email'],
            "username": user['username'], "display_name": user['display_name'], "avatar_id": user['avatar_id']}, token


def current_user(database_url, token):
    if not token:
        return None
    with connect(database_url) as connection:
        user = connection.execute(
            "SELECT u.id, u.email, u.username, p.display_name, p.avatar_id FROM user_sessions s "
            "JOIN users u ON u.id = s.user_id JOIN user_profiles p ON p.user_id = u.id "
            "WHERE s.token_hash = %s AND s.expires_at > now()", (token_hash(token),),
        ).fetchone()
    if user:
        user['id'] = str(user['id'])
    return user


def logout(database_url, token):
    if token:
        with connect(database_url) as connection:
            connection.execute("DELETE FROM user_sessions WHERE token_hash = %s",
                               (token_hash(token),))


def clean_sessions(database_url):
    with connect(database_url) as connection:
        return connection.execute("DELETE FROM user_sessions WHERE expires_at <= now()").rowcount
