import importlib.util
import json
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / 'scripts/testing'
sys.path.insert(0, str(SCRIPTS))
from coverage_report import read_frontend, read_python, ratio, summarize, test_counts as counts, totals


def test_total_coverage_is_weighted_by_lines_not_suite_percentages():
    a = summarize('a', [dict(file='a.py', lines={'covered': 1, 'total': 1},
                            branches={'covered': 1, 'total': 2})],
                  dict(passed=1, failed=0, skipped=0), 'PASS')
    b = summarize('b', [dict(file='b.py', lines={'covered': 1, 'total': 9},
                            branches={'covered': 1, 'total': 2})],
                  dict(passed=2, failed=0, skipped=1), 'PASS')
    formatted, combined = totals([a, b])
    assert combined['lines'] == {'covered': 2, 'total': 10}
    assert combined['tests'] == {'passed': 3, 'failed': 0, 'skipped': 1}
    assert '20.0%' in formatted
    assert '50.0%' in formatted
    assert ratio(0, 0) == '—'


def test_missing_report_is_incomplete_and_failed():
    formatted, combined = totals([summarize('missing', [], dict(passed=0, failed=0, skipped=0), 'FAIL')])
    assert combined['status'] == 'FAIL'
    assert 'Incomplete' in formatted
    assert 'N/A' in formatted


def test_junit_counts_failures_errors_and_skips(tmp_path):
    report = tmp_path / 'tests.xml'
    assert counts(report) == dict(passed=0, failed=0, skipped=0)
    report.write_text('<testsuites><testsuite><testcase/><testcase><failure/></testcase>'
                      '<testcase><error/></testcase><testcase><skipped/></testcase></testsuite></testsuites>')
    assert counts(report) == dict(passed=1, failed=2, skipped=1)


def test_python_report_preserves_missing_lines(tmp_path):
    report = tmp_path / 'coverage.json'
    report.write_text(json.dumps({'files': {'sample.py': {
        'summary': {'covered_lines': 1, 'num_statements': 2, 'covered_branches': 0, 'num_branches': 2},
        'missing_lines': [8]}}}))
    files = read_python(report)
    assert files[0]['missing'] == [8]
    assert files[0]['lines'] == {'covered': 1, 'total': 2}


def test_frontend_report_ignores_aggregate_row(tmp_path):
    report = tmp_path / 'coverage-summary.json'
    data = {'lines': {'covered': 2, 'total': 3}, 'branches': {'covered': 1, 'total': 2}}
    report.write_text(json.dumps({'total': data, str(tmp_path / 'app.ts'): data}))
    files = read_frontend(report, tmp_path)
    assert len(files) == 1
    assert files[0]['file'] == 'app.ts'
