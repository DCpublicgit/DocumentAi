# Internal Policy Chatbot

Retrieval-grounded (RAG) chatbot that answers employee questions about company
policies in Mongolian, strictly from official policy documents. See
`docs/ARCHITECTURE.md` and `docs/DATA_CONTRACT.md` for the design and the
authoritative schema/env var/citation contract.

## Run it

1. Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY` (needed
   unless you're running the V3 Ollama comparison, see below).

   ```
   cp .env.example .env
   ```

2. Start the stack:

   ```
   docker compose up -d
   ```

   This starts Postgres+pgvector, our FastAPI backend (creates the
   `policy_chunks` schema on startup if it doesn't exist), and the custom
   chat UI (`ui/`, React + Vite, served via nginx).

3. Load policy documents. Drop your `.pdf` / `.docx` / `.txt` files into
   `./policies/` (filename convention: `Name__v3__2025-01-01.pdf` — see
   `app/ingest/naming.py`; files that don't follow it fall back to `v1` /
   no effective date), then run the ingest CLI inside the `app` container:

   ```
   docker compose exec app python -m app.ingest
   ```

   This prints a DQ summary (chunk counts, null-embedding rate, per-file
   coverage) and fails loudly if it produced zero rows. Re-running it on the
   same file+version is safe (idempotent — replaces cleanly, no duplicates).

4. Open the chat: go to **http://localhost:3000**. No login (no auth in this
   phase — a single shared page for the pilot; SSO is a later phase, reusing
   SSO already used elsewhere on the platform). The UI talks only to our own
   backend (`/v1/chat/completions`, proxied by nginx to the `app` service) —
   never the raw Anthropic/Ollama API. Ask a policy question in Mongolian;
   the answer streams in and, once grounded, ends with a distinct citation
   panel (click a source to expand file/section/version/date). An
   off-topic question renders a visually distinct "not found in policy"
   state instead — the exact refusal string, no citation panel.

## Useful endpoints (our backend, not the UI)

- `GET http://localhost:8000/health` — liveness + DB connectivity
- `GET http://localhost:8000/v1/models` — the one model we expose
- `POST http://localhost:8000/v1/chat/completions` — OpenAI-compatible,
  supports `"stream": true` (SSE) and non-streaming

## V3 comparison run (local Ollama/Qwen)

The `ollama` service is commented out in `docker-compose.yml` by default
(it's a large image/model and not needed for the Anthropic-only path).  To
run the V3 comparison:

1. Uncomment the `ollama` service and the `ollama_data` volume in
   `docker-compose.yml`.
2. `docker compose up -d ollama`, then `docker compose exec ollama ollama
   pull qwen2.5:7b`.
3. In `.env`, set `LLM_PROVIDER=ollama` and `LLM_MODEL=qwen2.5:7b`.
4. `docker compose up -d app` to restart the backend with the new provider.

## Tests

```
uv run pytest tests/
```
