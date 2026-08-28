"""OpenAI-compatible FastAPI server. Per docs/ARCHITECTURE.md this is "the
brain" — hybrid retrieval + grounding + LLM live here, never in the UI. The
UI (Open WebUI) only calls /v1/chat/completions as an "OpenAI" connection.
"""

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, field_validator

from app.answering import (
    AnswerOutcome,
    EmptyCompletionError,
    StageEvent,
    answer_question,
    stream_answer,
)
from app import timing
from app.config import settings
from app.db import close_pool, create_audit_schema, create_feedback_schema, create_schema, get_pool
from app.documents import find_document_path, guess_content_type
from app.embedding import warm_up as warm_up_embedding
from app.feedback import KNOWN_REASONS, build_record, negative_by_document, write_feedback
from app.retrieve.reranker import warm_up as warm_up_reranker

logger = logging.getLogger(__name__)


async def _warm_up_models() -> None:
    # Both are synchronous torch calls (see app.retrieve.retriever) — off the
    # event loop so they don't block /health or an in-flight request during
    # startup. Pays the cold-load cost (measured ~20s embedder, ~130s
    # reranker on the CPU-only pilot VM) once at deploy time instead of on
    # whichever user asks the first question after every process start.
    with timing.stage("warm_up_embedding"):
        await asyncio.to_thread(warm_up_embedding)
    with timing.stage("warm_up_rerank"):
        await asyncio.to_thread(warm_up_reranker)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_schema()
    await create_audit_schema()
    await create_feedback_schema()
    if settings.warm_up_models_enabled:
        await _warm_up_models()
    yield
    await close_pool()


app = FastAPI(title="Policy Chatbot", lifespan=lifespan)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    messages: list[ChatMessage]
    stream: bool = False


def _split_history(messages: list[ChatMessage]) -> tuple[list[tuple[str, str]], str]:
    """Splits a request's messages into (everything before the current turn,
    the current turn's text) — the shape app.answering.answer_question /
    stream_answer take. The "current turn" is the LAST user-role message
    (the UI always appends the new question as the final entry, per
    ui/src/App.jsx); every message before it, in order, is history."""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            history = [(m.role, m.content) for m in messages[:i]]
            return history, messages[i].content
    # A request with no user turn is the caller's mistake, not ours — 400,
    # not an unhandled ValueError surfacing as a 500.
    raise HTTPException(status_code=400, detail="No user message in request.")


def _sse_chunk(chunk_id: str, created: int, model: str, delta: dict, finish_reason: str | None) -> str:
    payload = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_event(event: str, data: dict) -> str:
    # A named SSE event (vs. the default "message" event _sse_chunk sends) —
    # used for "citations" and "stage" below, so the client can tell a
    # structured payload apart from an ordinary content delta without
    # inspecting its shape. See ui/src/lib/streamChat.js's onCitations and
    # onStage handling.
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_chat_completion(
    question: str, history: list[tuple[str, str]], model: str
) -> AsyncIterator[str]:
    chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    outcome = AnswerOutcome()

    yield _sse_chunk(chunk_id, created, model, {"role": "assistant"}, None)

    try:
        async for item in stream_answer(question, history, outcome):
            if isinstance(item, StageEvent):
                # Pipeline progress ("retrieving" → "retrieved" (+ document
                # count) → "generating"), not answer text — drives
                # ui/src/components/StageIndicator.jsx, never mixed into the
                # content deltas below.
                data = {"stage": item.stage}
                if item.document_count is not None:
                    data["documentCount"] = item.document_count
                yield _sse_event("stage", data)
                continue
            yield _sse_chunk(chunk_id, created, model, {"content": item}, None)
    except Exception:
        # An unhandled exception here would otherwise abort the ASGI
        # response mid-stream, leaving the client's fetch reader hanging
        # forever with no error and no [DONE]. Emit a proper error event
        # (OpenAI-compatible convention) so the client's existing failure
        # path can catch it and finish the stream cleanly either way.
        logger.exception("chat completion stream failed")
        yield f"data: {json.dumps({'error': {'message': 'stream failed'}}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Sent once, after the text is fully streamed — never interleaved with
    # content deltas, so the client can finish rendering the answer text
    # before it has anything to resolve inline "[N]" markers against.
    # Omitted entirely on a refusal (outcome.citations stays empty — a
    # refusal ships no citations, same rule the text path already follows).
    if outcome.citations:
        yield _sse_event("citations", {"citations": outcome.citations})

    # "length" when the provider hit the token cap — a client told "stop" has
    # no way to know the answer was cut off mid-sentence.
    yield _sse_chunk(chunk_id, created, model, {}, outcome.finish_reason)
    yield "data: [DONE]\n\n"


@app.get("/health")
async def health() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": settings.llm_model,
                "object": "model",
                "created": 0,
                "owned_by": "policy-chatbot",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    history, question = _split_history(request.messages)

    if request.stream:
        return StreamingResponse(
            _stream_chat_completion(question, history, request.model),
            media_type="text/event-stream",
        )

    outcome = AnswerOutcome()
    try:
        answer = await answer_question(question, history, outcome)
    except EmptyCompletionError as exc:
        # 502: the upstream model failed to produce an answer. Deliberately not
        # a refusal — see EmptyCompletionError.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": outcome.finish_reason,
                "citations": outcome.citations,
            }
        ],
    }


@app.get("/v1/documents/{file_name}")
async def get_document(file_name: str, policy_version: str | None = None) -> Response:
    """Serves the raw source file behind a citation's `docId` — the "view
    full document" link in the citation drawer (ui/src/components/
    CitationDrawer.jsx). See app.documents for how `file_name` (never a raw
    filesystem path) resolves to an actual file."""
    path = find_document_path(file_name, policy_version)
    if path is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return Response(
        content=path.read_bytes(),
        media_type=guess_content_type(path),
        # No filename= — policy file names are Mongolian Cyrillic, and a raw
        # non-ASCII value here would raise encoding the response header
        # (HTTP headers are Latin-1). "inline" alone is enough to make the
        # browser render/view rather than force a download.
        headers={"Content-Disposition": "inline"},
    )


class FeedbackPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messageId: str
    conversationId: str
    verdict: Literal["up", "down"]
    question: str
    answer: str
    # Chunk PKs (app.citations.citation_fields' chunkId), not raw text — see
    # CREATE_FEEDBACK_SCHEMA_SQL in app.db for why.
    retrievedChunkIds: list[str] = []
    # Client-measured wall-clock time for this answer; None for feedback on
    # a message restored from a prior session (ui/src/lib/conversationStore.js
    # doesn't persist it — see FeedbackButtons.jsx).
    latencyMs: int | None = None
    ts: datetime | None = None
    # One of app.feedback.KNOWN_REASONS, only meaningful (and only ever sent
    # by the UI) alongside verdict="down" — see FeedbackButtons.jsx's
    # "Юу нь буруу байсан бэ?" follow-up.
    reason: str | None = None
    reasonText: str | None = None
    # Deliberately no `model` field — see app.feedback.build_record's
    # docstring: the backend stamps its own current settings.llm_model,
    # never trusting the client to report which model actually answered.

    @field_validator("reason")
    @classmethod
    def _reason_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in KNOWN_REASONS:
            raise ValueError(f"unknown reason: {value!r}")
        return value


@app.post("/api/feedback")
async def submit_feedback(payload: FeedbackPayload) -> dict:
    record = build_record(
        message_id=payload.messageId,
        conversation_id=payload.conversationId,
        verdict=payload.verdict,
        question=payload.question,
        answer=payload.answer,
        retrieved_chunk_ids=payload.retrievedChunkIds,
        latency_ms=payload.latencyMs,
        reason=payload.reason,
        reason_text=payload.reasonText,
        client_ts=payload.ts,
    )
    try:
        await write_feedback(record)
    except Exception as exc:
        # Not fail-open (contrast app.audit.write_audit): persisting IS this
        # endpoint's job, so a DB failure must not look like success to the
        # employee — see app.feedback.write_feedback's docstring.
        logger.exception("feedback write failed (id=%s)", record.id)
        raise HTTPException(status_code=500, detail="Failed to save feedback.") from exc
    return {"status": "ok", "id": str(record.id)}


@app.get("/api/feedback/negative-summary")
async def feedback_negative_summary() -> dict:
    """Backs the admin page (ui/public/admin-feedback.html) — 👎 feedback
    grouped by retrieved document, worst first (app.feedback.negative_by_document)."""
    summaries = await negative_by_document()
    return {
        "documents": [
            {
                "document": s.document,
                "downCount": s.down_count,
                "reasons": s.reasons,
                "recentExamples": [
                    {**example, "receivedAt": example["receivedAt"].isoformat()}
                    for example in s.recent_examples
                ],
            }
            for s in summaries
        ]
    }
