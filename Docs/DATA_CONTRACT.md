# Data Contract (authoritative — do not improvise these)

## Table: policy_chunks
Grain: one row per (file_name, policy_version, chunk_index). PK: (file_name, policy_version, chunk_index).

| column         | type          | notes |
|----------------|---------------|-------|
| file_name      | text          | source file, e.g. "Чөлөө олгох журам.pdf" |
| section        | text          | e.g. "5.2" or heading text; nullable |
| policy_version | text          | e.g. "v3"; from filename or a manifest |
| effective_date | date          | nullable |
| is_current     | boolean       | only true rows are retrieved by default |
| chunk_index    | int           | order within (file, version) |
| content        | text          | the chunk text |
| content_tsv    | tsvector      | to_tsvector('simple', content) — GIN index |
| embedding      | vector(1024)  | BGE-M3 dense — HNSW vector_cosine_ops index |
| ingested_at    | timestamptz   | freshness |

## Table: policy_documents
Grain: one row per (doc_number, policy_version, file_name). PK: (doc_number, policy_version, file_name).
`file_name` is part of the grain — not just `doc_number` + `policy_version` — because the
source corpus contains a confirmed real-world numbering collision (L1-POL-10 is used by two
distinct documents; see `data_quality_flags: duplicate_doc_number`). Without `file_name` in
the key, ingesting the second document would silently overwrite the first.

| column             | type        | notes |
|--------------------|-------------|-------|
| doc_number         | text        | e.g. "L3-SOP-49" |
| policy_version     | text        | matches policy_chunks.policy_version for this doc |
| doc_level          | text        | 'L1-POL' \| 'L2-MAS' \| 'L3-SOP' \| 'L5-REC' — parsed from doc_number prefix |
| department         | text        | owning department, nullable until dept rollout assigns one |
| title_mn           | text        | from cover page; NOT guaranteed to match title used elsewhere (see data_quality_flags) |
| file_name          | text        | FK to policy_chunks.file_name |
| effective_date     | date        | cover-page "Мөрдөж эхлэх огноо" |
| mandatory_from     | date        | nullable — compliance date from a governing Order, if different from effective_date |
| iso_clause         | text        | nullable |
| owner_unit         | text        | "Боловсруулсан нэгж" from cover page |
| is_current         | boolean     | true unless a newer policy_version of this same file_name has superseded it |
| data_quality_flags | text[]      | e.g. 'title_mismatch', 'duplicate_doc_number', 'toc_broken_ref', 'blank_template_appendix' |
| ingested_at        | timestamptz | |

## Table: policy_document_links
Grain: one row per (source_doc_number, source_version, source_file_name, target_doc_number, link_type).
PK: (source_doc_number, source_version, source_file_name, target_doc_number, link_type).
`source_file_name` is in the grain for the same reason as `policy_documents.file_name` above —
it disambiguates links declared by two distinct documents that share a colliding doc_number.

| column            | type        | notes |
|-------------------|-------------|-------|
| source_doc_number | text        | |
| source_version    | text        | |
| source_file_name  | text        | FK to policy_documents.file_name; disambiguates duplicate doc_numbers |
| target_doc_number | text        | |
| link_type         | text        | 'related' (from ХАМААРАХ БАРИМТ БИЧИГ table) \| 'parent' (L1-POL-04 registry membership) \| 'record' (points to an L5-REC) |
| ingested_at       | timestamptz | |

## Versioning
On re-ingest of a file with a NEW policy_version: insert new rows, then in the SAME
transaction recompute is_current across every version of that file_name. Never delete
old versions.

`is_current` is DERIVED by comparing versions (`app.ingest.naming.latest_version`),
never by ingest order: exactly the newest policy_version of a file_name is current and
all others are not. Re-ingesting an older version must not resurrect it as current, and
version comparison is segment-wise numeric — v2 < v10, v1 < v1.1 — so filename sort
order does not decide which version wins.

## Registry membership
A `.txt` with no `Бүртгэлийн дугаар` declares no doc_number and is NOT a registry
document — the corpus legitimately contains policy files predating the ISO document
set (the legacy HR policies). Registry ingest skips these with a WARNING and counts
them in `RegistrySummary.files_skipped`; they still get `policy_chunks` rows, just no
`policy_documents` row. A file that DOES declare a doc_number but is missing a
required field is a defect and aborts the run — before any writes, so an aborted run
never leaves the register half-written.

## Retrieval
- Filter: is_current = true (unless caller asks "as of" a version).
- Hybrid: top-N by cosine (`embedding <=> qvec`) + top-N by FTS, merged via
  Reciprocal Rank Fusion (RRF, k=60). TOP_K (env, default 5) is a ceiling on
  how many chunks retrieval considers, not a floor it pads citations up to —
  see "Per-chunk citation floor" below.
- Refusal gate: compare the top score against the threshold for ITS scale —
  `RERANK_ENABLED=true` → cross-encoder relevance vs `RERANK_SCORE_THRESHOLD`
  (default 0.5); `RERANK_ENABLED=false` → cosine similarity vs `SCORE_THRESHOLD`
  (default **0.52**, calibrated — see below). Never share one value across
  both: the reranker's score is sigmoid-squashed and strongly bimodal,
  cosine is a narrow mid-range band, so one number cannot mean the same
  strictness in both modes.
- **`SCORE_THRESHOLD` calibration.** `python -m app.eval calibrate`
  (`app/eval/calibrate.py`) retrieves (no generation, no LLM cost) every
  question in `app/eval/questions.yaml`, sweeps candidate thresholds against
  the `should_refuse` labels, and reports the count that minimizes a
  WEIGHTED error total — a false pass (answering from irrelevant policy
  content) counts double a false refuse, since CONTRIBUTING.md rule 1 calls
  refusing "correct behavior, not a failure," not an equal-cost error to a
  wrong answer. Measured 2026-08-26 (RERANK_ENABLED=false, this corpus):
  relevant questions scored 0.4263–0.7739, off-topic-but-real questions
  scored 0.4150–0.5969 — the two ranges genuinely overlap (0.4263–0.5969),
  so NO threshold value separates them perfectly; 0.52 minimizes total
  weighted error (4/13 off-topic still answered, 4/65 relevant refused) vs.
  the old, uncalibrated 0.35 default (13/13 off-topic answered, i.e. the
  gate did almost nothing). Re-run after any meaningful corpus or
  embedding-model change — this value is measured, not assumed to hold.
- **Standalone query rewriting (multi-turn).** Runs BEFORE query expansion,
  as the first step of retrieval proper. `/v1/chat/completions` now accepts
  the full conversation, not just the newest message (`app.server._split_history`
  splits it into `history` — everything before the current turn — and
  `question`, the current turn itself). `app.retrieve.query_rewrite.rewrite_standalone_query`
  condenses `question` + `history` into one context-free query — a followup
  like "Тэгвэл цалинтай юу?" ("Is it paid, then?") only means anything next
  to the turn before it, and embedding/FTS see nothing but the followup's
  own words otherwise. Retrieval, AND the "Асуулт:" line the generation
  model itself sees, both use the REWRITTEN query; `answer_audit.question`
  still records the raw turn the employee actually typed — the two can
  differ, and today that's only visible in the `query_rewritten` field of
  the structured timing log (`app/timing.py`), not a column of its own; a
  genuine audit-trail column is future work, not done here.
  QUERY_REWRITE_ENABLED/PROVIDER/MODEL (own provider, same reasoning as
  query expansion's below) gate and configure it. Same fail-open posture as
  everything else on this path: no history (first turn) or any rewrite
  failure returns the original question unchanged, never blocks the request.
- **Query expansion drift.** Each rephrasing (`app/retrieve/query_expansion.py`)
  is a fresh, temperature-sampled LLM generation — not deterministic like the
  original question. RRF sums scores per exact `(file_name, policy_version,
  chunk_index)`, not per document, so a document whose relevant content spans
  several chunks never has ONE chunk with a strong enough cumulative score to
  reliably out-rank a single-chunk competitor a drifted rephrasing happens to
  favor — observed in practice: the correct chunk was present in every
  phrasing's raw top-20 candidates, but a generic third rephrasing ("reliably
  storing digital information" instead of "the 3-2-1 rule") sometimes ranked
  an unrelated document #1 instead, dropping the correct chunk out of the
  final TOP_K. Mitigated, not eliminated, by keeping `QUERY_EXPANSION_N` low
  (default 1) and constraining the rephrasing prompt to preserve specific
  terms (numbers, standard names, clause references) rather than generalizing
  them — a genuine fix (e.g. aggregating RRF by document rather than by
  chunk) is retrieval-algorithm work for the Phase 5 eval, not a one-line
  change to make unilaterally.
- **Per-chunk citation floor.** The refusal gate above only looks at the
  best-scoring chunk. Without a per-chunk check too, a weak candidate can
  still ride into the TOP_K window on the strength of that one strong
  candidate and get surfaced as if it supported the answer — this happened
  in practice with `RERANK_ENABLED=false` (the FTS branch is deliberately
  high-recall/low-precision, see `app/retrieve/retriever.py`, relying on the
  reranker — when present — to clean it up before the cut). So EVERY chunk in
  the TOP_K window is checked against the same threshold as the refusal gate
  (`app.retrieve.retriever.select_cited_chunks`); only chunks that
  individually clear it become `RetrievalResult.cited_chunks`, which is what
  generation and the citation list are built from. `RetrievalResult.chunks`
  (the full, unfiltered TOP_K window) still exists and is still what
  `answer_audit.retrieved_chunks` records — the audit trail needs the
  near-misses to answer "why did it refuse" or "what did retrieval almost
  cite but reject"; `answer_audit.citations` reflects `cited_chunks`, i.e.
  exactly what the employee was shown.

**Gibberish gate.** Before any of the above runs — before standalone query
rewriting, query expansion, embedding, FTS, or reranking —
`app.query_guard.is_gibberish` checks the RAW question (never the rewritten
one) for input that never had linguistic structure to begin with (keyboard
mashing, e.g. "цйбйцанжуа", "kjshdf lkjashdf"). A hit skips retrieval
entirely and returns the refusal string directly
(`app.answering._retrieve_and_prepare`), so junk input costs microseconds
instead of an LLM query-rewrite call, an LLM query-expansion call, an
embedding call, and a DB round trip — the concern this exists for is latency
on obviously pointless input, not just correctness. `app.audit.build_record`'s
`result=None` case is this path: there is no `RetrievalResult` because
retrieval never ran.

This is NOT a substitute for the refusal gate above, and deliberately narrow:
it only catches input with no linguistic structure in ANY script (a run of
`GIBBERISH_MAX_CONSONANT_RUN`, default 5, consecutive consonants in one
letters-only token; or a digit run fused directly onto letters on both
sides). A fluent-but-off-topic real question ("Улаанбаатар хотын өнөөдрийн
цаг агаар ямар байна?") has real linguistic structure and passes through
untouched — that overlap between on-topic and off-topic cosine-similarity
scores (observed: off-topic sentences scoring as high as 0.60 against
on-topic questions as low as 0.56, both above the current 0.35
`SCORE_THRESHOLD`) is a harder, separate calibration problem the refusal
gate above and the model's own refusal instruction handle instead, and is
NOT fixed by this gate.

The threshold defaults to 5, not lower: 4 flags real Mongolian words with
genuine 4-consonant clusters (e.g. "идэвхждэг") and common security-domain
acronyms in this corpus ("CVSS"). Any change to `GIBBERISH_MAX_CONSONANT_RUN`
or to `app.query_guard._VOWELS` must be re-checked against every question in
`app/eval/questions.yaml` for zero false positives (`tests/test_query_guard.py`
enforces this) — a false positive here tells an employee their real question
doesn't make sense, which is worse than the latency this gate saves.

## Citation format (exact)
Each cited source rendered as:  `[{file_name} · {section} · {policy_version} ({effective_date})]`
Answer ends with a "Эх сурвалж:" list of the cited sources.

`effective_date` resolution order: the `__v{version}__{YYYY-MM-DD}` filename
convention first, then the document's own "Мөрдөж эхлэх огноо" cover-page date
(`app.ingest.registry.parse_effective_date`). Only when neither exists does a
citation render `огноогүй` — most of the corpus doesn't follow the filename
convention, so without the fallback half the citations claimed to have no date
for documents that plainly state one.

Chunk content must never contain the literal `Эх сурвалж:`. It is the citation
header, and both `ui/src/lib/parseCitations.js` and `app/eval/runner.py` split an
answer at its FIRST occurrence — a chunk carrying the transcription provenance
footer would truncate the answer and corrupt the citation list.
`app.ingest.frontmatter` strips the bracketed form on ingest.

**Used-context selection.** `RetrievalResult.cited_chunks` (everything that
individually cleared the score floor, see "Per-chunk citation floor" above)
can still contain chunks the model's answer never actually drew from — the
floor establishes relevance, not usage. So each context block handed to the
model is numbered `[1]`, `[2]`, ... and the model is required (system prompt
rule 7) to end its answer with one machine-only line naming which numbers it
actually used — optionally with the specific inline clause it drew from,
for a chunk that contains several:

```
АШИГЛАСАН: 1:4.2, 3
```

(chunk 1, specifically its `4.2` clause; chunk 3 as a whole, no clause named)

`app.citations.extract_used_context` splits this line off before the answer
ever reaches the employee (streamed or not) and
`app.answering._resolve_used_context` narrows `cited_chunks` down to just
those indices — and collects the named clauses, keyed by chunk PK — for
both the rendered citation list and the audit `citations` column. This is a
SELECTION signal only — which of the already-numbered, already-relevant
candidates, and which of ITS OWN clause numbers — never citation text
itself; the rendered citation string stays fully code-generated per this
document's own rule, and a named clause is only ever honored after
`app.citations._extract_clause` verifies it actually appears in that
chunk's own text (see "Clause-level citation" below) — never taken on the
model's word alone. Fail open, same shape as query expansion's failure
handling: a missing, malformed, or empty marker falls back to citing every
chunk in `cited_chunks` under its first clause (today's pre-marker
behavior) rather than suppressing a citation that might have been
genuinely used; a named-but-unverifiable clause falls back to the chunk's
first clause the same way. A refusal never carries the marker (system
prompt rule 4 excludes it).

Streaming (`app.answering.stream_answer`) holds back only the
currently-in-progress line while the answer streams — never the full
response — so the marker line (always the last thing the model emits) never
reaches the client; every other line streams live as it always has.

**Clause-level citation.** When a chunk's `content` contains an inline
multi-level numbered clause (e.g. `4.1.2.` — the chunker deliberately does
not split on these, see `app/ingest/chunker.py`, so they survive as plain
text inside the chunk), the `{section}` slot above is replaced with
`Заалт {number}: {short description}` instead of the chapter heading. The
description is the clause's own text, truncated to `CLAUSE_DESCRIPTION_MAX_CHARS`
— extracted verbatim by code (`app.citations`), never generated or selected
by the model, for the same reason the rest of this citation format is
code-generated. If a chunk contains more than one clause number, the one
named by "Used-context selection" above is cited, when the model named one
AND it's verified present in the chunk; otherwise (no marker, no clause
named, or an unverifiable one) the first clause found is cited — this is
the sole remaining fallback path, not the general rule it used to be.
Falls back to the existing `{section}` behavior when no clause number is
present in the chunk at all.

## Refusal string (exact, Mongolian — adjust wording to house style, keep the meaning)
"Уучлаарай, энэ асуултын хариултыг компанийн бодлогын баримт бичгээс олж чадсангүй."

Detecting a model-produced refusal uses `app.contract.is_refusal`, not `==`:
models echo the sentence with a trailing period, quotes, or rewrapped
whitespace, and treating those as real answers appends a citation list to a
refusal — the one outcome rule 2 forbids. It normalizes cosmetics only, never
substring-matches, so an answer that merely mentions the refusal wording and
then answers keeps its citations. Serving and eval share this function so
reported refusal_accuracy describes shipped behavior.

## System prompt requirements (generation)
- Answer ONLY from the provided context blocks. Do not use outside knowledge.
- Do NOT copy sentences verbatim from the context. Synthesize and paraphrase
  in natural Mongolian — explain the policy the way a colleague would, not
  the way the document states it.
- Structure every non-refusal answer as Markdown (the UI renders it via
  `react-markdown` + `remark-gfm`/`remark-breaks`, restricted to an
  allowlist — see `ui/src/components/AssistantMarkdown.jsx` — so any
  construct outside that list, e.g. a `#` heading or an image, just
  degrades to its own text content, never breaks), two labeled parts with a
  blank line between the bold label and what follows it (plain "\n" alone
  renders as a soft break inside the SAME block, not a new one — the label
  and its content would run together on one line without it):

  **Товч хариулт**

  1-2 sentence direct answer to the question.

  **Дэлгэрэнгүй тайлбар**

  3-6 short `- `-prefixed bullet points (a real Markdown list) covering the
  relevant rules, conditions, and exceptions found in the context. Each
  bullet is a paraphrased point, not a copied sentence.

- When a context chunk contains a clause number inline (e.g. "4.1.2."),
  cite it in the "Эх сурвалж" list as `Заалт {number}: {short description}`
  (see "Clause-level citation" above — this is code-generated, not
  something the model itself outputs). If no clause number is present in
  the chunk text, cite the section only (existing behavior). Never invent a
  clause number that isn't in the text.
- If the answer is not in the context, output ONLY the refusal string above
  — the structure above does not apply to refusals.
- Always answer in Mongolian. Always end with the "Эх сурвалж:" citation list.
- Each context block is numbered ("[1]", "[2]", ...). After the answer,
  append one machine-only line naming which numbers were actually used, and
  optionally the specific clause used within a chunk that has several (see
  "Used-context selection" above) — omitted entirely on a refusal.

**Residual gap.** Selection is a best-effort signal from a small, cheap
model (`gemini-flash-lite-latest` as configured) — it can still name the
wrong clause, or none, for a chunk it genuinely used, in which case
`_extract_clause` falls back to that chunk's first clause (the pre-fix
behavior) rather than the specific one the answer is about. Verified
against `app/citations._extract_clause`, so a wrong or missing clause name
never CITES a clause number absent from the chunk — it only occasionally
under-specifies which one, same failure shape as before this section
existed, just less frequent.

## Environment variables (names are fixed)
LLM_PROVIDER=anthropic|ollama|openai|gemini|deepseek
LLM_MODEL=claude-haiku-4-5-20251001      # V1
# LLM_MODEL=claude-sonnet-5              # V2  (verify current id at docs.claude.com)
# LLM_PROVIDER=ollama LLM_MODEL=qwen2.5:7b  # V3
# LLM_PROVIDER=openai LLM_MODEL=<verify current flagship id at platform.openai.com/docs/models>    # V4
# LLM_PROVIDER=gemini LLM_MODEL=<verify current flagship id at ai.google.dev/gemini-api/docs/models> # V5
# LLM_PROVIDER=deepseek LLM_MODEL=<verify current id at api-docs.deepseek.com>                       # V6
ANTHROPIC_API_KEY=
OLLAMA_BASE_URL=http://ollama:11434/v1
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
GEMINI_API_KEY=
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
EMBEDDING_MODEL=BAAI/bge-m3
DATABASE_URL=postgresql://policy:policy@postgres:5432/policy
TOP_K=5
SCORE_THRESHOLD=0.52                        # gate when RERANK_ENABLED=false (cosine scale) — calibrated,
                                             # see "SCORE_THRESHOLD calibration" above
POLICY_DIR=/app/policies
RERANK_ENABLED=true
RERANK_MODEL=BAAI/bge-reranker-v2-m3       # multilingual, local, pairs with BGE-M3
RERANK_TOP_N=10                             # candidates fed into reranker before truncating to TOP_K
                                             # was 20; halved after measuring ~4.8s/candidate on the
                                             # CPU-only pilot VM (~130s -> ~50-65s) for 1/22 eval recall loss
RERANK_SCORE_THRESHOLD=0.5                  # gate when RERANK_ENABLED=true (cross-encoder scale)
QUERY_EXPANSION_ENABLED=true
QUERY_EXPANSION_PROVIDER=anthropic          # own provider: expansion is orthogonal to the V1-V6 generation comparison
QUERY_EXPANSION_MODEL=claude-haiku-4-5-20251001   # verify current id at docs.claude.com
QUERY_EXPANSION_N=1                         # additional rephrasings generated per question — kept low
                                             # to bound query-expansion drift, see "Query expansion
                                             # drift" above
QUERY_REWRITE_ENABLED=true                  # condense a followup + prior turns into a standalone query
                                             # before retrieval, see "Standalone query rewriting" above
QUERY_REWRITE_PROVIDER=anthropic            # own provider, same reasoning as QUERY_EXPANSION_PROVIDER
QUERY_REWRITE_MODEL=claude-haiku-4-5-20251001     # verify current id at docs.claude.com
WARM_UP_MODELS_ENABLED=true                 # load BGE-M3 + reranker at startup, not on the first user question
LLM_MAX_RETRIES=5                           # retries on transient upstream failures (429 / 5xx) per LLM call
LLM_RETRY_BASE_DELAY=1.0                    # seconds; exponential backoff with full jitter, Retry-After wins
LLM_RETRY_MAX_DELAY=30.0                    # seconds; ceiling on any single backoff wait
CLAUSE_DESCRIPTION_MAX_CHARS=80             # truncation length for the clause-citation short description
GIBBERISH_MAX_CONSONANT_RUN=5               # pre-retrieval gate, see "Gibberish gate" above — keep >=5

## LLM provider clients (app/llm/)
`get_client()` (`app/llm/__init__.py`) dispatches on `LLM_PROVIDER`. Anthropic
and Ollama each have a dedicated client; `openai`, `gemini`, and `deepseek`
all share one `OpenAICompatibleClient` (`app/llm/openai_compatible_client.py`)
since all three speak the same OpenAI-style `/chat/completions` shape —
provider-specific behavior is just `<provider>_BASE_URL` + `<provider>_API_KEY`,
never a code branch per provider.
