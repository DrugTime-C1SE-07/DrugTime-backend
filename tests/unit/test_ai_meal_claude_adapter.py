"""Adapter Claude với HTTP giả lập, không gọi API thật (task 4.26: AC3, AC3b, AC8, AC9, AC18)."""

import json
import logging
import time

import anthropic
import httpx
import pytest

from drugtime.modules.ai_meal.adapters.outbound.claude_suggester import (
    EFFORT,
    ClaudeMealSuggester,
)
from drugtime.modules.ai_meal.domain.errors import LlmInvalidOutput, LlmUnavailable
from drugtime.modules.ai_meal.domain.model import DietaryDeclaration, MealSuggestionInput
from drugtime.modules.ai_meal.domain.prompt import LLM_OUTPUT_SCHEMA, build_prompt

KEY = "sk-ant-api03-SECRET-unit-test-key"
MODEL = "claude-sonnet-5-5"
SENSITIVE = "Tăng huyết áp"


def _prompt():
    return build_prompt(
        MealSuggestionInput.build(
            meal_type="toi",
            active_ingredients=["Losartan"],
            conditions=[SENSITIVE],
            avoid_foods=["Chuối"],
            allergies=DietaryDeclaration(False, ("Tôm",)),
            restrictions=DietaryDeclaration(True, ()),
        )
    )


def _message(text='{"meal_type":"toi","suggestions":[]}', stop_reason="end_turn", content=None):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": content if content is not None else [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }


class Recorder:
    def __init__(self, respond):
        self.requests, self.respond = [], respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.respond(request)


def _adapter(respond, timeout=8.0):
    rec = Recorder(respond)
    client = anthropic.DefaultHttpxClient(transport=httpx.MockTransport(rec))
    return ClaudeMealSuggester(
        api_key=KEY, model=MODEL, timeout_seconds=timeout, http_client=client
    ), rec


def _ok(request):
    return httpx.Response(200, json=_message())


def test_request_shape_and_secret__AC3(caplog):
    caplog.set_level(logging.DEBUG)
    adapter, rec = _adapter(_ok)
    assert adapter.suggest(_prompt()) == '{"meal_type":"toi","suggestions":[]}'
    (request,) = rec.requests
    assert request.url.path == "/v1/messages"
    assert request.headers["x-api-key"] == KEY
    body = json.loads(request.content)
    assert body["model"] == MODEL
    assert body["output_config"] == {
        "effort": EFFORT,
        "format": {"type": "json_schema", "schema": LLM_OUTPUT_SCHEMA},
    }
    assert body["messages"][0]["role"] == "user" and SENSITIVE in body["messages"][0]["content"]
    assert "thinking" not in body and "temperature" not in body
    assert KEY not in repr(adapter)
    assert KEY not in caplog.text and SENSITIVE not in caplog.text


def test_client_configured_no_retry_with_timeout__AC3_AC8():
    adapter, _ = _adapter(_ok, timeout=8.0)
    assert adapter._client.max_retries == 0
    assert adapter._client.timeout == 8.0


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_stop_reason_refusal_or_max_tokens__AC3b(stop_reason):
    adapter, _ = _adapter(lambda r: httpx.Response(
        200, json=_message(text='{"meal_type":"toi","sugg', stop_reason=stop_reason)))
    with pytest.raises(LlmInvalidOutput) as exc:
        adapter.suggest(_prompt())
    assert exc.value.reason == stop_reason


def test_missing_text_block_invalid__AC3b():
    adapter, _ = _adapter(lambda r: httpx.Response(200, json=_message(content=[])))
    with pytest.raises(LlmInvalidOutput) as exc:
        adapter.suggest(_prompt())
    assert exc.value.reason == "schema"


def test_timeout_raises_unavailable_once__AC8():
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    adapter, rec = _adapter(slow)
    started = time.monotonic()
    with pytest.raises(LlmUnavailable) as exc:
        adapter.suggest(_prompt())
    assert exc.value.reason == "timeout"
    assert len(rec.requests) == 1  # không retry
    assert time.monotonic() - started < 1.0


ERROR_BODY = {"type": "error", "error": {"type": "x", "message": f"bad key {KEY} {SENSITIVE}"}}


@pytest.mark.parametrize(
    "status,reason",
    [(401, "auth"), (403, "auth"), (429, "rate_limited"), (500, "upstream"),
     (529, "upstream"), (400, "upstream")],
)
def test_status_errors_mapped__AC9(status, reason):
    adapter, rec = _adapter(lambda r: httpx.Response(status, json=ERROR_BODY))
    with pytest.raises(LlmUnavailable) as exc:
        adapter.suggest(_prompt())
    assert exc.value.reason == reason
    assert len(rec.requests) == 1
    # AC9: message không chứa response thô; AC3: không chứa key.
    for text in (str(exc.value), repr(exc.value)):
        assert KEY not in text and "bad key" not in text and SENSITIVE not in text
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def test_network_error_mapped__AC9():
    def down(request):
        raise httpx.ConnectError("connection refused", request=request)

    adapter, _ = _adapter(down)
    with pytest.raises(LlmUnavailable) as exc:
        adapter.suggest(_prompt())
    assert exc.value.reason == "network"
