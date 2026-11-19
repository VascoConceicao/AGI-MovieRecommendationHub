"""Clear existing application data through service-owned reset endpoints."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[5]
SERVICES = (
    ('recommendation', 4207, 'RECOMMENDATION_RESET'),
    ('movie', 4206, 'MOVIE_RESET'),
    ('user', 4208, 'AUTH_RESET'),
)


def configuration(service, prefix):
    keys = [prefix + '_TOKEN', prefix + '_ENABLED']
    # Load each service's shell-format .env in isolation. Never print its contents.
    result = subprocess.run(
        ['sh', '-c', 'set -a; if [ -f "$1" ]; then . "$1"; fi; exec "$2" -c "$3"',
         'load-reset-config', str(ROOT / f'app/backend/{service}-service/.env'),
         sys.executable, 'import os,json; print(json.dumps({k:os.environ.get(k, "") for k in '
         + repr(keys) + '}))'],
        env={key: value for key, value in os.environ.items() if key not in keys},
        capture_output=True, text=True,
    )
    if result.returncode:
        raise ValueError(f'{service}: could not load .env.')
    try:
        config = json.loads(result.stdout)
    except ValueError:
        raise ValueError(f'{service}: could not read reset configuration.') from None
    if config[keys[1]].lower() != 'true' or not config[keys[0]]:
        raise ValueError(f'{service}: configure {keys[0]} and {keys[1]}=true in its .env.')
    return config[keys[0]]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', nargs='?', default='all', choices=['all', 'movie', 'user', 'recommendation'])
    selected = parser.parse_args(argv).database
    services = [entry for entry in SERVICES if selected in ('all', entry[0])]
    try:
        # Check selected credentials before deleting any data.
        tokens = {service: configuration(service, prefix) for service, _, prefix in services}
        for service, port, _ in services:
            request = Request(
                f'http://127.0.0.1:{port}/admin/reset-{service}-db',
                data=json.dumps({'table': 'all'}).encode(),
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + tokens[service]},
                method='POST',
            )
            print(f'Clearing {service} database...', flush=True)
            try:
                with urlopen(request, timeout=60) as response:
                    json.load(response)
            except HTTPError as error:
                raise ValueError(f'{service}: reset failed (HTTP {error.code}). Stopped; earlier resets may have completed.') from None
            except (URLError, OSError, ValueError):
                raise ValueError(f'{service}: reset not confirmed. Stopped; earlier resets may have completed. Retry when services are available.') from None
            print(f'{service}: cleared.', flush=True)
        return 0
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
