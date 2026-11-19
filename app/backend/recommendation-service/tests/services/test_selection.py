import copy
import json
import re
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID

import pytest
from services import assembly, candidates, reasons, reranker, selection
from services.inference_client import InferenceError
from services.reranker import RerankValidationError

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
URL = 'http://inference:4210'


def film(n, genres=('Drama',), directors=('D',), actors=('A',), year=2000, minutes=100):
    return {'id': str(UUID(int=n)), 'title': 'Title %d' % n, 'original_title': None, 'synopsis': 'Plot', 'release_date': None,
            'year': year, 'duration_minutes': minutes, 'genres': list(genres), 'actors': list(actors),
            'directors': list(directors), 'languages': ['en'], 'countries': ['US']}


def profile_of(*watched):
    context = {'as_of': NOW, 'watchlist': [], 'watched': [
        {'movie_id': m['id'], 'watched_at': None, 'recorded_at': NOW, 'effective_at': NOW} for m in watched]}
    return candidates.build_profile(context, list(watched))


LIKED = film(1, genres=['Action', 'Science Fiction'], directors=['Denis Villeneuve'], actors=['Ann Star'], year=2015, minutes=120)
PROFILE = profile_of(LIKED)
COLD = profile_of()


def ranked_pool(size=12, profile=PROFILE):
    movies = [film(n, genres=[('Action', 'Science Fiction', 'Comedy', 'Horror')[n % 4]], year=1950 + n * 5, minutes=70 + n * 9)
              for n in range(2, size + 2)]
    return candidates.rank(movies, profile)


def prepare(count=5, size=12, profile=PROFILE, pool=None):
    return reranker.prepare(pool if pool is not None else ranked_pool(size, profile), profile, count)


def valid(keys):
    return json.dumps({'selected': keys})


def run(preparation, *responses, profile=PROFILE):
    request = Mock(side_effect=list(responses))
    return request, selection_with(request, preparation, profile)


def selection_with(request, preparation, profile):
    original = selection.request_rerank
    selection.request_rerank = request
    try:
        return selection.select_recommendations(preparation, profile, URL)
    finally:
        selection.request_rerank = original


def ids(result):
    return [item.candidate.movie['id'] for item in result.recommendations]


def keys_to_ids(preparation, keys):
    return [preparation.candidates_by_key[key].movie['id'] for key in keys]


# --- success -----------------------------------------------------------------------------------

def test_valid_first_response_uses_the_llm_selection_without_fallback():
    preparation = prepare(count=3)
    request, result = run(preparation, valid([5, 2, 4]))
    assert request.call_count == 1
    assert (result.used_fallback, result.attempts, result.fallback_reason) == (False, 1, None)
    assert sorted(ids(result)) == sorted(keys_to_ids(preparation, [5, 2, 4]))
    request.assert_called_once_with(URL, preparation.messages, preparation.response_schema)


def test_success_uses_the_final_assembler_for_order_scores_and_reasons():
    preparation = prepare(count=3)
    _, result = run(preparation, valid([5, 2, 4]))         # deliberately not in deterministic order
    chosen = [preparation.candidates_by_key[key] for key in (5, 2, 4)]
    expected = assembly.assemble(chosen, PROFILE)
    assert result.recommendations == expected
    assert ids(result) == [c.movie['id'] for c in sorted(chosen, key=candidates.ranking_key)]
    assert [item.score for item in result.recommendations] == pytest.approx([1.0, 2 / 3, 1 / 3])
    for item in result.recommendations:
        assert item.reason == reasons.explain(item.candidate, PROFILE)
        assert any(item.candidate is original for original in preparation.candidates_by_key.values())


def test_success_and_fallback_call_the_same_assemble(monkeypatch):
    spy = Mock(wraps=assembly.assemble)
    monkeypatch.setattr(selection, 'assemble', spy)
    preparation = prepare(count=3)
    run(preparation, valid([1, 2, 3]))
    run(preparation, InferenceError('down'))
    assert spy.call_count == 2


# --- retry on invalid answers --------------------------------------------------------------------

INVALID = [
    'not json at all', '{"selected": [', '', '[]', '{"other": [1, 2, 3]}', '{"selected": [1, 2]}',
    '{"selected": [1, 2, 3, 4]}', '{"selected": [1, 1, 2]}', '{"selected": [1, 2, 99]}',
    '{"selected": [1, 2, "3"]}', '{"selected": [1, 2, 3], "note": "SECRET-RAW-ANSWER"}',
    '```json\n{"selected": [1, 2, 3]}\n```', '{"selected": [1, 2, NaN]}']


@pytest.mark.parametrize('bad', INVALID)
def test_each_kind_of_invalid_first_response_triggers_one_retry(bad):
    preparation = prepare(count=3)
    request, result = run(preparation, bad, valid([3, 1, 2]))
    assert request.call_count == 2
    assert (result.used_fallback, result.attempts, result.fallback_reason) == (False, 2, None)
    assert sorted(ids(result)) == sorted(keys_to_ids(preparation, [1, 2, 3]))


def test_retry_reuses_the_pool_and_schema_and_appends_a_corrective_copy_of_the_messages():
    preparation = prepare(count=3)
    snapshot = copy.deepcopy(preparation)
    request, result = run(preparation, '{"selected": [1, 1, 2]}', valid([1, 2, 3]))
    first, second = request.call_args_list
    assert first.args == (URL, preparation.messages, preparation.response_schema)
    assert second.args[0] == URL and second.args[2] is preparation.response_schema
    assert second.args[1][:-1] == preparation.messages and len(second.args[1]) == len(preparation.messages) + 1
    corrective = second.args[1][-1]
    assert corrective['role'] == 'user' and 'duplicate key 1' in corrective['content']
    assert 'exactly 3 distinct integer keys from 1 to 12' in corrective['content'] and '{"selected":[...]}' in corrective['content']
    assert second.args[1] is not preparation.messages and preparation.messages == snapshot.messages
    assert preparation == snapshot


def test_corrective_message_is_short_and_never_echoes_the_raw_answer_or_identifiers():
    preparation = prepare(count=3)
    request, _ = run(preparation, '{"selected": [1, 2, 3], "note": "SECRET-RAW-ANSWER"}', valid([1, 2, 3]))
    corrective = request.call_args_list[1].args[1][-1]['content']
    assert 'SECRET-RAW-ANSWER' not in corrective and len(corrective) < 400
    assert not re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', corrective)
    assert URL not in corrective


def test_retry_detail_is_capped(monkeypatch):
    monkeypatch.setattr(selection, 'validate_rerank_response',
                        Mock(side_effect=[RerankValidationError('x' * 5000), [prepare(count=3).candidates_by_key[1]]]))
    preparation = prepare(count=1)
    request, _ = run(preparation, 'a', 'b')
    assert len(request.call_args_list[1].args[1][-1]['content']) < 400


def test_two_invalid_responses_fall_back_after_exactly_two_calls():
    preparation = prepare(count=3)
    request, result = run(preparation, '{"selected": [1, 1, 1]}', 'garbage')
    assert request.call_count == 2
    assert (result.used_fallback, result.attempts, result.fallback_reason) == (True, 2, 'validation_error')
    assert result.recommendations == assembly.assemble(sorted(preparation.candidates_by_key.values(), key=candidates.ranking_key)[:3], PROFILE)


def test_never_more_than_two_inference_calls():
    preparation = prepare(count=3)
    request, _ = run(preparation, 'bad', 'bad', 'bad')
    assert request.call_count == 2 == selection.MAX_ATTEMPTS


# --- transport failures --------------------------------------------------------------------------

def test_initial_inference_error_falls_back_immediately_without_retry():
    preparation = prepare(count=3)
    request, result = run(preparation, InferenceError('Inference engine unavailable.'))
    assert request.call_count == 1
    assert (result.used_fallback, result.attempts, result.fallback_reason) == (True, 1, 'inference_error')
    assert len(result.recommendations) == 3


def test_inference_error_on_the_retry_falls_back():
    preparation = prepare(count=3)
    request, result = run(preparation, 'not json', InferenceError('timeout'))
    assert request.call_count == 2
    assert (result.used_fallback, result.attempts, result.fallback_reason) == (True, 2, 'inference_error')


def test_fallback_reason_and_result_do_not_leak_exception_details():
    preparation = prepare(count=3)
    _, result = run(preparation, InferenceError('Bearer secret-token-123 http://internal-host'))
    assert result.fallback_reason == 'inference_error'
    assert 'secret-token-123' not in repr(result) and 'internal-host' not in repr(result)
    _, result = run(preparation, '{"selected": [1, 2, 3], "note": "SECRET-RAW-ANSWER"}', 'SECRET-RAW-ANSWER')
    assert result.fallback_reason == 'validation_error' and 'SECRET-RAW-ANSWER' not in repr(result.fallback_reason)


# --- fallback quality ----------------------------------------------------------------------------

def test_fallback_is_the_deterministic_top_n_in_step_6_order():
    preparation = prepare(count=5, size=20)
    _, result = run(preparation, InferenceError('down'))
    pool = list(preparation.candidates_by_key.values())
    assert ids(result) == [c.movie['id'] for c in sorted(pool, key=candidates.ranking_key)[:5]]
    assert ids(result) == [c.movie['id'] for c in candidates.rank([c.movie for c in pool], PROFILE)[:5]]


def test_fallback_picks_by_score_even_if_the_pool_is_not_presented_in_rank_order():
    pool = list(reversed(ranked_pool(12)))
    preparation = prepare(count=4, pool=pool)
    _, result = run(preparation, InferenceError('down'))
    assert ids(result) == [c.movie['id'] for c in sorted(pool, key=candidates.ranking_key)[:4]]


def test_fallback_never_introduces_movies_outside_the_pool_or_watched_ones():
    watched = film(2, genres=['Action'])
    catalog = [watched] + [film(n, genres=['Action']) for n in range(3, 20)]
    context = {'as_of': NOW, 'watchlist': [], 'watched': [
        {'movie_id': watched['id'], 'watched_at': None, 'recorded_at': NOW, 'effective_at': NOW}]}
    profile = candidates.build_profile(context, catalog)
    pool = candidates.generate_candidates(catalog, context, {}, 5)
    preparation = reranker.prepare(pool, profile, 5)
    _, result = run(preparation, InferenceError('down'), profile=profile)
    assert watched['id'] not in ids(result) and set(ids(result)) <= {c.movie['id'] for c in pool}


def test_fallback_output_comes_from_the_final_assembler():
    preparation = prepare(count=5, size=20)
    _, result = run(preparation, InferenceError('down'))
    scores = [item.score for item in result.recommendations]
    assert scores[0] == 1.0 and all(a > b for a, b in zip(scores, scores[1:])) and all(0 < s <= 1 for s in scores)
    for item in result.recommendations:
        assert item.reason == reasons.explain(item.candidate, PROFILE) and 1 <= len(item.reason) <= reasons.MAX_REASON_CHARS
        assert any(item.candidate is original for original in preparation.candidates_by_key.values())


def test_fallback_and_llm_paths_produce_identical_output_for_the_same_selection():
    preparation = prepare(count=5, size=20)
    top_keys = sorted(preparation.candidates_by_key, key=lambda k: candidates.ranking_key(preparation.candidates_by_key[k]))[:5]
    _, llm = run(preparation, valid(top_keys))
    _, fallback = run(preparation, InferenceError('down'))
    assert llm.recommendations == fallback.recommendations
    assert (llm.used_fallback, fallback.used_fallback) == (False, True)


# --- edge cases ------------------------------------------------------------------------------------

def test_zero_candidates_makes_no_inference_call_and_is_not_a_failure():
    preparation = reranker.prepare([], PROFILE, 10)
    request, result = run(preparation)
    request.assert_not_called()
    assert result == selection.SelectionResult((), False, 0, None)


def test_one_candidate():
    preparation = prepare(count=10, pool=ranked_pool(1))
    assert preparation.target_count == 1
    _, result = run(preparation, valid([1]))
    assert len(result.recommendations) == 1 and result.recommendations[0].score == 1.0 and not result.used_fallback
    _, result = run(preparation, InferenceError('down'))
    assert len(result.recommendations) == 1 and result.used_fallback


def test_fewer_candidates_than_requested_returns_what_exists():
    preparation = prepare(count=10, pool=ranked_pool(4))
    assert preparation.target_count == 4
    _, result = run(preparation, valid([4, 3, 2, 1]))
    assert len(result.recommendations) == 4
    _, result = run(preparation, InferenceError('down'))
    assert len(result.recommendations) == 4 and result.used_fallback
    _, result = run(preparation, valid([1, 2]), valid([1, 2, 3, 4]))      # LLM must select all 4: 2 keys is invalid, then retry succeeds
    assert result.attempts == 2 and not result.used_fallback


def test_no_profile_history_gives_neutral_reasons_on_both_paths():
    preparation = prepare(count=3, profile=COLD)
    for responses in ((valid([1, 2, 3]),), (InferenceError('down'),)):
        _, result = run(preparation, *responses, profile=COLD)
        assert len(result.recommendations) == 3
        assert all(item.reason.startswith('Suggested from our catalog') for item in result.recommendations)


def test_inputs_are_not_mutated_and_output_is_deterministic():
    preparation, profile = prepare(count=3), copy.deepcopy(PROFILE)
    snapshot = copy.deepcopy((preparation, profile))
    for responses in ((valid([3, 1, 2]),), ('bad', valid([3, 1, 2])), ('bad', 'bad'), (InferenceError('down'),)):
        _, first = run(preparation, *responses, profile=profile)
        _, second = run(preparation, *responses, profile=profile)
        assert first == second
        assert (preparation, profile) == snapshot


# --- error boundaries ------------------------------------------------------------------------------

def test_unexpected_exceptions_from_the_inference_call_are_not_swallowed():
    for error in (RuntimeError('bug'), KeyError('x'), ValueError('y'), TypeError('z')):
        with pytest.raises(type(error)):
            run(prepare(count=3), error)


def test_unexpected_exceptions_from_the_validator_are_not_swallowed(monkeypatch):
    monkeypatch.setattr(selection, 'validate_rerank_response', Mock(side_effect=RuntimeError('validator bug')))
    with pytest.raises(RuntimeError):
        run(prepare(count=3), valid([1, 2, 3]))


def test_assembler_errors_are_not_converted_into_fallback(monkeypatch):
    monkeypatch.setattr(selection, 'assemble', Mock(side_effect=ValueError('assembler bug')))
    preparation = prepare(count=3)
    with pytest.raises(ValueError, match='assembler bug'):
        run(preparation, valid([1, 2, 3]))
    with pytest.raises(ValueError, match='assembler bug'):
        run(preparation, InferenceError('down'))             # the fallback path also surfaces assembler bugs


def test_assembler_error_on_success_path_does_not_trigger_a_retry(monkeypatch):
    monkeypatch.setattr(selection, 'assemble', Mock(side_effect=ValueError('assembler bug')))
    request = Mock(side_effect=[valid([1, 2, 3]), valid([1, 2, 3])])
    with pytest.raises(ValueError):
        selection_with(request, prepare(count=3), PROFILE)
    assert request.call_count == 1


# --- retry timeout, outcome and warning logs (step 10b) -----------------------------------------------

import io
import logging

from services import inference_client


def timeouts(request):
    return [call.kwargs.get('timeout') for call in request.call_args_list]


def test_timeout_constants():
    assert selection.RETRY_TIMEOUT_SECONDS == 60 and inference_client.INFERENCE_TIMEOUT_SECONDS == 120
    assert selection.RETRY_TIMEOUT_SECONDS < inference_client.INFERENCE_TIMEOUT_SECONDS


def test_first_attempt_keeps_the_default_timeout_and_only_the_retry_is_shortened():
    preparation = prepare(count=3)
    request, _ = run(preparation, valid([1, 2, 3]))
    assert timeouts(request) == [None] and request.call_args.kwargs == {}           # default (120 s) applies
    request, _ = run(preparation, 'bad', valid([1, 2, 3]))
    assert timeouts(request) == [None, selection.RETRY_TIMEOUT_SECONDS]
    request, _ = run(preparation, 'bad', 'bad')
    assert timeouts(request) == [None, 60]
    request, _ = run(preparation, 'bad', InferenceError('timeout'))
    assert timeouts(request) == [None, 60]


def test_transport_failure_on_the_first_call_is_unchanged_default_timeout_no_retry():
    request, result = run(prepare(count=3), InferenceError('down'))
    assert timeouts(request) == [None] and request.call_count == 1
    assert (result.used_fallback, result.attempts, result.fallback_reason) == (True, 1, 'inference_error')


def test_real_client_receives_120_then_60_seconds(monkeypatch):
    seen = []
    answers = iter(['{"selected": [1, 1, 2]}', valid([1, 2, 3])])

    def fake_urlopen(http_request, timeout):
        seen.append(timeout)
        content = next(answers)
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': content}}]}).encode())
    monkeypatch.setattr(inference_client, 'urlopen', fake_urlopen)
    result = selection.select_recommendations(prepare(count=3), PROFILE, URL)
    assert seen == [120, 60] and result.outcome == 'llm_after_retry'


def test_retry_still_sends_the_same_schema_and_a_copy_of_the_messages_with_the_short_timeout():
    preparation = prepare(count=3)
    snapshot = copy.deepcopy(preparation)
    request, _ = run(preparation, 'bad', valid([1, 2, 3]))
    assert request.call_args_list[1].args[2] is preparation.response_schema and preparation == snapshot


# --- outcome -------------------------------------------------------------------------------------------

def test_all_five_outcomes_from_real_selections():
    preparation = prepare(count=3)
    assert run(preparation, valid([1, 2, 3]))[1].outcome == selection.OUTCOME_LLM == 'llm'
    assert run(preparation, 'bad', valid([1, 2, 3]))[1].outcome == selection.OUTCOME_LLM_AFTER_RETRY == 'llm_after_retry'
    assert run(preparation, InferenceError('x'))[1].outcome == selection.OUTCOME_FALLBACK_INFERENCE_ERROR == 'fallback_inference_error'
    assert run(preparation, 'bad', InferenceError('x'))[1].outcome == 'fallback_inference_error'
    assert run(preparation, 'bad', 'bad')[1].outcome == selection.OUTCOME_FALLBACK_VALIDATION_ERROR == 'fallback_validation_error'
    assert run(reranker.prepare([], PROFILE, 10))[1].outcome == selection.OUTCOME_NO_CANDIDATES == 'no_candidates'


@pytest.mark.parametrize('fields,outcome', [
    (((), False, 0, None), 'no_candidates'), (((1,), False, 1, None), 'llm'), (((1,), False, 2, None), 'llm_after_retry'),
    (((1,), True, 1, 'inference_error'), 'fallback_inference_error'), (((1,), True, 2, 'inference_error'), 'fallback_inference_error'),
    (((1,), True, 2, 'validation_error'), 'fallback_validation_error')])
def test_outcome_is_derived_from_the_existing_fields(fields, outcome):
    result = selection.SelectionResult(*fields)
    assert result.outcome == outcome and tuple(result) == fields          # no new tuple field was added


def test_outcome_labels_are_distinct_and_the_result_is_still_immutable():
    labels = {selection.OUTCOME_LLM, selection.OUTCOME_LLM_AFTER_RETRY, selection.OUTCOME_FALLBACK_INFERENCE_ERROR,
              selection.OUTCOME_FALLBACK_VALIDATION_ERROR, selection.OUTCOME_NO_CANDIDATES}
    assert len(labels) == 5
    with pytest.raises(AttributeError):
        selection.SelectionResult((), False, 0, None).outcome = 'x'


# --- warning logs ----------------------------------------------------------------------------------------

def warnings(caplog):
    return [record for record in caplog.records if record.name == 'services.selection']


def messages_of(caplog):
    return [record.getMessage() for record in warnings(caplog)]


RETRY_LOG = 'LLM selection rejected, retrying once (reason=validation_error, attempt=1)'


def test_no_log_for_a_clean_success_or_for_zero_candidates(caplog):
    caplog.set_level(logging.DEBUG, logger='services.selection')
    run(prepare(count=3), valid([1, 2, 3]))
    run(reranker.prepare([], PROFILE, 10))
    assert warnings(caplog) == []


def test_retry_that_succeeds_logs_one_warning(caplog):
    caplog.set_level(logging.DEBUG, logger='services.selection')
    run(prepare(count=3), 'bad', valid([1, 2, 3]))
    assert messages_of(caplog) == [RETRY_LOG] and warnings(caplog)[0].levelno == logging.WARNING


def test_two_invalid_answers_log_the_retry_and_the_fallback(caplog):
    caplog.set_level(logging.DEBUG, logger='services.selection')
    run(prepare(count=3), 'bad', 'bad')
    assert messages_of(caplog) == [RETRY_LOG, 'Deterministic fallback used (reason=validation_error, attempts=2)']
    assert all(record.levelno == logging.WARNING for record in warnings(caplog))


def test_inference_error_logs_only_the_fallback(caplog):
    caplog.set_level(logging.DEBUG, logger='services.selection')
    run(prepare(count=3), InferenceError('down'))
    assert messages_of(caplog) == ['Deterministic fallback used (reason=inference_error, attempts=1)']
    caplog.clear()
    run(prepare(count=3), 'bad', InferenceError('down'))
    assert messages_of(caplog) == [RETRY_LOG, 'Deterministic fallback used (reason=inference_error, attempts=2)']


def test_logs_never_contain_prompts_answers_tokens_urls_or_exception_text(caplog):
    caplog.set_level(logging.DEBUG, logger='services.selection')
    preparation = prepare(count=3)
    secrets = ['SECRET-RAW-ANSWER', 'secret-token-123', 'internal-host', 'duplicate key', 'Title 2', 'Plot']
    run(preparation, '{"selected": [1, 1, 1], "note": "SECRET-RAW-ANSWER"}', '{"selected": [1, 2, 3], "note": "SECRET-RAW-ANSWER"}')
    run(preparation, InferenceError('Bearer secret-token-123 http://internal-host'))
    run(preparation, 'SECRET-RAW-ANSWER', InferenceError('Bearer secret-token-123 http://internal-host'))
    text = ' '.join(record.getMessage() + ' ' + str(record.args) + ' ' + str(record.exc_info) for record in warnings(caplog))
    assert warnings(caplog) and not any(secret in text for secret in secrets)
    assert URL not in text and all(record.exc_info is None for record in warnings(caplog))


def test_log_arguments_are_fixed_categories_and_counters_only(caplog):
    caplog.set_level(logging.DEBUG, logger='services.selection')
    run(prepare(count=3), 'bad', 'bad')
    for record in warnings(caplog):
        assert all(isinstance(arg, (int, str)) for arg in record.args)
        assert {arg for arg in record.args if isinstance(arg, str)} <= {'validation_error', 'inference_error'}


def test_outcome_and_logging_do_not_mutate_inputs(caplog):
    caplog.set_level(logging.DEBUG, logger='services.selection')
    preparation, profile = prepare(count=3), copy.deepcopy(PROFILE)
    snapshot = copy.deepcopy((preparation, profile))
    for responses in (('bad', 'bad'), ('bad', valid([1, 2, 3])), (InferenceError('down'),)):
        _, result = run(preparation, *responses, profile=profile)
        assert result.outcome
        assert (preparation, profile) == snapshot


# --- deterministic_top (shared by the fallback and the pipeline's overlap metric) --------------------------------------

def test_deterministic_top_is_the_fallback_selection():
    preparation = prepare(count=4, size=20)
    top = selection.deterministic_top(preparation)
    pool = list(preparation.candidates_by_key.values())
    assert top == sorted(pool, key=candidates.ranking_key)[:4] and len(top) == 4
    assert all(any(item is original for original in pool) for item in top)
    _, result = run(preparation, InferenceError('down'))
    assert ids(result) == [c.movie['id'] for c in top]


def test_deterministic_top_does_not_mutate_and_handles_small_and_empty_pools():
    preparation = prepare(count=10, pool=ranked_pool(3))
    snapshot = copy.deepcopy(preparation)
    assert len(selection.deterministic_top(preparation)) == 3 and preparation == snapshot
    assert selection.deterministic_top(reranker.prepare([], PROFILE, 10)) == []


def test_custom_timeouts_are_forwarded_to_the_first_call_and_the_retry():
    preparation = prepare(count=3)
    request = Mock(side_effect=['not json', valid([5, 2, 4])])
    original = selection.request_rerank
    selection.request_rerank = request
    try:
        result = selection.select_recommendations(preparation, PROFILE, URL, 600, 300)
    finally:
        selection.request_rerank = original
    assert result.attempts == 2 and not result.used_fallback
    assert request.call_args_list[0].kwargs == {'timeout': 600}
    assert request.call_args_list[1].kwargs == {'timeout': 300}


def test_default_timeouts_are_unchanged_when_none_are_given():
    preparation = prepare(count=3)
    request, _ = run(preparation, 'not json', valid([5, 2, 4]))
    assert request.call_args_list[0].kwargs == {}
    assert request.call_args_list[1].kwargs == {'timeout': selection.RETRY_TIMEOUT_SECONDS}


def test_deterministic_selection_never_calls_inference_and_is_not_a_failure(caplog):
    preparation = prepare(count=4)
    request = Mock(side_effect=AssertionError('the LLM must not be called'))
    original = selection.request_rerank
    selection.request_rerank = request
    try:
        result = selection.deterministic_selection(preparation, PROFILE)
    finally:
        selection.request_rerank = original
    request.assert_not_called()
    assert (result.outcome, result.used_fallback, result.attempts, result.fallback_reason) == ('deterministic', False, 0, 'not_requested')
    assert ids(result) == [c.movie['id'] for c in selection.deterministic_top(preparation)]
    assert 'fallback' not in caplog.text.lower()


def test_deterministic_selection_equals_the_fallback_selection_content():
    preparation = prepare(count=4)
    _, fallback = run(preparation, InferenceError('down'))
    chosen = selection.deterministic_selection(preparation, PROFILE)
    assert fallback.used_fallback and not chosen.used_fallback
    assert [(i.candidate.movie['id'], i.score, i.reason) for i in chosen.recommendations] == \
           [(i.candidate.movie['id'], i.score, i.reason) for i in fallback.recommendations]


def test_deterministic_selection_with_nothing_to_select_is_no_candidates():
    result = selection.deterministic_selection(prepare(count=3, pool=[]), PROFILE)
    assert (result.outcome, result.recommendations) == ('no_candidates', ())
