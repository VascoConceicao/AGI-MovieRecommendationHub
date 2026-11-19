#!/usr/bin/env python3
"""Inspect Flask routes, refresh Swagger UI, and validate selected service docs."""
import argparse
import html
import json
from pathlib import Path
import subprocess
import sys

SERVICES = ('movie', 'recommendation', 'user')
METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}


def route_inventory(service):
    python = service / '.venv/bin/python'
    if not python.exists():
        python = service / '.venv/Scripts/python.exe'
    if not python.exists():
        raise ValueError(f'Install the service virtual environment first: {service.name}')
    code = """
import json
from main import create_app
app = create_app()
routes = {}
for rule in app.url_map.iter_rules():
    if rule.endpoint == 'static' or rule.endpoint.endswith('.static'):
        continue
    path = rule.rule
    # Convert Flask converters to OpenAPI parameter syntax.
    import re
    path = re.sub(r'<(?:[^:>]+:)?([^>]+)>', r'{\\1}', path)
    routes.setdefault(path, []).extend(sorted(m.lower() for m in rule.methods - {'HEAD', 'OPTIONS'}))
print(json.dumps({p: sorted(set(m)) for p, m in sorted(routes.items())}))
"""
    result = subprocess.run([str(python), '-c', code], cwd=service,
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def validate_document(service, inventory):
    from openapi_spec_validator import validate_spec
    doc = json.loads((service / 'static/swagger.json').read_text())
    if doc.get('openapi') != '3.0.3':
        raise ValueError('Expected OpenAPI 3.0.3')
    validate_spec(doc)
    actual = {(path, method) for path, methods in inventory.items() for method in methods}
    documented = {(path, method) for path, operation in doc['paths'].items()
                  for method in operation if method in METHODS}
    if documented != actual:
        raise ValueError(f'Missing: {sorted(actual - documented)}; stale: {sorted(documented - actual)}')
    print(f'{service.name}: OpenAPI valid; {len(actual)} operations match Flask.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inventory', 'ui', 'validate'])
    parser.add_argument('root', type=Path)
    parser.add_argument('--services', nargs='+', choices=['all', *SERVICES], default=['all'])
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / 'docs/bootstrap.md').is_file():
        parser.error('ROOT must be the project repository, not an installed skill cache.')
    names = SERVICES if 'all' in args.services else tuple(dict.fromkeys(args.services))
    template = Path(__file__).resolve().parents[1] / 'assets/swagger.html'
    for name in names:
        service = root / f'app/backend/{name}-service'
        if not (service / 'main.py').is_file():
            raise ValueError(f'Missing service: {name}')
        if args.action == 'ui':
            static = service / 'static'
            static.mkdir(exist_ok=True)
            title = html.escape(name.title() + ' Service')
            (static / 'swagger.html').write_text(template.read_text().replace('__TITLE__', title))
            print(f'{name}: refreshed static/swagger.html')
        else:
            inventory = route_inventory(service)
            if args.action == 'inventory':
                print(json.dumps({'service': name, 'routes': inventory}, indent=2))
            else:
                validate_document(service, inventory)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, ImportError) as error:
        print(f'swagger: {error}', file=sys.stderr)
        sys.exit(1)
