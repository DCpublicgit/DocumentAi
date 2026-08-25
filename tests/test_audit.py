"""The audit trail is the record of what the bot told an employee.

These cover the two things that make it trustworthy: that a record faithfully
captures which policy VERSION an answer rested on, and that a failure to write
one never costs the employee their answer.
"""

import uuid
from datetime import date

import pytest

from app import audit
from app.audit import AuditRecord, build_record, write_audit
from app.contract import REFUSAL_STRING
from app.retrieve.models import RetrievalResult, RetrievedChunk


def _chunk(file_name: str, section: str | None = "1. Ерөнхий зүйл", index: int = 0,
           version: str = "v2") -> RetrievedChunk:
    return RetrievedChunk(
        file_name=file_name,
        section=section,
        policy_version=version,
        effective_date=date(2025, 1, 1),
        chunk_index=index,
        content="агуулга",
    )


def _result(
    *chunks: RetrievedChunk,
    top_score: float = 0.72,
    refuse: bool = False,
    cited_chunks: list[RetrievedChunk] | None = None,
):
    # Defaults cited_chunks to the same chunks retrieval surfaced — the
    # common case where every retrieved chunk also cleared its own relevance
    # bar. Pass cited_chunks explicitly to test the noisy case, where
    # retrieval surfaced more than it should cite.
    return RetrievalResult(
        chunks=list(chunks),
        cited_chunks=list(chunks) if cited_chunks is None else cited_chunks,
        top_score=top_score,
        refuse=refuse,
    )


def _record(**overrides) -> AuditRecord:
    kwargs = dict(
        question="Ээлжийн амралт хэдэн хоног вэ?",
        answer="хариулт",
        result=_result(_chunk("Чөлөө олгох журам.docx")),
        refused=False,
        streamed=False,
        finish_reason="stop",
        latency_ms=1234,
    )
    kwargs.update(overrides)
    return build_record(**kwargs)


def test_record_pins_the_policy_version_each_answer_rested_on():
    """The whole point of keeping superseded versions: an answer given last
    year must still be explainable against the version in force then."""
    record = _record(result=_result(_chunk("Чөлөө олгох журам.docx", version="v2")))

    assert record.retrieved_chunks == [
        {
            "file_name": "Чөлөө олгох журам.docx",
            "policy_version": "v2",
            "chunk_index": 0,
            "section": "1. Ерөнхий зүйл",
            "effective_date": "2025-01-01",
        }
    ]


def test_record_stores_chunk_identity_not_chunk_text():
    """Copying chunk text in would make the audit table a second, drifting
    copy of the corpus."""
    record = _record()

    assert "агуулга" not in str(record.retrieved_chunks)
    assert record.retrieved_chunks[0]["chunk_index"] == 0


def test_citations_are_deduplicated_like_the_rendered_list():
    """Two chunks from the same section render one citation line to the
    employee; the audit must not claim two."""
    same = [_chunk("a.txt", index=0), _chunk("a.txt", index=1)]
    record = _record(result=_result(*same))

    assert len(record.citations) == 1


def test_a_refusal_is_audited_with_its_retrieval_score():
    """'It refused a reasonable question' is only investigable if the score
    that caused the refusal was recorded."""
    record = _record(
        answer=REFUSAL_STRING,
        refused=True,
        result=_result(_chunk("a.txt"), top_score=0.41, refuse=True),
    )

    assert record.refused is True
    assert record.answer == REFUSAL_STRING
    assert record.top_score == pytest.approx(0.41)


def test_a_refusal_cites_nothing_but_still_records_what_was_retrieved():
    """A refusal ships no citation block, so the audit must not claim sources
    were cited. What retrieval found still has to be recoverable — that is
    what makes a wrong refusal diagnosable."""
    record = _record(
        answer=REFUSAL_STRING,
        refused=True,
        result=_result(_chunk("a.txt"), _chunk("b.txt"), top_score=0.41, refuse=True),
    )

    assert record.citations == []
    assert len(record.retrieved_chunks) == 2


def test_citations_exclude_retrieved_chunks_that_never_cleared_their_own_bar():
    """retrieval can surface a chunk in the TOP_K window without it being
    individually relevant (app.retrieve.retriever.select_cited_chunks) — the
    audit's citations column must reflect only what was actually shown to
    the employee, not everything retrieval looked at."""
    relevant = _chunk("a.txt")
    noise = _chunk("b.txt")
    record = _record(result=_result(relevant, noise, cited_chunks=[relevant]))

    assert len(record.retrieved_chunks) == 2
    assert len(record.citations) == 1
    assert "a.txt" in record.citations[0]


def test_record_without_any_retrieval_result_has_no_score_or_citations():
    record = _record(result=None)

    assert record.top_score is None
    assert record.retrieved_chunks == []
    assert record.citations == []


def test_each_record_gets_its_own_request_id():
    assert _record().request_id != _record().request_id


async def test_write_failure_never_costs_the_employee_their_answer(monkeypatch, caplog):
    """Fails open by design (see write_audit): a database problem must not
    turn a good answer into an error. It must still be loud in the log."""
    async def exploding_pool():
        raise RuntimeError("database is down")

    monkeypatch.setattr(audit, "get_pool", exploding_pool)

    await write_audit(_record())  # must not raise

    assert "audit write failed" in caplog.text


async def test_write_failure_logs_the_request_id_for_correlation(monkeypatch, caplog):
    async def exploding_pool():
        raise RuntimeError("database is down")

    monkeypatch.setattr(audit, "get_pool", exploding_pool)
    record = _record(request_id=uuid.UUID("00000000-0000-0000-0000-0000000000ab"))

    await write_audit(record)

    assert "0000000000ab" in caplog.text
