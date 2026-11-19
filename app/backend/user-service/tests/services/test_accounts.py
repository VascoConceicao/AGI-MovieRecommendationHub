from datetime import datetime, timezone
from hashlib import sha256
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from argon2.exceptions import VerificationError, InvalidHashError
from services import accounts


@pytest.fixture
def connection(monkeypatch):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr(accounts, 'connect', Mock(return_value=conn))
    return conn


@pytest.fixture
def passwords(monkeypatch):
    passwords = Mock()
    passwords.hash.return_value = 'new-hash'
    monkeypatch.setattr(accounts, 'PASSWORDS', passwords)
    return passwords


def test_connect(monkeypatch):
    connect = Mock()
    monkeypatch.setattr(accounts.psycopg, 'connect', connect)
    assert accounts.connect('db') is connect.return_value
    connect.assert_called_once_with('db', connect_timeout=3, options='-c statement_timeout=5000', row_factory=accounts.dict_row)


def test_initialize(connection):
    accounts.initialize('db')
    assert connection.execute.call_args_list[0].args == ('SELECT pg_advisory_xact_lock(150002)',)
    assert any('CREATE TABLE' in c.args[0] for c in connection.execute.call_args_list)


@pytest.mark.parametrize('previous', [None, 'old'])
def test_session_rotation_stores_only_hash(connection, monkeypatch, previous):
    monkeypatch.setattr(accounts.secrets, 'token_urlsafe', Mock(return_value='opaque'))
    before = datetime.now(timezone.utc)
    assert accounts._session(connection, 'user', previous) == 'opaque'
    args = connection.execute.call_args.args[1]
    assert args[:2] == (sha256(b'opaque').hexdigest(), 'user')
    assert accounts.SESSION_SECONDS <= (args[2] - before).total_seconds() < accounts.SESSION_SECONDS + 2
    deletes = [c for c in connection.execute.call_args_list if 'DELETE' in c.args[0]]
    assert len(deletes) == bool(previous)
    if previous:
        assert deletes[0].args[1] == (sha256(b'old').hexdigest(),)


def test_register_creates_profile_and_session(connection, passwords, monkeypatch):
    connection.execute.return_value.fetchone.return_value = {'id': UUID(int=1), 'avatar_id': 7}
    session = Mock(return_value='token')
    monkeypatch.setattr(accounts, '_session', session)
    user, token = accounts.register('db', 'email', 'password', 'Name', 'name', 'old')
    assert user == {'id': str(UUID(int=1)), 'email': 'email', 'username': 'name', 'display_name': 'Name', 'avatar_id': 7}
    assert token == 'token'
    passwords.hash.assert_called_once_with('password')
    assert connection.execute.call_args_list[0].args[1] == ('email', 'new-hash', 'name')
    assert connection.execute.call_args_list[1].args[1] == (UUID(int=1), 'Name')
    session.assert_called_once_with(connection, UUID(int=1), 'old')


@pytest.mark.parametrize('error', [VerificationError('wrong'), InvalidHashError('bad')])
def test_invalid_password_does_not_create_session(connection, passwords, error):
    connection.execute.return_value.fetchone.return_value = {'password_hash': 'hash'}
    passwords.verify.side_effect = error
    assert accounts.login('db', 'email', 'password') is None
    assert connection.execute.call_count == 1


def test_unknown_user_uses_dummy_hash(connection, passwords):
    connection.execute.return_value.fetchone.return_value = None
    assert accounts.login('db', 'email', 'password') is None
    passwords.verify.assert_called_once_with(accounts._DUMMY_HASH, 'password')


@pytest.mark.parametrize('rehash', [True, False])
def test_login_rehashes_when_needed(connection, passwords, monkeypatch, rehash):
    connection.execute.return_value.fetchone.return_value = {'id': UUID(int=1), 'email': 'email',
        'username': 'name', 'display_name': 'Name', 'password_hash': 'hash', 'avatar_id': 7}
    passwords.check_needs_rehash.return_value = rehash
    monkeypatch.setattr(accounts, '_session', Mock(return_value='token'))
    user, token = accounts.login('db', 'email', 'password')
    assert token == 'token'
    assert user == {'id': str(UUID(int=1)), 'email': 'email', 'username': 'name', 'display_name': 'Name', 'avatar_id': 7}
    assert any('UPDATE users' in c.args[0] for c in connection.execute.call_args_list) is rehash


def test_current_user_logout_and_expiry(connection):
    assert accounts.current_user('db', None) is None
    accounts.logout('db', None)
    connection.execute.assert_not_called()
    connection.execute.return_value.fetchone.return_value = None
    assert accounts.current_user('db', 'token') is None
    connection.execute.return_value.fetchone.return_value = {'id': UUID(int=1), 'email': 'email'}
    assert accounts.current_user('db', 'token') == {'id': str(UUID(int=1)), 'email': 'email'}
    accounts.logout('db', 'token')
    assert connection.execute.call_args.args[1] == (accounts.token_hash('token'),)
    connection.execute.return_value.rowcount = 4
    assert accounts.clean_sessions('db') == 4
