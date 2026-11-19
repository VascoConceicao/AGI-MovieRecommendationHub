"""Selection with one retry and a deterministic fallback: pure orchestration over a prepared request.

The LLM selects among the prepared candidates. A transport failure falls back immediately (a failed
call may already have used the whole timeout); an invalid answer gets exactly one more attempt. Both
the LLM path and the fallback finish in the same assemble(), so ordering, scores and reasons never differ.
"""
import logging
from typing import NamedTuple, Optional

from services.assembly import assemble
from services.candidates import ranking_key
from services.inference_client import InferenceError, request_rerank
from services.reranker import RerankValidationError, validate_rerank_response

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
# Per-call socket timeout for the retry only. The retry shares the first prompt's prefix, which llama.cpp
# usually still has cached, so it is normally fast. Like the default, it is a socket timeout, not an
# overall deadline: the two configured timeouts reduce the expected worst case but do not enforce a limit.
RETRY_TIMEOUT_SECONDS = 60
FALLBACK_INFERENCE_ERROR = 'inference_error'
FALLBACK_VALIDATION_ERROR = 'validation_error'
NOT_REQUESTED = 'not_requested'        # not a fallback: the LLM was deliberately not asked (used_fallback stays False)
MAX_ERROR_DETAIL_CHARS = 200

OUTCOME_LLM = 'llm'
OUTCOME_LLM_AFTER_RETRY = 'llm_after_retry'
OUTCOME_FALLBACK_INFERENCE_ERROR = 'fallback_inference_error'
OUTCOME_FALLBACK_VALIDATION_ERROR = 'fallback_validation_error'
OUTCOME_NO_CANDIDATES = 'no_candidates'
OUTCOME_DETERMINISTIC = 'deterministic'     # chosen on purpose (e.g. background agent): the LLM was not asked, nothing failed


class SelectionResult(NamedTuple):
    recommendations: tuple                  # FinalRecommendation objects, final order
    used_fallback: bool
    attempts: int                           # inference calls made (0 when there was nothing to select)
    fallback_reason: Optional[str]          # None, FALLBACK_INFERENCE_ERROR, FALLBACK_VALIDATION_ERROR or NOT_REQUESTED

    @property
    def outcome(self):
        """One label for logs, metrics and the report: the six ways a selection can end."""
        if self.attempts == 0 and self.fallback_reason == NOT_REQUESTED:
            return OUTCOME_DETERMINISTIC
        if self.attempts == 0:
            return OUTCOME_NO_CANDIDATES
        if self.used_fallback:
            return (OUTCOME_FALLBACK_INFERENCE_ERROR if self.fallback_reason == FALLBACK_INFERENCE_ERROR
                    else OUTCOME_FALLBACK_VALIDATION_ERROR)
        return OUTCOME_LLM if self.attempts == 1 else OUTCOME_LLM_AFTER_RETRY


def _retry_messages(preparation, error):
    """A copy of the original messages plus a short corrective message; the raw answer is never echoed."""
    detail = str(error).strip()[:MAX_ERROR_DETAIL_CHARS]
    corrective = (f'Your previous response was invalid: {detail} Return exactly {preparation.target_count} '
                  f'distinct integer keys from 1 to {len(preparation.candidates_by_key)} as '
                  '{"selected":[...]} and nothing else.')
    return [*preparation.messages, {'role': 'user', 'content': corrective}]


def deterministic_top(preparation):
    """The top target_count prepared candidates by the deterministic ranking: the fallback selection."""
    return sorted(preparation.candidates_by_key.values(), key=ranking_key)[:preparation.target_count]


def _fallback(preparation, profile, attempts, reason):
    # Fixed category and counters only: never the exception text, the prompt or the model's answer.
    logger.warning('Deterministic fallback used (reason=%s, attempts=%d)', reason, attempts)
    return SelectionResult(assemble(deterministic_top(preparation), profile), True, attempts, reason)


def deterministic_selection(preparation, profile):
    """The deterministic top-N chosen on purpose, without calling the LLM. Same assemble() as every other path, so
    ordering, scores and reasons are identical; not a failure, so no fallback flag and no warning."""
    if preparation.target_count == 0:
        return SelectionResult((), False, 0, None)
    return SelectionResult(assemble(deterministic_top(preparation), profile), False, 0, NOT_REQUESTED)


def select_recommendations(preparation, profile, inference_url, timeout=None, retry_timeout=None):
    """Final recommendations for a prepared request: LLM selection when usable, deterministic top-N otherwise.

    timeout / retry_timeout override the per-call socket timeouts (seconds) of the first call and of the retry;
    None keeps the module defaults. CPU-only inference needs far larger values than a GPU server.
    """
    if preparation.target_count == 0:
        return SelectionResult((), False, 0, None)
    messages = preparation.messages
    for attempt in range(1, MAX_ATTEMPTS + 1):
        options = ({'timeout': timeout} if timeout else {}) if attempt == 1 else {'timeout': retry_timeout or RETRY_TIMEOUT_SECONDS}
        try:
            raw = request_rerank(inference_url, messages, preparation.response_schema, **options)
        except InferenceError:
            return _fallback(preparation, profile, attempt, FALLBACK_INFERENCE_ERROR)
        try:
            selected = validate_rerank_response(raw, preparation)
        except RerankValidationError as error:
            if attempt == MAX_ATTEMPTS:
                return _fallback(preparation, profile, attempt, FALLBACK_VALIDATION_ERROR)
            logger.warning('LLM selection rejected, retrying once (reason=%s, attempt=%d)',
                           FALLBACK_VALIDATION_ERROR, attempt)
            messages = _retry_messages(preparation, error)
            continue
        return SelectionResult(assemble(selected, profile), False, attempt, None)
