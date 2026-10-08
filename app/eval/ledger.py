"""Append-only history of eval runs: one JSON line per run, holding the
summary (accuracy, cost, latency, settings, models per step) and nothing else.

Deliberately no question or answer text: those are policy content, and the
ledger is the file most likely to be shared or committed. Per-question detail
stays in the run's own CSV.

`python -m app.eval report` builds the latest comparison from this file, so
"which setup is best and what does it cost" never depends on remembering which
summary.json files to pass to `compare`.
"""

import json
from pathlib import Path

DEFAULT_LEDGER = Path("eval_results") / "ledger.jsonl"


def append_entry(summary: dict, path: Path = DEFAULT_LEDGER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")


def load_entries(path: Path = DEFAULT_LEDGER) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries
