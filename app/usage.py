"""Per-request record of every LLM call made: which role (answer, query
rephrasing, follow-up rewrite), which provider/model, and the token counts the
PROVIDER itself reported. Cost is derived from these (app.pricing), never
estimated from prompt text.

One UsageLog per request, held in a ContextVar like app.timing, so clients
record without any caller threading a parameter through. collect() reuses an
already-active log: the eval harness opens one around answer_question() to read
a question's totals, and answer_question's own collect() joins it instead of
shadowing it.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Iterator

from app import pricing


@dataclass(frozen=True)
class Call:
    role: str  # "answer" | "expansion" | "rewrite"
    provider: str
    model: str
    input_tokens: int
    output_tokens: int  # BILLED output: visible text plus any thinking tokens
    cost_usd: float | None  # None = no price on file for this model


@dataclass
class UsageLog:
    calls: list[Call] = field(default_factory=list)
    # True when an LLM call was made whose usage was NOT recorded (a streamed
    # answer without LLM_STREAM_USAGE, or a provider that returned no usage).
    # Totals are then unknown, not merely smaller: a sum over the calls that
    # did get recorded would read as the request's real cost.
    incomplete: bool = False

    @property
    def input_tokens(self) -> int | None:
        return None if self.incomplete else sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int | None:
        return None if self.incomplete else sum(c.output_tokens for c in self.calls)

    @property
    def cost_usd(self) -> float | None:
        """None when the log is incomplete or any call is unpriced."""
        if self.incomplete or any(c.cost_usd is None for c in self.calls):
            return None
        return sum(c.cost_usd for c in self.calls)

    def as_json(self) -> list[dict]:
        return [asdict(c) for c in self.calls]


_current: ContextVar[UsageLog | None] = ContextVar("app_usage_current", default=None)


@contextmanager
def collect() -> Iterator[UsageLog]:
    existing = _current.get()
    if existing is not None:
        yield existing
        return
    log = UsageLog()
    token = _current.set(log)
    try:
        yield log
    finally:
        _current.reset(token)


def current() -> UsageLog | None:
    return _current.get()


def require_answer_call() -> None:
    """Called once the answer LLM call has finished. If no answer call was
    recorded, the request's totals can't be trusted."""
    log = _current.get()
    if log is not None and not any(c.role == "answer" for c in log.calls):
        log.incomplete = True


def billed_tokens(usage: dict | None) -> tuple[int, int]:
    """(input, output) from an OpenAI-shaped `usage` object.

    Output is total - prompt rather than completion_tokens: Gemini's
    OpenAI-compatible endpoint reports thinking tokens in total_tokens but NOT
    in completion_tokens (measured 2026-10-08: gemini-3.8-flash showed 276
    completion tokens against 2,406 billed), and thinking is billed as output.
    max() keeps OpenAI-style providers, whose completion_tokens already
    includes reasoning, correct too.
    """
    if not usage:
        return 0, 0
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or 0)
    return prompt, max(completion, total - prompt)


def record(role: str, provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
    """No-op outside a collect() block (CLI use, tests, the query-expansion
    cache hit path), so clients can call it unconditionally."""
    log = _current.get()
    if log is None:
        return
    log.calls.append(
        Call(
            role=role,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=pricing.cost_usd(provider, model, input_tokens, output_tokens),
        )
    )
