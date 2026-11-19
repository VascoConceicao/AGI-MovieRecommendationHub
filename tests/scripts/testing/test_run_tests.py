import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from coverage_report import summarize
import run_tests


def test_entrypoint_runs_all_components(tmp_path, monkeypatch):
    import runpy
    monkeypatch.setattr(run_tests.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1))
    # Redirect paths resolved by the script so no real reports are overwritten.
    original = Path.resolve
    monkeypatch.setattr(Path, 'resolve', lambda self: tmp_path / 'scripts/testing/run_tests.py' if self.name == 'run_tests.py' else original(self))
    with pytest.raises(SystemExit) as error:
        runpy.run_path(run_tests.__file__, run_name='__main__')
    assert error.value.code == 1
    assert (tmp_path / 'coverage/summary.json').exists()


@pytest.mark.parametrize('failure', [None, 'movie', 'missing', 'malformed'])
def test_all_suites_run_and_any_failure_makes_project_fail(tmp_path, monkeypatch, capsys, failure):
    monkeypatch.setattr(run_tests, 'ROOT', tmp_path)
    called = []
    def run(command, **kwargs):
        component = Path(command[1]).parents[2]
        if Path(command[1]).name == 'test-common.sh':
            name = 'common'
            component = tmp_path / 'app/backend/common'
        else:
            name = 'scripts' if Path(command[1]).name == 'test-scripts.sh' else component.name.removesuffix('-service')
        called.append(name)
        folder = component / 'coverage/scripts' if name == 'scripts' else component / 'coverage'
        folder.mkdir(parents=True)
        if failure == 'missing' and name == 'movie':
            return SimpleNamespace(returncode=1)
        if failure == 'malformed' and name == 'movie':
            (folder / 'summary.json').write_text('{broken')
            return SimpleNamespace(returncode=1)
        summary = summarize(name, [dict(file='file.py', lines=dict(covered=1, total=2),
                                       branches=dict(covered=1, total=2))],
                            dict(passed=1, failed=0, skipped=0), 'PASS')
        (folder / 'summary.json').write_text(json.dumps(summary))
        return SimpleNamespace(returncode=1 if failure == name else 0)
    monkeypatch.setattr(run_tests.subprocess, 'run', run)
    assert run_tests.main() == (1 if failure else 0)
    assert called == ['scripts', 'common', 'movie', 'recommendation', 'user', 'frontend']
    report = json.loads((tmp_path / 'coverage/summary.json').read_text())
    assert report['total']['status'] == ('FAIL' if failure else 'PASS')
    output = capsys.readouterr().out
    assert 'file.py' not in output
    assert ('Incomplete' in output) == (failure in ('missing', 'malformed'))
