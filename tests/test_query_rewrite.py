import pytest

from app.config import settings
from app.retrieve.query_rewrite import clear_cache, rewrite_standalone_query


@pytest.fixture(autouse=True)
def _clear_rewrite_cache():
    """Different tests reuse question/history text under different mocked
    providers — without this, a later test could silently get an earlier
    test's cached rewrite instead of exercising its own mock."""
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def restore_rewrite_settings():
    original_enabled = settings.query_rewrite_enabled
    original_provider = settings.query_rewrite_provider
    original_model = settings.query_rewrite_model
    yield
    settings.query_rewrite_enabled = original_enabled
    settings.query_rewrite_provider = original_provider
    settings.query_rewrite_model = original_model


async def test_first_turn_returns_the_question_unchanged_with_no_llm_call(monkeypatch):
    """No history — nothing to resolve a pronoun against, so there is nothing
    for a rewrite to do. Must not spend an LLM call on it."""

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("generate() must not be called when there is no history")

    monkeypatch.setattr("app.llm.anthropic_client.AnthropicClient.generate", _fail_if_called)

    assert await rewrite_standalone_query("Ажлын цаг хэд вэ?", []) == "Ажлын цаг хэд вэ?"


async def test_disabled_rewrite_returns_the_question_unchanged_with_no_llm_call(
    restore_rewrite_settings, monkeypatch
):
    settings.query_rewrite_enabled = False

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("generate() must not be called when QUERY_REWRITE_ENABLED=false")

    monkeypatch.setattr("app.llm.anthropic_client.AnthropicClient.generate", _fail_if_called)

    history = [("user", "Жирэмсний амралт хэдэн хоног вэ?")]
    result = await rewrite_standalone_query("Тэгвэл цалинтай юу?", history)

    assert result == "Тэгвэл цалинтай юу?"


async def test_two_turn_followup_is_resolved_using_turn_one(
    restore_rewrite_settings, monkeypatch
):
    """Turn 2 ("Тэгвэл цалинтай юу?" — "Is it paid, then?") is meaningless on
    its own; it only resolves against turn 1's subject (pregnancy leave). The
    rewrite call must receive BOTH — the model can't resolve the pronoun off
    a prompt that never mentions leave — and the standalone result it hands
    back is what must reach the caller unchanged."""
    settings.query_rewrite_enabled = True
    settings.query_rewrite_provider = "anthropic"
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    history = [
        ("user", "Жирэмсний амралт хэдэн хоног вэ?"),
        ("assistant", "Жирэмсний амралт 120 хоног байна."),
    ]
    question = "Тэгвэл цалинтай юу?"
    standalone_question = "Жирэмсний амралтын үеэр цалин олгодог эсэх"

    captured = {}

    async def fake_generate(self, system, user, temperature=None):
        captured["user"] = user
        captured["temperature"] = temperature
        return standalone_question

    monkeypatch.setattr("app.llm.anthropic_client.AnthropicClient.generate", fake_generate)

    result = await rewrite_standalone_query(question, history)

    assert result == standalone_question
    # The prompt actually sent must carry turn 1's content and turn 2's
    # question — otherwise there is nothing for the model to resolve "тэгвэл"
    # against, regression-proofing exactly the wiring this feature depends on.
    assert "Жирэмсний амралт хэдэн хоног вэ?" in captured["user"]
    # The same followup must resolve to the same standalone question every
    # time (see LLMClient.generate's docstring) — never a fresh sample.
    assert captured["temperature"] == 0
    assert "120 хоног" in captured["user"]
    assert question in captured["user"]


async def test_asking_the_same_followup_twice_hits_the_cache_not_the_llm(
    restore_rewrite_settings, monkeypatch
):
    """The actual determinism guarantee: temperature=0 alone still isn't
    bit-exact on a hosted provider (see rephrase_cache.py), so the exact
    same question+history must reuse the first call's rewrite rather than
    risk sampling a different one."""
    settings.query_rewrite_enabled = True
    settings.query_rewrite_provider = "anthropic"
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    history = [("user", "Жирэмсний амралт хэдэн хоног вэ?")]
    question = "Тэгвэл цалинтай юу?"

    call_count = 0
    responses = iter(["Найруулга нэг", "Найруулга хоёр"])  # would differ if called twice

    async def fake_generate(self, system, user, temperature=None):
        nonlocal call_count
        call_count += 1
        return next(responses)

    monkeypatch.setattr("app.llm.anthropic_client.AnthropicClient.generate", fake_generate)

    first = await rewrite_standalone_query(question, history)
    second = await rewrite_standalone_query(question, history)

    assert call_count == 1
    assert second == first == "Найруулга нэг"


async def test_a_different_history_is_not_served_from_the_other_historys_cache_entry(
    restore_rewrite_settings, monkeypatch
):
    """The same followup text means something different depending on what
    came before it — the cache key must include history, not just the
    question."""
    settings.query_rewrite_enabled = True
    settings.query_rewrite_provider = "anthropic"
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    question = "Тэгвэл цалинтай юу?"
    call_count = 0

    async def fake_generate(self, system, user, temperature=None):
        nonlocal call_count
        call_count += 1
        return "Найруулсан асуулт"

    monkeypatch.setattr("app.llm.anthropic_client.AnthropicClient.generate", fake_generate)

    await rewrite_standalone_query(question, [("user", "Жирэмсний амралт хэдэн хоног вэ?")])
    await rewrite_standalone_query(question, [("user", "Ээлжийн амралт хэдэн хоног вэ?")])

    assert call_count == 2


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("429 rate limit exceeded"),
        ValueError("QUERY_REWRITE_PROVIDER='anthropic' requires ANTHROPIC_API_KEY"),
        TimeoutError("provider timed out"),
    ],
)
async def test_rewrite_failure_degrades_to_the_original_question(
    failure, restore_rewrite_settings, monkeypatch
):
    """Rewriting is a retrieval-quality optimization, never a dependency of
    answering — any failure must fall back to the raw question rather than
    failing the request."""
    settings.query_rewrite_enabled = True
    settings.query_rewrite_provider = "anthropic"
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    async def boom(self, system, user):
        raise failure

    monkeypatch.setattr("app.llm.anthropic_client.AnthropicClient.generate", boom)

    history = [("user", "Жирэмсний амралт хэдэн хоног вэ?")]
    result = await rewrite_standalone_query("Тэгвэл цалинтай юу?", history)

    assert result == "Тэгвэл цалинтай юу?"


async def test_empty_completion_degrades_to_the_original_question(
    restore_rewrite_settings, monkeypatch
):
    settings.query_rewrite_enabled = True
    settings.query_rewrite_provider = "anthropic"
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    async def fake_generate(self, system, user, temperature=None):
        return "   "

    monkeypatch.setattr("app.llm.anthropic_client.AnthropicClient.generate", fake_generate)

    history = [("user", "Жирэмсний амралт хэдэн хоног вэ?")]
    result = await rewrite_standalone_query("Тэгвэл цалинтай юу?", history)

    assert result == "Тэгвэл цалинтай юу?"


async def test_rewrite_provider_is_independent_of_generation_provider(
    restore_rewrite_settings, monkeypatch
):
    """Regression: rewriting must not construct AnthropicClient directly — an
    Ollama-only deployment must not need an Anthropic key to answer a
    followup question."""
    settings.query_rewrite_enabled = True
    settings.query_rewrite_provider = "ollama"
    settings.query_rewrite_model = "qwen2.5:7b"
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "llm_provider", "ollama")

    async def fake_generate(self, system, user, temperature=None):
        return "Жирэмсний амралтын үеэр цалин олгодог эсэх"

    monkeypatch.setattr("app.llm.ollama_client.OllamaClient.generate", fake_generate)

    history = [("user", "Жирэмсний амралт хэдэн хоног вэ?")]
    result = await rewrite_standalone_query("Тэгвэл цалинтай юу?", history)

    assert result == "Жирэмсний амралтын үеэр цалин олгодог эсэх"
