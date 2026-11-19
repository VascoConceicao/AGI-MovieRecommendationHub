import copy
import re
from datetime import date, datetime, timezone

import pytest
from services import candidates, reasons

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
CLAIMS = re.compile(r"\b(liked|loved|enjoyed|favou?rite|masterpiece|highly rated|you watched|you have watched|you've watched)\b", re.I)


def film(n, genres=('Drama',), directors=('D',), actors=('A',), languages=('en',), year=2000, minutes=100, title=None):
    return {'id': '%032d' % n, 'title': title or 'Title %d' % n, 'original_title': None, 'synopsis': 'Plot', 'release_date': None,
            'year': year, 'duration_minutes': minutes, 'genres': list(genres), 'actors': list(actors),
            'directors': list(directors), 'languages': list(languages), 'countries': ['US']}


def context(watched=(), watchlist=()):
    return {'as_of': NOW, 'watched': [{'movie_id': m['id'], 'watched_at': None, 'recorded_at': NOW, 'effective_at': NOW} for m in watched],
            'watchlist': [{'movie_id': m['id'], 'added_at': NOW} for m in watchlist]}


def profile_of(*watched, watchlist=()):
    return candidates.build_profile(context(watched, watchlist), list(watched) + list(watchlist))


COLD = candidates.build_profile(context(), [])


def candidate(movie, profile):
    return candidates.score_movie(movie, profile)


def reason(movie, profile):
    return reasons.explain(candidate(movie, profile), profile)


LIKED = film(1, genres=['Action', 'Science Fiction'], directors=['Denis Villeneuve'], actors=['Ann Star', 'Bob Lead'],
             languages=['en'], year=2015, minutes=120)
PROFILE = profile_of(LIKED)


def test_genre_reason_names_only_genres_the_movie_has_and_the_user_prefers():
    movie = film(2, genres=['Action', 'Science Fiction', 'Comedy'], directors=['X'], actors=['Y'], languages=['fr'], year=1960, minutes=200)
    assert reason(movie, PROFILE) == 'Matches your interest in Action and Science Fiction.'
    assert 'Comedy' not in reason(movie, PROFILE)


def test_genre_the_user_has_no_affinity_for_is_never_mentioned():
    movie = film(2, genres=['Comedy', 'Action'], directors=['X'], actors=['Y'], languages=['fr'], year=1960, minutes=200)
    assert reason(movie, PROFILE) == 'Matches your interest in Action.'
    assert 'Comedy' not in reason(movie, PROFILE)


def test_weak_affinity_below_threshold_is_not_a_match():
    old, recent = film(1, genres=['Western']), film(2, genres=['Drama'])
    context_ = {'as_of': NOW, 'watchlist': [], 'watched': [
        {'movie_id': old['id'], 'watched_at': None, 'recorded_at': NOW.replace(year=2020), 'effective_at': NOW.replace(year=2020)},
        {'movie_id': recent['id'], 'watched_at': None, 'recorded_at': NOW, 'effective_at': NOW}]}
    profile = candidates.build_profile(context_, [old, recent])
    assert 0 < profile['genres']['Western'] < reasons.MIN_MATCH_AFFINITY
    movie = film(3, genres=['Western'], directors=['X'], actors=['Y'], languages=['fr'], year=1900, minutes=300)
    assert reason(movie, profile) == 'Suggested from our catalog (Western, 1900).'


def test_director_reason_requires_the_name_in_both_movie_and_profile():
    movie = film(2, genres=['Horror'], directors=['Denis Villeneuve'], actors=['Y'], languages=['fr'], year=1960, minutes=200)
    assert reason(movie, PROFILE) == 'Directed by Denis Villeneuve, whose work appears in your watched or saved movies.'
    other = film(3, genres=['Horror'], directors=['Someone Else'], actors=['Y'], languages=['fr'], year=1960, minutes=200)
    assert 'Someone Else' not in reason(other, PROFILE) and reason(other, PROFILE).startswith('Suggested from our catalog')


def test_actor_reason_uses_top_billed_names_present_in_the_profile():
    movie = film(2, genres=['Horror'], directors=['X'], actors=['Ann Star', 'Nobody', 'Bob Lead'], languages=['fr'], year=1960, minutes=200)
    assert reason(movie, PROFILE) == 'Featuring Ann Star and Bob Lead, cast members from your watched or saved movies.'
    single = film(3, genres=['Horror'], directors=['X'], actors=['Bob Lead'], languages=['fr'], year=1960, minutes=200)
    assert reason(single, PROFILE) == 'Featuring Bob Lead, a cast member from your watched or saved movies.'


def test_actor_outside_top_billed_is_not_mentioned():
    late = ['N1', 'N2', 'N3', 'N4', 'N5', 'Ann Star']
    movie = film(2, genres=['Horror'], directors=['X'], actors=late, languages=['fr'], year=1960, minutes=200)
    assert 'Ann Star' not in reason(movie, PROFILE)


def test_two_strongest_signals_are_combined_in_strength_order():
    movie = film(2, genres=['Action'], directors=['Denis Villeneuve'], actors=['Ann Star'], languages=['fr'], year=1960, minutes=200)
    assert reason(movie, PROFILE) == ('Matches your interest in Action; directed by Denis Villeneuve, '
                                      'whose work appears in your watched or saved movies.')
    assert 'Ann Star' not in reason(movie, PROFILE)       # only the two strongest signals are used


def test_language_year_and_runtime_are_never_mentioned():
    for languages, year, minutes in ((['en'], 2015, 120), (['fr'], 1950, 300), (['en', 'fr'], 2016, 121)):
        text = reason(film(2, genres=['Action'], directors=['X'], actors=['Y'], languages=languages, year=year, minutes=minutes), PROFILE)
        assert text == 'Matches your interest in Action.'


def test_matching_language_year_and_runtime_alone_do_not_make_a_personalized_reason():
    movie = film(2, genres=['Horror'], directors=['X'], actors=['Y'], languages=['en'], year=2015, minutes=120)
    assert reason(movie, PROFILE) == 'Suggested from our catalog (Horror, 2015).'


def test_cold_start_is_neutral_and_makes_no_preference_claim():
    text = reason(film(2, genres=['Action', 'Comedy', 'Drama']), COLD)
    assert text == 'Suggested from our catalog (Action and Comedy, 2000).'
    assert 'interest' not in text and 'your' not in text.lower()


def test_no_matching_preferences_is_neutral():
    movie = film(2, genres=['Horror'], directors=['X'], actors=['Y'], languages=['fr'], year=1900, minutes=300)
    assert reason(movie, PROFILE) == 'Suggested from our catalog (Horror, 1900).'


def test_missing_metadata_does_not_crash():
    bare = film(2, genres=[], directors=[], actors=[], languages=[], year=None, minutes=None)
    assert reason(bare, PROFILE) == reasons.NEUTRAL_MINIMUM and reason(bare, COLD) == reasons.NEUTRAL_MINIMUM
    assert reason(film(3, genres=[], year=2001, directors=['X'], actors=['Y'], languages=['fr']), COLD) == 'Suggested from our catalog (2001).'
    assert reason(film(4, genres=['Action'], year=None, directors=['X'], actors=['Y'], languages=['fr'], minutes=None), PROFILE) == \
        'Matches your interest in Action.'


def test_reasons_never_claim_liking_or_that_saved_movies_were_watched():
    saved_only = profile_of(watchlist=[LIKED])
    movies = [film(2, genres=['Action'], directors=['Denis Villeneuve'], actors=['Ann Star']), film(3, genres=['Horror'])]
    for profile in (PROFILE, saved_only, COLD):
        for movie in movies:
            text = reason(movie, profile)
            assert not CLAIMS.search(text), text
            if 'your' in text:
                assert 'watched or saved' in text


def test_watchlist_only_history_still_grounds_the_reason():
    saved_only = profile_of(watchlist=[LIKED])
    assert reason(film(2, genres=['Action'], directors=['X'], actors=['Y'], languages=['fr'], year=1900, minutes=300), saved_only) == \
        'Matches your interest in Action.'


def test_reasons_are_short_and_fall_back_when_names_are_too_long():
    long_name = 'N' * 150
    liked = film(1, genres=['Action'], directors=[long_name], actors=['Ann Star'], languages=['en'], year=2015, minutes=120)
    profile = profile_of(liked)
    both = film(2, genres=['Action'], directors=[long_name], actors=['Q'], languages=['fr'], year=1900, minutes=300)
    text = reason(both, profile)
    assert len(text) <= reasons.MAX_REASON_CHARS and text == 'Matches your interest in Action.'      # weakest signal dropped
    only_long = film(3, genres=['Horror'], directors=[long_name], actors=['Q'], languages=['fr'], year=1900, minutes=300)
    assert len(reason(only_long, profile)) <= reasons.MAX_REASON_CHARS
    giant = film(4, genres=['G' * 150, 'H' * 150], directors=['X'], actors=['Y'], languages=['fr'], year=1900, minutes=300)
    assert reason(giant, COLD) == reasons.NEUTRAL_MINIMUM


def test_every_reason_stays_within_the_limit():
    movies = [film(n, genres=['Action', 'Science Fiction', 'Drama'][:n % 3 + 1], directors=['Denis Villeneuve', 'X'][:n % 2 + 1],
                   actors=['Ann Star', 'Bob Lead', 'Z'][:n % 3 + 1], year=2015 + n % 4) for n in range(2, 14)]
    for movie in movies:
        assert 1 <= len(reason(movie, PROFILE)) <= reasons.MAX_REASON_CHARS


def test_reasons_never_mention_a_movie_title():
    pool = [film(n, genres=['Action'], directors=['Denis Villeneuve'], actors=['Ann Star'], title='Unmistakable Title %d' % n) for n in range(2, 8)]
    for movie in pool:
        text = reason(movie, PROFILE)
        assert not any(other['title'] in text for other in pool) and 'Title' not in text


def test_reason_depends_only_on_the_candidates_own_facts():
    one = film(2, genres=['Action'], directors=['X'], actors=['Y'], languages=['fr'], year=1900, minutes=300, title='One')
    two = film(3, genres=['Horror'], directors=['X'], actors=['Y'], languages=['fr'], year=1900, minutes=300, title='Two')
    assert 'Action' in reason(one, PROFILE) and 'Action' not in reason(two, PROFILE)


def test_same_inputs_give_identical_reasons_and_nothing_is_mutated():
    movie = film(2, genres=['Action'], directors=['Denis Villeneuve'], actors=['Ann Star'])
    scored, profile = candidate(movie, PROFILE), copy.deepcopy(PROFILE)
    snapshot = copy.deepcopy((scored, profile))
    first = reasons.explain(scored, profile)
    assert first == reasons.explain(scored, profile) == reasons.explain(copy.deepcopy(scored), copy.deepcopy(profile))
    assert (scored, profile) == snapshot


def test_components_missing_from_the_candidate_do_not_break_explain():
    movie = film(2, genres=['Action'], directors=['Denis Villeneuve'], actors=['X'], languages=['fr'], year=1900, minutes=300)
    bare = candidates.Candidate(movie, 0.5, {})
    assert reasons.explain(bare, PROFILE) == ('Matches your interest in Action; directed by Denis Villeneuve, '
                                              'whose work appears in your watched or saved movies.')


def test_language_is_never_mentioned():
    for languages in (['en'], ['fr'], ['en', 'fr']):
        for movie in (film(2, genres=['Action'], languages=languages), film(3, genres=['Horror'], languages=languages)):
            assert 'language' not in reason(movie, PROFILE).lower()
