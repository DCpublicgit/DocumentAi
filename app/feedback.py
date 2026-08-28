"""Feedback: thumbs up/down on an assistant answer — wired from the existing
buttons (ui/src/components/FeedbackButtons.jsx) to POST /api/feedback
(app.server), plus the admin summary behind GET /api/feedback/negative-summary.

One row per feedback SUBMISSION, not per message — see CREATE_FEEDBACK_SCHEMA_SQL
in app.db for the grain and why a bare thumbs-down followed by a detailed
follow-up produces two rows, not an edit of one.

Record building is a pure function so it can be tested without a database;
only write_feedback()/negative_by_document() touch Postgres.
"""

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)

_INSERT_SQL = """
INSERT INTO feedback (
    id, received_at, client_ts, message_id, conversation_id, verdict,
    question, answer, retrieved_chunk_ids, model, latency_ms, reason, reason_text
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
"""

# Mirrors the four options in the 👎 follow-up ("Юу нь буруу байсан бэ?") —
# ui/src/components/FeedbackButtons.jsx. Kept as the exact Mongolian label
# text, not a separate code<->label table: this is a small, fixed, internal-
# tool set of options, and a translation layer buys nothing an admin reading
# the raw column wouldn't rather just read directly.
KNOWN_REASONS = frozenset({"буруу мэдээлэл", "олдсонгүй", "ойлгомжгүй", "бусад"})


@dataclass(frozen=True)
class FeedbackRecord:
    id: uuid.UUID
    received_at: datetime
    client_ts: datetime | None
    message_id: str
    conversation_id: str
    verdict: str
    question: str
    answer: str
    retrieved_chunk_ids: list[str]
    model: str
    latency_ms: int | None
    reason: str | None
    reason_text: str | None


def build_record(
    *,
    message_id: str,
    conversation_id: str,
    verdict: str,
    question: str,
    answer: str,
    retrieved_chunk_ids: list[str] | None = None,
    latency_ms: int | None = None,
    reason: str | None = None,
    reason_text: str | None = None,
    client_ts: datetime | None = None,
    record_id: uuid.UUID | None = None,
    received_at: datetime | None = None,
) -> FeedbackRecord:
    """`model` is never taken from the caller — it's always the CURRENT
    settings.llm_model, stamped at write time. The client can't be trusted
    to know (or accurately report) which model actually answered; the
    backend already does."""
    if verdict not in ("up", "down"):
        raise ValueError(f"verdict must be 'up' or 'down', got {verdict!r}")
    if reason is not None and reason not in KNOWN_REASONS:
        raise ValueError(f"unknown reason: {reason!r}")
    return FeedbackRecord(
        id=record_id or uuid.uuid4(),
        received_at=received_at or datetime.now(timezone.utc),
        client_ts=client_ts,
        message_id=message_id,
        conversation_id=conversation_id,
        verdict=verdict,
        question=question,
        answer=answer,
        retrieved_chunk_ids=list(retrieved_chunk_ids or []),
        model=settings.llm_model,
        latency_ms=latency_ms,
        reason=reason,
        reason_text=reason_text,
    )


async def write_feedback(record: FeedbackRecord) -> None:
    """Persists one feedback row. Deliberately NOT fail-open like
    app.audit.write_audit: audit is a side-channel on an answer already
    served to the employee, but persisting IS this endpoint's entire job —
    silently swallowing a DB failure here would tell the employee their
    feedback was recorded when it wasn't. app.server maps a raised
    exception to a 500 instead."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            _INSERT_SQL,
            record.id,
            record.received_at,
            record.client_ts,
            record.message_id,
            record.conversation_id,
            record.verdict,
            record.question,
            record.answer,
            record.retrieved_chunk_ids,
            record.model,
            record.latency_ms,
            record.reason,
            record.reason_text,
        )


def _chunk_id_to_document(chunk_id: str) -> str:
    """chunkId is "{file_name}::{policy_version}::{chunk_index}" (see
    app.citations.citation_fields) — file_name is the document grouping key.
    Split on the FIRST "::" only: file_name itself never contains "::" in
    the real corpus, but this stays correct even if that changed, since
    policy_version/chunk_index are the trailing two segments either way."""
    return chunk_id.split("::", 1)[0]


@dataclass(frozen=True)
class DocumentFeedbackSummary:
    document: str
    down_count: int
    reasons: dict[str, int] = field(default_factory=dict)
    recent_examples: list[dict] = field(default_factory=list)


def summarize_negative_by_document(
    rows: list[dict], limit_examples_per_doc: int = 5
) -> list[DocumentFeedbackSummary]:
    """Pure grouping logic — takes plain dicts (already newest-first) so it's
    testable without a database. `negative_by_document` below is the only
    caller that actually queries Postgres.

    Counts DISTINCT message_id per document, not rows: a message with both a
    bare 👎 and a detailed follow-up (two rows, see this module's docstring)
    must count once per document, not twice.

    Aggregated in Python rather than SQL: this is a low-volume pilot table
    (~200 users — CONTRIBUTING.md's cost posture), and a plain fetch-then-
    group here is far easier to read and test than the window-function SQL
    an equivalent "top N examples per group" query would need.
    """
    message_ids_per_doc: dict[str, set[str]] = defaultdict(set)
    reasons_per_doc: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    examples_per_doc: dict[str, list[dict]] = defaultdict(list)

    for row in rows:
        docs = {_chunk_id_to_document(cid) for cid in row["retrieved_chunk_ids"]}
        for doc in docs:
            message_ids_per_doc[doc].add(row["message_id"])
            if row["reason"] is not None:
                reasons_per_doc[doc][row["reason"]] += 1
            if len(examples_per_doc[doc]) < limit_examples_per_doc:
                examples_per_doc[doc].append(
                    {
                        "question": row["question"],
                        "reason": row["reason"],
                        "reasonText": row["reason_text"],
                        "receivedAt": row["received_at"],
                    }
                )

    summaries = [
        DocumentFeedbackSummary(
            document=doc,
            down_count=len(message_ids),
            reasons=dict(reasons_per_doc[doc]),
            recent_examples=examples_per_doc[doc],
        )
        for doc, message_ids in message_ids_per_doc.items()
    ]
    # Worst document first; ties broken alphabetically for a stable order.
    summaries.sort(key=lambda s: (-s.down_count, s.document))
    return summaries


async def negative_by_document(limit_examples_per_doc: int = 5) -> list[DocumentFeedbackSummary]:
    """👎 feedback grouped by which retrieved document it named, worst first —
    GET /api/feedback/negative-summary (the admin view)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT message_id, received_at, retrieved_chunk_ids, reason, reason_text, question
            FROM feedback
            WHERE verdict = 'down'
            ORDER BY received_at DESC
            """
        )
    return summarize_negative_by_document([dict(r) for r in rows], limit_examples_per_doc)
