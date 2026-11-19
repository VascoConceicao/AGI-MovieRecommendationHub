"""Run all component scripts; display only test/coverage totals."""
import json
from pathlib import Path
import subprocess
import sys

from coverage_report import summarize, totals

ROOT = Path(__file__).resolve().parents[2]


def main():
    summaries = []
    for name in ('scripts', 'common', 'movie', 'recommendation', 'user', 'frontend'):
        component = ROOT if name == 'scripts' else ROOT / ('app/frontend' if name == 'frontend' else
                            'app/backend/' + ('common' if name == 'common' else name + '-service'))
        script = component / 'scripts/testing' / ('test-scripts.sh' if name == 'scripts' else 'run-tests.sh')
        if name == 'common':
            script = ROOT / 'scripts/testing/test-common.sh'
        output = component / 'coverage/scripts' if name == 'scripts' else component / 'coverage'
        report = output / 'summary.json'
        report.unlink(missing_ok=True)
        print(f'Running {name} tests...', flush=True)
        result = subprocess.run(['sh', str(script), '--summary-only'], cwd=ROOT,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if report.exists():
            try:
                summary = json.loads(report.read_text())
                if result.returncode:
                    summary['status'] = 'FAIL'
            except (ValueError, KeyError):
                summary = summarize(name, [], {'passed': 0, 'failed': 0, 'skipped': 0}, 'FAIL')
        else:
            summary = summarize(name, [], {'passed': 0, 'failed': 0, 'skipped': 0}, 'FAIL')
        summaries.append(summary)
        if summary['status'] != 'PASS':
            print(f"{name} failed. Details: {output / 'test-output.log'}", flush=True)
    formatted, combined = totals(summaries)
    print(formatted)
    output = ROOT / 'coverage'
    output.mkdir(exist_ok=True)
    (output / 'summary.json').write_text(json.dumps({'components': summaries, 'total': combined}, indent=2) + '\n')
    return 0 if combined['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
