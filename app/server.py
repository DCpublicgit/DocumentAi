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
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.answering import (
    AnswerOutcome,
    EmptyCompletionError,
    answer_question,
    stream_answer,
)
from app import timing
from app.config import settings
from app.db import close_pool, create_audit_schema, create_schema, get_pool
from app.embedding import warm_up as warm_up_embedding
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


def _last_user_message(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
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


async def _stream_chat_completion(question: str, model: str) -> AsyncIterator[str]:
    chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    outcome = AnswerOutcome()

    yield _sse_chunk(chunk_id, created, model, {"role": "assistant"}, None)

    try:
        async for token in stream_answer(question, outcome):
            yield _sse_chunk(chunk_id, created, model, {"content": token}, None)
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
    question = _last_user_message(request.messages)

    if request.stream:
        return StreamingResponse(
            _stream_chat_completion(question, request.model),
            media_type="text/event-stream",
        )

    outcome = AnswerOutcome()
    try:
        answer = await answer_question(question, outcome)
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
            }
        ],
    }
