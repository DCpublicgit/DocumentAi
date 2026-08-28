"""CLI:
  python -m app.eval run --out eval_results/v1_haiku
      Runs the full question set against whatever LLM_PROVIDER/LLM_MODEL is
      set in the current environment (.env), writes <out>.csv (per-question
      detail) and <out>.summary.json (aggregate scores), and prints a
      one-row markdown summary table.

  python -m app.eval compare eval_results/v1_haiku.summary.json eval_results/v2_sonnet.summary.json [...]
      Reads N run summaries and prints one comparison markdown table across
      them. --out writes it to a file too.

  python -m app.eval calibrate --out eval_results/threshold_sweep
      Retrieval-only (no generation, no LLM cost): scores every question's
      top_score, sweeps refusal-gate thresholds against the should_refuse
      labels, and prints the recommended SCORE_THRESHOLD / RERANK_SCORE_THRESHOLD
      (whichever scale RERANK_ENABLED currently selects). Writes <out>.csv
      (the full sweep) and <out>.cases.csv (per-question top_score).

See docs/EVAL_RUNBOOK.md for the full V1/V2/V3 protocol.
"""

import argparse
import asyncio
import csv
import sys
from pathlib import Path

from app.config import settings
from app.db import close_pool
from app.eval.calibrate import best_threshold, score_cases, sweep
from app.eval.report import build_comparison_table
from app.eval.runner import load_cases, run_case, summarize, summary_markdown_table, write_csv, write_summary
from app.retrieve.retriever import refusal_threshold

DEFAULT_QUESTIONS = Path(__file__).parent / "questions.yaml"


async def _run(questions_path: Path, out_prefix: str) -> None:
    cases = load_cases(questions_path)
    results = []
    try:
        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] {case.question}", file=sys.stderr, flush=True)
            results.append(await run_case(case))
    finally:
        await close_pool()

    summary = summarize(results, settings.llm_provider, settings.llm_model)
    csv_path = Path(f"{out_prefix}.csv")
    summary_path = Path(f"{out_prefix}.summary.json")
    write_csv(results, csv_path)
    write_summary(summary, summary_path)

    print(f"\nWrote {csv_path}", file=sys.stderr)
    print(f"Wrote {summary_path}\n", file=sys.stderr)
    print(summary_markdown_table(summary))


async def _calibrate(questions_path: Path, out_prefix: str) -> None:
    cases = load_cases(questions_path)
    try:
        scored = await score_cases(cases)
    finally:
        await close_pool()

    cases_path = Path(f"{out_prefix}.cases.csv")
    cases_path.parent.mkdir(parents=True, exist_ok=True)
    with cases_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "question", "should_refuse", "top_score"])
        for c in scored:
            writer.writerow([c.id, c.question, c.should_refuse, round(c.top_score, 4)])

    rows = sweep(scored)
    sweep_path = Path(f"{out_prefix}.csv")
    with sweep_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["threshold", "false_pass", "false_refuse", "total_errors"])
        for r in rows:
            writer.writerow([r.threshold, r.false_pass, r.false_refuse, r.total_errors])

    best = best_threshold(rows)
    current = refusal_threshold()
    scale = "RERANK_SCORE_THRESHOLD" if settings.rerank_enabled else "SCORE_THRESHOLD"

    print(f"\nWrote {cases_path}", file=sys.stderr)
    print(f"Wrote {sweep_path}\n", file=sys.stderr)
    print(f"Current {scale} = {current}")
    n_off = sum(1 for c in scored if c.should_refuse)
    n_on = len(scored) - n_off
    current_row = min(rows, key=lambda r: abs(r.threshold - current))
    print(
        f"  at that threshold: {current_row.false_pass}/{n_off} off-topic answered, "
        f"{current_row.false_refuse}/{n_on} relevant refused, "
        f"{current_row.total_errors} total errors"
    )
    print(f"\nRecommended {scale} = {best.threshold}")
    print(
        f"  {best.false_pass}/{n_off} off-topic answered, "
        f"{best.false_refuse}/{n_on} relevant refused, "
        f"{best.total_errors} total errors "
        "(false passes weighted 2x — see app.eval.calibrate.best_threshold)"
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Evaluate the policy chatbot's answers.")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run the eval set against the current LLM_PROVIDER/LLM_MODEL.")
    run_p.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    run_p.add_argument(
        "--out",
        required=True,
        help="Output path prefix, e.g. eval_results/v1_haiku (writes .csv and .summary.json)",
    )

    cmp_p = sub.add_parser("compare", help="Build one comparison table from multiple run summaries.")
    cmp_p.add_argument("summaries", type=Path, nargs="+")
    cmp_p.add_argument("--out", type=Path, default=None, help="Optional path to also write the markdown table")

    cal_p = sub.add_parser(
        "calibrate", help="Sweep refusal-gate thresholds against the labeled eval set (retrieval only)."
    )
    cal_p.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    cal_p.add_argument(
        "--out",
        required=True,
        help="Output path prefix, e.g. eval_results/threshold_sweep (writes .cases.csv and .csv)",
    )

    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(_run(args.questions, args.out))
    elif args.command == "compare":
        table = build_comparison_table(args.summaries)
        print(table)
        if args.out:
            args.out.write_text(table, encoding="utf-8")
    elif args.command == "calibrate":
        asyncio.run(_calibrate(args.questions, args.out))


if __name__ == "__main__":
    main()
