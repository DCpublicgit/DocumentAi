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

from app.answering import AnswerOutcome, answer_question
from app.contract import is_refusal

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


def load_cases(path: Path) -> list[EvalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [EvalCase(**item) for item in raw]


async def run_case(case: EvalCase) -> EvalResult:
    start = time.monotonic()
    error = ""
    answer = ""
    outcome = AnswerOutcome()
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
    )


def summarize(results: list[EvalResult], provider: str, model: str) -> dict:
    n = len(results)
    if n == 0:
        raise ValueError("Cannot summarize an empty result set.")
    return {
        "provider": provider,
        "model": model,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_questions": n,
        "n_errors": sum(1 for r in results if r.error),
        "refusal_accuracy": round(sum(r.refusal_correct for r in results) / n, 3),
        "citation_accuracy": round(sum(r.citation_correct for r in results) / n, 3),
        "avg_latency_s": round(sum(r.latency_s for r in results) / n, 2),
    }


def write_csv(results: list[EvalResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))


def write_summary(summary: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def summary_markdown_table(summary: dict) -> str:
    headers = ["Provider", "Model", "Refusal accuracy", "Citation accuracy", "Avg latency (s)", "Errors"]
    row = [
        summary["provider"],
        summary["model"],
        f"{summary['refusal_accuracy']:.0%}",
        f"{summary['citation_accuracy']:.0%}",
        f"{summary['avg_latency_s']:.2f}",
        str(summary["n_errors"]),
    ]
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "|" + "---|" * len(headers),
            "| " + " | ".join(row) + " |",
        ]
    )
