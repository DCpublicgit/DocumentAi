"""Builds one comparison table across multiple eval runs (V1/V2/V3), each
identified by its <name>.summary.json written by `python -m app.eval run`.
"""

import json
from pathlib import Path

_HEADERS = ["Run", "Provider", "Model", "Refusal accuracy", "Citation accuracy", "Avg latency (s)", "Errors", "N"]


def _run_name(summary_path: Path) -> str:
    name = summary_path.name
    return name[: -len(".summary.json")] if name.endswith(".summary.json") else summary_path.stem


def _money(value: float | None, digits: int = 2) -> str:
    # "n/a", never "$0": a run whose cost could not be measured must not look free.
    return "n/a" if value is None else f"${value:,.{digits}f}"


def _setup(entry: dict) -> str:
    """`answer=gemini/x, rewrite=...` — the mix, in the order a request uses it."""
    models = entry.get("models_by_role") or {}
    order = ["rewrite", "expansion", "answer"]
    parts = [f"{role}={models[role]}" for role in order if role in models]
    return "<br>".join(parts) if parts else f"{entry.get('provider')}/{entry.get('model')}"


def build_ledger_report(entries: list[dict], last: int | None = None) -> str:
    """Markdown comparison of runs in the ledger, newest last. Runs that were
    stopped early or whose cost is unknown are flagged in the table, not
    dropped: a comparison that hides a bad run is worse than none."""
    if last is not None:
        entries = entries[-last:]
    if not entries:
        return "No eval runs in the ledger yet. Run `python -m app.eval run --out eval_results/<name>`."

    headers = [
        "Run", "When (UTC)", "Setup (per step)", "Refusal ok", "Source ok",
        "Off-topic answered", "Answerable refused", "Wrong source",
        "Median / p90 s", "$/1k questions", "Monthly @ scenario", "Notes",
    ]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for e in entries:
        notes = []
        if e.get("stopped_reason"):
            notes.append(f"STOPPED: {e['stopped_reason']} ({e['n_questions']}/{e.get('n_planned')} run)")
        if e.get("n_errors"):
            notes.append(f"{e['n_errors']} errors")
        if e.get("unpriced_models"):
            notes.append("unpriced: " + ", ".join(e["unpriced_models"]))
        row = [
            e.get("label") or "-",
            (e.get("timestamp") or "")[:16].replace("T", " "),
            _setup(e),
            f"{e['refusal_accuracy']:.1%}",
            f"{e['citation_accuracy']:.1%}",
            f"{e.get('off_topic_answered', '?')}/{e.get('n_off_topic', '?')}",
            f"{e.get('answerable_refused', '?')}/{e.get('n_answerable', '?')}",
            str(e.get("answered_wrong_source", "?")),
            f"{e.get('latency_p50_s', e['avg_latency_s'])} / {e.get('latency_p90_s', '?')}",
            _money(e.get("cost_per_1k_questions_usd")),
            _money(e.get("scenario_monthly_usd"), 0),
            "; ".join(notes) or "",
        ]
        lines.append("| " + " | ".join(row) + " |")

    scenario = entries[-1].get("scenario_questions")
    lines.append("")
    lines.append(
        f"Monthly @ scenario = cost per question x {scenario:,} questions/month "
        "(100 people x 5 sessions x 10 questions x 22 workdays). First-turn basis: "
        "follow-up rewrite calls are not in a single-turn eval."
        if scenario
        else "Monthly @ scenario: not recorded for these runs."
    )
    lines.append(
        "Off-topic answered is the worse error (a grounded-looking answer to a question "
        "the documents don't cover); answerable refused costs the employee a re-ask."
    )
    return "\n".join(lines)


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
