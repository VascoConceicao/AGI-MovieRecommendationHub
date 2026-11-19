"""Candidate generation: pure logic over the fetched catalog, no I/O."""
import math
from typing import NamedTuple

from services.filters import DURATIONS

HALF_LIFE_DAYS = 180        # an interaction this old counts half as much as one made today
WATCHLIST_WEIGHT = 0.6      # watchlist entries are weaker positive signals than watched movies
WEIGHTS = {'genre': 0.45, 'director': 0.15, 'actor': 0.15, 'language': 0.10, 'year': 0.10, 'duration': 0.05}
YEAR_SCALE = 15             # years away from the user's typical release year at which proximity is 1/e
DURATION_SCALE = 40         # minutes away from the user's typical runtime at which proximity is 1/e
TOP_BILLED_ACTORS = 5       # only the first billed actors count as signals
MIN_POOL_SIZE = 30
POOL_SIZE_FACTOR = 2

_DURATION_RANGES = {entry['id']: (entry['min'], entry['max']) for entry in DURATIONS}


def _any_of(values, wanted, fold=False):
    if not wanted:
        return True
    if fold:
        return bool({value.casefold() for value in values} & {name.casefold() for name in wanted})
    return bool(set(values) & set(wanted))


def matches(movie, filters):
    """True when the movie satisfies every active hard filter (OR within a field, AND across fields)."""
    filters = filters or {}
    for field in ('genres', 'languages'):
        if not _any_of(movie[field], filters.get(field)):
            return False
    for field in ('actors', 'directors'):
        if not _any_of(movie[field], filters.get(field), fold=True):
            return False
    year_from, year_to = filters.get('year_from'), filters.get('year_to')
    if (year_from is not None or year_to is not None) and movie['year'] is None:
        return False
    if year_from is not None and movie['year'] < year_from:
        return False
    if year_to is not None and movie['year'] > year_to:
        return False
    low, high = _DURATION_RANGES[filters.get('duration', 'any')]
    if low is not None or high is not None:
        minutes = movie['duration_minutes']
        if minutes is None or (low is not None and minutes < low) or (high is not None and minutes > high):
            return False
    return True


def hard_filter(catalog, watched_ids, filters):
    """Catalog movies the user has not watched that satisfy the filters, in catalog order.

    Watchlist movies stay eligible. The catalog and its movies are not modified.
    """
    watched = set(watched_ids)
    return [movie for movie in catalog if movie['id'] not in watched and matches(movie, filters)]


class Candidate(NamedTuple):
    """A catalog movie (the original, unmodified dict) with its deterministic score."""
    movie: dict
    score: float
    components: dict


def pool_size(count):
    return max(MIN_POOL_SIZE, POOL_SIZE_FACTOR * count)


def _age_days(moment, now):
    if moment is None or now is None:
        return 0.0
    return max(0.0, (now - moment).total_seconds() / 86400)


def _normalized(totals):
    top = max(totals.values(), default=0)
    return {key: value / top for key, value in totals.items()} if top > 0 else {}


def _center(pairs):
    weight = sum(w for _, w in pairs)
    return sum(value * w for value, w in pairs) / weight if weight > 0 else None


def build_profile(context, catalog):
    """Recency-weighted preferences from watched history and watchlist.

    Each interaction weighs source_weight * 0.5 ** (age / HALF_LIFE_DAYS), aged against the
    context's as_of. Categorical affinities are scaled so the strongest value is 1.
    """
    by_id = {movie['id']: movie for movie in catalog}
    interactions = [(row['movie_id'], row['effective_at'], 1.0) for row in context.get('watched', [])]
    interactions += [(row['movie_id'], row['added_at'], WATCHLIST_WEIGHT) for row in context.get('watchlist', [])]
    interactions = [item for item in interactions if item[0] in by_id]
    now = context.get('as_of') or max((moment for _, moment, _ in interactions if moment), default=None)
    totals = {key: {} for key in ('genres', 'directors', 'actors', 'languages')}
    years, durations = [], []
    for movie_id, moment, source_weight in interactions:
        movie = by_id[movie_id]
        weight = source_weight * 0.5 ** (_age_days(moment, now) / HALF_LIFE_DAYS)
        for key in totals:
            values = movie[key][:TOP_BILLED_ACTORS] if key == 'actors' else movie[key]
            for value in dict.fromkeys(values):
                totals[key][value] = totals[key].get(value, 0.0) + weight
        if movie['year'] is not None:
            years.append((movie['year'], weight))
        if movie['duration_minutes'] is not None:
            durations.append((movie['duration_minutes'], weight))
    return {**{key: _normalized(values) for key, values in totals.items()},
            'year': _center(years), 'duration': _center(durations), 'interactions': len(interactions)}


def _proximity(value, center, scale):
    if value is None or center is None:
        return 0.0
    return math.exp(-abs(value - center) / scale)


def _capped_sum(scores):
    return min(1.0, sum(scores))


def _affinity(values, affinities, combine):
    scores = [affinities.get(value, 0.0) for value in values]
    return combine(scores) if scores else 0.0


def score_movie(movie, profile):
    """Score one movie in [0, 1]; missing metadata contributes 0 for its component."""
    components = {
        'genre': _affinity(movie['genres'], profile['genres'], _capped_sum),
        'director': _affinity(movie['directors'], profile['directors'], max),
        'actor': _affinity(movie['actors'][:TOP_BILLED_ACTORS], profile['actors'], _capped_sum),
        'language': _affinity(movie['languages'], profile['languages'], max),
        'year': _proximity(movie['year'], profile['year'], YEAR_SCALE),
        'duration': _proximity(movie['duration_minutes'], profile['duration'], DURATION_SCALE),
    }
    return Candidate(movie, min(1.0, max(0.0, sum(WEIGHTS[key] * value for key, value in components.items()))), components)


def ranking_key(candidate):
    """Sort key for Candidates: best score first, ties broken by movie UUID."""
    return (-candidate.score, candidate.movie['id'])


def rank(movies, profile):
    """Score and order movies: best first, ties broken by movie UUID.

    With no usable history every score is 0, so the order is by UUID alone: deterministic
    and (UUIDs being random) an unbiased but stable sample of the catalog.
    """
    return sorted((score_movie(movie, profile) for movie in movies), key=ranking_key)


def generate_candidates(catalog, context, filters, count):
    """Hard-filter, rank and truncate to pool_size(count); the profile uses the whole catalog."""
    watched_ids = [row['movie_id'] for row in context.get('watched', [])]
    eligible = hard_filter(catalog, watched_ids, filters)
    return rank(eligible, build_profile(context, catalog))[:pool_size(count)]
