import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_component


@pytest.mark.parametrize('name', ['user', 'frontend'])
def test_component_reads_fresh_coverage_and_removes_app_credentials(tmp_path, monkeypatch, name):
    monkeypatch.setattr(test_component, 'ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['test_component.py', name])
    monkeypatch.setenv('DATABASE_URL', 'must-not-reach-tests')
    component = tmp_path / ('app/frontend' if name == 'frontend' else 'app/backend/user-service')
    component.mkdir(parents=True)
    def run(command, **kwargs):
        assert 'DATABASE_URL' not in kwargs['env']
        output = component / 'coverage'
        (output / 'tests.xml').write_text('<testsuites><testsuite><testcase/></testsuite></testsuites>')
        if name == 'frontend':
            data = {'lines': dict(covered=1, total=2), 'branches': dict(covered=0, total=2)}
            folder = output / 'frontend'
            folder.mkdir()
            (folder / 'coverage-summary.json').write_text(json.dumps({str(component / 'app.ts'): data, 'total': data}))
        else:
            (output / 'coverage.json').write_text(json.dumps({'files': {'main.py': {
                'summary': dict(covered_lines=1, num_statements=2, covered_branches=0, num_branches=2),
                'missing_lines': [3]}}}))
        return SimpleNamespace(returncode=0, stdout='test output')
    monkeypatch.setattr(test_component.subprocess, 'run', run)
    assert test_component.main() == 0
    summary = json.loads((component / 'coverage/summary.json').read_text())
    assert summary['lines'] == dict(covered=1, total=2)
    assert summary['tests']['passed'] == 1


def test_failed_startup_does_not_reuse_old_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(test_component, 'ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['test_component.py', 'frontend', '--summary-only'])
    output = tmp_path / 'app/frontend/coverage/frontend'
    output.mkdir(parents=True)
    (output / 'coverage-summary.json').write_text('{"total": {}}')
    def fail(*args, **kwargs):
        raise FileNotFoundError('missing runner')
    monkeypatch.setattr(test_component.subprocess, 'run', fail)
    assert test_component.main() == 1
    summary = json.loads((output.parent / 'summary.json').read_text())
    assert summary['status'] == 'FAIL'
    assert summary['files'] == []
    assert 'Incomplete' in capsys.readouterr().out


def test_missing_reports_print_failure_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(test_component, 'ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['test_component.py', 'common'])
    monkeypatch.setattr(test_component.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1, stdout='runner failed'))
    assert test_component.main() == 1
    assert 'runner failed' in capsys.readouterr().out


def test_entrypoint_help(monkeypatch, capsys):
    import runpy
    monkeypatch.setattr('sys.argv', ['test_component.py', '--help'])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(test_component.__file__, run_name='__main__')
    assert error.value.code == 0
    assert '--summary-only' in capsys.readouterr().out
