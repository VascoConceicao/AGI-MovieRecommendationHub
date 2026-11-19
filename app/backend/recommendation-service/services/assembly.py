"""Final recommendation assembly: pure logic shared by the LLM-selected and the fallback paths.

Whatever selected the Candidates, the final order, the stored score and the reason are derived here
from trusted deterministic data only.
"""
from typing import NamedTuple

from services.candidates import ranking_key
from services.reasons import explain


class FinalRecommendation(NamedTuple):
    candidate: object   # the original Candidate (not a copy)
    score: float        # positional ordering value, see ordering_score
    reason: str


def ordering_score(rank, total):
    """Value stored in the DB score column so that listing by score DESC reproduces the final order.

    It is (total - rank + 1) / total, strictly decreasing in rank and within (0, 1]. It encodes position
    only: it is NOT a relevance probability, a similarity, or a model confidence.
    """
    if total < 1 or not 1 <= rank <= total:
        raise ValueError('rank must be between 1 and total')
    return (total - rank + 1) / total


def assemble(selected, profile):
    """Order the selected Candidates like Step 6 (best deterministic score first, ties by movie UUID),
    then attach the positional ordering score and a grounded reason to each."""
    ordered = sorted(selected, key=ranking_key)
    if len({candidate.movie['id'] for candidate in ordered}) != len(ordered):
        raise ValueError('selected candidates must be distinct')
    return tuple(FinalRecommendation(candidate, ordering_score(rank, len(ordered)), explain(candidate, profile))
                 for rank, candidate in enumerate(ordered, 1))
