import copy
import math
from datetime import date

import pytest
from services import candidates, filters


def movie(n, **changes):
    base = {'id': 'm%d' % n, 'title': 'Title %d' % n, 'original_title': None, 'synopsis': 'Plot',
            'release_date': date(2000, 1, 1), 'year': 2000, 'duration_minutes': 100,
            'genres': ['Drama'], 'actors': ['Ann Actor'], 'directors': ['Dan Director'],
            'languages': ['en'], 'countries': ['US']}
    return {**base, **changes}


def ids(result):
    return [item['id'] for item in result]


def run(catalog, **active):
    return ids(candidates.hard_filter(catalog, [], active))


CATALOG = [movie(1), movie(2, genres=['Sci-Fi'], languages=['fr']), movie(3, genres=['Drama', 'Sci-Fi'])]


def test_no_filters_keeps_catalog_order():
    assert ids(candidates.hard_filter(CATALOG, [], None)) == ['m1', 'm2', 'm3']
    assert run(CATALOG) == ['m1', 'm2', 'm3']
    assert run(CATALOG, genres=[], languages=[], actors=[], directors=[], year_from=None, year_to=None,
               duration='any', count=10) == ['m1', 'm2', 'm3']


def test_watched_movies_always_excluded_even_with_matching_filters():
    assert ids(candidates.hard_filter(CATALOG, ['m1', 'unknown'], {'genres': ['Drama']})) == ['m3']
    assert ids(candidates.hard_filter(CATALOG, {'m1', 'm2', 'm3'}, {})) == []


def test_watchlist_movies_are_not_excluded():
    # Only watched ids are passed in; a watchlist movie is an ordinary catalog movie.
    assert ids(candidates.hard_filter(CATALOG, ['m2'], {})) == ['m1', 'm3']


def test_genre_and_language_filters():
    assert run(CATALOG, genres=['Sci-Fi']) == ['m2', 'm3']
    assert run(CATALOG, languages=['fr']) == ['m2']
    assert run(CATALOG, languages=['de']) == []


def test_actor_and_director_filters_case_insensitive_exact():
    catalog = [movie(1), movie(2, actors=['Bob Star'], directors=['Eve Auteur'])]
    assert run(catalog, actors=['bob star']) == ['m2']
    assert run(catalog, actors=['ANN ACTOR']) == ['m1']
    assert run(catalog, directors=['eve auteur']) == ['m2']
    assert run(catalog, directors=['DAN DIRECTOR']) == ['m1']
    assert run(catalog, actors=['Bob']) == [] and run(catalog, directors=['Eve']) == []


def test_choices_within_one_field_are_or():
    catalog = [movie(1, genres=['Drama']), movie(2, genres=['Comedy']), movie(3, genres=['Horror'])]
    assert run(catalog, genres=['Drama', 'Comedy']) == ['m1', 'm2']
    assert run(catalog, actors=['nobody', 'ann actor']) == ['m1', 'm2', 'm3']


def test_different_fields_are_and():
    assert run(CATALOG, genres=['Sci-Fi'], languages=['en']) == ['m3']
    assert run(CATALOG, genres=['Drama'], languages=['fr']) == []
    assert run(CATALOG, genres=['Sci-Fi'], languages=['en'], directors=['dan director'], year_from=2000) == ['m3']


YEARS = [movie(n, year=year, release_date=date(year, 6, 1)) for n, year in enumerate((1999, 2000, 2010, 2015, 2016), 1)]


def test_year_bounds_are_inclusive():
    assert run(YEARS, year_from=2000) == ['m2', 'm3', 'm4', 'm5']
    assert run(YEARS, year_to=2015) == ['m1', 'm2', 'm3', 'm4']
    assert run(YEARS, year_from=2000, year_to=2015) == ['m2', 'm3', 'm4']
    assert run(YEARS, year_from=2010, year_to=2010) == ['m3']


@pytest.mark.parametrize('preset,expected', [
    ('any', ['m1', 'm89', 'm90', 'm120', 'm121', 'm180', 'm181']),
    ('short', ['m1', 'm89']), ('medium', ['m90', 'm120']),
    ('long', ['m121', 'm180']), ('epic', ['m181'])])
def test_every_duration_preset(preset, expected):
    catalog = [movie(n, id='m%d' % n, duration_minutes=n) for n in (1, 89, 90, 120, 121, 180, 181)]
    assert run(catalog, duration=preset) == expected


def test_duration_presets_come_from_the_filter_contract():
    assert set(candidates._DURATION_RANGES) == {entry['id'] for entry in filters.DURATIONS}


def test_missing_metadata_excluded_only_by_active_filter():
    bare = movie(1, genres=[], languages=[], actors=[], directors=[], year=None, release_date=None, duration_minutes=None)
    catalog = [bare, movie(2)]
    assert run(catalog) == ['m1', 'm2']
    assert run(catalog, duration='any', year_from=None, year_to=None, genres=[]) == ['m1', 'm2']
    for active in ({'genres': ['Drama']}, {'languages': ['en']}, {'actors': ['Ann Actor']}, {'directors': ['Dan Director']},
                   {'year_from': 1900}, {'year_to': 2100}, {'duration': 'medium'}):
        assert run(catalog, **active) == ['m2'], active


def test_empty_catalog_and_empty_result():
    assert candidates.hard_filter([], [], {'genres': ['Drama']}) == []
    assert run(CATALOG, genres=['Western']) == []


def test_matches_predicate_ignores_watched_and_handles_missing_filters():
    assert candidates.matches(movie(1), None) and candidates.matches(movie(1), {})
    assert candidates.matches(movie(1), {'genres': ['Drama'], 'year_from': 2000})
    assert not candidates.matches(movie(1), {'genres': ['Comedy']})


def test_inputs_are_not_mutated_and_original_objects_returned():
    catalog = [movie(1), movie(2, genres=['Sci-Fi'])]
    snapshot, active, watched = copy.deepcopy(catalog), {'genres': ['Drama', 'Sci-Fi'], 'actors': ['ann actor']}, ['m9']
    frozen = copy.deepcopy((active, watched))
    result = candidates.hard_filter(catalog, watched, active)
    assert catalog == snapshot and (active, watched) == frozen
    assert result[0] is catalog[0] and result[1] is catalog[1]
    assert result is not catalog


# --- profile, scoring, ranking and pool size -------------------------------------------------

from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def days_ago(days):
    return NOW - timedelta(days=days)


def ctx(watched=(), watchlist=(), as_of=NOW):
    return {'user_id': 'u', 'as_of': as_of,
            'watched': [{'movie_id': m, 'watched_at': None, 'recorded_at': at, 'effective_at': at} for m, at in watched],
            'watchlist': [{'movie_id': m, 'added_at': at} for m, at in watchlist]}


def film(n, genres=('Drama',), directors=('D',), actors=('A',), languages=('en',), year=2000, minutes=100):
    return movie(n, id='%032d' % n, genres=list(genres), directors=list(directors), actors=list(actors),
                 languages=list(languages), year=year, release_date=date(year, 1, 1) if year else None, duration_minutes=minutes)


def test_weights_sum_to_one():
    assert sum(candidates.WEIGHTS.values()) == pytest.approx(1.0)


def test_watched_history_builds_affinities():
    catalog = [film(1, genres=['Drama', 'Sci-Fi'], directors=['Nolan'], actors=['Bale'], languages=['en'], year=2010, minutes=150),
               film(2, genres=['Drama'], directors=['Villeneuve'], actors=['Gosling'], languages=['fr'], year=2020, minutes=130)]
    profile = candidates.build_profile(ctx(watched=[(catalog[0]['id'], NOW), (catalog[1]['id'], NOW)]), catalog)
    assert profile['genres'] == {'Drama': 1.0, 'Sci-Fi': 0.5}
    assert profile['directors'] == {'Nolan': 1.0, 'Villeneuve': 1.0} and profile['actors'] == {'Bale': 1.0, 'Gosling': 1.0}
    assert profile['languages'] == {'en': 1.0, 'fr': 1.0}
    assert profile['year'] == pytest.approx(2015) and profile['duration'] == pytest.approx(140)
    assert profile['interactions'] == 2


def test_watchlist_counts_with_lower_weight_than_watched():
    catalog = [film(1, genres=['Drama']), film(2, genres=['Comedy'])]
    both = candidates.build_profile(ctx(watched=[(catalog[0]['id'], NOW)], watchlist=[(catalog[1]['id'], NOW)]), catalog)
    assert both['genres']['Drama'] == 1.0 and both['genres']['Comedy'] == pytest.approx(candidates.WATCHLIST_WEIGHT)
    assert candidates.WATCHLIST_WEIGHT < 1
    only = candidates.build_profile(ctx(watchlist=[(catalog[1]['id'], NOW)]), catalog)
    assert only['genres'] == {'Comedy': 1.0} and only['interactions'] == 1


def test_recency_decay_prefers_newer_interactions_with_half_life():
    catalog = [film(1, genres=['Old']), film(2, genres=['New']), film(3, genres=['Half'])]
    profile = candidates.build_profile(ctx(watched=[(catalog[0]['id'], days_ago(400)), (catalog[1]['id'], days_ago(1)),
                                                    (catalog[2]['id'], days_ago(candidates.HALF_LIFE_DAYS))]), catalog)
    assert profile['genres']['New'] > profile['genres']['Half'] > profile['genres']['Old']
    assert profile['genres']['Half'] / profile['genres']['New'] == pytest.approx(0.5, rel=0.01)


def test_watched_uses_effective_at_and_watchlist_uses_added_at():
    catalog = [film(1, genres=['A']), film(2, genres=['B']), film(3, genres=['C']), film(4, genres=['D'])]
    context = ctx(watched=[(catalog[0]['id'], days_ago(1)), (catalog[1]['id'], days_ago(300))],
                  watchlist=[(catalog[2]['id'], days_ago(1)), (catalog[3]['id'], days_ago(300))])
    # watched_at/recorded_at must be ignored in favour of effective_at
    context['watched'][0]['recorded_at'] = days_ago(900)
    context['watched'][1]['watched_at'] = days_ago(0)
    genres = candidates.build_profile(context, catalog)['genres']
    assert genres['A'] > genres['B'] and genres['C'] > genres['D']
    assert genres['A'] == 1.0


def test_age_falls_back_to_newest_interaction_without_as_of_and_ignores_unknown_movies():
    catalog = [film(1, genres=['A']), film(2, genres=['B'])]
    context = ctx(watched=[(catalog[0]['id'], days_ago(0)), (catalog[1]['id'], days_ago(180)), ('missing', days_ago(1))], as_of=None)
    profile = candidates.build_profile(context, catalog)
    assert profile['genres']['B'] == pytest.approx(0.5) and profile['interactions'] == 2


def test_component_scores_for_each_signal():
    liked = film(1, genres=['Drama', 'Sci-Fi'], directors=['Nolan'], actors=['Bale', 'Caine'], languages=['en'], year=2010, minutes=150)
    profile = candidates.build_profile(ctx(watched=[(liked['id'], NOW)]), [liked])
    same = candidates.score_movie(liked, profile)
    assert same.components == pytest.approx({key: 1.0 for key in candidates.WEIGHTS}) and same.score == pytest.approx(1.0)
    assert candidates.score_movie(film(2, genres=['Drama', 'Comedy']), profile).components['genre'] == 1.0
    assert candidates.score_movie(film(2, genres=['Comedy']), profile).components['genre'] == 0.0
    assert candidates.score_movie(film(2, directors=['Nolan', 'X']), profile).components['director'] == 1.0
    assert candidates.score_movie(film(2, directors=['X']), profile).components['director'] == 0.0
    assert candidates.score_movie(film(2, actors=['Bale', 'X', 'Y', 'Z']), profile).components['actor'] == 1.0
    assert candidates.score_movie(film(2, actors=['X', 'Y']), profile).components['actor'] == 0.0
    assert candidates.score_movie(film(2, actors=['X', 'Y', 'Z', 'W', 'V', 'Bale']), profile).components['actor'] == 0.0  # beyond top billed
    assert candidates.score_movie(film(2, languages=['fr']), profile).components['language'] == 0.0
    assert candidates.score_movie(film(2, languages=['fr', 'en']), profile).components['language'] == 1.0


def test_year_and_duration_proximity():
    liked = film(1, year=2000, minutes=100)
    profile = candidates.build_profile(ctx(watched=[(liked['id'], NOW)]), [liked])
    near, far = candidates.score_movie(film(2, year=2002, minutes=105), profile), candidates.score_movie(film(3, year=1950, minutes=240), profile)
    assert near.components['year'] > far.components['year'] > 0 and near.components['duration'] > far.components['duration'] > 0
    assert candidates.score_movie(film(4, year=2000, minutes=100), profile).components['year'] == 1.0
    assert candidates.score_movie(film(5, year=2000 + candidates.YEAR_SCALE), profile).components['year'] == pytest.approx(math.exp(-1))


def test_scores_and_components_stay_in_unit_interval():
    catalog = [film(1, genres=['A', 'B'], year=1950, minutes=60), film(2, genres=['A'], year=2024, minutes=300),
               film(3, genres=['C'], actors=['X', 'Y']), film(4, genres=[], directors=[], actors=[], languages=[], year=None, minutes=None)]
    profile = candidates.build_profile(ctx(watched=[(catalog[0]['id'], days_ago(5))], watchlist=[(catalog[1]['id'], days_ago(2))]), catalog)
    for item in candidates.rank(catalog, profile):
        assert 0 <= item.score <= 1 and all(0 <= value <= 1 for value in item.components.values())


def test_missing_metadata_scores_zero_without_crashing():
    liked = film(1)
    profile = candidates.build_profile(ctx(watched=[(liked['id'], NOW)]), [liked])
    bare = film(2, genres=[], directors=[], actors=[], languages=[], year=None, minutes=None)
    result = candidates.score_movie(bare, profile)
    assert result.score == 0 and set(result.components.values()) == {0.0}
    # profile built from movies lacking year/duration leaves those components at zero
    profile = candidates.build_profile(ctx(watched=[(bare['id'], NOW)]), [bare])
    assert profile['year'] is None and profile['duration'] is None
    assert candidates.score_movie(liked, profile).score == 0


def test_ranking_is_best_first_and_deterministic():
    liked = film(1, genres=['Drama'])
    catalog = [film(2, genres=['Comedy']), film(3, genres=['Drama']), film(4, genres=['Comedy', 'Drama'])]
    profile = candidates.build_profile(ctx(watched=[(liked['id'], NOW)]), [liked] + catalog)
    first = [item.movie['id'] for item in candidates.rank(catalog, profile)]
    assert first[0] == catalog[1]['id'] and first[-1] == catalog[0]['id']
    assert first == [item.movie['id'] for item in candidates.rank(list(reversed(catalog)), profile)]


def test_equal_scores_are_ordered_by_uuid():
    profile = candidates.build_profile(ctx(), [])
    catalog = [film(3), film(1), film(2)]
    assert [item.movie['id'] for item in candidates.rank(catalog, profile)] == sorted(movie_['id'] for movie_ in catalog)


def test_cold_start_is_deterministic_and_independent_of_catalog_order():
    catalog = [film(n, genres=['G%d' % (n % 3)]) for n in range(1, 8)]
    for context in (ctx(), ctx(watched=[('unknown', NOW)])):
        profile = candidates.build_profile(context, catalog)
        assert profile['interactions'] == 0
        ranked = candidates.rank(catalog, profile)
        assert {item.score for item in ranked} == {0.0}
        assert [item.movie['id'] for item in ranked] == sorted(item['id'] for item in catalog)
        assert [item.movie['id'] for item in candidates.rank(list(reversed(catalog)), profile)] == [item.movie['id'] for item in ranked]


@pytest.mark.parametrize('count,expected', [(5, 30), (10, 30), (15, 30), (20, 40)])
def test_pool_size(count, expected):
    assert candidates.pool_size(count) == expected
    catalog = [film(n) for n in range(1, 61)]
    assert len(candidates.generate_candidates(catalog, ctx(), {}, count)) == expected


def test_fewer_candidates_than_pool_size_returns_all_of_them():
    catalog = [film(n) for n in range(1, 8)]
    assert len(candidates.generate_candidates(catalog, ctx(), {}, 10)) == 7
    assert candidates.generate_candidates(catalog, ctx(), {'genres': ['Western']}, 10) == []
    assert candidates.generate_candidates([], ctx(), {}, 10) == []


def test_generate_candidates_excludes_watched_keeps_watchlist_and_applies_filters():
    watched, listed = film(1, genres=['Drama']), film(2, genres=['Drama'])
    catalog = [watched, listed, film(3, genres=['Drama']), film(4, genres=['Comedy'])]
    context = ctx(watched=[(watched['id'], NOW)], watchlist=[(listed['id'], NOW)])
    result = [item.movie['id'] for item in candidates.generate_candidates(catalog, context, {'genres': ['Drama']}, 5)]
    assert watched['id'] not in result and listed['id'] in result and catalog[3]['id'] not in result
    assert result[0] == listed['id'] or result[0] == catalog[2]['id']


def test_scoring_does_not_mutate_inputs():
    catalog = [film(1, genres=['Drama']), film(2, genres=['Comedy'])]
    context = ctx(watched=[(catalog[0]['id'], days_ago(3))], watchlist=[(catalog[1]['id'], days_ago(9))])
    snapshot = copy.deepcopy((catalog, context, {'genres': ['Drama']}))
    result = candidates.generate_candidates(catalog, context, {'genres': ['Drama', 'Comedy']}, 5)
    assert (catalog, context) == snapshot[:2]
    assert all(item.movie is original for item, original in zip(result, [catalog[1]]))


def test_extra_unrelated_genres_do_not_dilute_a_strong_match():
    liked = film(1, genres=['Drama'])
    profile = candidates.build_profile(ctx(watched=[(liked['id'], NOW)]), [liked])
    plain = candidates.score_movie(film(2, genres=['Drama']), profile)
    padded = candidates.score_movie(film(3, genres=['Drama', 'Comedy', 'Horror', 'Western', 'Music']), profile)
    assert plain.components['genre'] == padded.components['genre'] == 1.0
    assert plain.score == pytest.approx(padded.score)


def test_extra_unrelated_actors_do_not_dilute_a_strong_match():
    liked = film(1, actors=['Bale'])
    profile = candidates.build_profile(ctx(watched=[(liked['id'], NOW)]), [liked])
    plain = candidates.score_movie(film(2, actors=['Bale']), profile)
    padded = candidates.score_movie(film(3, actors=['Bale', 'W', 'X', 'Y', 'Z']), profile)
    assert plain.components['actor'] == padded.components['actor'] == 1.0


def test_genre_and_actor_affinities_add_up_and_are_capped_at_one():
    movies = [film(1, genres=['A'], actors=['a']), film(2, genres=['B'], actors=['b']), film(3, genres=['C'], actors=['c'])]
    context = ctx(watched=[(movies[0]['id'], NOW), (movies[1]['id'], days_ago(180)), (movies[2]['id'], days_ago(360))])
    profile = candidates.build_profile(context, movies)
    assert profile['genres'] == pytest.approx({'A': 1.0, 'B': 0.5, 'C': 0.25})
    for key, field in (('genre', 'genres'), ('actor', 'actors')):
        values = ('B', 'C') if key == 'genre' else ('b', 'c')
        below_cap = candidates.score_movie(film(9, **{field: list(values)}), profile)
        assert below_cap.components[key] == pytest.approx(0.75)
        top_two = ('A', 'B') if key == 'genre' else ('a', 'b')
        assert candidates.score_movie(film(9, **{field: list(top_two)}), profile).components[key] == 1.0
        assert candidates.score_movie(film(9, **{field: list(values) + [top_two[0], 'x']}), profile).components[key] == 1.0


def test_actor_sum_only_counts_top_billed():
    liked = film(1, actors=['Bale'])
    profile = candidates.build_profile(ctx(watched=[(liked['id'], NOW)]), [liked])
    billed_late = film(2, actors=['W', 'X', 'Y', 'Z', 'V', 'Bale'])
    assert candidates.score_movie(billed_late, profile).components['actor'] == 0.0
