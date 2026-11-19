#!/usr/bin/env python3
"""Apply the project's branch protections and post-merge CI policy."""
import fnmatch
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

API = 'https://gitlab.rnl.tecnico.ulisboa.pt/api/v4'
PROJECT = 'psia/groups26/g15'
POLICY = {'development': 30, 'master': 40}


def read_token():
    env = Path(__file__).resolve().parents[1] / '.env'
    values = []
    for line in env.read_text().splitlines():
        key, separator, value = line.strip().partition('=')
        if separator and key.strip() == 'GITLAB_API_TOKEN':
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values.append(value)
    if len(values) != 1 or not values[0]:
        sys.exit('Set GITLAB_API_TOKEN in infra/ci-cd/.env first.')
    return values[0]


def main():
    token = read_token()

    def api(method, path, data=None, missing_ok=False):
        request = Request(API + path, method=method,
                          data=json.dumps(data).encode() if data is not None else None,
                          headers={'PRIVATE-TOKEN': token, 'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else None
        except HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            # Never log credentials or request headers.
            sys.exit(f'GitLab {method} {path} failed: HTTP {error.code}')

    project = api('GET', '/projects/' + quote(PROJECT, safe=''))
    permissions = project.get('permissions', {})
    role = max((item or {}).get('access_level', 0) for item in permissions.values())
    if role < 40:
        sys.exit('The API token needs Maintainer or Owner access to this project.')
    base = f"/projects/{project['id']}"
    rules = api('GET', base + '/protected_branches?per_page=100')
    # A broader permissive rule can override a stricter exact branch rule.
    for rule in rules:
        for branch, level in POLICY.items():
            if rule['name'] == branch or not fnmatch.fnmatchcase(branch, rule['name']):
                continue
            push = rule['push_access_levels']
            merge = rule['merge_access_levels']
            if (rule['allow_force_push'] or any(x['access_level'] != 0 for x in push)
                    or any(x['access_level'] not in (0, level, 40, 50) for x in merge)):
                sys.exit(f"Conflicting rule {rule['name']} matches {branch}; review it first.")

    def access_update(entries, level):
        roles = [e for e in entries if not any(e.get(k) for k in
                 ('user_id', 'group_id', 'deploy_key_id', 'member_role_id'))]
        keep = roles[0]['id'] if roles else None
        result = [{'id': e['id'], '_destroy': True} for e in entries if e['id'] != keep]
        result.append({'id': keep, 'access_level': level} if keep else {'access_level': level})
        return result

    for branch, level in POLICY.items():
        path = base + '/protected_branches/' + quote(branch, safe='')
        current = api('GET', path, missing_ok=True)
        if current is None:
            api('POST', base + '/protected_branches', {
                'name': branch, 'push_access_level': 0,
                'merge_access_level': level, 'allow_force_push': False,
            })
        else:
            api('PATCH', path, {
                'allow_force_push': False,
                'allowed_to_push': access_update(current['push_access_levels'], 0),
                'allowed_to_merge': access_update(current['merge_access_levels'], level),
            })
        actual = api('GET', path)
        for key, expected in [('push_access_levels', 0), ('merge_access_levels', level)]:
            entries = actual[key]
            if len(entries) != 1 or entries[0]['access_level'] != expected:
                sys.exit(f'{branch}: {key} does not match the requested policy.')
        if actual['allow_force_push']:
            sys.exit(f'{branch}: force push is still enabled.')
        print(f'{branch}: protected; direct/force pushes off; merge access {level}')

    api('PUT', base, {'only_allow_merge_if_pipeline_succeeds': False,
                     'allow_merge_on_skipped_pipeline': False})
    actual = api('GET', base)
    if (actual['only_allow_merge_if_pipeline_succeeds']
            or actual['allow_merge_on_skipped_pipeline']):
        sys.exit('Post-merge pipeline setting did not apply.')
    print('Merge pipeline gate disabled; tests run after changes reach development/master.')


if __name__ == '__main__':
    main()
