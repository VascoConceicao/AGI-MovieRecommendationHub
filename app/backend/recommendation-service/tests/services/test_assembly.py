import copy
import itertools
import random
from datetime import datetime, timezone

import pytest
from services import assembly, candidates, reasons

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def film(n, genres=('Drama',), directors=('D',), actors=('A',), languages=('en',), year=2000, minutes=100):
    return {'id': '%032d' % n, 'title': 'Title %d' % n, 'original_title': None, 'synopsis': 'Plot', 'release_date': None,
            'year': year, 'duration_minutes': minutes, 'genres': list(genres), 'actors': list(actors),
            'directors': list(directors), 'languages': list(languages), 'countries': ['US']}


def profile_of(*watched):
    context = {'as_of': NOW, 'watchlist': [], 'watched': [
        {'movie_id': m['id'], 'watched_at': None, 'recorded_at': NOW, 'effective_at': NOW} for m in watched]}
    return candidates.build_profile(context, list(watched))


LIKED = film(1, genres=['Action', 'Science Fiction'], directors=['Denis Villeneuve'], actors=['Ann Star'], year=2015, minutes=120)
PROFILE = profile_of(LIKED)
COLD = profile_of()


def sample_pool():
    """Distinct movies with clearly different deterministic scores."""
    movies = [film(2, genres=['Action', 'Science Fiction'], directors=['Denis Villeneuve'], actors=['Ann Star'], year=2015, minutes=120),
              film(3, genres=['Action'], year=2012, minutes=130),
              film(4, genres=['Science Fiction', 'Comedy'], year=1990, minutes=90),
              film(5, genres=['Comedy'], languages=['fr'], year=1960, minutes=200),
              film(6, genres=['Horror'], languages=['fr'], year=1950, minutes=300)]
    return [candidates.score_movie(movie, PROFILE) for movie in movies]


def ids(result):
    return [item.candidate.movie['id'] for item in result]


def test_final_order_follows_the_deterministic_score_not_the_input_order():
    pool = sample_pool()
    by_score = sorted(pool, key=lambda c: (-c.score, c.movie['id']))
    assert len({c.score for c in pool}) == len(pool)                 # fixture really has distinct scores
    for permutation in itertools.islice(itertools.permutations(pool), 0, 120, 7):
        assert ids(assembly.assemble(permutation, PROFILE)) == [c.movie['id'] for c in by_score]


def test_llm_returned_order_does_not_determine_final_order():
    pool = sample_pool()
    llm_order = [pool[4], pool[1], pool[3], pool[0], pool[2]]         # deliberately scrambled
    reordered = assembly.assemble(llm_order, PROFILE)
    assert ids(reordered) == ids(assembly.assemble(pool, PROFILE)) == [c.movie['id'] for c in pool]


def test_equal_scores_are_ordered_by_movie_uuid():
    pool = [candidates.score_movie(film(n), COLD) for n in (9, 3, 7, 1)]
    assert {c.score for c in pool} == {0.0}
    assert ids(assembly.assemble(pool, COLD)) == sorted(c.movie['id'] for c in pool)


def test_final_order_matches_step_6_ranking_semantics():
    movies = [film(n, genres=[('Action', 'Drama', 'Horror')[n % 3]], year=1950 + n * 3, minutes=80 + n * 4) for n in range(2, 40)]
    ranked = candidates.rank(movies, PROFILE)
    shuffled = list(ranked)
    random.Random(7).shuffle(shuffled)
    assert [c.movie['id'] for c in candidates.rank(movies, PROFILE)] == ids(assembly.assemble(shuffled, PROFILE))
    subset = sorted(random.Random(3).sample(ranked, 10), key=candidates.ranking_key)
    scrambled = list(subset)
    random.Random(4).shuffle(scrambled)
    assert ids(assembly.assemble(scrambled, PROFILE)) == [c.movie['id'] for c in subset]


def test_ordering_score_formula():
    assert [assembly.ordering_score(rank, 10) for rank in range(1, 11)] == pytest.approx([1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1])
    assert assembly.ordering_score(1, 10) == 1.0 and assembly.ordering_score(10, 10) == pytest.approx(0.1)
    assert assembly.ordering_score(1, 1) == 1.0 and assembly.ordering_score(3, 3) == pytest.approx(1 / 3)


@pytest.mark.parametrize('rank,total', [(0, 5), (6, 5), (-1, 5), (1, 0), (1, -3)])
def test_ordering_score_rejects_impossible_positions(rank, total):
    with pytest.raises(ValueError):
        assembly.ordering_score(rank, total)


@pytest.mark.parametrize('size', [1, 2, 5, 10, 15, 20, 40])
def test_scores_are_strictly_decreasing_and_within_zero_exclusive_one_inclusive(size):
    pool = [candidates.score_movie(film(n, genres=[('Action', 'Drama')[n % 2]], year=1990 + n), PROFILE) for n in range(2, size + 2)]
    scores = [item.score for item in assembly.assemble(pool, PROFILE)]
    assert scores[0] == 1.0 and all(0 < score <= 1 for score in scores)
    assert all(a > b for a, b in zip(scores, scores[1:]))


def test_scores_do_not_depend_on_the_deterministic_scores_or_ties():
    pool = [candidates.score_movie(film(n), COLD) for n in range(2, 7)]          # all deterministic scores are 0
    assert [item.score for item in assembly.assemble(pool, COLD)] == pytest.approx([1.0, 0.8, 0.6, 0.4, 0.2])


def test_empty_selection():
    assert assembly.assemble([], PROFILE) == () and assembly.assemble((), COLD) == ()


def test_single_recommendation():
    pool = sample_pool()
    [only] = assembly.assemble([pool[0]], PROFILE)
    assert only.score == 1.0 and only.candidate is pool[0]
    assert only.reason == reasons.explain(pool[0], PROFILE)


def test_reason_comes_from_the_deterministic_reasons_module():
    pool = sample_pool()
    for item in assembly.assemble(pool, PROFILE):
        assert item.reason == reasons.explain(item.candidate, PROFILE)
        assert 1 <= len(item.reason) <= reasons.MAX_REASON_CHARS


def test_each_reason_describes_its_own_movie():
    result = assembly.assemble(sample_pool(), PROFILE)
    by_id = {item.candidate.movie['id']: item.reason for item in result}
    assert 'Action and Science Fiction' in by_id['%032d' % 2]
    assert 'Science Fiction' in by_id['%032d' % 4] and 'Comedy' not in by_id['%032d' % 4]
    assert by_id['%032d' % 6].startswith('Suggested from our catalog (Horror')


def test_cold_start_recommendations_are_neutral_and_ordered_by_uuid():
    pool = [candidates.score_movie(film(n), COLD) for n in (5, 2, 4)]
    result = assembly.assemble(pool, COLD)
    assert ids(result) == ['%032d' % n for n in (2, 4, 5)]
    assert all(item.reason == 'Suggested from our catalog (Drama, 2000).' for item in result)


def test_original_candidate_identity_is_preserved():
    pool = sample_pool()
    for item in assembly.assemble(pool, PROFILE):
        assert isinstance(item, assembly.FinalRecommendation)
        assert any(item.candidate is original for original in pool)
        assert any(item.candidate.movie is original.movie for original in pool)


def test_final_recommendation_is_immutable():
    item = assembly.assemble(sample_pool(), PROFILE)[0]
    with pytest.raises(AttributeError):
        item.score = 0.5
    with pytest.raises(AttributeError):
        item.reason = 'changed'


def test_duplicate_selection_is_rejected():
    pool = sample_pool()
    with pytest.raises(ValueError):
        assembly.assemble([pool[0], pool[1], pool[0]], PROFILE)


def test_inputs_are_not_mutated_and_output_is_deterministic():
    pool, profile = sample_pool(), copy.deepcopy(PROFILE)
    snapshot = copy.deepcopy((pool, profile))
    first = assembly.assemble(pool, profile)
    assert (pool, profile) == snapshot
    assert first == assembly.assemble(list(reversed(pool)), copy.deepcopy(profile)) == assembly.assemble(pool, profile)


def test_same_function_serves_llm_selection_and_fallback_selection():
    full_pool = sorted(sample_pool(), key=candidates.ranking_key)
    llm_selection = [full_pool[3], full_pool[0], full_pool[2]]           # arbitrary subset, arbitrary order
    fallback_selection = full_pool[:3]                                   # top-N by deterministic rank
    assert ids(assembly.assemble(llm_selection, PROFILE)) == [full_pool[i].movie['id'] for i in (0, 2, 3)]
    assert ids(assembly.assemble(fallback_selection, PROFILE)) == [c.movie['id'] for c in full_pool[:3]]
    for selection in (llm_selection, fallback_selection):
        result = assembly.assemble(selection, PROFILE)
        assert [item.score for item in result] == pytest.approx([1.0, 2 / 3, 1 / 3])
