"""LLM candidate selection: pure logic that turns ranked candidates into a closed-set prompt and
validates the model's answer.

The LLM is a selector, not a ranker: it receives the deterministic candidates under temporary integer
keys 1..N (our ranking order, never movie UUIDs) and returns only the keys it selects. Its order, and any
score or reason, are not used; the key -> Candidate mapping stays here so the pipeline can recover the
real movies. Real runs with Qwen2.5-3B did not show consistent improvement from LLM reranking (with the
ranking visible it echoed it; with it hidden its picks were close to noise), so robustness and
predictable behaviour are preferred over trusting the model's judgement.
"""
import json
from typing import NamedTuple

MAX_ACTORS = 3              # actors per candidate sent to the LLM
MAX_DIRECTORS = 2
MAX_SYNOPSIS_CHARS = 200
MAX_PROFILE_ITEMS = 5       # strongest values per preference category

PROFILE_CATEGORIES = ('genres', 'directors', 'actors', 'languages')


class Preparation(NamedTuple):
    target_count: int
    candidates_by_key: dict     # internal only: key -> Candidate (never sent to the LLM)
    llm_candidates: list        # compact, UUID-free candidate dicts, in key order
    profile_summary: dict
    messages: list
    response_schema: dict


def _synopsis(text, limit=MAX_SYNOPSIS_CHARS):
    if limit <= 0:
        return None                 # synopsis left out entirely: a much shorter prompt for slow CPU inference
    text = ' '.join((text or '').split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def llm_candidate(key, movie, synopsis_chars=MAX_SYNOPSIS_CHARS):
    """Compact LLM-facing view of a movie; fields that are missing or empty are omitted."""
    view = {'key': key, 'title': movie['title'], 'year': movie['year'], 'genres': list(movie['genres']),
            'directors': movie['directors'][:MAX_DIRECTORS], 'actors': movie['actors'][:MAX_ACTORS],
            'languages': list(movie['languages']), 'runtime_minutes': movie['duration_minutes'],
            'synopsis': _synopsis(movie['synopsis'], synopsis_chars)}
    return {name: value for name, value in view.items() if value not in (None, '', [])}


def summarize_profile(profile):
    """Strongest preferences from build_profile(); categories without data are omitted."""
    summary = {}
    for category in PROFILE_CATEGORIES:
        ranked = sorted(profile[category].items(), key=lambda item: (-item[1], item[0]))
        if ranked:
            summary[category] = [name for name, _ in ranked[:MAX_PROFILE_ITEMS]]
    if profile['year'] is not None:
        summary['typical_release_year'] = round(profile['year'])
    if profile['duration'] is not None:
        summary['typical_runtime_minutes'] = round(profile['duration'])
    return summary


def response_schema(candidate_count, target_count):
    """JSON schema of the expected LLM output: {"selected": [exactly target_count keys in 1..N]}.

    Key uniqueness is not expressible here (uniqueItems is not relied on); the validator enforces it.
    """
    return {'type': 'object',
            'properties': {'selected': {'type': 'array',
                                        'items': {'type': 'integer', 'minimum': 1, 'maximum': candidate_count},
                                        'minItems': target_count, 'maxItems': target_count}},
            'required': ['selected'], 'additionalProperties': False}


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


SYSTEM_PROMPT = (
    'You are the final selection step of a movie recommender. You are given a fixed list of candidate '
    'movies that were already filtered for one user and listed in order of a preliminary relevance ranking '
    '(best first). '
    'Select only from the supplied candidates and never invent or suggest any other movie. '
    'Identify every movie only by its integer "key" and use each key at most once. '
    'Choose the movies most relevant to the user preferences and candidate details; consider variety only '
    'as a secondary factor between similarly relevant candidates. '
    'Reply with a single JSON object of the form {"selected":[<key>,<key>,...]} and nothing else.')


def build_messages(llm_candidates, profile_summary, target_count):
    if profile_summary:
        preferences = 'User preference summary (strongest first): ' + _json(profile_summary)
    else:
        preferences = 'The user has no usable viewing history yet; rely mainly on the candidate order.'
    lines = '\n'.join(_json(candidate) for candidate in llm_candidates)
    task = (f'Select exactly {target_count} of the {len(llm_candidates)} candidates above. Return exactly '
            f'{target_count} distinct keys from 1 to {len(llm_candidates)}. The order of the keys in your '
            'answer does not matter.')
    return [{'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': f'{preferences}\n\nCandidates (one JSON object per line):\n{lines}\n\n{task}'}]


def prepare(candidates, profile, count, synopsis_chars=MAX_SYNOPSIS_CHARS):
    """Everything the inference call needs for one selection; callers skip the LLM when target_count is 0.

    synopsis_chars caps each candidate's synopsis in the prompt (0 omits it); the default is unchanged.
    """
    if count < 1:
        raise ValueError('count must be at least 1')
    target_count = min(count, len(candidates))
    by_key = {key: candidate for key, candidate in enumerate(candidates, start=1)}
    compact = [llm_candidate(key, candidate.movie, synopsis_chars) for key, candidate in by_key.items()]
    summary = summarize_profile(profile)
    return Preparation(target_count, by_key, compact, summary, build_messages(compact, summary, target_count),
                       response_schema(len(compact), target_count))


class RerankValidationError(Exception):
    """The inference call succeeded but its assistant content is unusable (not a transport failure)."""


def _reject_constant(name):
    raise ValueError(f'non-standard number {name}')


def _unique_properties(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('duplicate property name')
        result[name] = value
    return result


def _parse(raw):
    if not isinstance(raw, str):
        raise RerankValidationError('Assistant content is not a string.')
    try:
        return json.loads(raw, parse_constant=_reject_constant, object_pairs_hook=_unique_properties)
    except (ValueError, RecursionError) as error:
        detail = error.msg if isinstance(error, json.JSONDecodeError) else str(error)
        raise RerankValidationError(f'Malformed JSON: {detail}.') from error


def _candidate_for(position, key, candidates_by_key, seen):
    if type(key) is not int:
        raise RerankValidationError(f'Position {position}: key must be an integer.')
    if key not in candidates_by_key:
        raise RerankValidationError(f'Position {position}: unknown key {key}.')
    if key in seen:
        raise RerankValidationError(f'Position {position}: duplicate key {key}.')
    seen.add(key)
    return candidates_by_key[key]


def validate_rerank_response(raw_content, preparation):
    """Strictly parse the assistant content and map the selected keys back to the original Candidates.

    Returns the original Candidate objects (not copies) in the order the model returned them, or raises
    RerankValidationError. Ordering them is not this function's job. Keys must belong to
    preparation.candidates_by_key, which was built from the already filtered pool: that membership is the
    closed-set boundary, so filters and watched movies are not re-checked here.
    """
    data = _parse(raw_content)
    if not isinstance(data, dict):
        raise RerankValidationError('Response must be a JSON object.')
    if 'selected' not in data:
        raise RerankValidationError('Missing "selected".')
    if len(data) > 1:
        raise RerankValidationError('Unexpected top-level properties.')
    keys = data['selected']
    if not isinstance(keys, list):
        raise RerankValidationError('"selected" must be an array.')
    if len(keys) != preparation.target_count:
        raise RerankValidationError(f'Expected {preparation.target_count} selected keys, got {len(keys)}.')
    seen = set()
    return tuple(_candidate_for(position, key, preparation.candidates_by_key, seen)
                 for position, key in enumerate(keys, 1))
