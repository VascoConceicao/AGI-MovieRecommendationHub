import copy
import json
import re
from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from services import candidates, reranker

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
UUID_PATTERN = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)


def film(n, **changes):
    movie = {'id': str(UUID(int=n)), 'title': 'Title %d' % n, 'original_title': 'Orig %d' % n, 'synopsis': 'A plot.',
             'release_date': date(2010, 5, 1), 'year': 2010, 'duration_minutes': 120, 'genres': ['Drama'],
             'actors': ['A1', 'A2', 'A3', 'A4', 'A5'], 'directors': ['D1'], 'languages': ['en'], 'countries': ['US'],
             'source': 'tmdb', 'source_id': '550', 'poster_key': 'abc.jpg', 'poster_url': '/api/movie/posters/abc.jpg',
             'created_at': '2026-10-01T00:00:00+00:00'}
    return {**movie, **changes}


def pool(size, **changes):
    movies = [film(n, **changes) for n in range(1, size + 1)]
    return [candidates.Candidate(movie, 1 - n / 100, {}) for n, movie in enumerate(movies, 1)]


def profile_for(*liked):
    context = {'as_of': NOW, 'watchlist': [], 'watched': [
        {'movie_id': m['id'], 'watched_at': None, 'recorded_at': NOW, 'effective_at': NOW} for m in liked]}
    return candidates.build_profile(context, list(liked))


EMPTY_PROFILE = candidates.build_profile({'as_of': NOW, 'watched': [], 'watchlist': []}, [])


def test_keys_follow_ranking_order_and_recover_candidates():
    ranked = pool(5)
    prepared = reranker.prepare(ranked, EMPTY_PROFILE, 3)
    assert list(prepared.candidates_by_key) == [1, 2, 3, 4, 5]
    assert [view['key'] for view in prepared.llm_candidates] == [1, 2, 3, 4, 5]
    for key, candidate in prepared.candidates_by_key.items():
        assert candidate is ranked[key - 1]
        assert prepared.llm_candidates[key - 1]['title'] == candidate.movie['title']


def test_llm_facing_output_never_contains_movie_uuids():
    ranked = pool(6)
    prepared = reranker.prepare(ranked, profile_for(ranked[0].movie), 3)
    facing = json.dumps([prepared.llm_candidates, prepared.profile_summary, prepared.messages, prepared.response_schema])
    for candidate in ranked:
        assert candidate.movie['id'] not in facing
    assert not UUID_PATTERN.search(facing)
    assert any(candidate.movie['id'] == str(UUID(int=1)) for candidate in prepared.candidates_by_key.values())  # internal only


def test_irrelevant_movie_fields_are_excluded():
    [view] = reranker.prepare(pool(1), EMPTY_PROFILE, 1).llm_candidates
    assert set(view) == {'key', 'title', 'year', 'genres', 'directors', 'actors', 'languages', 'runtime_minutes', 'synopsis'}
    for hidden in ('id', 'source', 'source_id', 'poster_key', 'poster_url', 'created_at', 'original_title', 'countries'):
        assert hidden not in view


def test_actors_and_directors_are_capped():
    [view] = reranker.prepare(pool(1, directors=['D1', 'D2', 'D3']), EMPTY_PROFILE, 1).llm_candidates
    assert view['actors'] == ['A1', 'A2', 'A3'][:reranker.MAX_ACTORS] and len(view['actors']) == reranker.MAX_ACTORS
    assert view['directors'] == ['D1', 'D2'][:reranker.MAX_DIRECTORS]


def test_synopsis_is_normalized_and_bounded():
    long = 'word ' * 200
    [view] = reranker.prepare(pool(1, synopsis=long), EMPTY_PROFILE, 1).llm_candidates
    assert len(view['synopsis']) <= reranker.MAX_SYNOPSIS_CHARS and view['synopsis'].endswith('…')
    [view] = reranker.prepare(pool(1, synopsis='  Two\n\n  lines\tof   text '), EMPTY_PROFILE, 1).llm_candidates
    assert view['synopsis'] == 'Two lines of text'
    exact = 'x' * reranker.MAX_SYNOPSIS_CHARS
    assert reranker.prepare(pool(1, synopsis=exact), EMPTY_PROFILE, 1).llm_candidates[0]['synopsis'] == exact


def test_missing_metadata_is_omitted():
    bare = pool(1, synopsis=None, year=None, duration_minutes=None, genres=[], directors=[], actors=[], languages=[])
    assert reranker.prepare(bare, EMPTY_PROFILE, 1).llm_candidates == [{'key': 1, 'title': 'Title 1'}]


def test_profile_summary_picks_strongest_affinities_deterministically():
    profile = {'genres': {'G%d' % n: n / 10 for n in range(1, 9)}, 'directors': {'b': 1.0, 'a': 1.0, 'c': 0.5},
               'actors': {'x': 0.2}, 'languages': {'en': 1.0, 'fr': 0.4}, 'year': 2009.6, 'duration': 117.4, 'interactions': 3}
    summary = reranker.summarize_profile(profile)
    assert summary['genres'] == ['G8', 'G7', 'G6', 'G5', 'G4'] and len(summary['genres']) == reranker.MAX_PROFILE_ITEMS
    assert summary['directors'] == ['a', 'b', 'c']          # tie broken by name
    assert summary['actors'] == ['x'] and summary['languages'] == ['en', 'fr']
    assert summary['typical_release_year'] == 2010 and summary['typical_runtime_minutes'] == 117
    assert reranker.summarize_profile(profile) == summary


def test_profile_summary_for_empty_cold_start_profile():
    assert reranker.summarize_profile(EMPTY_PROFILE) == {}
    prepared = reranker.prepare(pool(3), EMPTY_PROFILE, 2)
    assert prepared.profile_summary == {} and 'no usable viewing history' in prepared.messages[1]['content']
    assert 'User preference summary' not in prepared.messages[1]['content']


def test_profile_summary_from_real_profile_has_centres_and_appears_in_prompt():
    liked = film(99, genres=['Sci-Fi'], year=2014, duration_minutes=169, directors=['Nolan'])
    summary = reranker.summarize_profile(profile_for(liked))
    assert summary['genres'] == ['Sci-Fi'] and summary['directors'] == ['Nolan']
    assert summary['typical_release_year'] == 2014 and summary['typical_runtime_minutes'] == 169
    content = reranker.prepare(pool(3), profile_for(liked), 2).messages[1]['content']
    assert 'User preference summary' in content and '"typical_release_year":2014' in content


@pytest.mark.parametrize('size,count,target', [(30, 5, 5), (30, 10, 10), (30, 20, 20), (7, 10, 7), (3, 3, 3), (0, 10, 0)])
def test_target_count_is_requested_or_available(size, count, target):
    prepared = reranker.prepare(pool(size), EMPTY_PROFILE, count)
    assert prepared.target_count == target
    assert prepared.response_schema['properties']['selected']['minItems'] == target
    assert prepared.response_schema['properties']['selected']['maxItems'] == target


def test_invalid_count_is_rejected():
    for count in (0, -1):
        with pytest.raises(ValueError):
            reranker.prepare(pool(3), EMPTY_PROFILE, count)


def test_schema_is_selected_keys_only_with_exact_count():
    schema = reranker.prepare(pool(30), EMPTY_PROFILE, 10).response_schema
    assert schema == {'type': 'object', 'required': ['selected'], 'additionalProperties': False,
                      'properties': {'selected': {'type': 'array', 'minItems': 10, 'maxItems': 10,
                                                  'items': {'type': 'integer', 'minimum': 1, 'maximum': 30}}}}
    text = json.dumps(schema)
    assert 'score' not in text and 'reason' not in text


def test_messages_forbid_invented_movies_and_request_exact_distinct_keys():
    prepared = reranker.prepare(pool(12), profile_for(film(99)), 5)
    system, user = prepared.messages
    assert [system['role'], user['role']] == ['system', 'user']
    assert 'never invent' in system['content'] and 'only from the supplied candidates' in system['content']
    assert 'only by its integer "key"' in system['content'] and 'at most once' in system['content']
    assert '{"selected":[<key>,<key>,...]}' in system['content']
    assert 'exactly 5 of the 12 candidates' in user['content'] and 'exactly 5 distinct keys from 1 to 12' in user['content']
    assert 'order of the keys in your answer does not matter' in user['content']
    assert '"key":1,' in user['content'] and '"key":12,' in user['content'] and '"key":13' not in user['content']
    assert 'Title 1' in user['content'] and 'User preference summary' in user['content']


def test_prompt_keeps_ranking_visible_and_prioritizes_relevance_over_variety():
    system = reranker.prepare(pool(3), EMPTY_PROFILE, 2).messages[0]['content']
    assert 'listed in order of a preliminary relevance ranking (best first)' in system
    assert 'most relevant to the user preferences' in system
    assert 'variety only as a secondary factor between similarly relevant candidates' in system


def test_messages_do_not_ask_for_scores_or_reasons():
    for message in reranker.prepare(pool(5), profile_for(film(99)), 3).messages:
        assert 'score' not in message['content'].lower() and 'reason' not in message['content'].lower()


def test_messages_use_reduced_target_when_few_candidates():
    content = reranker.prepare(pool(4), EMPTY_PROFILE, 10).messages[1]['content']
    assert 'exactly 4 of the 4 candidates' in content and 'exactly 4 distinct keys from 1 to 4' in content


def test_preparation_is_deterministic():
    ranked, profile = pool(10), profile_for(film(99, genres=['Drama', 'Sci-Fi']))
    assert reranker.prepare(ranked, profile, 5) == reranker.prepare(list(ranked), copy.deepcopy(profile), 5)


def test_inputs_are_not_mutated_and_payload_is_independent():
    ranked, profile = pool(5), profile_for(film(99))
    snapshot = copy.deepcopy((ranked, profile))
    prepared = reranker.prepare(ranked, profile, 3)
    assert (ranked, profile) == snapshot
    prepared.llm_candidates[0]['genres'].append('Mutated')
    prepared.llm_candidates[0]['actors'].append('Mutated')
    assert ranked[0].movie['genres'] == ['Drama'] and ranked[0].movie['actors'] == ['A1', 'A2', 'A3', 'A4', 'A5']


# --- response validation -----------------------------------------------------------------------

from unittest.mock import Mock

from services import inference_client


def prepared(size=5, count=3):
    return reranker.prepare(pool(size), EMPTY_PROFILE, count)


def raw(keys):
    return json.dumps({'selected': keys})


def validate(content, preparation=None):
    return reranker.validate_rerank_response(content, preparation or prepared())


def rejected(content, preparation=None):
    with pytest.raises(reranker.RerankValidationError) as error:
        validate(content, preparation)
    return str(error.value)


def test_valid_response_returns_the_original_candidates_in_returned_order():
    preparation = prepared()
    result = validate('{"selected":[3,1,5]}', preparation)
    assert isinstance(result, tuple)
    assert list(result) == [preparation.candidates_by_key[key] for key in (3, 1, 5)]


@pytest.mark.parametrize('content', [
    '', '   ', 'not json', '{"selected": [', '[]', '"text"', 'null', '3', '{}', '{"other": []}',
    '{"selected": "x"}', '{"selected": null}', '{"selected": {}}',
    '{"selected": [], "extra": 1}',
    '```json\n{"selected": []}\n```', 'Here you go: {"selected": []}', '{"selected": []} Hope it helps!',
    '{"selected": [1, NaN, 3]}', '{"selected": [1, Infinity, 3]}', '{"selected": [1, -Infinity, 3]}',
    '{"selected": [1, 1e999, 3]}',
    '{"selected": [], "selected": []}',
    '{"recommendations": [{"key": 1, "score": 0.9, "reason": "old contract"}]}',
    '[' * 100000])
def test_envelope_rejected(content):
    rejected(content, prepared(size=0) if content.startswith('{"selected": []') else prepared())


def test_envelope_errors_are_specific_and_short():
    assert 'Malformed JSON' in rejected('nope')
    assert 'must be a JSON object' in rejected('[]')
    assert 'Missing "selected"' in rejected('{}')
    assert 'Missing "selected"' in rejected('{"recommendations": []}')
    assert 'must be an array' in rejected('{"selected": 1}')
    assert 'Unexpected top-level' in rejected('{"selected": [], "x": 1}', prepared(size=0))
    assert 'non-standard number NaN' in rejected('{"selected": [1, NaN, 3]}')
    huge = '{"selected": [1, 2, 3], "note": "' + 'secret prompt text ' * 5000 + '"}'
    assert len(rejected(huge)) < 200


def test_non_string_content_rejected():
    for content in (None, {'selected': []}, b'{}'):
        assert 'not a string' in rejected(content)


def test_count_must_match_target_exactly():
    preparation = prepared(size=10, count=3)
    assert len(validate(raw([1, 2, 3]), preparation)) == 3
    assert 'Expected 3 selected keys, got 2' in rejected(raw([1, 2]), preparation)
    assert 'Expected 3 selected keys, got 4' in rejected(raw([1, 2, 3, 4]), preparation)
    assert 'got 0' in rejected(raw([]), preparation)


def test_target_count_is_reduced_when_few_candidates():
    preparation = prepared(size=2, count=10)
    assert len(validate(raw([2, 1]), preparation)) == 2
    assert 'Expected 2' in rejected(raw([1]), preparation)


def test_zero_target_accepts_only_empty_selection():
    preparation = reranker.prepare([], EMPTY_PROFILE, 10)
    assert preparation.target_count == 0
    assert validate('{"selected": []}', preparation) == ()
    assert 'Expected 0' in rejected(raw([1]), preparation)


@pytest.mark.parametrize('item', [{'key': 1, 'score': 0.9, 'reason': 'old item shape'}, {'key': 1}, [1], 'x', None, 2.5, 1.0])
def test_selected_items_must_be_integers(item):
    assert 'integer' in rejected(raw([item, 2, 3]))


@pytest.mark.parametrize('key,message', [(6, 'unknown key 6'), (0, 'unknown key 0'), (-1, 'unknown key -1'), (999, 'unknown key'),
                                         (True, 'integer'), (False, 'integer'), (1.0, 'integer'),
                                         ('1', 'integer'), (None, 'integer')])
def test_invalid_keys_rejected(key, message):
    assert message in rejected(raw([key, 2, 3]))


def test_duplicate_keys_rejected():
    assert 'duplicate key 2' in rejected(raw([2, 1, 2]))
    assert 'Position 3' in rejected(raw([2, 1, 2]))


def test_valid_keys_map_to_the_exact_original_candidate_objects():
    preparation = prepared()
    result = validate(raw([4, 2, 5]), preparation)
    for key, candidate in zip((4, 2, 5), result):
        assert candidate is preparation.candidates_by_key[key]
        assert candidate.movie is preparation.candidates_by_key[key].movie


def test_returned_order_is_preserved_and_not_sorted():
    preparation = prepared()
    result = validate(raw([5, 2, 4]), preparation)
    assert list(result) == [preparation.candidates_by_key[key] for key in (5, 2, 4)]
    assert result[0] is preparation.candidates_by_key[5]


def test_validation_does_not_mutate_inputs_or_call_inference(monkeypatch):
    http = Mock(side_effect=AssertionError('no HTTP in the validator'))
    monkeypatch.setattr(inference_client, 'urlopen', http)
    preparation = prepared()
    snapshot = copy.deepcopy(preparation)
    originals = {key: candidate for key, candidate in preparation.candidates_by_key.items()}
    validate(raw([1, 2, 3]), preparation)
    assert preparation == snapshot
    assert all(preparation.candidates_by_key[key] is candidate for key, candidate in originals.items())
    http.assert_not_called()


def test_validation_errors_are_not_inference_errors():
    assert not issubclass(reranker.RerankValidationError, inference_client.InferenceError)
    assert not issubclass(inference_client.InferenceError, reranker.RerankValidationError)


def test_synopsis_cap_is_configurable_and_zero_omits_it():
    movie = film(1, synopsis='word ' * 200)
    assert len(reranker.llm_candidate(1, movie)['synopsis']) == reranker.MAX_SYNOPSIS_CHARS       # default unchanged
    assert len(reranker.llm_candidate(1, movie, 50)['synopsis']) == 50
    assert 'synopsis' not in reranker.llm_candidate(1, movie, 0)


def test_prompt_without_synopsis_is_much_shorter_but_keeps_every_candidate_key():
    ranked = pool(30, synopsis='A long synopsis. ' * 30)
    full = reranker.prepare(ranked, EMPTY_PROFILE, 10)
    short = reranker.prepare(ranked, EMPTY_PROFILE, 10, 0)
    size = lambda prepared: sum(len(message['content']) for message in prepared.messages)
    assert size(short) < size(full) * 0.7
    assert [c['key'] for c in short.llm_candidates] == list(range(1, 31))
    assert all('synopsis' not in c for c in short.llm_candidates)
    assert short.response_schema == full.response_schema and short.target_count == full.target_count
