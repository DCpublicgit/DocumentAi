"""Eval harness core: loads the Mongolian Q&A set, runs each question through
the real answer_question() pipeline (same code path as /v1/chat/completions),
and scores citation + refusal correctness against the expected answer.

Grain: one EvalResult row per (question id, run). A run is one LLM_PROVIDER/
LLM_MODEL combination (see docs/EVAL_RUNBOOK.md for the V1/V2/V3 protocol).
"""

import csv
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app import usage
from app.answering import AnswerOutcome, answer_question
from app.config import settings
from app.contract import is_refusal

# A provider answering like this will answer the same way to every remaining
# question, and each attempt may bill. Stop the run instead of burning the
# whole set on errors (it happened: two Haiku runs lost most of their
# questions to "credit balance is too low").
_FATAL_ERROR_MARKERS = (
    "credit balance", "billing", "quota", "insufficient", "unauthorized",
    "permission denied", "invalid api key", "api key not valid",
    " 401", " 402", " 403", "'401", "'402", "'403",
)


def is_fatal_provider_error(error: str) -> bool:
    lowered = error.lower()
    return any(marker in lowered for marker in _FATAL_ERROR_MARKERS)


CSV_FIELDS = [
    "id",
    "question",
    "expected_source_file",
    "should_refuse",
    "actual_refused",
    "refusal_correct",
    "cited_files",
    "citation_correct",
    "latency_s",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "error",
    "answer_text",
]


@dataclass(frozen=True)
class EvalCase:
    id: int
    question: str
    expected_source_file: str | None
    should_refuse: bool


@dataclass(frozen=True)
class EvalResult:
    id: int
    question: str
    expected_source_file: str
    should_refuse: bool
    actual_refused: bool
    refusal_correct: bool
    cited_files: str
    citation_correct: bool
    latency_s: float
    error: str
    answer_text: str
    # From the provider's own usage reports (app.usage). None = unknown
    # (a call went unrecorded, or a model has no price on file), never 0.
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    # [{role, provider, model, input_tokens, output_tokens, cost_usd}, ...]
    calls: tuple = ()


def load_cases(path: Path) -> list[EvalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [EvalCase(**item) for item in raw]


async def run_case(case: EvalCase) -> EvalResult:
    start = time.monotonic()
    error = ""
    answer = ""
    outcome = AnswerOutcome()
    # Opened here so the totals are readable after answer_question returns;
    # its own collect() joins this log instead of shadowing it.
    with usage.collect() as usage_log:
        try:
            answer = await answer_question(case.question, outcome=outcome)
        except Exception as exc:  # noqa: BLE001 — eval must record, not crash, on a bad question
            error = f"{type(exc).__name__}: {exc}"
    latency = time.monotonic() - start

    # Same rule the serving path uses (app.contract.is_refusal) — if the eval
    # scored refusals more strictly than production detects them, the reported
    # refusal_accuracy wouldn't describe the shipped behavior.
    actual_refused = is_refusal(answer)
    refusal_correct = actual_refused == case.should_refuse

    # Structured citations (app.citations.citation_fields), not text-parsed —
    # answer_question no longer appends a citation block to the returned
    # string at all (see AnswerOutcome.citations' docstring).
    cited_files = [c["docId"] for c in outcome.citations]
    citation_correct = (
        True if case.should_refuse else case.expected_source_file in cited_files
    )

    return EvalResult(
        id=case.id,
        question=case.question,
        expected_source_file=case.expected_source_file or "",
        should_refuse=case.should_refuse,
        actual_refused=actual_refused,
        refusal_correct=refusal_correct,
        cited_files="; ".join(cited_files),
        citation_correct=citation_correct,
        latency_s=round(latency, 2),
        error=error,
        answer_text=answer,
        # A failed question may still have spent tokens (a call that succeeded
        # before a later one raised); those are in the log and count.
        input_tokens=usage_log.input_tokens,
        output_tokens=usage_log.output_tokens,
        cost_usd=usage_log.cost_usd,
        calls=tuple(usage_log.as_json()),
    )


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Nearest-rank percentile of an ascending list."""
    import math

    rank = math.ceil(fraction * len(sorted_values))  # 1-based
    return sorted_values[max(1, min(len(sorted_values), rank)) - 1]


def _git_commit() -> str:
    import os
    import subprocess

    if os.environ.get("GIT_COMMIT"):
        return os.environ["GIT_COMMIT"][:12]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 — no git in the container; the commit is informational
        return "unknown"


def summarize(
    results: list[EvalResult],
    provider: str,
    model: str,
    *,
    label: str | None = None,
    n_planned: int | None = None,
    stopped_reason: str | None = None,
    scenario_questions: int = 110_000,
) -> dict:
    n = len(results)
    if n == 0:
        raise ValueError("Cannot summarize an empty result set.")

    off_topic = [r for r in results if r.should_refuse]
    answerable = [r for r in results if not r.should_refuse]
    # The two directions of a wrong decision are not equally bad
    # (CONTRIBUTING.md rule 1): answering something not in the documents
    # asserts grounding that isn't there; refusing an answerable question only
    # makes the employee re-ask. Reported separately so a change that trades
    # one for the other is visible, not averaged away.
    off_topic_answered = sum(1 for r in off_topic if not r.actual_refused)
    answerable_refused = sum(1 for r in answerable if r.actual_refused)
    answered_wrong_source = sum(
        1 for r in answerable if not r.actual_refused and not r.citation_correct
    )

    latencies = sorted(r.latency_s for r in results)

    costs = [r.cost_usd for r in results]
    cost_known = all(c is not None for c in costs)
    total_cost = sum(costs) if cost_known else None
    tokens_known = all(r.input_tokens is not None for r in results)

    calls = [c for r in results for c in r.calls]
    models_by_role = {}
    cost_by_role: dict[str, float | None] = {}
    for call in calls:
        models_by_role[call["role"]] = f"{call['provider']}/{call['model']}"
    for role in models_by_role:
        role_costs = [c["cost_usd"] for c in calls if c["role"] == role]
        cost_by_role[role] = None if any(c is None for c in role_costs) else round(sum(role_costs), 6)
    unpriced = sorted(
        {f"{c['provider']}/{c['model']}" for c in calls if c["cost_usd"] is None}
    )

    summary = {
        "label": label,
        "provider": provider,
        "model": model,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit": _git_commit(),
        "n_questions": n,
        "n_planned": n_planned if n_planned is not None else n,
        "stopped_reason": stopped_reason,
        "n_errors": sum(1 for r in results if r.error),
        "refusal_accuracy": round(sum(r.refusal_correct for r in results) / n, 3),
        "citation_accuracy": round(sum(r.citation_correct for r in results) / n, 3),
        "n_off_topic": len(off_topic),
        "off_topic_answered": off_topic_answered,
        "n_answerable": len(answerable),
        "answerable_refused": answerable_refused,
        "answered_wrong_source": answered_wrong_source,
        "avg_latency_s": round(sum(r.latency_s for r in results) / n, 2),
        "latency_p50_s": round(_percentile(latencies, 0.5), 2),
        "latency_p90_s": round(_percentile(latencies, 0.9), 2),
        "total_input_tokens": sum(r.input_tokens for r in results) if tokens_known else None,
        "total_output_tokens": sum(r.output_tokens for r in results) if tokens_known else None,
        "cost_usd": round(total_cost, 6) if total_cost is not None else None,
        "cost_per_question_usd": round(total_cost / n, 6) if total_cost is not None else None,
        "cost_per_1k_questions_usd": round(total_cost / n * 1000, 4) if total_cost is not None else None,
        "scenario_questions": scenario_questions,
        # First-turn cost x volume: follow-up rewrite calls are not in a
        # single-turn eval, so a chat-heavy workload runs somewhat above this.
        "scenario_monthly_usd": (
            round(total_cost / n * scenario_questions, 2) if total_cost is not None else None
        ),
        "models_by_role": models_by_role,
        "cost_by_role_usd": cost_by_role,
        "unpriced_models": unpriced,
        "failed_ids": [r.id for r in results if not r.refusal_correct or not r.citation_correct],
        "settings": {
            "score_threshold": settings.score_threshold,
            "rerank_enabled": settings.rerank_enabled,
            "query_expansion_enabled": settings.query_expansion_enabled,
            "query_rewrite_enabled": settings.query_rewrite_enabled,
            "top_k": settings.top_k,
        },
    }
    return summary


def write_csv(results: list[EvalResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        # `calls` (the per-call breakdown) lives in the ledger/summary, not in this
        # one-row-per-question view.
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))


def write_summary(summary: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def summary_markdown_table(summary: dict) -> str:
    headers = [
        "Provider", "Model", "Refusal accuracy", "Citation accuracy", "Avg latency (s)",
        "Errors", "$/1k questions",
    ]
    per_1k = summary.get("cost_per_1k_questions_usd")
    row = [
        summary["provider"],
        summary["model"],
        f"{summary['refusal_accuracy']:.0%}",
        f"{summary['citation_accuracy']:.0%}",
        f"{summary['avg_latency_s']:.2f}",
        str(summary["n_errors"]),
        # "n/a", not "$0": unknown cost must never read as free.
        "n/a" if per_1k is None else f"${per_1k:.2f}",
    ]
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "|" + "---|" * len(headers),
            "| " + " | ".join(row) + " |",
        ]
    )
