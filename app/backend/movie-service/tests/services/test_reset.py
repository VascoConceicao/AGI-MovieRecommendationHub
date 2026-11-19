import io
import json
from unittest.mock import MagicMock, Mock
from urllib.error import URLError

import pytest
from services import reset


@pytest.fixture
def setup(monkeypatch, tmp_path):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr(reset, 'connect', Mock(return_value=conn))
    config = {'DATABASE_URL': 'test-only', 'USER_SERVICE_URL': 'http://user/',
              'WATCHED_CLEANUP_TOKEN': 'secret', 'MOVIE_MEDIA_DIR': str(tmp_path)}
    return conn, config


def test_guard_serializes_resets(setup, monkeypatch):
    conn, config = setup
    conn.execute.return_value.fetchone.return_value = {'acquired': False}
    clear = Mock(return_value={'ok': True})
    monkeypatch.setattr(reset, '_clear', clear)
    with pytest.raises(reset.CleanupPending, match='running'):
        reset.clear(config)
    clear.assert_not_called()
    conn.execute.return_value.fetchone.return_value = {'acquired': True}
    assert reset.clear(config) == {'ok': True}
    clear.assert_called_once_with(config)


def test_clear_posters_only_managed_files(tmp_path):
    managed = tmp_path / ('a' * 64 + '.jpg')
    managed.write_bytes(b'jpeg')
    other = tmp_path / 'keep.jpg'
    other.write_bytes(b'keep')
    reset.clear_posters(tmp_path)
    assert not managed.exists()
    assert other.read_bytes() == b'keep'
    reset.clear_posters(tmp_path / 'missing')


@pytest.mark.parametrize('key', ['USER_SERVICE_URL', 'WATCHED_CLEANUP_TOKEN'])
def test_missing_cleanup_configuration(setup, key):
    conn, config = setup
    config[key] = ''
    with pytest.raises(reset.CleanupPending, match='Configure'):
        reset._clear(config)
    conn.execute.assert_not_called()


@pytest.mark.parametrize('existing', [True, False])
def test_durable_job_and_cleanup(setup, monkeypatch, existing):
    conn, config = setup
    job = {'id': 'operation', 'movie_ids': ['movie'], 'deleted_count': 1}
    conn.execute.return_value.fetchone.side_effect = [job] if existing else [None, job]
    conn.execute.return_value.fetchall.return_value = [{'id': 'movie'}]
    fetch = Mock(return_value=io.BytesIO(json.dumps({'operation_id': 'operation', 'deleted_rows': 3}).encode()))
    monkeypatch.setattr(reset, 'urlopen', fetch)
    assert reset._clear(config) == {'cleared_tables': ['movies'], 'deleted_rows': {'movies': 1},
                                     'watched_deleted_rows': 3, 'operation_id': 'operation'}
    req = fetch.call_args.args[0]
    assert req.full_url == 'http://user/internal/clear-watched'
    assert req.get_header('Authorization') == 'Bearer secret'
    assert json.loads(req.data) == {'operation_id': 'operation', 'movie_ids': ['movie']}
    assert any('DELETE FROM movies' in c.args[0] for c in conn.execute.call_args_list) is not existing
    assert conn.execute.call_args.args[1] == ('operation',)


@pytest.mark.parametrize('body', [{'operation_id': 'wrong', 'deleted_rows': 1},
                                 {'operation_id': 'operation', 'deleted_rows': True}, None])
def test_failed_remote_cleanup_stays_pending(setup, monkeypatch, body):
    conn, config = setup
    conn.execute.return_value.fetchone.return_value = {'id': 'operation', 'movie_ids': [], 'deleted_count': 0}
    fetch = Mock(side_effect=URLError('offline')) if body is None else Mock(return_value=io.BytesIO(json.dumps(body).encode()))
    monkeypatch.setattr(reset, 'urlopen', fetch)
    with pytest.raises(reset.CleanupPending, match='watched cleanup pending'):
        reset._clear(config)
    assert not any('UPDATE' in c.args[0] for c in conn.execute.call_args_list)


def test_poster_failure_stays_pending(setup, monkeypatch):
    conn, config = setup
    conn.execute.return_value.fetchone.return_value = {'id': 'operation', 'movie_ids': [], 'deleted_count': 0}
    monkeypatch.setattr(reset, 'urlopen', lambda *a, **kw: io.BytesIO(b'{"operation_id":"operation","deleted_rows":0}'))
    monkeypatch.setattr(reset, 'clear_posters', Mock(side_effect=OSError('denied')))
    with pytest.raises(reset.CleanupPending, match='poster cleanup pending'):
        reset._clear(config)
    assert not any('UPDATE' in c.args[0] for c in conn.execute.call_args_list)
