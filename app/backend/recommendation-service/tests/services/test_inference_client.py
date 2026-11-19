import copy
import io
import json
import socket
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest
from main import create_app
from services import inference_client as client

URL = 'http://inference:4210'
MESSAGES = [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'pick'}]
SCHEMA = {'type': 'object', 'properties': {'recommendations': {'type': 'array'}}, 'required': ['recommendations'],
          'additionalProperties': False}


def completion(content):
    return {'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': content}}]}


def serve(monkeypatch, body):
    def fake(request, timeout):
        if isinstance(body, Exception):
            raise body
        return io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode())
    mock = Mock(side_effect=fake)
    monkeypatch.setattr(client, 'urlopen', mock)
    return mock


def sent(mock):
    return mock.call_args.args[0], json.loads(mock.call_args.args[0].data)


def test_request_shape(monkeypatch):
    mock = serve(monkeypatch, completion('{}'))
    client.request_rerank(URL + '/', MESSAGES, SCHEMA)
    request, payload = sent(mock)
    assert request.full_url == 'http://inference:4210/v1/chat/completions'
    assert request.get_method() == 'POST'
    assert request.get_header('Content-type') == 'application/json'
    assert payload['messages'] == MESSAGES and payload['temperature'] == 0.2 == client.TEMPERATURE
    assert payload['response_format'] == {'type': 'json_schema', 'json_schema': {
        'name': client.RESPONSE_FORMAT_NAME, 'strict': True, 'schema': SCHEMA}}
    assert mock.call_args.kwargs == {'timeout': client.INFERENCE_TIMEOUT_SECONDS}
    assert 'model' not in payload


def test_returns_only_assistant_content_without_parsing(monkeypatch):
    raw = '{"recommendations":[{"key":999,"score":7,"reason":""}]}'  # semantically invalid is still a success here
    serve(monkeypatch, completion(raw))
    assert client.request_rerank(URL, MESSAGES, SCHEMA) == raw
    serve(monkeypatch, completion('not json at all'))
    assert client.request_rerank(URL, MESSAGES, SCHEMA) == 'not json at all'
    serve(monkeypatch, completion(''))
    assert client.request_rerank(URL, MESSAGES, SCHEMA) == ''


def test_uses_first_choice_and_ignores_extra_fields(monkeypatch):
    body = {'choices': [{'message': {'content': 'first'}}, {'message': {'content': 'second'}}], 'usage': {}, 'id': 'x'}
    serve(monkeypatch, body)
    assert client.request_rerank(URL, MESSAGES, SCHEMA) == 'first'


@pytest.mark.parametrize('failure', [
    HTTPError('http://inference', 500, 'boom', {}, io.BytesIO(b'{}')),
    HTTPError('http://inference', 400, 'bad', {}, io.BytesIO(b'{"error":"x"}')),
    URLError('refused'), ConnectionRefusedError(), TimeoutError(), socket.timeout()])
def test_transport_failures_raise_inference_error(monkeypatch, failure):
    serve(monkeypatch, failure)
    with pytest.raises(client.InferenceError):
        client.request_rerank(URL, MESSAGES, SCHEMA)


def test_http_error_message_has_status_but_no_url(monkeypatch):
    serve(monkeypatch, HTTPError('http://secret-host/v1', 503, 'busy', {}, io.BytesIO(b'{}')))
    with pytest.raises(client.InferenceError) as error:
        client.request_rerank(URL, MESSAGES, SCHEMA)
    assert '503' in str(error.value) and 'secret-host' not in str(error.value)


@pytest.mark.parametrize('body', [
    b'not json', b'', b'[]', b'"text"', b'null', {}, {'choices': None}, {'choices': []}, {'choices': {}},
    {'choices': ['x']}, {'choices': [{}]}, {'choices': [{'message': None}]}, {'choices': [{'message': {}}]},
    {'choices': [{'message': {'content': None}}]}, {'choices': [{'message': {'content': 5}}]},
    {'choices': [{'message': {'content': {'recommendations': []}}}]}, {'choices': [{'message': {'content': ['x']}}]}])
def test_malformed_envelope_raises_inference_error(monkeypatch, body):
    serve(monkeypatch, body)
    with pytest.raises(client.InferenceError):
        client.request_rerank(URL, MESSAGES, SCHEMA)


def test_no_retry_one_call_one_request(monkeypatch):
    mock = serve(monkeypatch, URLError('refused'))
    with pytest.raises(client.InferenceError):
        client.request_rerank(URL, MESSAGES, SCHEMA)
    assert mock.call_count == 1
    mock = serve(monkeypatch, {'choices': []})
    with pytest.raises(client.InferenceError):
        client.request_rerank(URL, MESSAGES, SCHEMA)
    assert mock.call_count == 1


def test_inputs_are_not_mutated(monkeypatch):
    messages, schema = copy.deepcopy(MESSAGES), copy.deepcopy(SCHEMA)
    serve(monkeypatch, completion('ok'))
    client.request_rerank(URL, messages, schema)
    assert (messages, schema) == (MESSAGES, SCHEMA)


def test_inference_url_is_configuration(monkeypatch):
    monkeypatch.delenv('INFERENCE_SERVICE_URL', raising=False)
    assert create_app().config['INFERENCE_SERVICE_URL'] == 'http://127.0.0.1:4210'
    monkeypatch.setenv('INFERENCE_SERVICE_URL', 'http://llm:9')
    assert create_app().config['INFERENCE_SERVICE_URL'] == 'http://llm:9'


def test_default_timeout_is_120_seconds_and_unchanged_without_an_argument(monkeypatch):
    assert client.INFERENCE_TIMEOUT_SECONDS == 120
    mock = serve(monkeypatch, completion('ok'))
    client.request_rerank(URL, MESSAGES, SCHEMA)
    assert mock.call_args.kwargs == {'timeout': 120}


def test_optional_timeout_overrides_the_default_for_that_call_only(monkeypatch):
    mock = serve(monkeypatch, completion('ok'))
    assert client.request_rerank(URL, MESSAGES, SCHEMA, timeout=60) == 'ok'
    assert mock.call_args.kwargs == {'timeout': 60}
    mock = serve(monkeypatch, completion('ok'))
    client.request_rerank(URL, MESSAGES, SCHEMA)
    assert mock.call_args.kwargs == {'timeout': client.INFERENCE_TIMEOUT_SECONDS}
    assert 'timeout' not in sent(mock)[1]                      # a transport setting, never sent to the server


def test_a_short_timeout_still_maps_failures_to_inference_error(monkeypatch):
    serve(monkeypatch, TimeoutError())
    with pytest.raises(client.InferenceError):
        client.request_rerank(URL, MESSAGES, SCHEMA, timeout=60)
