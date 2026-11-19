"""Run one component suite; never load application .env or reset databases."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from coverage_report import per_file, read_frontend, read_python, summarize, test_counts, totals

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', choices=['scripts', 'common', 'movie', 'recommendation', 'user', 'frontend'])
    parser.add_argument('--summary-only', action='store_true')
    args = parser.parse_args()
    frontend = args.component == 'frontend'
    component = (ROOT if args.component == 'scripts' else ROOT / 'app/frontend' if frontend else ROOT / 'app/backend' /
                 ('common' if args.component == 'common' else args.component + '-service'))
    output = component / 'coverage' / 'scripts' if args.component == 'scripts' else component / 'coverage'
    output.mkdir(parents=True, exist_ok=True)
    # Remove prior reports so failed startup cannot be mistaken for current coverage.
    for filename in ('summary.json', 'coverage.json', 'coverage-summary.json', 'tests.xml'):
        for previous in output.rglob(filename):
            previous.unlink()
    env = dict(os.environ)
    env.pop('DATABASE_URL', None)
    env.pop('AUTH_RESET_TOKEN', None)
    if frontend:
        command = ['sh', str(component / 'scripts/with-node.sh'),
                   'npm', 'exec', '--', 'ng', 'test', '--watch=false', '--coverage', '--progress=false']
    else:
        python = (ROOT / 'app/backend/common/.venv/bin/python' if args.component == 'scripts'
                  else component / '.venv/bin/python')
        report_dir = str(output.relative_to(component))
        command = [str(python), '-m', 'pytest', '-q', '--cov', '--cov-branch',
                   f'--cov-report=json:{report_dir}/coverage.json', f'--cov-report=html:{report_dir}/html',
                   f'--junitxml={report_dir}/tests.xml']
    log = output / 'test-output.log'
    try:
        result = subprocess.run(command, cwd=component, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log.write_text(result.stdout)
        code = result.returncode
    except OSError as error:
        log.write_text(f'Cannot start test runner: {error}\nInstall component test dependencies.\n')
        code = 1
    # Angular writes reports under coverage/<project> in some CLI versions.
    coverage_path = output / ('coverage-summary.json' if frontend else 'coverage.json')
    if frontend and not coverage_path.exists():
        candidates = list(output.glob('*/coverage-summary.json'))
        if len(candidates) == 1:
            coverage_path = candidates[0]
    try:
        files = read_frontend(coverage_path, component) if frontend else read_python(coverage_path)
        tests = test_counts(output / 'tests.xml')
    except (OSError, ValueError, KeyError) as error:
        with log.open('a') as stream:
            stream.write(f'Coverage/report unavailable: {error}\n')
        files, tests, code = [], {'passed': 0, 'failed': 0, 'skipped': 0}, code or 1
    status = 'PASS' if code == 0 and sum(tests.values()) and files else 'FAIL'
    summary = summarize(args.component, files, tests, status)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    if args.summary_only:
        print(totals([summary])[0])
    elif files:
        print(per_file(summary))
        print(f"Tests: {tests['passed']} passed, {tests['failed']} failed, {tests['skipped']} skipped. {status}")
    if status != 'PASS':
        if not args.summary_only:
            print(log.read_text())
        print(f'Failure details: {log}')
    return 0 if status == 'PASS' else code or 1


if __name__ == '__main__':
    sys.exit(main())
