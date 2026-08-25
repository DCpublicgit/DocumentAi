# Architecture

## Flow
Employee → custom chat UI (ui/, React + Vite, plain CSS, served via nginx)
        → OUR FastAPI  /v1/chat/completions  (the brain)
              → hybrid retrieve (pgvector + Postgres FTS, RRF merge)
              → build small grounded prompt (top_k chunks only)
              → LLM (Anthropic Haiku/Sonnet, local Ollama Qwen, or a hosted
                OpenAI-compatible provider: OpenAI, Gemini, DeepSeek)
              → Mongolian answer + citations, OR refusal
Offline (CLI, cron-able): policies/ → extract → chunk → BGE-M3 embed → pgvector

## Components
- **Postgres 16 + pgvector** — one DB. Vector search, FTS, and metadata in one engine
  we can run on the free VM. (5k chunks is tiny; this is deliberately boring.)
- **BGE-M3** (BAAI/bge-m3, dim 1024) — multilingual embeddings, runs on CPU. No API cost.
- **FastAPI backend** — retrieval + grounding + OpenAI-compatible serving.
- **Custom chat UI** (`ui/`) — React + Vite, plain CSS, no heavy framework. Talks only to
  our `/v1/chat/completions` (SSE streaming); no retrieval/grounding of its own, no model
  selector (model is fixed by backend env), no auth in this phase. Served via nginx.
- **Ollama (optional)** — local Qwen for the V3 comparison run.
- **OpenAI-compatible providers (optional)** — OpenAI, Gemini, DeepSeek for the
  V4–V6 comparison runs. No local service — hosted APIs, paid, need budget
  approval before use (see `docs/EVAL_RUNBOOK.md`).

## Why these choices (do not relitigate mid-build)
- NOT Snowflake Cortex: it bills warehouse compute per question; our retrieval is ~free on the VM.
- NOT a turnkey RAG app (AnythingLLM/RAGFlow) as the brain: they take back retrieval and
  can't cite policy *version*. We keep the brain to enforce grounding + versioning.
- pgvector over FAISS/Qdrant: one engine, metadata filtering, runs on the free box.

## Ingestion note
The ingest module exposes a single `run_ingest(policy_dir)` entrypoint so it can later
become a Dagster asset in the main platform. For the pilot it runs standalone via CLI/cron.

## Deployment
Single `docker compose up` on an Oracle A1 (ARM64) instance: postgres, app, ui,
(ollama for V3). Use ARM-compatible images.