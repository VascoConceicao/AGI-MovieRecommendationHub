"""Synchronous recommendation pipeline: one function shared by user requests and the background agent.

user context -> movie catalog -> profile -> candidate pool -> LLM selection / deterministic fallback ->
final assembly -> atomic persistence. Everything external (context, catalog, inference) finishes before the
only write, and no failure is caught here: an upstream error propagates and replace_set() is never called, so
a failed generation can never erase or overwrite previously valid recommendations.
"""
import logging
import time
from typing import NamedTuple, Optional

from services import filters as filter_contract
from services.candidates import build_profile, generate_candidates
from services.context import fetch_full_context
from services.movie_client import MovieCatalogError, fetch_catalog
from services.recommendations import replace_set, validate_set
from services.reranker import MAX_SYNOPSIS_CHARS, prepare
from services.selection import (OUTCOME_LLM, OUTCOME_LLM_AFTER_RETRY, SelectionResult, deterministic_selection, deterministic_top,
                                select_recommendations)

logger = logging.getLogger(__name__)

REQUIRED_CONFIG = ('USER_SERVICE_URL', 'MOVIE_SERVICE_URL', 'INFERENCE_SERVICE_URL', 'DATABASE_URL')


class PipelineResult(NamedTuple):
    user_id: str
    source: str
    requested_count: int
    catalog_count: int
    candidate_count: int
    persisted_count: int
    selection: SelectionResult
    llm_overlap: Optional[int]      # selected movies also in the deterministic top-N; only for LLM selections
    duration_seconds: float

    @property
    def recommendations(self):
        return self.selection.recommendations

    @property
    def outcome(self):
        return self.selection.outcome

    @property
    def attempts(self):
        return self.selection.attempts

    @property
    def used_fallback(self):
        return self.selection.used_fallback

    @property
    def fallback_reason(self):
        return self.selection.fallback_reason


def normalize_criteria(filters, count=None):
    """Normalized filters (count included), or ValueError. count, if given, must agree with filters['count']."""
    data = {} if filters is None else filters
    if isinstance(data, dict) and count is not None:
        if 'count' in data and data['count'] != count:
            raise ValueError('count conflicts with filters.count.')
        data = {**data, 'count': count}
    return filter_contract.validate_offline(data)


def _check_config(config):
    missing = [key for key in REQUIRED_CONFIG if not config.get(key)]
    if missing:
        raise ValueError('Missing configuration: ' + ', '.join(missing) + '.')


def _llm_overlap(preparation, selection):
    if selection.outcome not in (OUTCOME_LLM, OUTCOME_LLM_AFTER_RETRY):
        return None                  # a fallback selection is the baseline itself, not an LLM contribution
    top = {candidate.movie['id'] for candidate in deterministic_top(preparation)}
    return sum(1 for item in selection.recommendations if item.candidate.movie['id'] in top)


def generate_recommendations(config, user_id, source, filters=None, count=None):
    """Generate and atomically persist the (user_id, source) recommendation set.

    config: mapping with USER_SERVICE_URL, AGENT_CONTEXT_TOKEN, MOVIE_SERVICE_URL, INFERENCE_SERVICE_URL and
    DATABASE_URL (Flask's app.config works). filters: structured filters as in the filter contract, or None.
    count: 5/10/15/20; defaults to filters['count'] and then to 10. Invalid input raises ValueError before any
    external call, and genres/languages the catalog does not offer raise ValueError before inference or any
    write. A valid request with no eligible movies persists an intentionally empty set; an empty catalog raises
    MovieCatalogError instead.
    """
    started = time.monotonic()
    user_id, source, _ = validate_set(user_id, source, ())
    criteria = normalize_criteria(filters, count)
    requested = criteria['count']
    _check_config(config)

    context = fetch_full_context(config, user_id)
    catalog = fetch_catalog(config['MOVIE_SERVICE_URL'])
    if not catalog:
        # An empty catalog suggests an ingestion or service data problem, unlike valid filters that match nothing.
        raise MovieCatalogError('Movie catalog is empty.')
    criteria = filter_contract.validate(criteria, filter_contract.catalog_options(catalog))   # unknown genre/language -> ValueError
    profile = build_profile(context, catalog)
    pool = generate_candidates(catalog, context, criteria, requested)
    preparation = prepare(pool, profile, requested, config.get('INFERENCE_SYNOPSIS_CHARS', MAX_SYNOPSIS_CHARS))
    # Background (source 'auto') generations may skip the slow LLM entirely: AUTO_INFERENCE_ENABLED=false. The default keeps
    # today's behaviour (every source may use inference); user-requested generations always do.
    if source == 'auto' and not config.get('AUTO_INFERENCE_ENABLED', True):
        selection = deterministic_selection(preparation, profile)
    else:
        selection = select_recommendations(preparation, profile, config['INFERENCE_SERVICE_URL'],
                                           config.get('INFERENCE_TIMEOUT_SECONDS'), config.get('INFERENCE_RETRY_TIMEOUT_SECONDS'))
    persisted = replace_set(config['DATABASE_URL'], user_id, source, selection.recommendations)

    result = PipelineResult(user_id, source, requested, len(catalog), len(pool), persisted, selection,
                            _llm_overlap(preparation, selection), time.monotonic() - started)
    logger.info('Recommendations generated (user=%s, source=%s, requested=%d, candidates=%d, persisted=%d, '
                'outcome=%s, attempts=%d, fallback=%s, llm_overlap=%s, seconds=%.1f)',
                user_id[:8], source, requested, len(pool), persisted, result.outcome, result.attempts,
                result.fallback_reason or 'no', 'n/a' if result.llm_overlap is None else result.llm_overlap,
                result.duration_seconds)
    return result
