"""Audit trail: what the bot told an employee, and what it based that on.

One row per answered request (see CREATE_AUDIT_SCHEMA_SQL in app.db for the
grain and column rationale). This exists so three questions can be answered
after the fact, none of which the application logs can answer today:

  - "The bot told me I get 15 days leave." — what did it actually say?
  - Which policy chunks, at which VERSION, did that answer rest on?
  - It refused a reasonable question — what did retrieval score, and on what?

Record building is a pure function so it can be tested without a database;
only write_audit() touches Postgres.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.citations import format_citation
from app.config import settings
from app.db import get_pool
from app.retrieve.models import RetrievalResult, RetrievedChunk

logger = logging.getLogger(__name__)

_INSERT_SQL = """
INSERT INTO answer_audit (
    request_id, asked_at, question, answer, refused, top_score,
    retrieved_chunks, citations, llm_provider, llm_model,
    finish_reason, latency_ms, streamed
) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12, $13)
ON CONFLICT (request_id) DO NOTHING
"""


@dataclass(frozen=True)
class AuditRecord:
    request_id: uuid.UUID
    asked_at: datetime
    question: str
    answer: str
    refused: bool
    top_score: float | None
    retrieved_chunks: list[dict]
    citations: list[str]
    llm_provider: str
    llm_model: str
    finish_reason: str
    latency_ms: int
    streamed: bool


def _chunk_ref(chunk: RetrievedChunk) -> dict:
    """policy_chunks' primary key plus the fields a reader needs to make sense
    of it without a join. Deliberately not the chunk text: the audit table
    would then be a second, drifting copy of the corpus."""
    return {
        "file_name": chunk.file_name,
        "policy_version": chunk.policy_version,
        "chunk_index": chunk.chunk_index,
        "section": chunk.section,
        "effective_date": chunk.effective_date.isoformat() if chunk.effective_date else None,
    }


def build_record(
    *,
    question: str,
    answer: str,
    result: RetrievalResult | None,
    refused: bool,
    streamed: bool,
    finish_reason: str,
    latency_ms: int,
    cited_chunks: list[RetrievedChunk] | None = None,
    request_id: uuid.UUID | None = None,
    asked_at: datetime | None = None,
) -> AuditRecord:
    """`result` is None only when retrieval itself never produced one; a
    refusal still carries its result, because the score that triggered the
    refusal is the interesting part.

    `cited_chunks`, when given, overrides `result.cited_chunks` — the caller
    (app.answering) narrows retrieval's cited_chunks down to what the
    model's answer actually named via its "АШИГЛАСАН:" marker
    (app.citations.extract_used_context), and the audit's
    `citations` column must reflect exactly what the employee was shown, not
    everything that merely cleared the score floor.
    """
    chunks = result.chunks if result is not None else []
    if cited_chunks is None:
        cited_chunks = result.cited_chunks if result is not None else []
    return AuditRecord(
        request_id=request_id or uuid.uuid4(),
        asked_at=asked_at or datetime.now(timezone.utc),
        question=question,
        answer=answer,
        refused=refused,
        top_score=result.top_score if result is not None else None,
        # Every candidate retrieval surfaced, INCLUDING ones that never
        # cleared their own relevance bar — deliberately unfiltered so "why
        # did it refuse" (or "what did retrieval almost include but reject")
        # stays answerable. What was actually shown lives in `citations`.
        retrieved_chunks=[_chunk_ref(c) for c in chunks],
        # What was actually CITED to the employee, which on a refusal is
        # nothing — a refusal ships no citation block. Recording the retrieved
        # chunks' citation lines here would make the audit assert that the bot
        # cited sources it never showed. What retrieval found is already in
        # retrieved_chunks; these two columns answer different questions.
        # Deduplicated on the rendered line — the same source cited via two
        # different chunks (e.g. two clauses in the same section) collapses
        # to one entry here, same as it always has.
        citations=(
            []
            if refused
            else list(dict.fromkeys(format_citation(c) for c in cited_chunks))
        ),
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        finish_reason=finish_reason,
        latency_ms=latency_ms,
        streamed=streamed,
    )


async def write_audit(record: AuditRecord) -> None:
    """Persists one audit row.

    Fails OPEN by design: a failed audit write is logged at exception level
    but never propagates, so a database hiccup cannot stop an employee getting
    an answer. If policy ever requires the opposite — no answer without a
    durable audit record — delete the try/except; both call sites already run
    before the caller sees the answer.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                _INSERT_SQL,
                record.request_id,
                record.asked_at,
                record.question,
                record.answer,
                record.refused,
                record.top_score,
                json.dumps(record.retrieved_chunks, ensure_ascii=False),
                record.citations,
                record.llm_provider,
                record.llm_model,
                record.finish_reason,
                record.latency_ms,
                record.streamed,
            )
    except Exception:
        logger.exception(
            "audit write failed; answer was still served (request_id=%s)",
            record.request_id,
        )
