"""Builds one comparison table across multiple eval runs (V1/V2/V3), each
identified by its <name>.summary.json written by `python -m app.eval run`.
"""

import json
from pathlib import Path

_HEADERS = ["Run", "Provider", "Model", "Refusal accuracy", "Citation accuracy", "Avg latency (s)", "Errors", "N"]


def _run_name(summary_path: Path) -> str:
    name = summary_path.name
    return name[: -len(".summary.json")] if name.endswith(".summary.json") else summary_path.stem


def build_comparison_table(summary_paths: list[Path]) -> str:
    rows = []
    for p in summary_paths:
        s = json.loads(p.read_text(encoding="utf-8"))
        rows.append(
            [
                _run_name(p),
                s["provider"],
                s["model"],
                f"{s['refusal_accuracy']:.0%}",
                f"{s['citation_accuracy']:.0%}",
                f"{s['avg_latency_s']:.2f}",
                str(s["n_errors"]),
                str(s["n_questions"]),
            ]
        )

    lines = ["| " + " | ".join(_HEADERS) + " |", "|" + "---|" * len(_HEADERS)]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
