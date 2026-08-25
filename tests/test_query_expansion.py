import pytest

from app.config import settings
from app.retrieve.query_expansion import expand_query


@pytest.fixture
def restore_expansion_settings():
    original_enabled = settings.query_expansion_enabled
    original_n = settings.query_expansion_n
    original_provider = settings.query_expansion_provider
    original_model = settings.query_expansion_model
    yield
    settings.query_expansion_enabled = original_enabled
    settings.query_expansion_n = original_n
    settings.query_expansion_provider = original_provider
    settings.query_expansion_model = original_model


async def test_disabled_expansion_returns_question_unchanged_with_no_llm_call(
    restore_expansion_settings, monkeypatch
):
    settings.query_expansion_enabled = False

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("AnthropicClient.generate must not be called when QUERY_EXPANSION_ENABLED=false")

    monkeypatch.setattr("app.llm.anthropic_client.AnthropicClient.generate", _fail_if_called)

    result = await expand_query("Ажлын цаг хэд вэ?")

    assert result == ["Ажлын цаг хэд вэ?"]


async def test_enabled_expansion_makes_exactly_one_llm_call_for_all_rephrasings(
    restore_expansion_settings, monkeypatch
):
    settings.query_expansion_enabled = True
    settings.query_expansion_n = 2
    settings.query_expansion_provider = "anthropic"
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    call_count = 0

    async def fake_generate(self, system, user):
        nonlocal call_count
        call_count += 1
        return "Амралтын хүсэлт хэдэн хоногийн өмнө өгөх вэ?\nЧөлөөний өргөдлийг хэзээ гаргах ёстой вэ?"

    monkeypatch.setattr("app.llm.anthropic_client.AnthropicClient.generate", fake_generate)

    question = "Чөлөө авахын өмнө хэдэн хоногийн өмнө мэдэгдэх вэ?"
    result = await expand_query(question)

    assert call_count == 1
    assert result == [
        question,
        "Амралтын хүсэлт хэдэн хоногийн өмнө өгөх вэ?",
        "Чөлөөний өргөдлийг хэзээ гаргах ёстой вэ?",
    ]


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("429 rate limit exceeded"),
        ValueError("QUERY_EXPANSION_PROVIDER='anthropic' requires ANTHROPIC_API_KEY"),
        TimeoutError("provider timed out"),
    ],
)
async def test_expansion_failure_degrades_to_the_plain_question(
    failure, restore_expansion_settings, monkeypatch
):
    """Expansion is a recall optimization, never a dependency of answering.
    Regression: any failure — a free-tier 429, a missing key — used to
    propagate and 500 the whole request instead of retrieving unexpanded."""
    settings.query_expansion_enabled = True
    settings.query_expansion_provider = "anthropic"
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    async def boom(self, system, user):
        raise failure

    monkeypatch.setattr("app.llm.anthropic_client.AnthropicClient.generate", boom)

    assert await expand_query("Ажлын цаг хэд вэ?") == ["Ажлын цаг хэд вэ?"]


async def test_misconfigured_expansion_provider_does_not_break_answering(
    restore_expansion_settings,
):
    """A bad provider name fails at build_client — inside the guarded block."""
    settings.query_expansion_enabled = True
    settings.query_expansion_provider = "not-a-real-provider"

    assert await expand_query("Ажлын цаг хэд вэ?") == ["Ажлын цаг хэд вэ?"]


async def test_expansion_provider_is_independent_of_generation_provider(
    restore_expansion_settings, monkeypatch
):
    """Regression: expansion used to construct AnthropicClient directly, so an
    Ollama-only deployment (the "no API cost" path) still called Anthropic on
    every question and broke outright with an empty ANTHROPIC_API_KEY."""
    settings.query_expansion_enabled = True
    settings.query_expansion_n = 1
    settings.query_expansion_provider = "ollama"
    settings.query_expansion_model = "qwen2.5:7b"
    # No Anthropic credentials anywhere — expansion must not need them.
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "llm_provider", "ollama")

    async def fake_generate(self, system, user):
        return "Өөр үг хэллэгээр найруулсан асуулт?"

    monkeypatch.setattr("app.llm.ollama_client.OllamaClient.generate", fake_generate)

    result = await expand_query("Ажлын цаг хэд вэ?")

    assert result == ["Ажлын цаг хэд вэ?", "Өөр үг хэллэгээр найруулсан асуулт?"]
