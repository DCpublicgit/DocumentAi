import json

import httpx
import pytest

from app.config import settings
from app.llm import build_client, get_client
from app.llm.anthropic_client import AnthropicClient
from app.llm.ollama_client import OllamaClient
from app.llm.openai_compatible_client import OpenAICompatibleClient
from app.llm import openai_compatible_client as occ


@pytest.fixture(autouse=True)
def api_keys_present(monkeypatch):
    """Hosted providers now fail fast on an empty key, so dispatch tests
    supply one — they assert which client is built, not credential handling
    (see test_missing_api_key_* below for that)."""
    for attr in ("anthropic_api_key", "openai_api_key", "gemini_api_key", "deepseek_api_key"):
        monkeypatch.setattr(settings, attr, "test-key")


@pytest.fixture
def restore_provider():
    original = settings.llm_provider
    yield
    settings.llm_provider = original


def test_anthropic_provider_dispatches_to_anthropic_client(restore_provider):
    settings.llm_provider = "anthropic"
    assert isinstance(get_client(), AnthropicClient)


def test_ollama_provider_dispatches_to_ollama_client(restore_provider):
    settings.llm_provider = "ollama"
    assert isinstance(get_client(), OllamaClient)


@pytest.mark.parametrize("provider", ["openai", "gemini", "deepseek"])
def test_openai_compatible_providers_share_one_client(provider, restore_provider):
    settings.llm_provider = provider
    assert isinstance(get_client(), OpenAICompatibleClient)


def test_unknown_provider_raises(restore_provider):
    settings.llm_provider = "not-a-real-provider"
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        get_client()


def test_ollama_needs_no_api_key(monkeypatch):
    """Local Ollama is the "no API cost" path — it must not require a key."""
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert isinstance(build_client("ollama", "qwen2.5:7b"), OllamaClient)


@pytest.mark.parametrize(
    "provider, key_attr, key_name",
    [
        ("anthropic", "anthropic_api_key", "ANTHROPIC_API_KEY"),
        ("openai", "openai_api_key", "OPENAI_API_KEY"),
        ("gemini", "gemini_api_key", "GEMINI_API_KEY"),
        ("deepseek", "deepseek_api_key", "DEEPSEEK_API_KEY"),
    ],
)
def test_missing_api_key_fails_at_construction_not_mid_request(
    provider, key_attr, key_name, monkeypatch
):
    monkeypatch.setattr(settings, key_attr, "")
    with pytest.raises(ValueError, match=key_name):
        build_client(provider, "some-model")


def test_error_message_names_the_setting_that_was_misconfigured():
    """Query expansion builds its client from QUERY_EXPANSION_PROVIDER, so a
    bad value there must not report itself as a bad LLM_PROVIDER."""
    with pytest.raises(ValueError, match="Unknown QUERY_EXPANSION_PROVIDER"):
        build_client("nonsense", "m", setting_name="QUERY_EXPANSION_PROVIDER")


# --- retry / backoff on transient upstream failures -------------------------
#
# A Gemini free-tier 429 used to reach the employee as a 500: one 30-question
# eval run lost 19 questions that way.

_OK_BODY = {"choices": [{"finish_reason": "stop", "message": {"content": "хариулт"}}]}
_SSE_BODY = (
    b'data: {"choices":[{"delta":{"content":"\\u0445\\u0430\\u0440\\u0438\\u0443"},'
    b'"finish_reason":null}]}\n\n'
    b"data: [DONE]\n\n"
)


@pytest.fixture
def fast_retries(monkeypatch):
    """Removes the real waiting and records what the client would have slept,
    so backoff is asserted on without the test actually sleeping."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(occ.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(settings, "llm_max_retries", 3)
    monkeypatch.setattr(settings, "llm_retry_base_delay", 1.0)
    monkeypatch.setattr(settings, "llm_retry_max_delay", 30.0)
    return slept


@pytest.fixture
def transport(monkeypatch):
    """Swaps in a MockTransport and returns a list the test appends responses
    to; each request pops the next one."""
    queued: list[httpx.Response] = []
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return queued.pop(0) if queued else httpx.Response(200, json=_OK_BODY)

    # Bound before patching: the factory replaces httpx.AsyncClient, so
    # calling it by name inside itself would recurse forever.
    real_client_cls = httpx.AsyncClient

    def factory(*_args, **_kwargs):
        return real_client_cls(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(occ.httpx, "AsyncClient", factory)
    return queued, calls


def _client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient("m", "https://example.test/v1", "k", 128)


async def test_generate_retries_a_429_and_then_succeeds(fast_retries, transport):
    queued, calls = transport
    queued.extend([httpx.Response(429), httpx.Response(429), httpx.Response(200, json=_OK_BODY)])

    assert await _client().generate("sys", "user") == "хариулт"
    assert len(calls) == 3, "should have retried twice before succeeding"
    assert len(fast_retries) == 2


async def test_generate_does_not_retry_a_400(fast_retries, transport):
    """A bad request is not transient — retrying burns quota and hides the
    real error. This is the shape of the credit-exhausted failure that wiped
    an earlier eval run."""
    queued, calls = transport
    queued.append(httpx.Response(400, json={"error": {"message": "bad request"}}))

    with pytest.raises(httpx.HTTPStatusError):
        await _client().generate("sys", "user")
    assert len(calls) == 1
    assert fast_retries == []


async def test_generate_gives_up_and_raises_after_max_retries(fast_retries, transport):
    queued, calls = transport
    queued.extend(httpx.Response(429) for _ in range(settings.llm_max_retries + 1))

    with pytest.raises(httpx.HTTPStatusError):
        await _client().generate("sys", "user")
    assert len(calls) == settings.llm_max_retries + 1


async def test_retry_after_header_overrides_computed_backoff(fast_retries, transport):
    """The provider knows when its own quota window resets; guessing shorter
    just wastes an attempt."""
    queued, _ = transport
    queued.extend(
        [httpx.Response(429, headers={"retry-after": "7"}), httpx.Response(200, json=_OK_BODY)]
    )

    await _client().generate("sys", "user")
    assert fast_retries == [7.0]


async def test_backoff_grows_and_is_bounded(fast_retries, transport):
    queued, _ = transport
    queued.extend([httpx.Response(429), httpx.Response(429), httpx.Response(200, json=_OK_BODY)])

    await _client().generate("sys", "user")
    first, second = fast_retries
    # Full jitter puts each delay in (0.5, 1.0] of its cap, so assert the
    # bounds rather than exact values.
    assert 0.5 < first <= 1.0
    assert 1.0 < second <= 2.0


async def test_stream_retries_a_429_before_any_token_is_emitted(fast_retries, transport):
    queued, calls = transport
    queued.extend([httpx.Response(429), httpx.Response(200, content=_SSE_BODY)])

    tokens = [t async for t in _client().stream("sys", "user")]

    assert tokens == ["хариу"]
    assert len(calls) == 2


# temperature — deterministic generation for query rewrite/expansion
# (app/retrieve/query_rewrite.py, app/retrieve/query_expansion.py), left at
# the provider default (None) for the main answer. See LLMClient.generate's
# docstring for why.


async def test_generate_sends_temperature_when_given(transport):
    queued, calls = transport
    queued.append(httpx.Response(200, json=_OK_BODY))

    await _client().generate("sys", "user", temperature=0)

    assert json.loads(calls[0].content)["temperature"] == 0


async def test_generate_omits_temperature_when_not_given(transport):
    queued, calls = transport
    queued.append(httpx.Response(200, json=_OK_BODY))

    await _client().generate("sys", "user")

    assert "temperature" not in json.loads(calls[0].content)


def test_ollama_payload_includes_temperature_when_given():
    payload = OllamaClient("m", "http://x", 128)._payload(
        "sys", "user", stream=False, temperature=0
    )
    assert payload["temperature"] == 0


def test_ollama_payload_omits_temperature_when_not_given():
    payload = OllamaClient("m", "http://x", 128)._payload("sys", "user", stream=False)
    assert "temperature" not in payload


class _FakeAnthropicMessages:
    """Records the kwargs AnthropicClient.generate passed to the real SDK
    call, without a network round trip or a real API key."""

    def __init__(self):
        self.captured = None

    async def create(self, **kwargs):
        self.captured = kwargs

        class _Response:
            stop_reason = "end_turn"
            content = []

        return _Response()


async def test_anthropic_generate_sends_temperature_when_given():
    client = AnthropicClient("m", "k", 128)
    fake_messages = _FakeAnthropicMessages()
    client._client.messages = fake_messages

    await client.generate("sys", "user", temperature=0)

    assert fake_messages.captured["temperature"] == 0


async def test_anthropic_generate_omits_temperature_when_not_given():
    client = AnthropicClient("m", "k", 128)
    fake_messages = _FakeAnthropicMessages()
    client._client.messages = fake_messages

    await client.generate("sys", "user")

    assert "temperature" not in fake_messages.captured
