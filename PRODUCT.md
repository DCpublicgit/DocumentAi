# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React + Vite, plain CSS (no heavy UI framework) — user's explicit choice for this surface, a single-page custom chat interface.

## Users

Internal company employees (~200, low real volume) asking questions about company policy in Mongolian. Not the public; an internal pilot tool accessed from inside the company.

## Product Purpose

A retrieval-grounded (RAG) chatbot that answers employee policy questions strictly from official policy documents, in Mongolian. It exists to replace ad-hoc "ask HR" / "search the shared drive" behavior with a single, trustworthy, always-cited answer surface — and to refuse cleanly rather than hallucinate when a question isn't covered by policy.

## Positioning

Unlike a generic chatbot bolted onto an LLM, every answer is grounded in retrieved policy chunks only, always carries a `file · section · version (effective_date)` citation, and refuses with a fixed, exact string when the retrieved context doesn't cover the question. Policy versioning is first-class (old versions kept, not deleted, for "as of" questions). This is a compliance surface, not a demo chatbot.

## Operating Context

Pilot hosted on one small VM (Oracle A1 Always Free) via `docker compose`. The UI is one more `ui/` service alongside `postgres` and `app` (our FastAPI backend). All retrieval/grounding lives in the backend; the UI only calls our OpenAI-compatible `POST /v1/chat/completions` (SSE streaming) — never the raw Anthropic/Ollama API, never its own retrieval. Responses stream token-by-token in Mongolian Cyrillic.

## Capabilities and Constraints

- Single conversation view: input box, send on Enter, streaming assistant reply rendered token-by-token as SSE arrives.
- The backend appends a citation block (`Эх сурвалж: ...`) to grounded answers; the UI must parse it into structured data (file, section, version, effective_date) and render it as a distinct, clickable/expandable panel per source — not inline text.
- The backend's refusal is one exact fixed string (see `docs/DATA_CONTRACT.md`). When the reply IS that exact string, render a visually distinct "not found in policy" state with no citation panel.
- No model selector: the model is fixed by backend env var, never user-facing. The UI is intentionally "dumb" — no retrieval, chunking, or grounding logic of its own (CONTRIBUTING.md rule 4).
- No auth in this phase: a single shared page for the pilot. SSO integration is a later phase, reusing SSO already used elsewhere on the platform — the UI should not preclude adding it later, but does not implement it now.
- Mongolian Cyrillic is the only user-facing language (UI chrome, refusal state, citations) and must render correctly (UTF-8, a font and line-height suited to Cyrillic).
- ARM64-friendly deployment (Oracle A1) — the UI's docker-compose service must build/run on arm64.

## Brand Commitments

None. No company name, logo, or existing visual identity was provided — this is an internal pilot tool without an established brand to preserve.

## Evidence on Hand

No screenshots, mockups, or existing UI to reference (Open WebUI was used in an earlier phase but is being replaced by this custom UI, not extended). No real user content beyond the 3 sample Mongolian policy documents already ingested in `./policies/`. Future work must not fabricate company branding, testimonials, or user data.

## Product Principles

- Grounding and refusal are compliance behavior, not UI copy — the refusal state must never be stylistically softened into looking like a normal answer, and citations must never be optional decoration.
- Citations are structured data (they're the audit trail), not prose — always parse and render them as distinct, inspectable sources.
- The UI stays dumb by design: all intelligence (retrieval, grounding, refusal decisions) lives in the backend; the UI only renders what it's given.
- Low-volume internal pilot: prioritize clarity, correctness, and trustworthiness over scale, growth, or engagement features.

## Accessibility & Inclusion

Default good practices, no formal compliance target: semantic HTML, full keyboard operability (send on Enter, focus management), sufficient color contrast, no accessibility-hostile patterns. Not targeting a formal WCAG level for this pilot.
