from datetime import datetime, timezone

import pytest

from app.config import settings
from app.feedback import build_record, summarize_negative_by_document


def test_build_record_stamps_the_current_llm_model_never_the_caller():
    monkeypatch_model = settings.llm_model
    settings.llm_model = "gemini-flash-lite-latest"
    try:
        record = build_record(
            message_id="m1", conversation_id="c1", verdict="up",
            question="q", answer="a",
        )
        assert record.model == "gemini-flash-lite-latest"
    finally:
        settings.llm_model = monkeypatch_model


def test_build_record_rejects_an_unknown_verdict():
    with pytest.raises(ValueError):
        build_record(
            message_id="m1", conversation_id="c1", verdict="sideways",
            question="q", answer="a",
        )


def test_build_record_rejects_an_unknown_reason():
    with pytest.raises(ValueError):
        build_record(
            message_id="m1", conversation_id="c1", verdict="down",
            question="q", answer="a", reason="буруу зантай",
        )


def test_build_record_accepts_a_known_reason():
    record = build_record(
        message_id="m1", conversation_id="c1", verdict="down",
        question="q", answer="a", reason="ойлгомжгүй",
    )
    assert record.reason == "ойлгомжгүй"


def test_build_record_defaults_reason_and_latency_to_none():
    record = build_record(
        message_id="m1", conversation_id="c1", verdict="up",
        question="q", answer="a",
    )
    assert record.reason is None
    assert record.reason_text is None
    assert record.latency_ms is None
    assert record.retrieved_chunk_ids == []


def _row(message_id, chunk_ids, reason=None, reason_text=None, question="q"):
    return {
        "message_id": message_id,
        "received_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "retrieved_chunk_ids": chunk_ids,
        "reason": reason,
        "reason_text": reason_text,
        "question": question,
    }


def test_summarize_groups_by_document_extracted_from_chunk_id():
    rows = [
        _row("m1", ["a.txt::v1::0"]),
        _row("m2", ["a.txt::v1::3"]),
        _row("m3", ["b.txt::v2::0"]),
    ]

    summaries = summarize_negative_by_document(rows)

    by_doc = {s.document: s.down_count for s in summaries}
    assert by_doc == {"a.txt": 2, "b.txt": 1}


def test_summarize_counts_distinct_message_id_not_rows():
    """A bare thumbs-down plus its detailed follow-up (two rows, same
    message_id — see CREATE_FEEDBACK_SCHEMA_SQL's grain note) must count
    once per document, not twice."""
    rows = [
        _row("m1", ["a.txt::v1::0"]),  # bare
        _row("m1", ["a.txt::v1::0"], reason="ойлгомжгүй"),  # follow-up, same message
    ]

    summaries = summarize_negative_by_document(rows)

    assert len(summaries) == 1
    assert summaries[0].down_count == 1


def test_summarize_a_message_citing_two_chunks_from_one_document_counts_once():
    rows = [_row("m1", ["a.txt::v1::0", "a.txt::v1::5"])]

    summaries = summarize_negative_by_document(rows)

    assert len(summaries) == 1
    assert summaries[0].document == "a.txt"
    assert summaries[0].down_count == 1


def test_summarize_a_message_citing_two_different_documents_counts_in_both():
    rows = [_row("m1", ["a.txt::v1::0", "b.txt::v1::0"])]

    summaries = summarize_negative_by_document(rows)

    by_doc = {s.document: s.down_count for s in summaries}
    assert by_doc == {"a.txt": 1, "b.txt": 1}


def test_summarize_sorts_worst_document_first():
    rows = [
        _row("m1", ["a.txt::v1::0"]),
        _row("m2", ["b.txt::v1::0"]),
        _row("m3", ["b.txt::v1::0"]),
        _row("m4", ["b.txt::v1::0"]),
    ]

    summaries = summarize_negative_by_document(rows)

    assert [s.document for s in summaries] == ["b.txt", "a.txt"]


def test_summarize_tallies_reasons_per_document_ignoring_bare_rows():
    rows = [
        _row("m1", ["a.txt::v1::0"]),  # bare, no reason
        _row("m2", ["a.txt::v1::0"], reason="ойлгомжгүй"),
        _row("m3", ["a.txt::v1::0"], reason="ойлгомжгүй"),
        _row("m4", ["a.txt::v1::0"], reason="олдсонгүй"),
    ]

    summaries = summarize_negative_by_document(rows)

    assert summaries[0].reasons == {"ойлгомжгүй": 2, "олдсонгүй": 1}


def test_summarize_caps_recent_examples_per_document():
    rows = [_row(f"m{i}", ["a.txt::v1::0"], question=f"q{i}") for i in range(10)]

    summaries = summarize_negative_by_document(rows, limit_examples_per_doc=3)

    assert len(summaries[0].recent_examples) == 3


def test_summarize_ignores_a_message_with_no_retrieved_chunks():
    """A negative-feedback row with zero citations (nothing was retrieved)
    contributes no document — there is nothing to blame."""
    rows = [_row("m1", [])]

    summaries = summarize_negative_by_document(rows)

    assert summaries == []
