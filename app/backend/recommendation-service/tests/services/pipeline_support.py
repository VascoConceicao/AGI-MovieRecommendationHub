"""Shared harness for the pipeline tests: fakes only the external service boundaries (User Service,
Movie Service, inference) and optionally persistence. Profile, filtering, scoring, preparation, selection,
assembly and (when not faked) replace_set are the real implementations."""
import json
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID

from services import candidates, filters, pipeline, selection

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
USER = str(UUID(int=0xA))
OTHER_USER = str(UUID(int=0xB))
GENRES = ('Action', 'Drama', 'Comedy', 'Horror')
CONFIG = {'USER_SERVICE_URL': 'http://user.test', 'AGENT_CONTEXT_TOKEN': 'tok-SECRET', 'MOVIE_SERVICE_URL': 'http://movie.test',
          'INFERENCE_SERVICE_URL': 'http://llm.test', 'DATABASE_URL': 'postgresql://u:pw-SECRET@db.test/recommendation'}


def mid(n):
    return str(UUID(int=n))


def film(n):
    return {'id': mid(n), 'title': 'Title %d' % n, 'original_title': None, 'synopsis': 'Plot %d' % n,
            'release_date': None, 'year': 1980 + n, 'duration_minutes': 70 + n * 2, 'genres': [GENRES[n % 4]],
            'actors': ['Actor %d' % (n % 7)], 'directors': ['Director %d' % (n % 5)], 'languages': ['en'], 'countries': ['US']}


def catalog(size=60):
    return [film(n) for n in range(1, size + 1)]


def context(watched=(), watchlist=(), user_id=USER):
    return {'user_id': user_id, 'as_of': NOW,
            'watched': [{'movie_id': mid(n), 'watched_at': None, 'recorded_at': NOW, 'effective_at': NOW} for n in watched],
            'watchlist': [{'movie_id': mid(n), 'added_at': NOW} for n in watchlist]}


def echo(schema):
    """A valid answer selecting the first target_count keys."""
    return json.dumps({'selected': list(range(1, schema['properties']['selected']['maxItems'] + 1))})


def keys(*numbers):
    return lambda schema: json.dumps({'selected': list(numbers)})


def script(*items):
    """Mock inference: each call consumes one item (string, exception, or callable(schema)); then echoes."""
    queue = list(items)

    def fake(url, messages, schema, **options):
        item = queue.pop(0) if queue else echo
        if isinstance(item, Exception):
            raise item
        return item(schema) if callable(item) else item
    return Mock(side_effect=fake)


class World:
    """Patches the boundaries and records the order of calls."""

    def __init__(self, monkeypatch, user_context=None, movies=None, fake_persistence=True, config=None):
        self.calls, self.persisted, self.pool = [], [], None
        self.context = context() if user_context is None else user_context
        self.catalog = catalog() if movies is None else movies
        self.config = dict(CONFIG if config is None else config)
        self.context_error = self.catalog_error = self.persistence_error = None
        self.gate = self.gate_entered = None          # optional threading.Events: hold the pipeline inside the catalog fetch
        self.llm = script()
        monkeypatch.setattr(pipeline, 'fetch_full_context', self._fetch_context)
        monkeypatch.setattr(pipeline, 'fetch_catalog', self._fetch_catalog)
        monkeypatch.setattr(selection, 'request_rerank', self._request)
        real_select, real_generate = pipeline.select_recommendations, pipeline.generate_candidates
        monkeypatch.setattr(pipeline, 'select_recommendations', lambda *a: self._note('select') or real_select(*a))
        monkeypatch.setattr(pipeline, 'generate_candidates', lambda *a: self._remember_pool(real_generate(*a)))
        if fake_persistence:
            monkeypatch.setattr(pipeline, 'replace_set', self._replace_set)

    def _note(self, name):
        self.calls.append(name)

    def _fetch_context(self, config, user_id):
        self.calls.append('context')
        if self.context_error:
            raise self.context_error
        return self.context

    def _fetch_catalog(self, movie_url):
        self.calls.append('catalog')
        if self.gate is not None:
            self.gate_entered.set()
            assert self.gate.wait(20), 'test gate was never released'
        if self.catalog_error:
            raise self.catalog_error
        return self.catalog

    def _remember_pool(self, pool):
        self.pool = pool
        return pool

    def _request(self, *args, **options):
        self.calls.append('inference')
        return self.llm(*args, **options)

    def _replace_set(self, url, user_id, source, recommendations):
        self.calls.append('replace')
        if self.persistence_error:
            raise self.persistence_error
        self.persisted.append((url, user_id, source, recommendations))
        return len(recommendations)

    def run(self, source='user_requested', filters=None, count=None, user_id=USER):
        return pipeline.generate_recommendations(self.config, user_id, source, filters, count)

    def expected_pool(self, filters=None, count=10):
        normalized = globals()['filters'].validate_offline({**(filters or {}), 'count': count})
        return candidates.generate_candidates(self.catalog, self.context, normalized, normalized['count'])
