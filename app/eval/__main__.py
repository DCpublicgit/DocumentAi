"""CLI:
  python -m app.eval run --out eval_results/v1_haiku
      Runs the full question set against whatever LLM_PROVIDER/LLM_MODEL is
      set in the current environment (.env), writes <out>.csv (per-question
      detail) and <out>.summary.json (aggregate scores), and prints a
      one-row markdown summary table.

  python -m app.eval compare eval_results/v1_haiku.summary.json eval_results/v2_sonnet.summary.json [...]
      Reads N run summaries and prints one comparison markdown table across
      them. --out writes it to a file too.

See docs/EVAL_RUNBOOK.md for the full V1/V2/V3 protocol.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import settings
from app.db import close_pool
from app.eval.report import build_comparison_table
from app.eval.runner import load_cases, run_case, summarize, summary_markdown_table, write_csv, write_summary

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

    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(_run(args.questions, args.out))
    elif args.command == "compare":
        table = build_comparison_table(args.summaries)
        print(table)
        if args.out:
            args.out.write_text(table, encoding="utf-8")


if __name__ == "__main__":
    main()
