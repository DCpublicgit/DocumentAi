"""Truncation must be reported, not hidden.

LLM_MAX_TOKENS is tight for Mongolian Cyrillic. When a provider stops at the
cap, the answer is cut mid-sentence but still ships with its "Эх сурвалж:"
citation list — and finish_reason used to be hardcoded "stop", telling the
client it was complete. A citation asserts the policy documents back the
statement (CONTRIBUTING.md rule 2), so "complete" must not be claimed on a fragment.
"""

import json

import pytest

from app.answering import AnswerOutcome
from app.llm.ollama_client import OllamaClient
from app.llm.openai_compatible_client import OpenAICompatibleClient


def test_outcome_defaults_to_stop():
    assert AnswerOutcome().finish_reason == "stop"


def test_truncated_outcome_reports_length():
    assert AnswerOutcome(truncated=True).finish_reason == "length"


@pytest.mark.parametrize(
    "client_factory",
    [
        lambda: OpenAICompatibleClient("m", "http://x/v1", "k", 16),
        lambda: OllamaClient("m", "http://x/v1", 16),
    ],
)
def test_clients_start_untruncated(client_factory):
    assert client_factory().truncated is False


@pytest.mark.parametrize(
    "finish_reason, expected",
    [("length", True), ("stop", False), (None, False)],
)
@pytest.mark.parametrize(
    "client_factory",
    [
        lambda: OpenAICompatibleClient("m", "http://x/v1", "k", 16),
        lambda: OllamaClient("m", "http://x/v1", 16),
    ],
)
async def test_stream_sets_truncated_from_finish_reason(
    finish_reason, expected, client_factory, monkeypatch
):
    """Both OpenAI-compatible clients read finish_reason off the SSE choice."""
    client = client_factory()

    payload = {"choices": [{"delta": {"content": "хэсэг"}, "finish_reason": finish_reason}]}
    lines = [f"data: {json.dumps(payload, ensure_ascii=False)}", "data: [DONE]"]

    class _FakeResponse:
        # The OpenAI-compatible client inspects status_code before streaming
        # so it can retry a 429 (see its retry loop); a healthy double has to
        # report a status like the real httpx.Response does.
        status_code = 200

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            for line in lines:
                yield line

    class _FakeStream:
        async def __aenter__(self):
            return _FakeResponse()

        async def __aexit__(self, *exc):
            return False

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, *args, **kwargs):
            return _FakeStream()

    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _FakeClient())

    tokens = [t async for t in client.stream("sys", "user")]

    assert tokens == ["хэсэг"]
    assert client.truncated is expected


@pytest.mark.parametrize(
    "content, expected",
    [("бодит хариулт", "бодит хариулт"), (None, ""), ("", "")],
)
async def test_null_content_does_not_crash_generate(content, expected, monkeypatch):
    """Gemini's OpenAI-compat endpoint returns content: null on a filtered or
    empty completion; .strip() on None used to 500 the request."""
    client = OpenAICompatibleClient("m", "http://x/v1", "k", 16)

    class _FakeResponse:
        status_code = 200  # see the streaming double above

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _FakeClient())

    assert await client.generate("sys", "user") == expected
