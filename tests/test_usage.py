"""Token and cost accounting. These pin the rules that keep a cost figure
honest: thinking tokens are billed as output, an unpriced model is unknown
(never free), and a request whose answer call went unrecorded is unknown
(never "cheap")."""

import httpx
import pytest

from app import pricing, usage
from app import audit as audit_module
from app.audit import build_record
from app.config import settings
from app.llm import build_client
from app.llm import openai_compatible_client as occ
from app.llm.openai_compatible_client import OpenAICompatibleClient
from app.retrieve.models import RetrievalResult


# --- billed_tokens ---------------------------------------------------------

def test_billed_output_includes_thinking_tokens_gemini_leaves_out_of_completion():
    """Measured 2026-10-08: gemini-3.8-flash reported 276 completion tokens but
    7,174 total on a 4,768-token prompt; the 2,130 missing tokens are thinking,
    billed as output."""
    tokens_in, tokens_out = usage.billed_tokens(
        {"prompt_tokens": 4768, "completion_tokens": 276, "total_tokens": 7174}
    )

    assert (tokens_in, tokens_out) == (4768, 2406)


def test_billed_output_is_completion_tokens_when_there_is_no_thinking():
    assert usage.billed_tokens(
        {"prompt_tokens": 5456, "completion_tokens": 276, "total_tokens": 5732}
    ) == (5456, 276)


def test_billed_tokens_tolerates_a_missing_usage_object():
    assert usage.billed_tokens(None) == (0, 0)
    assert usage.billed_tokens({}) == (0, 0)


# --- pricing ---------------------------------------------------------------

def test_cost_is_tokens_times_per_million_price():
    # 1M in at $0.30 + 1M out at $2.50
    assert pricing.cost_usd("gemini", "gemini-3.5-flash-lite", 1_000_000, 1_000_000) == pytest.approx(2.80)


def test_a_model_with_no_price_is_unknown_not_free():
    assert pricing.cost_usd("openai", "some-model-we-never-priced", 1000, 1000) is None


def test_local_ollama_costs_no_api_money():
    assert pricing.cost_usd("ollama", "qwen2.5:7b", 5000, 500) == 0.0


# --- UsageLog --------------------------------------------------------------

def test_log_sums_calls_across_roles():
    with usage.collect() as log:
        usage.record("expansion", "gemini", "gemini-3.5-flash-lite", 500, 35)
        usage.record("answer", "gemini", "gemini-3.5-flash-lite", 4800, 280)

    assert log.input_tokens == 5300
    assert log.output_tokens == 315
    assert log.cost_usd == pytest.approx((5300 * 0.30 + 315 * 2.50) / 1e6)


def test_one_unpriced_call_makes_the_whole_cost_unknown():
    """A partial sum would read as the request's real cost."""
    with usage.collect() as log:
        usage.record("expansion", "gemini", "gemini-3.5-flash-lite", 500, 35)
        usage.record("answer", "openai", "unpriced-model", 4800, 280)

    assert log.cost_usd is None
    assert log.input_tokens == 5300  # tokens are still real


def test_missing_answer_call_makes_totals_unknown_not_small():
    """A streamed answer without LLM_STREAM_USAGE records no answer call; the
    rewrite call alone must not be reported as the request's cost."""
    with usage.collect() as log:
        usage.record("rewrite", "gemini", "gemini-3.5-flash-lite", 1200, 35)
        usage.require_answer_call()

    assert log.incomplete
    assert log.cost_usd is None
    assert log.input_tokens is None and log.output_tokens is None


def test_recorded_answer_call_keeps_totals_known():
    with usage.collect() as log:
        usage.record("answer", "gemini", "gemini-3.5-flash-lite", 4800, 280)
        usage.require_answer_call()

    assert not log.incomplete
    assert log.cost_usd is not None


def test_nested_collect_joins_the_outer_log():
    """The eval harness opens a log around answer_question(), whose own
    collect() must add to it, not start a separate one."""
    with usage.collect() as outer:
        with usage.collect() as inner:
            usage.record("answer", "gemini", "gemini-3.5-flash-lite", 10, 5)
        assert inner is outer
    assert len(outer.calls) == 1


def test_record_outside_a_request_is_a_no_op():
    usage.record("answer", "gemini", "gemini-3.5-flash-lite", 10, 5)  # must not raise


# --- the audit row ---------------------------------------------------------

def _record(usage_log):
    return build_record(
        question="q", answer="a", result=RetrievalResult(), refused=False,
        streamed=False, finish_reason="stop", latency_ms=1, usage_log=usage_log,
    )


def test_audit_record_carries_tokens_cost_and_the_per_call_breakdown():
    with usage.collect() as log:
        usage.record("answer", "gemini", "gemini-3.5-flash-lite", 4800, 280)

    record = _record(log)

    assert record.input_tokens == 4800 and record.output_tokens == 280
    assert record.cost_usd == pytest.approx((4800 * 0.30 + 280 * 2.50) / 1e6)
    assert record.llm_calls[0]["role"] == "answer"


def test_audit_record_without_a_usage_log_is_unmeasured_not_zero():
    record = _record(None)

    assert record.input_tokens is None and record.cost_usd is None and record.llm_calls is None


def test_a_request_that_never_called_an_llm_records_zero_spend():
    """Gibberish / refused before the model: measured, and nothing was spent."""
    with usage.collect() as log:
        pass

    record = _record(log)

    assert record.input_tokens == 0 and record.cost_usd == 0


async def test_eval_runs_do_not_write_audit_rows(monkeypatch):
    monkeypatch.setattr(audit_module, "_disabled", False)
    audit_module.disable_writes()
    try:
        # With writes disabled this must return before touching the database.
        await audit_module.write_audit(_record(None))
    finally:
        monkeypatch.setattr(audit_module, "_disabled", False)


# --- clients ---------------------------------------------------------------

@pytest.fixture
def mock_http(monkeypatch):
    queued: list[httpx.Response] = []
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queued.pop(0)

    real = httpx.AsyncClient
    monkeypatch.setattr(occ.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(handler)))
    return queued, seen


def _client(role="answer"):
    client = OpenAICompatibleClient("gemini-3.5-flash-lite", "https://example.test/v1", "k", 128)
    client.provider = "gemini"
    client.role = role
    return client


async def test_generate_records_the_providers_reported_usage(mock_http):
    queued, _ = mock_http
    queued.append(httpx.Response(200, json={
        "choices": [{"finish_reason": "stop", "message": {"content": "x"}}],
        "usage": {"prompt_tokens": 4768, "completion_tokens": 276, "total_tokens": 7174},
    }))

    with usage.collect() as log:
        await _client("answer").generate("s", "u")

    call = log.calls[0]
    assert (call.role, call.provider, call.model) == ("answer", "gemini", "gemini-3.5-flash-lite")
    assert (call.input_tokens, call.output_tokens) == (4768, 2406)


async def test_stream_records_the_usage_chunk_and_survives_its_empty_choices(mock_http, monkeypatch):
    """The include_usage chunk has `choices: []`; indexing [0] on it used to be
    the only thing between this option and an IndexError mid-answer."""
    monkeypatch.setattr(settings, "llm_stream_usage", True)
    queued, seen = mock_http
    body = (
        b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        b'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":7,"total_tokens":107}}\n\n'
        b"data: [DONE]\n\n"
    )
    queued.append(httpx.Response(200, content=body))

    with usage.collect() as log:
        text = "".join([t async for t in _client().stream("s", "u")])

    assert text == "hi"
    assert (log.calls[0].input_tokens, log.calls[0].output_tokens) == (100, 7)
    assert b'"include_usage":true' in seen[0].content.replace(b" ", b"")


async def test_stream_options_are_not_sent_unless_enabled(mock_http, monkeypatch):
    """Not every OpenAI-compatible endpoint is known to accept it; a 400 here
    would break the live answer path."""
    monkeypatch.setattr(settings, "llm_stream_usage", False)
    queued, seen = mock_http
    queued.append(httpx.Response(200, content=b"data: [DONE]\n\n"))

    _ = [t async for t in _client().stream("s", "u")]

    assert b"stream_options" not in seen[0].content


def test_build_client_tags_the_role_from_the_setting_that_chose_it(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "k")

    assert build_client("gemini", "m", setting_name="QUERY_REWRITE_PROVIDER").role == "rewrite"
    assert build_client("gemini", "m", setting_name="QUERY_EXPANSION_PROVIDER").role == "expansion"
    assert build_client("gemini", "m").role == "answer"
    assert build_client("gemini", "m").provider == "gemini"
