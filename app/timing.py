"""Per-request, per-stage latency instrumentation for the
/v1/chat/completions call path.

Measurement only. Nothing here influences retrieval, grounding, or
generation — it records how long each stage took and emits it as structured
JSON, one line per stage plus one summary line per request. Replaces the
ad-hoc print("[TIMING] ...") calls that had accumulated in app.answering and
app.retrieve.retriever (CONTRIBUTING.md: structured logging, not print).

Stage timings accumulate into a request-scoped ContextVar rather than being
threaded through every function signature. ContextVars propagate into
asyncio.to_thread(), so the synchronous torch stages (query embedding,
reranking) record against the request that spawned them.

Two deliberate choices:

- json.dumps(ensure_ascii=True): policy file names and questions are
  Mongolian Cyrillic. A Windows dev console is cp1252 and raises
  UnicodeEncodeError on writing Cyrillic, which would turn an instrumentation
  line into a 500 on a real request. Escaping to \\uXXXX keeps every log line
  pure ASCII and safe on any console encoding.
- A private handler on this logger (propagate=False) instead of
  logging.basicConfig(): configuring the root logger to INFO for a
  measurement pass would also switch on INFO for httpx, asyncpg and
  transformers. This keeps the audit's footprint to exactly one logger.
"""

import json
import logging
import sys
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

logger = logging.getLogger("app.timing")

_current: ContextVar["RequestTimings | None"] = ContextVar(
    "app_timing_current_request", default=None
)


def _ensure_handler() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    # Bare message: each record is already a complete JSON object, so a
    # logging prefix would make the line unparseable.
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


_ensure_handler()


def _emit(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, ensure_ascii=True))


class RequestTimings:
    """Accumulator for one request's stage timings.

    Grain: one instance per /v1/chat/completions request. Stage names are the
    key; a stage entered more than once per request (vector/FTS search, which
    run once per query-expansion phrasing) sums rather than overwrites, so the
    summary reports that stage's total contribution to wall time.
    """

    __slots__ = ("request_id", "started", "stages", "counts", "notes")

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.started = time.perf_counter()
        self.stages: dict[str, float] = {}
        self.counts: dict[str, int] = {}
        self.notes: dict[str, Any] = {}

    def add(self, name: str, seconds: float) -> None:
        self.stages[name] = self.stages.get(name, 0.0) + seconds
        self.counts[name] = self.counts.get(name, 0) + 1


@contextmanager
def stage(name: str, **fields: Any) -> Iterator[None]:
    """Times the enclosed block and records it against the current request.

    Emits even when no request context is active (CLI use, tests) so a stage
    is never silently unmeasured; it just doesn't land in a summary.
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - t0
        current = _current.get()
        if current is not None:
            current.add(name, elapsed)
        _emit("stage", stage=name, ms=round(elapsed * 1000, 1), **fields)


def mark(name: str, seconds: float, **fields: Any) -> None:
    """Records a duration measured by the caller — for stages whose start and
    end are not a lexical block, such as time-to-first-token inside a stream."""
    current = _current.get()
    if current is not None:
        current.add(name, seconds)
    _emit("stage", stage=name, ms=round(seconds * 1000, 1), **fields)


def note(**fields: Any) -> None:
    """Attaches non-timing facts to the current request's summary line
    (candidate counts, whether a stage blocked the ones after it, etc.)."""
    current = _current.get()
    if current is not None:
        current.notes.update(fields)


@contextmanager
def request_timing(label: str) -> Iterator[RequestTimings]:
    """Wraps one end-to-end request, emitting the per-stage summary on exit.

    `label` is the call path (e.g. "stream_answer"), never the question text —
    questions are Mongolian and user-supplied; keeping them out of the log
    avoids both the encoding hazard and logging employee queries verbatim.

    Percentages are of total wall time. "unaccounted" is the remainder that no
    instrumented stage claimed — if it is large, a real cost is unmeasured.
    """
    timings = RequestTimings(uuid.uuid4().hex[:8])
    token = _current.set(timings)
    try:
        yield timings
    finally:
        _current.reset(token)
        total = time.perf_counter() - timings.started
        measured = sum(timings.stages.values())
        breakdown = {
            name: {
                "ms": round(seconds * 1000, 1),
                "pct": round(100.0 * seconds / total, 1) if total > 0 else 0.0,
                "calls": timings.counts[name],
            }
            for name, seconds in sorted(
                timings.stages.items(), key=lambda kv: kv[1], reverse=True
            )
        }
        unaccounted = total - measured
        _emit(
            "request",
            request_id=timings.request_id,
            path=label,
            total_ms=round(total * 1000, 1),
            stages=breakdown,
            unaccounted_ms=round(unaccounted * 1000, 1),
            unaccounted_pct=round(100.0 * unaccounted / total, 1) if total > 0 else 0.0,
            **timings.notes,
        )
