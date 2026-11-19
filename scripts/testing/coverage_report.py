"""Normalize Python/Istanbul coverage and print readable tables."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def ratio(covered, total):
    return f'{100 * covered / total:.1f}%' if total else '—'


def table(headers, rows):
    rows = [[str(value) for value in row] for row in rows]
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    border = '+' + '+'.join('-' * (width + 2) for width in widths) + '+'
    def row(values):
        return '| ' + ' | '.join(value.ljust(width) for value, width in zip(values, widths)) + ' |'
    return '\n'.join([border, row(headers), border, *(row(values) for values in rows), border])


def test_counts(path):
    counts = {'passed': 0, 'failed': 0, 'skipped': 0}
    if not path.exists():
        return counts
    for case in ET.parse(path).getroot().iter('testcase'):
        if case.find('failure') is not None or case.find('error') is not None:
            counts['failed'] += 1
        elif case.find('skipped') is not None:
            counts['skipped'] += 1
        else:
            counts['passed'] += 1
    return counts


def read_python(path):
    raw = json.loads(path.read_text())
    return [dict(file=name, lines={'covered': item['summary']['covered_lines'],
                                 'total': item['summary']['num_statements']},
                 branches={'covered': item['summary'].get('covered_branches', 0),
                           'total': item['summary'].get('num_branches', 0)},
                 missing=item['missing_lines']) for name, item in sorted(raw['files'].items())]


def read_frontend(path, root):
    raw = json.loads(path.read_text())
    return [dict(file=str(Path(name).relative_to(root)),
                 lines={key: value['lines'][key] for key in ('covered', 'total')},
                 branches={key: value['branches'][key] for key in ('covered', 'total')},
                 missing=[]) for name, value in sorted(raw.items()) if name != 'total']


def summarize(name, files, tests, status):
    return {'component': name, 'status': status, 'tests': tests, 'files': files,
            **{metric: {key: sum(item[metric][key] for item in files)
                        for key in ('covered', 'total')} for metric in ('lines', 'branches')}}


def per_file(summary):
    rows = [[item['file'], f"{item['lines']['covered']}/{item['lines']['total']}",
             ratio(**item['lines']), f"{item['branches']['covered']}/{item['branches']['total']}",
             ratio(**item['branches'])] for item in summary['files']]
    rows.append(['TOTAL', f"{summary['lines']['covered']}/{summary['lines']['total']}",
                 ratio(**summary['lines']), f"{summary['branches']['covered']}/{summary['branches']['total']}",
                 ratio(**summary['branches'])])
    return table(['File', 'Lines', 'Line %', 'Branches', 'Branch %'], rows)


def totals(summaries):
    rows = [[s['component'], s['status'], s['tests']['passed'], s['tests']['failed'],
             s['tests']['skipped'], ratio(**s['lines']) if s['files'] else 'N/A',
             ratio(**s['branches']) if s['files'] else 'N/A'] for s in summaries]
    total = summarize('ALL', [f for s in summaries for f in s['files']],
                      {key: sum(s['tests'][key] for s in summaries)
                       for key in ('passed', 'failed', 'skipped')},
                      'PASS' if all(s['status'] == 'PASS' for s in summaries) else 'FAIL')
    complete = all(s['files'] for s in summaries)
    rows.append(['ALL', total['status'], total['tests']['passed'], total['tests']['failed'],
                 total['tests']['skipped'], ratio(**total['lines']) if complete else 'Incomplete',
                 ratio(**total['branches']) if complete else 'Incomplete'])
    return table(['Component', 'Status', 'Passed', 'Failed', 'Skipped', 'Lines', 'Branches'], rows), total
