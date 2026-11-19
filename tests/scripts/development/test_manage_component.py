import importlib.util
import io
import json
from pathlib import Path
import runpy
import signal
import subprocess
from unittest.mock import MagicMock, Mock

import pytest

PATH = Path(__file__).resolve().parents[3] / 'scripts/development/manage-component.py'
spec = importlib.util.spec_from_file_location('manage_component', PATH)
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


@pytest.fixture(autouse=True)
def boundaries(monkeypatch):
    for name in ['killpg', 'getpgid']:
        monkeypatch.setattr(manager.os, name, Mock())
    for name in ['run', 'check_output', 'Popen']:
        monkeypatch.setattr(manager.subprocess, name, Mock())
    monkeypatch.setattr(manager.time, 'sleep', Mock())
    monkeypatch.setattr(manager, 'urlopen', Mock())
    monkeypatch.setattr(manager.socket, 'create_connection', MagicMock())
    monkeypatch.setattr(manager.signal, 'signal', Mock())


def test_linux_identity(monkeypatch):
    monkeypatch.setattr(manager.Path, 'read_text', Mock(return_value='1 (name with ) brackets) ' + ' '.join(map(str, range(25)))))
    assert manager.identity(1) == '19'
    manager.subprocess.check_output.assert_not_called()


@pytest.mark.parametrize('output,expected', [(' date \n', 'date'), ('', None), (OSError(), None), (subprocess.CalledProcessError(1, 'ps'), None)])
def test_macos_identity_fallback(monkeypatch, output, expected):
    monkeypatch.setattr(manager.Path, 'read_text', Mock(side_effect=FileNotFoundError()))
    if isinstance(output, Exception):
        manager.subprocess.check_output.side_effect = output
    else:
        manager.subprocess.check_output.return_value = output
    assert manager.identity(42) == expected
    assert manager.subprocess.check_output.call_args.args[0] == ['ps', '-o', 'lstart=', '-p', '42']


@pytest.mark.parametrize('errors', [[ProcessLookupError()], [None, ProcessLookupError()], [None, PermissionError()],
    [None] * 52, [None] * 51 + [PermissionError()]])
def test_stop_group_handles_exit_and_escalation(errors):
    manager.os.killpg.side_effect = errors
    manager.stop(42)
    assert manager.os.killpg.call_args_list[0].args == (42, signal.SIGTERM)
    if len(errors) == 52:
        assert manager.os.killpg.call_args.args == (42, signal.SIGKILL)
        assert manager.time.sleep.call_count == 50


def test_stop_port_unavailable():
    manager.subprocess.check_output.side_effect = OSError()
    manager.stop_port(4206)
    manager.os.killpg.assert_not_called()


@pytest.mark.parametrize('exit_early', [True, False])
def test_stop_port_handles_invalid_pids_and_polling(exit_early):
    manager.subprocess.check_output.side_effect = ['invalid\n42\n43\n'] + ([OSError()] if exit_early else [b'42'] * 50)
    manager.os.getpgid.side_effect = [PermissionError(), 43]
    manager.stop_port(4206)
    manager.os.killpg.assert_called_once_with(43, signal.SIGTERM)
    assert manager.time.sleep.call_count == (0 if exit_early else 50)


def test_component_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, '__file__', str(tmp_path / 'scripts/development/manage-component.py'))
    for name, folder, port in [('frontend', 'app/frontend', 4204), ('proxy', 'app/proxy', 4205), ('movie', 'app/backend/movie-service', 4206)]:
        (tmp_path / folder).mkdir(parents=True)
        component, runtime, state, actual_port = manager.component_paths(name)
        assert component == tmp_path / folder
        assert runtime.is_dir()
        assert state == runtime / 'process.json'
        assert actual_port == port
    with pytest.raises(SystemExit, match='Unknown component'):
        manager.component_paths('unknown')


@pytest.mark.parametrize('start,current', [(None, 'same'), ('same', 'different'), ('same', 'same')])
def test_stop_component_does_not_kill_reused_pid(tmp_path, monkeypatch, start, current):
    state = tmp_path / 'process.json'
    state.write_text(json.dumps({'pid': 42, 'start': start}))
    monkeypatch.setattr(manager, 'identity', Mock(return_value=current))
    stop, stop_port = Mock(), Mock()
    monkeypatch.setattr(manager, 'stop', stop)
    monkeypatch.setattr(manager, 'stop_port', stop_port)
    manager.stop_component('movie', state, 4206)
    assert stop.call_count == (start is not None and start == current)
    assert not state.exists()
    manager.stop_component('movie', state, 4206)
    assert stop_port.call_count == 2


def test_ensure_rejects_frontend(tmp_path):
    with pytest.raises(SystemExit, match='backend'):
        manager.ensure_component('frontend', tmp_path, tmp_path, tmp_path / 'state', 4204)
    manager.subprocess.run.assert_not_called()


@pytest.mark.parametrize('running,saved', [(True, None), (True, 'same'), (False, 'same'), (False, 'different'), (False, None)])
def test_ensure_reuses_or_starts_service(tmp_path, monkeypatch, running, saved):
    state = tmp_path / 'state'
    if saved:
        state.write_text(json.dumps({'pid': 42, 'start': saved}))
    if not running:
        manager.socket.create_connection.side_effect = OSError()
    monkeypatch.setattr(manager, 'identity', Mock(return_value='same'))
    manager.subprocess.Popen.return_value.pid = 99
    manager.urlopen.return_value = io.BytesIO(b'{"service":"movie-service","status":"ok"}')
    assert manager.ensure_component('movie', tmp_path, tmp_path, state, 4206) == 0
    reused = running or saved == 'same'
    assert manager.subprocess.Popen.call_count == (not reused)
    if not reused:
        assert json.loads(state.read_text()) == {'pid': 99, 'start': 'same'}
    manager.os.killpg.assert_not_called()


@pytest.mark.parametrize('failure', ['exit', 'timeout'])
def test_ensure_reports_failure_without_restart(tmp_path, monkeypatch, failure):
    manager.socket.create_connection.side_effect = OSError()
    manager.subprocess.Popen.return_value.pid = 99
    manager.subprocess.Popen.return_value.poll.return_value = 1 if failure == 'exit' else None
    monkeypatch.setattr(manager, 'identity', Mock(return_value=None))
    monkeypatch.setattr(manager.time, 'monotonic', Mock(side_effect=[0, 1, 2, 61]))
    manager.urlopen.side_effect = [OSError(), io.BytesIO(b'{"service":"other","status":"ok"}')]
    with pytest.raises(SystemExit, match='startup failed' if failure == 'exit' else 'did not become ready'):
        manager.ensure_component('movie', tmp_path, tmp_path, tmp_path / 'state', 4206)
    manager.os.killpg.assert_not_called()


def test_running_unhealthy_service_times_out_without_restart(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    state.write_text(json.dumps({'pid': 42, 'start': None}))
    manager.socket.create_connection.side_effect = OSError()
    manager.subprocess.Popen.return_value.pid = 99
    monkeypatch.setattr(manager, 'identity', Mock(return_value=None))
    manager.subprocess.Popen.return_value.poll.return_value = None
    monkeypatch.setattr(manager.time, 'monotonic', Mock(side_effect=[0, 1, 61]))
    manager.urlopen.return_value = io.BytesIO(b'{"service":"movie-service","status":"bad"}')
    with pytest.raises(SystemExit, match='did not become ready'):
        manager.ensure_component('movie', tmp_path, tmp_path, state, 4206)


@pytest.mark.parametrize('argv', [['manager'], ['manager', 'wrong', 'movie']])
def test_main_usage(monkeypatch, argv):
    monkeypatch.setattr('sys.argv', argv)
    with pytest.raises(SystemExit, match='Usage'):
        manager.main()


@pytest.mark.parametrize('action', ['stop', 'ensure', 'run'])
@pytest.mark.parametrize('new_state', [False, True, None])
def test_main_lifecycle(tmp_path, monkeypatch, action, new_state):
    state = tmp_path / 'state'
    monkeypatch.setattr('sys.argv', ['manager', action, 'movie'])
    monkeypatch.setattr(manager, 'component_paths', Mock(return_value=(tmp_path, tmp_path, state, 4206)))
    monkeypatch.setattr(manager, 'stop_component', Mock())
    monkeypatch.setattr(manager, 'ensure_component', Mock(return_value=0))
    monkeypatch.setattr(manager, 'identity', Mock(return_value='start'))
    stop = Mock()
    monkeypatch.setattr(manager, 'stop', stop)
    child = manager.subprocess.Popen.return_value
    child.pid = 42

    def wait():
        if new_state:
            state.write_text('{"pid":99}')
        elif new_state is None:
            state.unlink()
        for call in manager.signal.signal.call_args_list:
            call.args[1](call.args[0], None)
        return 7

    child.wait.side_effect = wait
    assert manager.main() == (7 if action == 'run' else 0)
    if action == 'run':
        assert state.exists() == bool(new_state)
        assert stop.call_count == 2
    else:
        manager.subprocess.Popen.assert_not_called()


def test_entrypoint_invalid_usage(monkeypatch):
    monkeypatch.setattr('sys.argv', ['manager'])
    with pytest.raises(SystemExit, match='Usage'):
        runpy.run_path(str(PATH), run_name='__main__')
