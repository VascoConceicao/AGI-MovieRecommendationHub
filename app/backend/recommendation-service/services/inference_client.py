"""Transport to the llama.cpp inference server (OpenAI-compatible chat completions).

One call is one HTTP request. The assistant content is returned as a raw string: parsing and
validating the recommendations is not this module's job.
"""
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

# Default per-call socket timeout. urllib applies it to each blocking socket operation (connect, reads); it is
# not a strict wall-clock deadline for the whole request. CPU inference of a ~14k character prompt can be slow.
INFERENCE_TIMEOUT_SECONDS = 120
TEMPERATURE = 0.2
RESPONSE_FORMAT_NAME = 'recommendations'


class InferenceError(Exception):
    """The inference server could not be reached or did not return a usable chat completion."""


def request_rerank(inference_url, messages, response_schema, timeout=INFERENCE_TIMEOUT_SECONDS):
    """POST the prepared messages and schema; return choices[0].message.content unchanged.

    timeout is the per-call socket timeout in seconds (see INFERENCE_TIMEOUT_SECONDS), not an overall deadline.
    """
    payload = {'messages': messages, 'temperature': TEMPERATURE,
               'response_format': {'type': 'json_schema',
                                  'json_schema': {'name': RESPONSE_FORMAT_NAME, 'strict': True, 'schema': response_schema}}}
    request = Request(inference_url.rstrip('/') + '/v1/chat/completions', data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.load(response)
    except HTTPError as error:
        raise InferenceError(f'Inference engine returned HTTP {error.code}.') from error
    except OSError as error:  # URLError, connection refused, timeouts
        raise InferenceError('Inference engine unavailable.') from error
    except ValueError as error:
        raise InferenceError('Inference engine returned an invalid response.') from error
    try:
        content = body['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as error:
        raise InferenceError('Inference engine returned an invalid response.') from error
    if not isinstance(content, str):
        raise InferenceError('Inference engine returned an invalid response.')
    return content
