# Contributing — Internal Policy Chatbot

## What this is
A retrieval-grounded (RAG) chatbot that answers employee questions about company
policies **in Mongolian**, strictly from official policy documents. ~200 users,
low real volume. Pilot hosted on one small VM (Oracle A1 Always Free).

## Non-negotiable rules (this is a compliance surface)
1. **Answer ONLY from retrieved policy chunks.** Never use outside/model knowledge.
   If the retrieved context does not contain the answer, REFUSE with the exact
   Mongolian refusal string in docs/DATA_CONTRACT.md. Refusing is correct behavior,
   not a failure.
2. **Every answer cites `file · section · version`.** See the citation format in
   docs/DATA_CONTRACT.md. No answer ships without a citation.
3. **Answers are in Mongolian (Cyrillic).** The UI, refusal, and citations too.
4. **Retrieval and grounding live in THIS backend, never in the UI.** The UI
   The UI is a custom, dumb chat frontend that only calls our OpenAI-compatible endpoint and renders the response + structured citations. It does no retrieval, chunking, or grounding of its own.
5. **The generation model is swappable by env** (`LLM_PROVIDER`, `LLM_MODEL`) with
   zero code change: Anthropic (Haiku/Sonnet), local Ollama (Qwen), or a hosted
   OpenAI-compatible provider (OpenAI, Gemini, DeepSeek — one shared client,
   see `app/llm/openai_compatible_client.py`). We run a full comparison across
   providers (`docs/EVAL_RUNBOOK.md`) before picking one for long-run production
   use — pending company budget approval for the paid third-party API keys.
6. **Policy versioning is first-class.** Only `is_current = true` chunks are
   retrieved by default. Old versions are kept, not deleted, for "as of" questions.

## Engineering standards
- Layered, single-responsibility modules. No god-files, no giant joined query.
- **Idempotent + re-runnable.** Same docs in → same rows out, no duplicates.
- **Atomic ingest:** build new-version rows, then flip `is_current` in ONE
  transaction. Never leave the index half-written.
- **Declare grain + primary key before writing any table.** State it in a comment.
- **No hardcoded secrets, no hardcoded magic numbers.** `top_k`, score threshold,
  chunk size, model names → env/config, never inline literals.
- **Data-quality checks on ingest:** chunk row count, null-embedding rate,
  per-file coverage, freshness timestamp. Log them; fail loudly on zero rows.
- Typed Python (type hints + pydantic settings). Structured logging, not print.
- Postgres dialect only. pgvector cosine (`<=>`); FTS uses the `simple` config
  (there is no Mongolian dictionary — do NOT use `english`).
- Async FastAPI. The `/v1/chat/completions` endpoint MUST stream (SSE).
- Tests for: chunker (section/version parsing), retriever (returns is_current only),
  refusal (below-threshold → refusal string), citation formatter.

## Cost & scale posture
- At real volume this is ~$20/mo in tokens; do NOT build cost-optimization
  machinery (model routing, caches) until measured traffic justifies it.
- Flag anything that breaks at 10x docs or 10x QPS before finishing a phase.

## Workflow
- Work ONE phase at a time. At the end of each phase, run the phase's acceptance
  check, show me the result, and STOP. Do not start the next phase unprepared.
- Read docs/ARCHITECTURE.md and docs/DATA_CONTRACT.md before writing code.
  DATA_CONTRACT.md is authoritative for schemas, env names, citation format,
  and the refusal string — do not invent your own.