from datetime import date

import pytest

from app.answering import _resolve_used_context, _retrieve_and_prepare, compose_answer
from app.contract import REFUSAL_STRING
from app.retrieve.models import RetrievalResult, RetrievedChunk


async def test_gibberish_input_short_circuits_before_retrieval(monkeypatch):
    """The gibberish gate must run BEFORE app.db.get_pool — that's the whole
    point (see app.query_guard's module docstring): skip the embedding/DB
    round trip entirely, not just skip generation after paying for it."""

    async def _fail_if_called():
        raise AssertionError("get_pool() was called — gibberish gate did not short-circuit")

    monkeypatch.setattr("app.answering.get_pool", _fail_if_called)

    result, user_message = await _retrieve_and_prepare("kjshdf lkjashdf lkasjdhf")

    assert result is None
    assert user_message is None


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

    chunks, preferred = _resolve_used_context([used, unused], used=[(1, None)])

    assert chunks == [used]
    assert preferred == {}


def test_resolve_used_context_falls_back_to_everything_when_used_is_none():
    """Missing/malformed marker (extract_used_context returned None) — fail
    open to the pre-marker behavior, not an empty citation list."""
    chunks = [_chunk("a.txt"), _chunk("b.txt")]

    result_chunks, preferred = _resolve_used_context(chunks, used=None)

    assert result_chunks == chunks
    assert preferred == {}


def test_resolve_used_context_falls_back_when_named_indices_are_all_out_of_range():
    """A hallucinated index (e.g. "[7]" when only 2 blocks existed) must not
    silently produce zero citations for an answer that has real grounding."""
    chunks = [_chunk("a.txt"), _chunk("b.txt")]

    result_chunks, preferred = _resolve_used_context(chunks, used=[(7, None), (9, None)])

    assert result_chunks == chunks
    assert preferred == {}


def test_resolve_used_context_ignores_out_of_range_indices_but_keeps_valid_ones():
    a, b = _chunk("a.txt"), _chunk("b.txt")

    chunks, _preferred = _resolve_used_context([a, b], used=[(2, None), (99, None)])

    assert chunks == [b]


def test_resolve_used_context_collects_the_named_clause_keyed_by_chunk_pk():
    a = _chunk("a.txt", chunk_index=3)
    b = _chunk("b.txt", chunk_index=5)

    chunks, preferred = _resolve_used_context([a, b], used=[(1, "4.2"), (2, None)])

    assert chunks == [a, b]
    assert preferred == {("a.txt", "v1", 3): "4.2"}
