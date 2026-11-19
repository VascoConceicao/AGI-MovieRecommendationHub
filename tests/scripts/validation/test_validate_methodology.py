import importlib.util
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

PATH = Path(__file__).resolve().parents[3] / 'scripts/validation/validate_methodology.py'
spec = importlib.util.spec_from_file_location('validate_methodology', PATH)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def write(root, name, text=''):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def valid(tmp_path, monkeypatch):
    for name in validator.REQUIRED_FILES:
        write(tmp_path, name)
    for name, headings in validator.REQUIRED_HEADINGS.items():
        write(tmp_path, name, '\n'.join(headings))
    write(tmp_path, 'README.md', '# Project\n## Documentation\n')
    write(tmp_path, 'docs/template/phases/phase.md', '# Phase: `<Title>`\n## Recommended Model\n### Codex\n- Model: model\n- Effort: high\n### Claude Code\n- Model: model\n- Effort: high\n## Work Completed\n## Validation\n')
    for skill in validator.SKILLS:
        write(tmp_path, f'agents/plugins/forge/skills/{skill}/SKILL.md', f'name: {skill}\ndescription: Test')
        write(tmp_path, f'agents/plugins/forge/skills/{skill}/agents/openai.yaml')
    for name in validator.REQUIRED_FILES:
        if name.endswith('.sh'):
            write(tmp_path, name, '#!/bin/sh\nset -eu\n').chmod(0o755)
    write(tmp_path, '.gitignore')
    write(tmp_path, '.vscode/tasks.json', json.dumps({'version': '2.0.0', 'tasks': []}))
    for provider, catalog in [('codex', '.agents/plugins/marketplace.json'), ('claude', '.claude-plugin/marketplace.json')]:
        write(tmp_path, f'agents/plugins/forge/.{provider}-plugin/plugin.json', json.dumps({'name': 'forge', 'version': '1', 'skills': './skills/'}))
        source = {'source': 'local', 'path': './agents/plugins/forge'} if provider == 'codex' else './agents/plugins/forge'
        write(tmp_path, catalog, json.dumps({'name': 'test', 'plugins': [{'name': 'forge', 'source': source}, {'name': 'other'}]}))
    monkeypatch.setattr(validator.subprocess, 'run', Mock(return_value=SimpleNamespace(returncode=0, stdout='{"entries":[]}', stderr='')))
    return tmp_path


def test_valid_package(valid):
    assert all(not errors for _, errors in validator.validate(valid))


def test_missing_package(tmp_path):
    results = dict(validator.validate(tmp_path))
    assert all(results.values())
    assert 'missing required directory: docs' in results['Documentation and task structure']


@pytest.mark.parametrize('heading', ['', '# ', 'Project'])
def test_bad_readme_and_missing_headings(valid, heading):
    write(valid, 'README.md', heading)
    errors = []
    validator.check_headings(valid, errors)
    assert any('missing required section' in error for error in errors)
    assert any('level-one' in error for error in errors)


@pytest.mark.parametrize('text,expected', [('', 0), ('## Recommended Model\n- Model: x', 1),
    ('## Recommended Model\n- Cost profile: expensive', 2),
    ('## Recommended Model\n- Model: x\n- Effort: high\n## Other\n- Rationale: ignored', 0)])
def test_compact_recommendations(tmp_path, text, expected):
    path = write(tmp_path, 'phase.md', text)
    errors = []
    validator.check_recommendation_block(path, tmp_path, errors)
    assert len(errors) == expected
    validator.check_recommendation_block(path, tmp_path, errors, require_both_providers=True)
    if '## Recommended Model' in text:
        assert any('both' in e or 'Codex and Claude' in e for e in errors)


def test_documentation_layout(valid):
    write(valid, 'docs/unexpected.md')
    write(valid, 'docs/template/unexpected.md')
    write(valid, 'docs/template/phases/unexpected.md')
    errors = []
    validator.check_docs(valid, errors)
    assert len(errors) == 3


def test_missing_tasks_and_optional_template(tmp_path):
    (tmp_path / 'docs').mkdir()
    errors = []
    validator.check_docs(tmp_path, errors)
    assert errors == ['missing required directory: docs/tasks']
    (tmp_path / 'docs/tasks').mkdir()
    errors.clear()
    validator.check_docs(tmp_path, errors)
    assert errors == []
    (tmp_path / 'docs/template').mkdir()
    validator.check_docs(tmp_path, errors)
    assert errors == []


@pytest.mark.parametrize('result,message', [
    (SimpleNamespace(returncode=1, stdout='bad\nentry', stderr=''), 'bad entry'),
    (SimpleNamespace(returncode=1, stdout='', stderr=''), 'no diagnostic'),
    (SimpleNamespace(returncode=0, stdout='bad', stderr=''), 'invalid entries'),
    (SimpleNamespace(returncode=0, stdout='{}', stderr=''), 'invalid entries'),
    (SimpleNamespace(returncode=0, stdout='{"entries":[{"path":1}]}', stderr=''), 'invalid task path'),
])
def test_task_helper_errors(valid, monkeypatch, result, message):
    monkeypatch.setattr(validator.subprocess, 'run', Mock(return_value=result))
    errors = []
    validator.check_docs(valid, errors)
    assert any(message in e for e in errors)


def test_task_phases(valid, monkeypatch):
    monkeypatch.setattr(validator.subprocess, 'run', Mock(return_value=SimpleNamespace(returncode=0, stdout='{"entries":[{"path":"task"}]}')))
    errors = []
    validator.check_docs(valid, errors)
    assert any('missing required path' in e for e in errors)
    write(valid, 'docs/tasks/task/phases/01-valid.md', '## Recommended Model\n- Model: x\n- Effort: high')
    write(valid, 'docs/tasks/task/phases/bad.md')
    (valid / 'docs/tasks/task/phases/02-directory.md').mkdir()
    errors.clear()
    validator.check_docs(valid, errors)
    assert len(errors) == 2
    assert all('invalid task phase' in e for e in errors)


def test_skills_missing_metadata_symlinks_and_loose_copies(valid):
    write(valid, 'agents/plugins/forge/skills/custom/SKILL.md', 'wrong metadata')
    (valid / 'agents/plugins/forge/alias').symlink_to('skills')
    write(valid, '.agents/skills/custom')
    (valid / '.claude/skills').mkdir(parents=True)
    (valid / '.claude/skills/custom').symlink_to('missing')
    errors = []
    validator.check_skills(valid, errors, (*validator.SKILLS, 'missing'))
    assert any('missing required skill' in e for e in errors)
    assert any('invalid skill metadata' in e for e in errors)
    assert any('must not be a symlink' in e for e in errors)
    assert sum('duplicate loose skill' in e for e in errors) == 2


@pytest.mark.parametrize('file,value,message', [
    ('agents/plugins/forge/.codex-plugin/plugin.json', {'name': 'bad', 'version': 1}, 'invalid Forge manifest'),
    ('.agents/plugins/marketplace.json', {'name': 'bad name', 'plugins': []}, 'invalid catalog identity'),
    ('.claude-plugin/marketplace.json', {}, 'invalid claude plugin package'),
])
def test_invalid_plugin_manifests(valid, file, value, message):
    write(valid, file, json.dumps(value))
    errors = []
    validator.check_skills(valid, errors, validator.SKILLS)
    assert any(message in e for e in errors)


@pytest.mark.parametrize('tasks', ['invalid', '[]', '{"version":"wrong","tasks":[]}'])
def test_invalid_configuration(valid, tasks):
    write(valid, 'gitignore.template')
    write(valid, '.vscode/tasks.json', tasks)
    script = write(valid, 'agents/plugins/forge/skills/create-task/scripts/task-helper.sh', '#!/bin/bash\n')
    script.chmod(0o644)
    errors = []
    validator.check_configuration(valid, errors)
    assert len(errors) == 4
    assert any('exactly one' in e for e in errors)
    assert any('POSIX' in e for e in errors)
    assert any('executable' in e for e in errors)


def test_cli_success_failure_and_invalid_skill(valid, monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['validator', '--root', str(valid)])
    assert validator.main() == 0
    assert 'passed' in capsys.readouterr().out
    (valid / 'AGENTS.md').unlink()
    assert validator.main() == 1
    assert 'missing required file' in capsys.readouterr().err
    monkeypatch.setattr('sys.argv', ['validator', '--extra-skill', 'Bad Skill'])
    with pytest.raises(SystemExit) as error:
        validator.main()
    assert error.value.code == 2


def test_cli_entrypoint(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['validator', '--help'])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(PATH), run_name='__main__')
    assert error.value.code == 0
    assert '--extra-skill' in capsys.readouterr().out
