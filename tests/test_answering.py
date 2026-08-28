from datetime import date

import pytest

from app.answering import (
    StageEvent,
    _document_count,
    _resolve_used_context,
    _retrieve_and_prepare,
    compose_answer,
    stream_answer,
)
from app.contract import REFUSAL_STRING
from app.retrieve.models import RetrievalResult, RetrievedChunk


async def test_gibberish_input_short_circuits_before_retrieval(monkeypatch):
    """The gibberish gate must run BEFORE app.db.get_pool — that's the whole
    point (see app.query_guard's module docstring): skip the embedding/DB
    round trip entirely, not just skip generation after paying for it."""

    async def _fail_if_called():
        raise AssertionError("get_pool() was called — gibberish gate did not short-circuit")

    monkeypatch.setattr("app.answering.get_pool", _fail_if_called)

    result, user_message = await _retrieve_and_prepare("kjshdf lkjashdf lkasjdhf", [])

    assert result is None
    assert user_message is None


async def test_two_turn_followup_retrieves_against_the_rewritten_standalone_question(
    monkeypatch,
):
    """Turn 2 ("Тэгвэл цалинтай юу?") only means anything next to turn 1
    ("Жирэмсний амралт хэдэн хоног вэ?") — retrieval must run against the
    rewritten, context-resolved question app.retrieve.query_rewrite hands
    back, not the raw pronoun-bearing fragment the employee actually typed."""
    history = [
        ("user", "Жирэмсний амралт хэдэн хоног вэ?"),
        ("assistant", "Жирэмсний амралт 120 хоног байна."),
    ]
    question = "Тэгвэл цалинтай юу?"
    standalone_question = "Жирэмсний амралтын үеэр цалин олгодог эсэх"

    async def fake_rewrite(q, h):
        assert q == question
        assert h == history
        return standalone_question

    monkeypatch.setattr("app.answering.rewrite_standalone_query", fake_rewrite)

    async def fake_get_pool():
        return object()

    captured = {}

    async def fake_retrieve(pool, query):
        captured["query"] = query
        return RetrievalResult(chunks=[], top_score=0.0, refuse=True)

    monkeypatch.setattr("app.answering.get_pool", fake_get_pool)
    monkeypatch.setattr("app.answering.retrieve", fake_retrieve)

    await _retrieve_and_prepare(question, history)

    assert captured["query"] == standalone_question


def test_below_threshold_result_composes_refusal_string():
    result = RetrievalResult(chunks=[], top_score=0.1, refuse=True)

    assert compose_answer(result) == REFUSAL_STRING


def test_above_threshold_result_defers_to_llm_call():
    result = RetrievalResult(chunks=[], top_score=0.9, refuse=False)

    assert compose_answer(result) is None


def _chunk(name: str, chunk_index: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        file_name=name,
        section="1",
        policy_version="v1",
        effective_date=date(2025, 1, 1),
        chunk_index=chunk_index,
        content="агуулга",
    )


def test_resolve_used_context_narrows_to_the_indices_the_model_named():
    used, unused = _chunk("used.txt"), _chunk("unused.txt")

    indexed, preferred = _resolve_used_context([used, unused], used=[(1, None)])

    assert indexed == [(1, used)]
    assert preferred == {}


def test_resolve_used_context_falls_back_to_everything_when_used_is_none():
    """Missing/malformed marker (extract_used_context returned None) — fail
    open to the pre-marker behavior, not an empty citation list."""
    chunks = [_chunk("a.txt"), _chunk("b.txt")]

    indexed, preferred = _resolve_used_context(chunks, used=None)

    assert indexed == [(1, chunks[0]), (2, chunks[1])]
    assert preferred == {}


def test_resolve_used_context_falls_back_when_named_indices_are_all_out_of_range():
    """A hallucinated index (e.g. "[7]" when only 2 blocks existed) must not
    silently produce zero citations for an answer that has real grounding."""
    chunks = [_chunk("a.txt"), _chunk("b.txt")]

    indexed, preferred = _resolve_used_context(chunks, used=[(7, None), (9, None)])

    assert indexed == [(1, chunks[0]), (2, chunks[1])]
    assert preferred == {}


def test_resolve_used_context_ignores_out_of_range_indices_but_keeps_valid_ones():
    a, b = _chunk("a.txt"), _chunk("b.txt")

    indexed, _preferred = _resolve_used_context([a, b], used=[(2, None), (99, None)])

    assert indexed == [(2, b)]


def test_resolve_used_context_preserves_the_original_index_through_narrowing():
    """The index in each returned pair is the chunk's ORIGINAL 1-based
    position, not a renumbered 1..N — otherwise an inline "[3]" marker the
    model placed in its own prose would point at the wrong citation (or
    none) once chunk 2 of 3 gets dropped for being unused."""
    a, b, c = _chunk("a.txt"), _chunk("b.txt"), _chunk("c.txt")

    indexed, _preferred = _resolve_used_context([a, b, c], used=[(1, None), (3, None)])

    assert indexed == [(1, a), (3, c)]


def test_resolve_used_context_collects_the_named_clause_keyed_by_chunk_pk():
    a = _chunk("a.txt", chunk_index=3)
    b = _chunk("b.txt", chunk_index=5)

    indexed, preferred = _resolve_used_context([a, b], used=[(1, "4.2"), (2, None)])

    assert indexed == [(1, a), (2, b)]
    assert preferred == {("a.txt", "v1", 3): "4.2"}


def test_document_count_counts_distinct_files_not_chunks():
    # Two chunks from a.txt, one from b.txt — "found 2 documents", not 3.
    chunks = [_chunk("a.txt", 0), _chunk("a.txt", 1), _chunk("b.txt", 0)]

    assert _document_count(chunks) == 2


class _FakeStreamingClient:
    """Minimal LLMClient stand-in: streams fixed tokens, never truncates."""

    truncated = False

    def __init__(self, tokens):
        self._tokens = tokens

    async def stream(self, system, user):
        for token in self._tokens:
            yield token


async def _drain(agen):
    """Splits a stream_answer generator into (StageEvents in order, joined text)."""
    stages, text = [], []
    async for item in agen:
        if isinstance(item, StageEvent):
            stages.append(item)
        else:
            text.append(item)
    return stages, "".join(text)


async def test_stream_answer_emits_retrieving_then_retrieved_then_generating_before_any_text(
    monkeypatch,
):
    chunks = [_chunk("a.txt", 0), _chunk("a.txt", 1), _chunk("b.txt", 0)]
    result = RetrievalResult(chunks=chunks, cited_chunks=chunks, top_score=0.9, refuse=False)

    async def fake_get_pool():
        return object()

    async def fake_retrieve(pool, query):
        return result

    monkeypatch.setattr("app.answering.get_pool", fake_get_pool)
    monkeypatch.setattr("app.answering.retrieve", fake_retrieve)
    monkeypatch.setattr(
        "app.answering.get_client", lambda: _FakeStreamingClient(["Тийм", " ", "ээ."])
    )

    stages, text = await _drain(stream_answer("Асуулт", []))

    assert stages == [
        StageEvent("retrieving"),
        StageEvent("retrieved", document_count=2),  # a.txt + b.txt — not 3 chunks
        StageEvent("generating"),
    ]
    assert text == "Тийм ээ."


async def test_stream_answer_emits_retrieved_with_zero_documents_before_a_below_threshold_refusal(
    monkeypatch,
):
    """Retrieval ran (unlike the gibberish case) but nothing cleared the bar
    — "retrieved" still fires, reporting 0, since a search genuinely
    happened and came up empty; only the LLM-generation stage is skipped."""
    result = RetrievalResult(chunks=[], cited_chunks=[], top_score=0.1, refuse=True)

    async def fake_get_pool():
        return object()

    async def fake_retrieve(pool, query):
        return result

    monkeypatch.setattr("app.answering.get_pool", fake_get_pool)
    monkeypatch.setattr("app.answering.retrieve", fake_retrieve)

    stages, text = await _drain(stream_answer("Асуулт", []))

    assert stages == [StageEvent("retrieving"), StageEvent("retrieved", document_count=0)]
    assert text == REFUSAL_STRING


async def test_stream_answer_skips_retrieved_stage_when_gibberish_short_circuits(monkeypatch):
    """No RetrievalResult is ever produced on this path (see
    _retrieve_and_prepare) — there is no document count to report for a
    search that never ran, so only "retrieving" fires before the refusal."""

    async def _fail_if_called():
        raise AssertionError("get_pool() was called — gibberish gate did not short-circuit")

    monkeypatch.setattr("app.answering.get_pool", _fail_if_called)

    stages, text = await _drain(stream_answer("kjshdf lkjashdf lkasjdhf", []))

    assert stages == [StageEvent("retrieving")]
    assert text == REFUSAL_STRING
