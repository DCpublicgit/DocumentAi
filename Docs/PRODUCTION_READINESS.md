# Production Readiness — Internal Policy Chatbot

Status as of 2026-08-10. Every number below is **measured on the real corpus**,
not estimated; where something is an estimate it says so.

This is a compliance surface (see CONTRIBUTING.md). The ordering below reflects that:
a wrong answer with a confident citation is worse than a slow answer, and a
leak of who-asked-what is worse than both.

---

## 1. Where we actually are

| Dimension | Measured | Verdict |
|---|---|---|
| False answers (should refuse, answered) | **0 / 8** | Good — never fabricated |
| Refusal accuracy | **83.3%** (30 q) | Fixable, cause known |
| Citation accuracy | **80.0%** (30 q) | Fixable, same cause |
| Wrong-document retrieval | **6 / 22** answerable | **The core defect** |
| Latency, rerank off | ~1.5–3 s retrieval + ~1.0 s TTFT | Acceptable |
| Latency, rerank on | ~43 s (rerank = 93%) | Unshippable; disabled |
| Eval errors | 0 / 30 (was 19/30 pre-retry-fix) | Fixed |
| Corpus | 304 chunks / 25 files, 1.3% over budget | Healthy |

**The single accuracy defect:** HR questions retrieve ISO-27001 security
chunks. The corpus is ~92% security documents (22 files, 8–29 chunks each)
against 3 small HR documents (5–6 chunks each). All 6 failures are this. The
LLM then refuses rather than fabricate — rule 1 working — so the symptom is
false refusals, but the fault is upstream in ranking.

Not a threshold problem: 5 of the 6 wrong documents score **above** the 0.5
gate. Raising the gate refuses more; lowering it answers from the wrong policy.

---

## 2. P0 — blockers before any real employee uses this

> **Not a blocker: authentication.** `PRODUCT.md:35` deliberately defers auth
> ("no auth in this phase: a single shared page for the pilot; SSO is a later
> phase"), and the deployment target is confirmed internal-only — not reachable
> from outside the company network. That decision stands for the pilot.
>
> Two things to revisit later, neither urgent:
> - The corpus grew after that decision was made. It now includes access
>   control, cryptography/key management, network security, vulnerability
>   management, physical security and logging procedures (L1-POL/L2-MAS/L3-SOP).
>   Whether *every* employee should retrieve those is a data-governance
>   question, separate from perimeter security. `policy_documents.doc_level`
>   already carries the field you would filter on.
> - `docker-compose.yml` binds `ui` and `app` to `0.0.0.0` (Postgres is
>   correctly `127.0.0.1`). Harmless behind the current network boundary;
>   revisit if that boundary ever changes.

### 2.1 The project is not in version control
There is no `.git` in the project. `git status` resolves to `C:\`. So there is
no change history, no rollback, no review, no CI — on a system whose answers
are supposed to be auditable.

**Acceptance:** `git log` inside the project returns this project's history;
`.env` stays ignored (it already is in `.gitignore`).

### 2.2 No audit trail of questions and answers
Nothing persists what was asked, what was retrieved, what was cited, or which
policy version was in force. For an HR/compliance bot that is the record you
will be asked for. It also makes every quality regression un-investigable.

- Persist per request: timestamp, user, question, retrieved chunk PKs,
  citations, refusal flag, model, latency, request id.
- Decide retention up front — employee questions are personal data. State the
  retention window and who can read the table.

**Acceptance:** any answer can be reconstructed from the log, including the
exact policy version cited.

### 2.3 The real corpus is not loaded
The 3 HR documents are stubs: 836, 1256 and 1353 characters. The eval is
written against them. Real policies will change chunk distribution, retrieval
behaviour and every number in section 1.

**Acceptance:** production documents ingested; section 1 re-measured against
them before go-live.

### 2.4 Secrets handling
`.env` is correctly gitignored, but holds live provider keys in plaintext and
is the only source of config on the box.

- Move to the deployment's secret mechanism; rotate the keys that have been
  in developer hands.
- No key ever reaches the browser (currently true — the UI calls a relative
  path).

---

## 3. P1 — before rolling out to all ~200 users

### 3.1 Fix retrieval precision (the accuracy defect)
Options, cheapest first. Measure each against the eval, do not stack blindly:

1. **Metadata filtering / routing.** `policy_documents` already carries
   `doc_level`, `department`, `owner_unit`. An HR question should not be able
   to retrieve L1-POL/L2-MAS/L3-SOP security chunks at all. Highest
   expected value, no new model, no latency cost.
2. **Fix and re-enable the reranker.** This is exactly the job a cross-encoder
   does. It needs both fixes together: an explicit `max_length` (it currently
   has none against 500-token chunks, and scored every candidate ~0.000–0.003),
   plus int8 quantization / a smaller model to make it affordable on CPU.
   See section 4.
3. **Revisit query expansion.** Suspected of diluting the candidate pool: with
   one phrasing a target chunk scored 0.996; with three phrasings and a
   71-candidate pool the same question scored 0.0027. Currently unproven and
   worth an A/B — it is already env-gated.

**Acceptance:** wrong-document retrieval < 1/22 on the expanded eval; citation
accuracy ≥ 95%; still 0 false answers.

> **Update, 2026-08-13.** Two partial mitigations shipped, confirming this
> section's analysis rather than resolving it:
>
> - **Per-chunk citation floor** (`app.retrieve.retriever.select_cited_chunks`):
>   a chunk now has to individually clear `refusal_threshold()` to be cited,
>   not just ride into the TOP_K window on a stronger candidate's strength.
>   Stops the worst case (a returned chunk with no individual score-based
>   support at all). **Does not fix the precision defect above.** Traced live,
>   rerank off: for "Нөөцлөлтийн 3-2-1 дүрэм гэж юу вэ?" the correct chunk
>   scored 0.534 cosine and an unrelated network-security-policy chunk scored
>   0.516 — an 0.018 gap. No `SCORE_THRESHOLD` value separates those cleanly,
>   which is this section's own point: cosine alone is "a much narrower band"
>   (see `refusal_threshold()`'s docstring) than the bimodal reranker signal
>   option 2 above proposes. With rerank off, several genuinely-answered runs
>   still cited 3-4 unrelated policies alongside the correct one.
> - **Query expansion prompt tightened** + `QUERY_EXPANSION_N` default 2→1
>   (`app/retrieve/query_expansion.py`, `app/config.py`): the rephrasing
>   prompt now explicitly forbids generalizing away specific terms (numbers,
>   standard names). Reduced but did not eliminate drift — live testing after
>   the change still hit a complete miss (correct document entirely absent
>   from retrieval) in roughly 1 of 6 repeated identical questions. Fewer,
>   tighter rephrasings lower the odds one drifts; a single rephrasing can
>   still drift on its own. This is evidence toward option 3 above, not a
>   substitute for the A/B it recommends.
>
> Neither change touched `SCORE_THRESHOLD`, `RERANK_ENABLED`, or RRF — see
> §3.3 and option 2 above for why those need the expanded eval (§3.2) behind
> them, not a hand-tune against one question.

### 3.2 Expand the eval set and gate on it
30 questions cover 3 of 25 documents. 22 files have zero coverage, so today's
83%/80% describe a corner of the corpus.

> **Update, 2026-08-13.** `app/eval/questions.yaml` has grown to **78
> questions**, covering **22 of the 23 currently-ingested documents** (only
> `10. МАБ үүрэг хариуцлагын баримт бичиг.docx` has zero coverage). A fresh
> run against the current pipeline (gemini-flash-lite, rerank off, query
> expansion on) scored **96% refusal / 96% citation accuracy, 0 errors** —
> see `eval_results/gemini_flash_lite_citation_fixes.summary.json`. The
> 83%/80% figures above are the OLD 30-question baseline; kept for the
> historical comparison, not current state. `Docs/EVAL_RUNBOOK.md` has been
> updated to describe the set as 78-question.

- Author grounded Mongolian Q&A per document, verified against real chunks.
- Include: answerable, must-refuse, and **wrong-document traps** (questions
  whose vocabulary overlaps another policy).
- Run in CI on every change to chunking, retrieval or prompts; fail the build
  on a regression in false-answer count.

**Acceptance:** every ingested document has ≥3 questions; eval runs in CI.

### 3.3 Reconcile `SCORE_THRESHOLD`
`.env` says `0.5`; `Docs/DATA_CONTRACT.md` and the `app/config.py` default say
`0.35`. Production runs 0.5. Do not sync blindly — measured evidence: the
off-topic q28 scores 0.4150, so it refuses correctly at 0.5 and would
**wrongly answer** at 0.35. Pick deliberately, then make doc, default and
`.env` agree.

> **Update, 2026-08-13.** `.env` now reads `SCORE_THRESHOLD=0.35` (matches
> `app/config.py` and `Docs/DATA_CONTRACT.md`) and `RERANK_ENABLED=false` — so
> the three-way drift this section describes is gone, but that is incidental
> to whenever `.env` was last edited, not a deliberate resolution of the
> question this section actually asks: which value is *correct* for this
> corpus. §3.1's update above shows 0.35 is too loose to separate relevant
> from merely-similar chunks; this section's own q28 evidence shows 0.5 was
> chosen specifically because 0.35 answers a wrong-document case. Both point
> the same direction — 0.35 is very likely wrong — but neither is the
> eval-backed decision this section calls for. Still open.
>
> **Update, 2026-08-26. Resolved — `SCORE_THRESHOLD=0.52`, eval-backed.**
> `python -m app.eval calibrate` (new: `app/eval/calibrate.py`) scores every
> question in the (now 78-question, see §3.2) eval set and sweeps candidate
> thresholds against the `should_refuse` labels. Measured: relevant
> questions score 0.4263–0.7739, off-topic-but-real questions score
> 0.4150–0.5969 — genuine overlap (0.4263–0.5969), confirming this section's
> own point that no threshold separates these perfectly on cosine alone.
> 0.52 minimizes a false-pass-weighted error count (4/13 off-topic still
> answered, 4/65 relevant refused) — a real, measured improvement over the
> old 0.35 default, which let through 13/13 of the off-topic questions
> (the gate was doing almost nothing). Concretely reproduced live: "Цалин
> олгох өдөр хэзээ вэ?" scored 0.4842 — below 0.5969 (this corpus's off-topic
> ceiling), so no cosine threshold below ~0.60 would have refused it reliably;
> 0.52 does, at an acceptable cost in false refuses. Re-run `calibrate` after
> any meaningful corpus or embedding-model change.
>
> **A separate, more urgent finding surfaced while diagnosing that query:**
> §3.1's "core defect" analysis (2026-08-10) describes the corpus as "~92%
> security documents (22 files) against 3 small HR documents (5–6 chunks
> each)." As of this update, `policy_chunks` and `policy_documents` contain
> **zero** HR documents — not de-ranked, not `is_current=false`, not present
> in any version. `policies/` on disk has no HR-titled files either. The
> 22–23 security documents are otherwise unchanged. This means the "HR
> questions retrieve ISO-27001 chunks" defect §3.1 describes is no longer a
> ranking problem at all — there is nothing HR-related left to rank. Whether
> those 3 documents were deliberately removed (e.g. descoping this pilot to
> security policy only) or lost some other way is unknown from what's
> visible here — worth confirming deliberately, since §3.1's options
> (metadata filtering, reranking, query expansion) all assume HR content
> exists to be found. If it's gone for good, §1's "core defect" framing and
> §3.1 both need rewriting around a content gap, not a precision defect.

### 3.4 Close the remaining retry gap
`OpenAICompatibleClient` now retries 429/5xx with bounded jitter (Retry-After
honoured, non-429 4xx deliberately not retried). **`AnthropicClient` still has
the original gap** and will fail the same way under load.

### 3.5 Provider decision and cost control
Gemini free tier cannot serve 200 users: each question costs **two** calls
(expansion + generation), and a 30-question eval exhausted the quota until
backoff was added. The provider comparison in `Docs/EVAL_RUNBOOK.md` is still
pending the paid-key budget approval noted in CONTRIBUTING.md.

Also: `eval_results/comparison.md` still contains numbers from runs where 26/30
questions failed on exhausted Anthropic credit. **Delete or annotate it** — it
currently reads as a real V1/V2 comparison and is not one.

---

## 4. Latency and capacity

Current shape, per question, rerank disabled:

| stage | ms | share |
|---|---:|---:|
| query_expansion | ~1,240 | serial, blocks retrieval |
| llm_ttft | ~1,030 | hosted provider RTT |
| query_embedding | ~350 | |
| vector + FTS search | ~29 | free |
| rrf_merge / prompt assembly | ~0 | free |

This is fine for the pilot. Two things to know:

- **Reranking is not viable on CPU as configured.** ~4.1 s per candidate,
  ~1.29 TFLOP per question at `RERANK_TOP_N=10`, ~32 GFLOP/s sustained on 4
  fp32 threads — that is roughly the *expected* speed for a 302M-param
  cross-encoder, not a bug. Levers: int8 dynamic quantization (2–4×), explicit
  `max_length` (up to ~7× on batches padded to a 1260-token outlier), a smaller
  reranker such as `bge-reranker-base` (~3.5×), ONNX/OpenVINO (2–3×).
  Stacked, ~41 s → ~2–4 s. The Oracle A1 pilot VM is 4 ARM cores with no
  AVX-512, so expect it to be **no faster than the dev laptop**.
- **Throughput, not latency, is the scaling risk.** Embedding and reranking are
  CPU-bound and hold a core for their duration. `to_thread` keeps the event
  loop responsive but does not add cores. Set an explicit concurrency limit and
  queue beyond it, so a burst degrades predictably instead of thrashing.

**Memory:** both models resident ≈ 4.0 GB. The 24 GB pilot VM is fine. Warm-up
adds ~19–25 s to startup (deliberate — it moved that cost off the first user
question), so any health check must tolerate it.

---

## 5. Reliability, observability, operations

- **Health checks:** `/health` verifies Postgres but not model readiness. It
  returns 200 only after warm-up today, which is the right behaviour — keep it
  and make the orchestrator's start-up probe tolerant of ~30 s.
- **Metrics:** `app/timing.py` emits structured per-stage JSON. Ship it
  somewhere queryable and alert on: refusal rate (a spike means retrieval
  broke), p95 latency, provider error rate, and zero-chunk retrievals.
- **Backups:** the `postgres_data` volume holds the only copy of the embedded
  index and the document registry. Re-ingest is a ~10 min recovery path for
  chunks, but `policy_documents`/`policy_document_links` history is not
  reproducible from files alone. Back it up and **test a restore**.
- **Ingest operations:** ingest is atomic and idempotent (verified: 25 files →
  304 rows, no duplicates). Decide who re-ingests when a policy changes, and
  how a new version is signed off — `is_current` flipping is what employees see.
- **Runbook:** provider outage, quota exhaustion, bad ingest rollback, and "the
  bot answered wrong" triage using the audit log from 2.2.

---

## 6. Product and human factors

- **Feedback capture.** A thumbs-down with the request id is the cheapest
  source of eval questions you will ever get.
- **Escalation path.** When the bot refuses, tell the employee who to ask.
  Refusal is correct behaviour, but a dead end is a bad experience.
- **Publish the scope.** Employees must know which policies are covered and as
  of when, or they will assume silence means "no such rule".
- **Answer freshness.** Citations already carry version and date. Surface them
  prominently; that is the difference between an answer and an authority.

---

## 7. Suggested order

1. Version control + audit log (P0 §2.1–2.2) — independent, can run in parallel.
2. Load the real corpus (§2.3), re-measure the baseline.
3. Retrieval precision via metadata filtering (§3.1.1), re-measure.
4. Expand eval + CI gate (§3.2). Everything after this is measurable.
5. Reranker fix/decision (§3.1.2, §4) and threshold reconciliation (§3.3).
6. Provider decision + cost controls (§3.5), pending budget approval.
7. Backups, alerting, runbook (§5).

Steps 1–2 are prerequisites for trusting any number produced after them.
