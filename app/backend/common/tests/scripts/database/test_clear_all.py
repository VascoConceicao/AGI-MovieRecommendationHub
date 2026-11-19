import importlib.util
import io
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

PATH = Path(__file__).resolve().parents[3] / 'scripts/database/clear-all.py'
spec = importlib.util.spec_from_file_location('clear_all', PATH)
reset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)


@pytest.mark.parametrize('result,message', [
    (SimpleNamespace(returncode=1, stdout=''), 'could not load'),
    (SimpleNamespace(returncode=0, stdout='invalid'), 'could not read'),
    (SimpleNamespace(returncode=0, stdout='{"AUTH_RESET_TOKEN":"token","AUTH_RESET_ENABLED":"false"}'), 'configure'),
    (SimpleNamespace(returncode=0, stdout='{"AUTH_RESET_TOKEN":"","AUTH_RESET_ENABLED":"true"}'), 'configure'),
])
def test_configuration_failure(monkeypatch, result, message):
    monkeypatch.setattr(reset.subprocess, 'run', Mock(return_value=result))
    with pytest.raises(ValueError, match=message):
        reset.configuration('user', 'AUTH_RESET')


def test_configuration_isolates_environment(monkeypatch):
    monkeypatch.setenv('AUTH_RESET_TOKEN', 'must-not-inherit')
    monkeypatch.setenv('AUTH_RESET_ENABLED', 'true')
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout='{"AUTH_RESET_TOKEN":"test-token","AUTH_RESET_ENABLED":"TRUE"}'))
    monkeypatch.setattr(reset.subprocess, 'run', run)
    assert reset.configuration('user', 'AUTH_RESET') == 'test-token'
    assert 'AUTH_RESET_TOKEN' not in run.call_args.kwargs['env']
    assert 'AUTH_RESET_ENABLED' not in run.call_args.kwargs['env']
    assert run.call_args.args[0][4].endswith('/user-service/.env')


@pytest.mark.parametrize('selected,services', [('all', ['recommendation', 'movie', 'user']), ('movie', ['movie'])])
def test_reset_order_and_scope(monkeypatch, selected, services):
    config = Mock(return_value='test-token')
    monkeypatch.setattr(reset, 'configuration', config)
    requests = []

    def fetch(request, **kwargs):
        assert config.call_count == len(services)
        assert request.get_method() == 'POST'
        assert request.get_header('Authorization') == 'Bearer test-token'
        assert json.loads(request.data) == {'table': 'all'}
        requests.append(request.full_url)
        return io.BytesIO(b'{}')

    monkeypatch.setattr(reset, 'urlopen', fetch)
    assert reset.main([selected]) == 0
    assert [url.split('/admin/reset-')[1].removesuffix('-db') for url in requests] == services


@pytest.mark.parametrize('error', [HTTPError('http://test', 503, 'offline', {}, None), URLError('offline'), ValueError('invalid')])
def test_reset_failure_stops_remaining_services(monkeypatch, capsys, error):
    monkeypatch.setattr(reset, 'configuration', Mock(return_value='test-token'))
    fetch = Mock(side_effect=error)
    monkeypatch.setattr(reset, 'urlopen', fetch)
    assert reset.main([]) == 1
    fetch.assert_called_once()
    assert 'earlier resets may have completed' in capsys.readouterr().err


def test_preflight_failure_never_resets(monkeypatch):
    monkeypatch.setattr(reset, 'configuration', Mock(side_effect=['token', ValueError('missing')]))
    fetch = Mock()
    monkeypatch.setattr(reset, 'urlopen', fetch)
    assert reset.main([]) == 1
    fetch.assert_not_called()


def test_entrypoint_help(monkeypatch):
    monkeypatch.setattr('sys.argv', ['clear-all', '--help'])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(PATH), run_name='__main__')
    assert error.value.code == 0
