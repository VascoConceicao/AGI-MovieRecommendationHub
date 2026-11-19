"""Test-wide settings and the shared PostgreSQL fixture.

No background generation worker is started by the many tests that build the app. The `url` fixture gives a
throwaway database per test module, created on the server named by DATABASE_URL as recommendation_test_<random>
with the service migrations, and dropped afterwards; the configured database is never touched. Tests using it are
skipped when DATABASE_URL is unset or the server is unreachable.
"""
import os
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from services import recommendations as store

PREFIX = 'recommendation_test_'

os.environ.setdefault('GENERATION_WORKER', 'false')


@pytest.fixture(scope='module')
def url():
    base = os.environ.get('DATABASE_URL')
    if not base:
        pytest.skip('Set DATABASE_URL (set -a; . ./.env; set +a) to run the PostgreSQL integration tests.')
    name = PREFIX + uuid.uuid4().hex[:12]
    try:
        admin = psycopg.connect(make_conninfo(base, dbname='postgres'), autocommit=True, connect_timeout=3)
    except psycopg.Error:
        pytest.skip('PostgreSQL is not reachable.')
    try:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    except psycopg.Error:
        admin.close()
        pytest.skip('Cannot create a throwaway test database.')
    test_url = make_conninfo(base, dbname=name)
    try:
        assert conninfo_to_dict(test_url)['dbname'].startswith(PREFIX)
        store.initialize(test_url)
        yield test_url
    finally:
        admin.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
        admin.close()
