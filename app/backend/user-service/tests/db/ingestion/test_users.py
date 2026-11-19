import importlib.util
from pathlib import Path
import io
import json
import runpy
from unittest.mock import MagicMock, Mock
from uuid import UUID

import psycopg
import pytest


def load_ingestion():
    path = Path(__file__).resolve().parents[3] / 'db/ingestion/users.py'
    spec = importlib.util.spec_from_file_location('ingestion_users', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_identities_are_unique_and_repeatable():
    ingestion = load_ingestion()
    templates = ingestion.load_templates()
    users = [ingestion.sample_user(number, templates) for number in range(1, 1001)]
    assert len({user['username'].lower() for user in users}) == 1000
    assert len({user['email'].lower() for user in users}) == 1000
    assert users[0] == ingestion.sample_user(1, templates)
    assert all(user['password'] and len(user['display_name'].split()) == 2 for user in users)
    assert all(user['email'] != 'admin@admin.com' for user in users)


def test_catalog_pagination(monkeypatch):
    ingestion = load_ingestion()
    ids = [str(UUID(int=i)) for i in [1, 2]]
    fetch = Mock(side_effect=[io.BytesIO(json.dumps({'ids': [ids[0]], 'next_cursor': ids[0]}).encode()),
                              io.BytesIO(json.dumps({'ids': ids, 'next_cursor': None}).encode())])
    monkeypatch.setattr(ingestion, 'urlopen', fetch)
    assert ingestion.load_movie_ids('http://movie/') == ids
    assert fetch.call_args.args[0] == 'http://movie/movies/ids?after=' + ids[0]


@pytest.mark.parametrize('pages', [
    [{'ids': [], 'next_cursor': str(UUID(int=1))}],
    [{'ids': [str(UUID(int=1))], 'next_cursor': str(UUID(int=2))}],
    [{'ids': [str(UUID(int=1))], 'next_cursor': str(UUID(int=1))}] * 2,
])
def test_reject_invalid_catalog_cursor(monkeypatch, pages):
    ingestion = load_ingestion()
    monkeypatch.setattr(ingestion, 'urlopen', Mock(side_effect=[io.BytesIO(json.dumps(page).encode()) for page in pages]))
    with pytest.raises(ValueError, match='cursor'):
        ingestion.load_movie_ids('http://movie')


@pytest.mark.parametrize('maximum', [0, 3])
def test_seed_lists_exclude_existing_and_watched(monkeypatch, maximum):
    ingestion = load_ingestion()
    rng = Mock()
    rng.randint.side_effect = lambda low, high: high
    rng.sample.side_effect = lambda values, count: values[:count]
    monkeypatch.setattr(ingestion.random, 'Random', Mock(return_value=rng))
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [('a',)]
    count = ingestion.seed_watched(conn, 'user', 1, ['a', 'b', 'c'], maximum)
    assert count == (2 if maximum else 0)
    assert rng.sample.call_args.args[0] == ['b', 'c']
    watched, existing = MagicMock(), MagicMock()
    watched.__iter__.return_value = [('a',)]
    existing.__iter__.return_value = [('b',)]
    conn.execute.side_effect = [watched, existing, MagicMock()]
    assert ingestion.seed_watchlist(conn, 'user', 1, ['a', 'b', 'c'], maximum) == (1 if maximum else 0)
    assert rng.sample.call_args.args[0] == ['c']


@pytest.mark.parametrize('args', [['--count', '0'], ['--max-watched', '-1'], ['--max-watchlist', '-1'], []])
def test_invalid_cli_arguments(monkeypatch, args):
    ingestion = load_ingestion()
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr('sys.argv', ['users.py', *args])
    with pytest.raises(SystemExit) as error:
        ingestion.main()
    assert error.value.code == 2


def test_catalog_failure_never_opens_database(monkeypatch):
    ingestion = load_ingestion()
    monkeypatch.setenv('DATABASE_URL', 'test-only')
    monkeypatch.setattr('sys.argv', ['users.py'])
    monkeypatch.setattr(ingestion, 'load_movie_ids', Mock(side_effect=OSError('offline')))
    connect = Mock()
    monkeypatch.setattr(ingestion.psycopg, 'connect', connect)
    with pytest.raises(SystemExit) as error:
        ingestion.main()
    assert error.value.code == 1
    connect.assert_not_called()


@pytest.mark.parametrize('admin,invalid_password,disabled', [(False, False, False), (True, True, False), (True, False, True)])
def test_ingestion_creates_updates_skips_and_writes_private_report(monkeypatch, tmp_path, capsys, admin, invalid_password, disabled):
    ingestion = load_ingestion()
    monkeypatch.setattr(ingestion, 'ROOT', tmp_path)
    monkeypatch.setenv('DATABASE_URL', 'test-only')
    args = ['users.py', '--count', '100']
    if disabled:
        args += ['--max-watched', '0', '--max-watchlist', '0']
    monkeypatch.setattr('sys.argv', args)
    monkeypatch.setattr(ingestion, 'load_movie_ids', Mock(return_value=['retired', 'current']))
    passwords = Mock()
    passwords.hash.return_value = 'hash'
    if invalid_password:
        passwords.verify.side_effect = ingestion.VerificationError('old password')
    monkeypatch.setattr(ingestion, 'PasswordHasher', Mock(return_value=passwords))
    watched, watchlist = Mock(return_value=1), Mock(return_value=2)
    monkeypatch.setattr(ingestion, 'seed_watched', watched)
    monkeypatch.setattr(ingestion, 'seed_watchlist', watchlist)
    conn = MagicMock()
    conn.__enter__.return_value = conn
    templates = ingestion.load_templates()
    first_email = ingestion.sample_user(1, templates)['email']

    def execute(sql, params=None):
        result = Mock()
        result.fetchall.return_value = [('retired',)]
        result.fetchone.return_value = None
        if 'SELECT id, password_hash' in sql:
            result.fetchone.return_value = ('admin-id', 'old-hash') if admin else None
        elif 'SELECT id FROM users' in sql and params == (first_email,):
            result.fetchone.return_value = ('existing-id',)
        elif 'SELECT u.id' in sql and params[0] == 'sample0002@example.test':
            result.fetchone.return_value = ('legacy-id',)
        elif 'INSERT INTO users' in sql:
            result.fetchone.return_value = ('new-id',)
        return result

    conn.execute.side_effect = execute
    monkeypatch.setattr(ingestion.psycopg, 'connect', Mock(return_value=conn))
    ingestion.main()
    report = tmp_path / '.run/ingestion-users.csv'
    with report.open() as source:
        records = list(ingestion.csv.DictReader(source))
    assert len(records) == 101
    assert records[0]['username'] == 'admin'
    assert report.stat().st_mode & 0o777 == 0o600
    assert watched.call_count == watchlist.call_count == 101
    assert watched.call_args.args[3] == ([] if disabled else ['current'])
    output = capsys.readouterr().out
    assert 'Created 98, updated 1 old samples, skipped 1' in output
    assert 'Prepared 100/100' in output
    assert any('UPDATE users SET password_hash' in c.args[0] for c in conn.execute.call_args_list) is invalid_password


def test_database_failure_leaves_no_report(monkeypatch, tmp_path):
    ingestion = load_ingestion()
    monkeypatch.setattr(ingestion, 'ROOT', tmp_path)
    monkeypatch.setenv('DATABASE_URL', 'test-only')
    monkeypatch.setattr('sys.argv', ['users.py', '--max-watched', '0', '--max-watchlist', '0'])
    monkeypatch.setattr(ingestion.psycopg, 'connect', Mock(side_effect=psycopg.OperationalError('offline')))
    with pytest.raises(SystemExit) as error:
        ingestion.main()
    assert error.value.code == 1
    assert not (tmp_path / '.run').exists()


def test_script_entrypoint_help(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['users.py', '--help'])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(Path(__file__).resolve().parents[3] / 'db/ingestion/users.py'), run_name='__main__')
    assert error.value.code == 0
    assert '--max-watchlist' in capsys.readouterr().out
