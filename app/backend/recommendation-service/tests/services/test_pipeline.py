import copy
import logging
from unittest.mock import Mock

import psycopg
import pytest
from services import assembly, candidates, pipeline, reasons, selection
from services.context import ContextError
from services.inference_client import InferenceError
from services.movie_client import MovieCatalogError
from tests.services.pipeline_support import (CONFIG, OTHER_USER, USER, World, catalog, context, echo, keys, mid, script)


@pytest.fixture
def world(monkeypatch):
    return World(monkeypatch, context(watched=[1, 2], watchlist=[3]))


def ids(items):
    return [item.candidate.movie['id'] for item in items]


# --- success -------------------------------------------------------------------------------------------------

def test_unfiltered_user_request_calls_components_in_order_and_persists_exactly_the_selection(world):
    result = world.run('user_requested')
    assert world.calls == ['context', 'catalog', 'select', 'inference', 'replace']
    url, user, source, persisted = world.persisted[0]
    assert (url, user, source) == (CONFIG['DATABASE_URL'], USER, 'user_requested')
    assert persisted is result.selection.recommendations and persisted is result.recommendations
    assert (result.user_id, result.source, result.requested_count, result.catalog_count) == (USER, 'user_requested', 10, 60)
    assert (result.candidate_count, result.persisted_count) == (30, 10) and len(persisted) == 10
    assert (result.outcome, result.attempts, result.used_fallback, result.fallback_reason) == ('llm', 1, False, None)
    assert world.llm.call_count == 1 and world.llm.call_args.args[0] == CONFIG['INFERENCE_SERVICE_URL']


def test_full_catalog_profile_and_candidate_generation_are_the_real_reused_ones(world):
    result = world.run()
    expected = world.expected_pool()
    assert [c.movie['id'] for c in world.pool] == [c.movie['id'] for c in expected] and len(world.pool) == 30
    assert ids(result.recommendations) == [c.movie['id'] for c in expected[:10]]       # echo selects keys 1..10
    assert {movie['id'] for movie in world.catalog} >= {c.movie['id'] for c in world.pool}
    assert len(world.catalog) == result.catalog_count == 60


def test_the_whole_catalog_object_is_what_scoring_receives(monkeypatch):
    world = World(monkeypatch, context(watched=[1]))
    seen = {}
    real = pipeline.generate_candidates
    monkeypatch.setattr(pipeline, 'generate_candidates', lambda cat, ctx, f, n: seen.update(cat=cat, ctx=ctx) or real(cat, ctx, f, n))
    world.run()
    assert seen['cat'] is world.catalog and seen['ctx'] is world.context


def test_filtered_user_request(world):
    filters = {'genres': ['Action', 'Drama'], 'year_from': 1990, 'year_to': 2030, 'duration': 'medium', 'count': 5}
    result = world.run('user_requested', filters=filters)
    assert result.requested_count == 5 and result.persisted_count == 5 and result.candidate_count == len(world.pool)
    normalized = {'genres': ['Action', 'Drama'], 'languages': [], 'actors': [], 'directors': [], 'year_from': 1990, 'year_to': 2030,
                  'duration': 'medium', 'count': 5}
    assert world.pool and all(candidates.matches(c.movie, normalized) for c in world.pool)
    assert all(candidates.matches(item.candidate.movie, normalized) for item in result.recommendations)
    assert ids(result.recommendations) == [c.movie['id'] for c in world.expected_pool(filters, 5)[:5]]
    assert world.persisted[0][2] == 'user_requested'


def test_fewer_eligible_movies_than_requested_persists_what_exists(world):
    result = world.run(filters={'genres': ['Action'], 'year_from': 1990, 'year_to': 2030, 'duration': 'medium', 'count': 5})
    assert result.requested_count == 5 and result.candidate_count == 4 and result.persisted_count == 4
    assert len(result.recommendations) == 4 and result.outcome == 'llm'
    assert world.persisted[0][3] is result.recommendations


def test_filtered_and_unfiltered_requests_differ(monkeypatch):
    world = World(monkeypatch, context(watched=[1, 2]))
    unfiltered = ids(world.run().recommendations)
    filtered = ids(world.run(filters={'genres': ['Horror']}).recommendations)
    assert unfiltered != filtered and all(world.catalog[int(i[-8:], 16) - 1]['genres'] == ['Horror'] for i in filtered)


def test_automatic_generation_uses_the_same_pipeline_with_defaults(world):
    result = world.run('auto')
    assert world.persisted[0][2] == 'auto' and result.source == 'auto' and result.requested_count == 10
    assert ids(result.recommendations) == [c.movie['id'] for c in world.expected_pool()[:10]]


@pytest.mark.parametrize('count,pool', [(5, 30), (10, 30), (15, 30), (20, 40)])
def test_supported_counts_and_pool_sizes(world, count, pool):
    result = world.run(count=count)
    assert (result.requested_count, result.persisted_count, result.candidate_count) == (count, count, pool)


def test_count_defaults_to_the_filters_count_and_must_agree_with_an_explicit_one(world):
    assert world.run(filters={'count': 5}).requested_count == 5
    assert world.run(filters={'count': 15}, count=15).requested_count == 15
    world.calls.clear()
    with pytest.raises(ValueError, match='conflicts'):
        world.run(filters={'count': 5}, count=10)
    assert world.calls == []


def test_selection_result_is_exposed_unchanged(world):
    result = world.run()
    assert isinstance(result.selection, selection.SelectionResult)
    assert (result.outcome, result.attempts, result.used_fallback, result.fallback_reason) == (
        result.selection.outcome, result.selection.attempts, result.selection.used_fallback, result.selection.fallback_reason)
    with pytest.raises(AttributeError):
        result.persisted_count = 0


# --- fallback --------------------------------------------------------------------------------------------------

def test_inference_failure_falls_back_and_persists_the_deterministic_top_n(world):
    world.llm = script(InferenceError('down'))
    result = world.run()
    assert (result.outcome, result.used_fallback, result.attempts, result.fallback_reason) == ('fallback_inference_error', True, 1, 'inference_error')
    assert world.llm.call_count == 1 and world.calls == ['context', 'catalog', 'select', 'inference', 'replace']
    assert world.persisted[0][3] is result.recommendations and result.persisted_count == 10
    assert ids(result.recommendations) == [c.movie['id'] for c in world.expected_pool()[:10]]


def test_two_invalid_answers_fall_back_after_two_calls(world):
    world.llm = script('not json', '{"selected": [1, 1]}')
    result = world.run()
    assert (result.outcome, result.attempts, result.fallback_reason) == ('fallback_validation_error', 2, 'validation_error')
    assert world.llm.call_count == 2 and result.persisted_count == 10 and world.persisted


def test_invalid_then_valid_answer_is_success_after_retry(world):
    world.llm = script('not json')
    result = world.run()
    assert (result.outcome, result.attempts, result.used_fallback) == ('llm_after_retry', 2, False)


def test_fallback_and_llm_echo_produce_identical_persisted_sets(monkeypatch):
    llm = World(monkeypatch, context(watched=[1])).run()
    fallback_world = World(monkeypatch, context(watched=[1]))
    fallback_world.llm = script(InferenceError('down'))
    assert fallback_world.run().recommendations == llm.recommendations


# --- cold start / zero candidates -----------------------------------------------------------------------------

def test_a_real_empty_history_is_cold_start_and_still_produces_recommendations(monkeypatch):
    world = World(monkeypatch, context())
    result = world.run()
    assert result.persisted_count == 10 and result.outcome == 'llm'
    assert all(item.reason.startswith('Suggested from our catalog') for item in result.recommendations)
    assert ids(result.recommendations) == [c.movie['id'] for c in world.expected_pool()[:10]]       # UUID order, no invented preferences


@pytest.mark.parametrize('how', ['impossible year', 'valid genre with impossible year', 'valid actor nobody has', 'all watched'])
def test_zero_eligible_movies_persist_an_intentionally_empty_set_without_inference(monkeypatch, how):
    filters = None
    watched = [1, 2]
    if how == 'impossible year':
        filters = {'year_from': 1888, 'year_to': 1888}
    elif how == 'valid genre with impossible year':
        filters = {'genres': ['Horror'], 'languages': ['en'], 'year_from': 1888, 'year_to': 1888}
    elif how == 'valid actor nobody has':
        filters = {'actors': ['Nobody Famous']}                 # names are free text: valid, matches nothing
    else:
        watched = list(range(1, 61))
    world = World(monkeypatch, context(watched=watched))
    result = world.run(filters=filters)
    assert world.llm.call_count == 0 and 'inference' not in world.calls
    assert world.persisted == [(CONFIG['DATABASE_URL'], USER, 'user_requested', ())]
    assert (result.outcome, result.attempts, result.used_fallback, result.fallback_reason) == ('no_candidates', 0, False, None)
    assert (result.persisted_count, result.candidate_count, result.recommendations, result.llm_overlap) == (0, 0, (), None)


# --- unsupported genres / languages vs valid zero-match filters --------------------------------------------------

UNSUPPORTED = [{'genres': ['CompletelyInvalidGenre']}, {'genres': ['Action', 'CompletelyInvalidGenre']}, {'genres': ['action']},
               {'genres': ['Western']}, {'languages': ['xx']}, {'languages': ['EN']}, {'languages': ['en', 'zz']},
               {'genres': ['Action'], 'languages': ['xx']}, {'genres': ['Horror'], 'year_from': 1888, 'year_to': 1888, 'languages': ['xx']}]


@pytest.mark.parametrize('source', ['auto', 'user_requested'])
@pytest.mark.parametrize('filters', UNSUPPORTED)
def test_unsupported_genre_or_language_is_rejected_before_inference_and_persistence(world, source, filters):
    with pytest.raises(ValueError, match='available'):
        world.run(source, filters=filters)
    assert world.calls == ['context', 'catalog']                   # structural checks passed; catalog check failed
    assert world.llm.call_count == 0 and world.persisted == []


def test_the_supported_options_are_those_of_the_fetched_catalog(monkeypatch):
    movies = [{**movie, 'genres': ['Western'] if movie['id'] == mid(5) else movie['genres'],
               'languages': ['pt'] if movie['id'] == mid(6) else movie['languages']} for movie in catalog()]
    world = World(monkeypatch, context(watched=[1]), movies)
    result = world.run(filters={'genres': ['Western'], 'languages': ['pt']})            # supported now, but no movie has both
    assert result.outcome == 'no_candidates' and world.persisted[0][3] == ()
    assert world.run(filters={'genres': ['Western']}).persisted_count == 1


def test_a_failed_filter_check_does_not_change_the_default_flow(world):
    world.run('auto')
    assert world.run('auto', filters={'genres': ['Action', 'Drama'], 'languages': ['en']}).outcome == 'llm'


# --- empty catalog ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('source', ['auto', 'user_requested'])
@pytest.mark.parametrize('filters', [None, {'genres': ['Action']}, {'year_from': 1888, 'year_to': 1888}])
def test_an_empty_catalog_raises_before_inference_and_persistence(monkeypatch, source, filters):
    world = World(monkeypatch, context(watched=[1, 2]), [])
    with pytest.raises(MovieCatalogError, match='empty'):
        world.run(source, filters=filters)
    assert world.calls == ['context', 'catalog'] and world.llm.call_count == 0 and world.persisted == []


def test_an_empty_catalog_is_reported_before_any_catalog_dependent_filter_check(monkeypatch):
    world = World(monkeypatch, context(), [])
    with pytest.raises(MovieCatalogError):
        world.run(filters={'genres': ['CompletelyInvalidGenre']})


def test_empty_catalog_is_different_from_a_non_empty_catalog_that_yields_no_candidates(monkeypatch):
    with pytest.raises(MovieCatalogError):
        World(monkeypatch, context(), []).run()
    assert World(monkeypatch, context(watched=list(range(1, 61)))).run().outcome == 'no_candidates'
    assert World(monkeypatch, context(), catalog(1)).run().persisted_count == 1


# --- errors: nothing is persisted and the error propagates ------------------------------------------------------

@pytest.mark.parametrize('error', [ContextError(503, 'User context unavailable. Please retry.'), ContextError(404, 'User not found.')])
def test_user_service_failure_propagates_and_nothing_else_runs(world, error):
    world.context_error = error
    with pytest.raises(ContextError) as raised:
        world.run()
    assert raised.value.status == error.status and world.calls == ['context'] and world.persisted == []


def test_movie_service_failure_propagates_without_inference_or_persistence(world):
    world.catalog_error = MovieCatalogError('Movie catalog unavailable. Please retry.')
    with pytest.raises(MovieCatalogError):
        world.run()
    assert world.calls == ['context', 'catalog'] and world.persisted == [] and world.llm.call_count == 0


INVALID_FILTERS = [{'extra': 1}, {'genres': 'Drama'}, {'genres': ['Drama'] * 11}, {'genres': [1]}, {'actors': ['']}, {'duration': 'weird'},
                   {'count': 7}, {'count': True}, {'count': '10'}, {'year_from': 2000, 'year_to': 1999}, {'year_from': True},
                   {'year_to': 9999}, 'drama', 5, ['x']]


@pytest.mark.parametrize('filters', INVALID_FILTERS)
def test_invalid_filters_fail_before_any_external_call(world, filters):
    with pytest.raises(ValueError):
        world.run(filters=filters)
    assert world.calls == [] and world.persisted == []


@pytest.mark.parametrize('kwargs', [{'user_id': None}, {'user_id': 'nope'}, {'user_id': 5}, {'source': 'all'}, {'source': None},
                                    {'source': 'AUTO'}, {'count': 0}, {'count': 7}, {'count': True}, {'count': '10'}, {'count': -5}, {'count': 25}])
def test_invalid_user_source_or_count_fail_before_any_external_call(world, kwargs):
    with pytest.raises(ValueError):
        world.run(**kwargs)
    assert world.calls == [] and world.persisted == []


@pytest.mark.parametrize('missing', ['USER_SERVICE_URL', 'MOVIE_SERVICE_URL', 'INFERENCE_SERVICE_URL', 'DATABASE_URL'])
def test_missing_configuration_fails_before_any_external_call_without_leaking_values(world, missing):
    world.config[missing] = ''
    with pytest.raises(ValueError) as raised:
        world.run()
    assert missing in str(raised.value) and 'SECRET' not in str(raised.value) and world.calls == []
    del world.config[missing]
    with pytest.raises(ValueError):
        world.run()


def test_unexpected_candidate_generation_error_propagates_without_persisting(world, monkeypatch):
    monkeypatch.setattr(pipeline, 'generate_candidates', Mock(side_effect=RuntimeError('bug')))
    with pytest.raises(RuntimeError, match='bug'):
        world.run()
    assert world.persisted == [] and world.llm.call_count == 0


def test_unexpected_selection_error_propagates_without_persisting(world, monkeypatch):
    monkeypatch.setattr(pipeline, 'select_recommendations', Mock(side_effect=RuntimeError('selection bug')))
    with pytest.raises(RuntimeError, match='selection bug'):
        world.run()
    assert world.persisted == []


def test_unexpected_inference_side_error_is_not_turned_into_fallback_or_an_empty_set(world):
    world.llm = script(RuntimeError('programming error'))
    with pytest.raises(RuntimeError):
        world.run()
    assert world.persisted == [] and 'replace' not in world.calls


def test_unexpected_profile_error_propagates(world, monkeypatch):
    monkeypatch.setattr(pipeline, 'build_profile', Mock(side_effect=KeyError('bad context')))
    with pytest.raises(KeyError):
        world.run()
    assert world.persisted == [] and world.calls == ['context', 'catalog']


def test_persistence_failure_propagates_after_inference_and_returns_no_result(world):
    world.persistence_error = psycopg.OperationalError('database down')
    with pytest.raises(psycopg.OperationalError):
        world.run()
    assert world.calls == ['context', 'catalog', 'select', 'inference', 'replace'] and world.persisted == []


def test_failures_never_log_a_success_line(world, caplog):
    caplog.set_level(logging.INFO, logger='services.pipeline')
    world.context_error = ContextError(503, 'x')
    with pytest.raises(ContextError):
        world.run()
    world.context_error = None
    world.persistence_error = psycopg.OperationalError('x')
    with pytest.raises(psycopg.OperationalError):
        world.run()
    assert [r for r in caplog.records if r.name == 'services.pipeline'] == []


# --- isolation ---------------------------------------------------------------------------------------------------

def test_each_run_writes_only_its_own_user_and_source(world):
    world.run('auto')
    world.run('user_requested')
    world.run('auto', user_id=OTHER_USER)
    assert [(user, source) for _, user, source, _ in world.persisted] == [(USER, 'auto'), (USER, 'user_requested'), (OTHER_USER, 'auto')]


# --- consistency ---------------------------------------------------------------------------------------------------

def test_scores_reasons_and_candidates_come_from_the_selection_layer_untouched(world, monkeypatch):
    spy = Mock(wraps=assembly.assemble)
    monkeypatch.setattr(selection, 'assemble', spy)
    result = world.run()
    persisted = world.persisted[0][3]
    assert spy.call_count == 1 and not hasattr(pipeline, 'assemble')
    assert persisted is result.recommendations
    profile = candidates.build_profile(world.context, world.catalog)
    for rank, item in enumerate(persisted, 1):
        assert item.score == assembly.ordering_score(rank, 10) and item.reason == reasons.explain(item.candidate, profile)
        assert any(item.candidate is candidate for candidate in world.pool)


def test_no_watched_movie_and_nothing_outside_the_eligible_pool(world):
    result = world.run(count=20)
    watched = {row['movie_id'] for row in world.context['watched']}
    eligible = {c.movie['id'] for c in world.pool}
    assert not watched & set(ids(result.recommendations)) and set(ids(result.recommendations)) <= eligible
    assert watched.isdisjoint(eligible)


def test_watchlist_movies_remain_recommendable(monkeypatch):
    world = World(monkeypatch, context(watched=[1], watchlist=[4]))
    world.run()
    assert mid(4) in {c.movie['id'] for c in world.pool}


def test_inputs_are_not_mutated_and_output_is_deterministic(world):
    snapshot = copy.deepcopy((world.context, world.catalog))
    filters = {'genres': ['Action'], 'count': 5}
    frozen = copy.deepcopy(filters)
    first = world.run(filters=filters)
    second = world.run(filters=filters)
    assert (world.context, world.catalog) == snapshot and filters == frozen
    assert first.recommendations == second.recommendations and first.outcome == second.outcome


# --- observability -----------------------------------------------------------------------------------------------

def info_lines(caplog):
    return [r.getMessage() for r in caplog.records if r.name == 'services.pipeline' and r.levelno == logging.INFO]


def test_one_concise_info_summary_after_a_successful_generation(world, caplog):
    caplog.set_level(logging.INFO, logger='services.pipeline')
    result = world.run('user_requested')
    [line] = info_lines(caplog)
    for part in ('source=user_requested', 'requested=10', 'candidates=30', 'persisted=10', 'outcome=llm', 'attempts=1',
                 'fallback=no', 'llm_overlap=10', 'seconds=', 'user=' + USER[:8]):
        assert part in line, part
    assert isinstance(result.duration_seconds, float) and result.duration_seconds >= 0


def test_summary_for_retry_fallback_and_zero_candidates(world, caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger='services.pipeline')
    world.llm = script('bad')
    world.run()
    world.llm = script(InferenceError('down'))
    world.run('auto')
    world.run(filters={'year_from': 1888, 'year_to': 1888})
    retry, fallback, zero = info_lines(caplog)
    assert 'outcome=llm_after_retry' in retry and 'attempts=2' in retry and 'fallback=no' in retry and 'llm_overlap=10' in retry
    assert 'outcome=fallback_inference_error' in fallback and 'fallback=inference_error' in fallback and 'llm_overlap=n/a' in fallback
    assert 'outcome=no_candidates' in zero and 'persisted=0' in zero and 'attempts=0' in zero and 'llm_overlap=n/a' in zero


def test_llm_overlap_measures_agreement_with_the_deterministic_top_n_for_llm_selections_only(world, caplog):
    caplog.set_level(logging.INFO, logger='services.pipeline')
    world.llm = script(keys(21, 22, 23, 24, 25, 26, 27, 28, 29, 30))
    different = world.run()
    assert different.llm_overlap == 0 and 'llm_overlap=0' in info_lines(caplog)[-1]
    world.llm = script(keys(1, 2, 3, 4, 5, 6, 7, 8, 9, 20))
    assert world.run().llm_overlap == 9
    world.llm = script(InferenceError('down'))
    assert world.run().llm_overlap is None


def test_logs_never_contain_secrets_prompts_titles_synopses_or_full_user_ids(world, caplog):
    caplog.set_level(logging.DEBUG)
    world.llm = script('bad', InferenceError('Bearer tok-SECRET http://internal'))
    world.run()
    text = ' '.join(r.getMessage() for r in caplog.records)
    for forbidden in ('tok-SECRET', 'pw-SECRET', 'postgresql://', 'Title', 'Plot', USER, 'internal', 'selected', 'Actor', 'Director'):
        assert forbidden not in text, forbidden
    assert any(r.name == 'services.pipeline' for r in caplog.records)


def test_inference_options_from_config_reach_the_prompt_and_the_inference_call(monkeypatch):
    config = {**CONFIG, 'INFERENCE_TIMEOUT_SECONDS': 777, 'INFERENCE_RETRY_TIMEOUT_SECONDS': 333, 'INFERENCE_SYNOPSIS_CHARS': 0}
    world = World(monkeypatch, context(watched=[1, 2], watchlist=[3]), config=config)
    world.llm = script(echo)
    world.run('user_requested')
    first = world.llm.call_args_list[0]
    assert first.kwargs == {'timeout': 777}
    assert 'synopsis' not in first.args[1][1]['content']              # messages: the user message has no synopsis field


def test_default_pipeline_keeps_the_synopsis_and_default_timeouts(world):
    world.run('user_requested')
    first = world.llm.call_args_list[0]
    assert first.kwargs == {} and '"synopsis"' in first.args[1][1]['content']


def test_automatic_generation_uses_inference_by_default(world):
    world.llm = script(echo)
    result = world.run('auto')
    assert 'inference' in world.calls and result.outcome == 'llm'


def test_automatic_generation_can_skip_inference_and_stays_deterministic(monkeypatch):
    world = World(monkeypatch, context(watched=[1, 2], watchlist=[3]), config={**CONFIG, 'AUTO_INFERENCE_ENABLED': False})
    result = world.run('auto')
    assert 'inference' not in world.calls and 'select' not in world.calls
    assert (result.outcome, result.used_fallback, result.attempts, result.fallback_reason) == ('deterministic', False, 0, 'not_requested')
    assert len(result.recommendations) == 10 and world.persisted[-1][2] == 'auto' and len(world.persisted[-1][3]) == 10
    top = [c.movie['id'] for c in selection.deterministic_top(pipeline.prepare(world.pool, pipeline.build_profile(world.context, world.catalog), 10))]
    assert sorted(i.candidate.movie['id'] for i in result.recommendations) == sorted(top)


def test_user_requested_generation_still_uses_inference_when_automatic_inference_is_disabled(monkeypatch):
    world = World(monkeypatch, context(watched=[1, 2], watchlist=[3]), config={**CONFIG, 'AUTO_INFERENCE_ENABLED': False})
    world.llm = script(echo)
    result = world.run('user_requested')
    assert 'inference' in world.calls and result.outcome == 'llm'


def test_unavailable_qwen_with_configured_timeouts_still_falls_back_to_the_deterministic_top_n(monkeypatch):
    config = {**CONFIG, 'INFERENCE_TIMEOUT_SECONDS': 300, 'INFERENCE_RETRY_TIMEOUT_SECONDS': 150, 'INFERENCE_SYNOPSIS_CHARS': 0}
    world = World(monkeypatch, context(watched=[1, 2], watchlist=[3]), config=config)
    world.llm = script(InferenceError('Inference engine unavailable.'))
    result = world.run('user_requested')
    assert world.llm.call_args_list[0].kwargs == {'timeout': 300}
    assert (result.outcome, result.used_fallback, result.attempts, result.fallback_reason) == ('fallback_inference_error', True, 1, 'inference_error')
    assert len(world.persisted[-1][3]) == 10 and world.calls[-1] == 'replace'      # the fallback set is persisted as usual


def test_invalid_qwen_answers_with_configured_timeouts_retry_with_the_retry_timeout_then_fall_back(monkeypatch):
    config = {**CONFIG, 'INFERENCE_TIMEOUT_SECONDS': 300, 'INFERENCE_RETRY_TIMEOUT_SECONDS': 150}
    world = World(monkeypatch, context(watched=[1, 2], watchlist=[3]), config=config)
    world.llm = script('not json', 'still not json')
    result = world.run('user_requested')
    assert [c.kwargs for c in world.llm.call_args_list] == [{'timeout': 300}, {'timeout': 150}]
    assert (result.outcome, result.attempts) == ('fallback_validation_error', 2)
