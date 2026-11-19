"""Deterministic, grounded recommendation reasons: pure logic, no LLM.

A reason only states facts that can be checked against trusted data: the movie's own metadata, the
user's preference profile and the deterministic score components. The profile is built from watched
movies AND watchlist entries, so the wording is always "watched or saved", never "liked" or "watched".
Only concrete signals are mentioned (genres, directors, top-billed actors). Language, release year and
runtime are not: in a recent, mostly English catalog they match almost every movie and say nothing.
"""
from services.candidates import TOP_BILLED_ACTORS, WEIGHTS

MAX_REASON_CHARS = 200
MIN_MATCH_AFFINITY = 0.2        # share of the user's strongest value needed to count as a real match
MAX_NAMED_VALUES = 2            # genres / people named per signal
MAX_SIGNALS = 2                 # signals combined in one reason

HISTORY = 'your watched or saved movies'
SIGNALS = ('genre', 'director', 'actor')                    # also the tie-break priority
NEUTRAL_MINIMUM = 'Suggested from our catalog.'


def _strong_matches(values, affinities):
    """Values of the movie the profile has a meaningful affinity for, strongest first (ties by name)."""
    matched = [(value, affinities.get(value, 0.0)) for value in dict.fromkeys(values)]
    matched = [item for item in matched if item[1] >= MIN_MATCH_AFFINITY]
    return [value for value, _ in sorted(matched, key=lambda item: (-item[1], item[0]))][:MAX_NAMED_VALUES]


def _names(values):
    return ' and '.join(values)


def _plural(count, singular, plural):
    return singular if count == 1 else plural


def _matches(movie, profile):
    return {'genre': _strong_matches(movie['genres'], profile['genres']),
            'director': _strong_matches(movie['directors'], profile['directors']),
            'actor': _strong_matches(movie['actors'][:TOP_BILLED_ACTORS], profile['actors'])}


def _clause(signal, values):
    if signal == 'genre':
        return f'matches your interest in {_names(values)}'
    if signal == 'director':
        return f'directed by {_names(values)}, whose work appears in {HISTORY}'
    return f'featuring {_names(values)}, {_plural(len(values), "a cast member", "cast members")} from {HISTORY}'


def _neutral(movie):
    """Truthful, non-personal reason from the movie's own metadata only."""
    facts = [' and '.join(dict.fromkeys(movie['genres'][:MAX_NAMED_VALUES]))]
    if movie['year'] is not None:
        facts.append(str(movie['year']))
    facts = [fact for fact in facts if fact]
    return f'Suggested from our catalog ({", ".join(facts)}).' if facts else NEUTRAL_MINIMUM


def _sentence(clauses):
    text = '; '.join(clauses)
    return text[0].upper() + text[1:] + '.'


def explain(candidate, profile):
    """One short, truthful sentence for why this candidate is recommended (at most MAX_REASON_CHARS)."""
    movie, components = candidate.movie, candidate.components
    matches = {signal: values for signal, values in _matches(movie, profile).items() if values}
    if not matches:
        return _fit(_neutral(movie))

    def strength(signal):
        return (-WEIGHTS[signal] * components.get(signal, 0.0), SIGNALS.index(signal))

    clauses = [_clause(signal, matches[signal]) for signal in sorted(matches, key=strength)[:MAX_SIGNALS]]
    for count in range(len(clauses), 0, -1):          # drop the weakest signal if the text is too long
        text = _sentence(clauses[:count])
        if len(text) <= MAX_REASON_CHARS:
            return text
    return _fit(_neutral(movie))


def _fit(text):
    return text if len(text) <= MAX_REASON_CHARS else NEUTRAL_MINIMUM
