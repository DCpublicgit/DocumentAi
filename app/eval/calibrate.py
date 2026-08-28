"""Calibrates the refusal gate's threshold (SCORE_THRESHOLD when
RERANK_ENABLED=false, RERANK_SCORE_THRESHOLD when true — see
app.retrieve.retriever.refusal_threshold) against the labeled eval set.

Retrieval only, no generation: `top_score` doesn't depend on the LLM, so this
is fast and provider-cost-free, and can be re-run any time the corpus grows
or the embedding/reranker model changes — not a one-off, throwaway script.

Grain: one ThresholdCase row per question id, scored once and reused across
every candidate threshold in the sweep (top_score is threshold-independent).

Known limitation: this calibrates and reports against the SAME 78-question
set — a real train/test split would catch overfitting to this particular
label set, but at this size (and a pilot's low real volume — see
CONTRIBUTING.md's cost posture) that is more machinery than the eval set
currently justifies. Revisit if the question set grows meaningfully.
"""

from dataclasses import dataclass

from app.db import get_pool
from app.eval.runner import EvalCase
from app.retrieve import retrieve


@dataclass(frozen=True)
class ThresholdCase:
    id: int
    question: str
    should_refuse: bool
    top_score: float


async def score_cases(cases: list[EvalCase]) -> list[ThresholdCase]:
    pool = await get_pool()
    scored = []
    for case in cases:
        result = await retrieve(pool, case.question)
        scored.append(
            ThresholdCase(
                id=case.id,
                question=case.question,
                should_refuse=case.should_refuse,
                top_score=result.top_score,
            )
        )
    return scored


@dataclass(frozen=True)
class ThresholdSweepRow:
    threshold: float
    # Off-topic (should_refuse=True) whose top_score still clears this
    # threshold — the gate answers when it shouldn't. The worse error: the
    # bot cites real policy content that doesn't actually cover the
    # question, which reads as a grounded answer when it isn't.
    false_pass: int
    # On-topic (should_refuse=False) whose top_score falls short — the gate
    # refuses when it shouldn't. The employee just re-asks; CONTRIBUTING.md
    # rule 1 explicitly calls refusing "correct behavior, not a failure."
    false_refuse: int
    total_errors: int


def sweep(
    scored: list[ThresholdCase], candidates: list[float] | None = None
) -> list[ThresholdSweepRow]:
    if candidates is None:
        candidates = [round(0.20 + 0.01 * i, 2) for i in range(61)]  # 0.20..0.80
    rows = []
    for t in candidates:
        false_pass = sum(1 for c in scored if c.should_refuse and c.top_score >= t)
        false_refuse = sum(1 for c in scored if not c.should_refuse and c.top_score < t)
        rows.append(ThresholdSweepRow(t, false_pass, false_refuse, false_pass + false_refuse))
    return rows


def best_threshold(rows: list[ThresholdSweepRow], false_pass_weight: float = 2.0) -> ThresholdSweepRow:
    """Picks the sweep row minimizing a WEIGHTED error count, not raw total —
    see ThresholdSweepRow's docstring for why a false pass costs more than a
    false refuse. Ties broken toward the LOWER threshold (more permissive),
    since ThresholdSweepRow ordering from `sweep()` is ascending and `min`
    keeps the first minimum it sees.
    """
    return min(rows, key=lambda r: false_pass_weight * r.false_pass + r.false_refuse)
