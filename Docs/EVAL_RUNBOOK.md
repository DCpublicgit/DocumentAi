# Eval Runbook

Compares LLM_PROVIDER/LLM_MODEL configurations against the same 78-question
Mongolian eval set (`app/eval/questions.yaml`, covering 22 of the 23
currently-ingested documents), scoring:

- **Refusal correctness** — did the model refuse exactly when `should_refuse:
  true` (off-topic / not covered), and answer when `should_refuse: false`?
- **Citation correctness** — for non-refusal questions, does the answer's
  `Эх сурвалж:` block cite `expected_source_file`?
- **Answer text** — captured verbatim in the CSV for manual Mongolian-quality
  rating (grammar, naturalness) — this eval does not auto-score fluency.

Each run is fully driven by the real pipeline (`app.answering.answer_question`
— the same code path as `/v1/chat/completions`), against the live Postgres
index. Two independent dimensions can vary between runs:

1. **Generation model** — `LLM_PROVIDER`/`LLM_MODEL` (V1–V6 below).
2. **Retrieval config** — `RERANK_ENABLED` and `QUERY_EXPANSION_ENABLED` (see
   "Retrieval-quality dimension" below). Both default to `true`.

The question set and grounding logic itself stay fixed either way — only
which chunks get selected (retrieval config) and which model answers from
them (generation model) vary.

## Prerequisites

- `docker compose up -d` running (postgres + app), with policies already
  ingested (`docker compose exec app python -m app.ingest`).
- For V3: the `ollama` service uncommented in `docker-compose.yml` and
  `qwen2.5:7b` pulled (see README.md's "V3 comparison run" section).
- For V4–V6: a paid API key for that provider (`OPENAI_API_KEY`,
  `GEMINI_API_KEY`, `DEEPSEEK_API_KEY` in `.env`) — **needs budget approval
  first**, these are real hosted APIs, not free/local like V3. See
  `docs/DATA_CONTRACT.md` for the exact env var names and default base URLs.
  Verify the current flagship model ID for each provider before running —
  they move faster than this doc.

## Run V1 — claude-haiku-4-5-20251001

1. In `.env`: `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-haiku-4-5-20251001`.
2. `docker compose up -d app` (picks up the new env).
3. ```
   docker compose exec app python -m app.eval run --out eval_results/v1_haiku
   ```

## Run V2 — claude-sonnet-5

1. In `.env`: `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-sonnet-5`.
2. `docker compose up -d app`.
3. ```
   docker compose exec app python -m app.eval run --out eval_results/v2_sonnet
   ```

## Run V3 — ollama qwen2.5:7b

1. In `.env`: `LLM_PROVIDER=ollama`, `LLM_MODEL=qwen2.5:7b`.
2. `docker compose up -d app` (and `ollama` if not already running).
3. ```
   docker compose exec app python -m app.eval run --out eval_results/v3_qwen
   ```

## Run V4 — OpenAI

1. In `.env`: `LLM_PROVIDER=openai`, `LLM_MODEL=<current flagship, verify at platform.openai.com/docs/models>`, `OPENAI_API_KEY=<key>`.
2. `docker compose up -d app`.
3. ```
   docker compose exec app python -m app.eval run --out eval_results/v4_openai
   ```

## Run V5 — Gemini

1. In `.env`: `LLM_PROVIDER=gemini`, `LLM_MODEL=<current flagship, verify at ai.google.dev/gemini-api/docs/models>`, `GEMINI_API_KEY=<key>`.
2. `docker compose up -d app`.
3. ```
   docker compose exec app python -m app.eval run --out eval_results/v5_gemini
   ```

## Run V6 — DeepSeek

1. In `.env`: `LLM_PROVIDER=deepseek`, `LLM_MODEL=<current id, verify at api-docs.deepseek.com>`, `DEEPSEEK_API_KEY=<key>`.
2. `docker compose up -d app`.
3. ```
   docker compose exec app python -m app.eval run --out eval_results/v6_deepseek
   ```

## Retrieval-quality dimension: rerank + query expansion

Independent of which generation model is under test, `RERANK_ENABLED` and
`QUERY_EXPANSION_ENABLED` (`docs/DATA_CONTRACT.md`) each toggle a retrieval
upgrade on or off. Run the same eval set with both `true` and both `false`
against a fixed generation model (any one of V1–V6) to isolate the effect of
retrieval quality from the effect of model choice — don't conflate the two
by changing both at once:

```
# baseline: pre-upgrade retrieval behavior
# .env: RERANK_ENABLED=false, QUERY_EXPANSION_ENABLED=false
docker compose up -d app
docker compose exec app python -m app.eval run --out eval_results/v1_haiku_baseline

# upgraded retrieval
# .env: RERANK_ENABLED=true, QUERY_EXPANSION_ENABLED=true
docker compose up -d app
docker compose exec app python -m app.eval run --out eval_results/v1_haiku_rerank_expand
```

`app.eval`'s summary doesn't currently record which retrieval config produced
it — that's why the `--out` name itself has to carry it (`_baseline` vs
`_rerank_expand`), same as it already carries the model name. Keep that
naming convention for every run in this comparison.

**Query expansion always calls Anthropic (`QUERY_EXPANSION_MODEL`), even
when the generation model under test is V3–V6.** It's a fixed, model-
independent step by design (see `app/retrieve/query_expansion.py`) — so
`ANTHROPIC_API_KEY` must be valid for *any* run with
`QUERY_EXPANSION_ENABLED=true`, regardless of `LLM_PROVIDER`. Reranking has
no such dependency — it's a local CPU cross-encoder, same footprint as
BGE-M3 embedding.

`SCORE_THRESHOLD` (0.52, calibrated via `python -m app.eval calibrate` — see
`Docs/DATA_CONTRACT.md` "SCORE_THRESHOLD calibration") is on the raw cosine
similarity scale. With `RERANK_ENABLED=true` the refusal gate switches to the
cross-encoder's score instead (different scale — see the comment in
`app/retrieve/retriever.py`), so refusal accuracy may shift between the two
runs for reasons unrelated to retrieval quality. If that shows up in the
comparison, retune `RERANK_SCORE_THRESHOLD` for the reranked path (the same
`calibrate` command works there too) rather than reading it as a regression.

## Compare

Run with whichever summaries you actually have — `compare` accepts any number
of `.summary.json` paths, so a partial comparison (e.g. just V1 + V2 while
waiting on budget approval for V4–V6) works the same way:

```
docker compose exec app python -m app.eval compare \
  eval_results/v1_haiku.summary.json \
  eval_results/v2_sonnet.summary.json \
  eval_results/v3_qwen.summary.json \
  eval_results/v4_openai.summary.json \
  eval_results/v5_gemini.summary.json \
  eval_results/v6_deepseek.summary.json \
  --out eval_results/comparison.md
```

Prints (and writes) one markdown table with refusal accuracy, citation
accuracy, average latency, and error count per run.

## Choosing for long-run production use

Refusal accuracy and citation accuracy are pass/fail requirements, not
tie-breakers — a provider that scores lower on either is disqualified
regardless of price or speed (CONTRIBUTING.md rules 1–2: grounding and citations
are compliance behavior, not a quality knob). Among providers that pass both,
weigh:

- **Manual Mongolian-quality rating** of the `answer_text` column — the eval
  doesn't auto-score fluency, so this is a human read of each run's CSV.
- **Avg latency** — matters more here than usual, since the backend streams
  token-by-token to a live chat UI.
- **Cost at real volume** — CONTRIBUTING.md's cost posture is ~$20/mo in tokens at
  current pilot volume; get each provider's actual per-token price at
  decision time, not a remembered number (pricing changes faster than this
  repo).
- **Ops burden** — V3 (Ollama) has zero per-token cost but needs a VM with
  enough RAM/CPU to run inference; V1/V2/V4–V6 have no local footprint but
  recur as a paid bill.
- **Retrieval config is a separate decision from model choice** — pick the
  best model first using a fixed retrieval config, then separately confirm
  rerank+expansion actually improves that model's citation accuracy enough
  to justify the extra latency (cross-encoder pass) and cost (one Anthropic
  call per question for expansion, regardless of the chosen generation
  provider).

## Reading the per-question CSV

Each `eval_results/<name>.csv` has one row per question: whether refusal was
correct, which files were actually cited, whether that matched
`expected_source_file`, latency, and the full answer text. Open in
Excel/Sheets (not a plain text editor) — answer text can contain embedded
newlines from the citation block, which CSV quoting handles correctly but a
line-oriented viewer will not.

`eval_results/` is gitignored — these are run artifacts, not source.
