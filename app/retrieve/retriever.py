"""Hybrid retrieval: pgvector cosine top-N + Postgres FTS ('simple') top-N,
merged via RRF, filtered to is_current=true, gated by SCORE_THRESHOLD.

Two optional stages, both env-gated (see docs/DATA_CONTRACT.md) so they're
an A/B-able dimension in the Phase 5 eval, not just model choice:

- Query expansion (app.retrieve.query_expansion) runs BEFORE retrieval,
  rewriting the question into QUERY_EXPANSION_N alternate phrasings. Hybrid
  search runs once per phrasing (the original question is always phrasing
  0); every phrasing's vector + FTS ranked lists feed the SAME RRF fusion,
  so a chunk surfaced by several phrasings scores higher — the natural
  extension of RRF's existing "sum contributions across ranked lists"
  behavior, previously only applied across the vector/FTS branches of one
  query. Disabled, phrasings is just [question] — identical to the old
  single-query path.
- Reranking (app.retrieve.reranker) runs AFTER the RRF merge, BEFORE the
  top_k truncation. Widens the candidate pool to RERANK_TOP_N, scores each
  candidate against the ORIGINAL question with a local cross-encoder,
  reorders by that score, then truncates to TOP_K. Disabled, this is a
  no-op straight through today's TOP_K cut from RRF order.

Grain/PK reminder (see docs/DATA_CONTRACT.md): a chunk's identity is
(file_name, policy_version, chunk_index) — used here as the RRF item id so
the same chunk found by multiple ranked lists (vector/FTS branches, and now
multiple phrasings) is deduplicated and its scores summed.
"""

import asyncio

import asyncpg
from pgvector.asyncpg import register_vector

from app import timing
from app.config import settings
from app.contract import RRF_K
from app.embedding import embed_texts
from app.retrieve.models import RetrievalResult, RetrievedChunk
from app.retrieve.query_expansion import expand_query
from app.retrieve.reranker import rerank
from app.retrieve.rrf import reciprocal_rank_fusion

# cosine_similarity is computed in Postgres against $3 — the ORIGINAL query's
# embedding — while ordering uses $1, the current phrasing's. Two reasons:
# the refusal gate must always score against what the user actually asked, not
# whichever expansion happened to surface the row first; and returning the
# scalar instead of the vector(1024) keeps ~20 candidates x 2 branches x N
# phrasings worth of 1024-float payloads off the wire on every question.
_VECTOR_SQL = """
SELECT file_name, section, policy_version, effective_date, chunk_index, content,
       1 - (embedding <=> $3) AS cosine_similarity
FROM policy_chunks
WHERE is_current = true
ORDER BY embedding <=> $1
LIMIT $2
"""

# The lexical branch OR-joins the question's terms rather than AND-joining
# them. plainto_tsquery/websearch_to_tsquery both AND every term, and the
# 'simple' config does no stemming — there is no Mongolian dictionary — so an
# AND query requires a chunk to contain every inflected surface form of the
# question, interrogative particle ("вэ") included. Measured against the real
# corpus, that returned zero rows for all 30 questions in
# app/eval/questions.yaml: FTS contributed nothing and "hybrid" retrieval was
# silently dense-only.
#
# OR-joining is deliberately high-recall / low-precision. That is the correct
# division of labour here: this branch exists to surface lexical matches the
# dense vector misses, ts_rank_cd orders by how many terms actually hit, RRF
# fuses by RANK (so a weak lexical hit contributes little), and the reranker
# plus the refusal gate decide relevance. A branch that returns nothing cannot
# be outvoted — one that over-returns can.
_FTS_QUERY = """
    (SELECT string_agg(lexeme, ' | ')::tsquery
     FROM unnest(tsvector_to_array(to_tsvector('simple', $1))) AS lexeme)
"""

_FTS_SQL = f"""
SELECT file_name, section, policy_version, effective_date, chunk_index, content,
       1 - (embedding <=> $3) AS cosine_similarity
FROM policy_chunks
WHERE is_current = true AND content_tsv @@ {_FTS_QUERY}
ORDER BY ts_rank_cd(content_tsv, {_FTS_QUERY}) DESC
LIMIT $2
"""


def _pk(row: asyncpg.Record) -> tuple[str, str, int]:
    return (row["file_name"], row["policy_version"], row["chunk_index"])


def _chunk_pk(chunk: RetrievedChunk) -> tuple[str, str, int]:
    return (chunk.file_name, chunk.policy_version, chunk.chunk_index)


def refusal_threshold() -> float:
    """The SCORE_THRESHOLD variant matching the score scale currently in use.

    These are two different scales and must never share one env value:
      rerank on  -> cross-encoder relevance, sigmoid-squashed to (0, 1) and
                    strongly bimodal. RERANK_SCORE_THRESHOLD, default 0.5 =
                    the model's own relevant/not decision boundary.
      rerank off -> raw cosine similarity, a much narrower band around the
                    middle of (0, 1). SCORE_THRESHOLD, default 0.35.

    Both defaults still want calibrating against the Phase 5 eval; what
    matters here is that flipping RERANK_ENABLED can no longer silently
    change how strict the refusal gate is (CONTRIBUTING.md rule 1).
    """
    if settings.rerank_enabled:
        return settings.rerank_score_threshold
    return settings.score_threshold


def _own_score(chunk: RetrievedChunk, rerank_score: float, rows_by_id: dict) -> float:
    """`chunk`'s score on the scale refusal_threshold() compares against.

    With reranking on, that's the cross-encoder score already carried
    alongside the chunk. With it off, top_chunks is in RRF order, which does
    NOT track cosine-similarity order (RRF fuses vector-rank and FTS-rank,
    not raw distances) — so each chunk needs its own cosine lookup, the same
    one the top-1 case already did, not just the window's top entry."""
    if settings.rerank_enabled:
        return rerank_score
    row = rows_by_id[_chunk_pk(chunk)]
    return float(row["cosine_similarity"])


def include_best_match(
    candidate_ids: list[tuple[str, str, int]],
    best_id: tuple[str, str, int],
    limit: int,
) -> list[tuple[str, str, int]]:
    """Guarantees the chunk most similar to the ORIGINAL question survives the
    TOP_K cut, replacing the lowest-ranked candidate if RRF pushed it out.

    The refusal gate scores the best candidate in this window (see
    retrieve()), so the window must contain the best match — otherwise the
    gate's verdict and what the model actually sees would rest on different
    evidence. RRF can push it out: the lexical branch OR-joins every query
    term, so a chunk matching only common words ("гэж", "юу", "вэ") in several
    ranked lists outranks one that is the single best dense match. Traced
    live: for "(BoD) гэж юуг илэрхийлж байгаа вэ?" the only chunk that
    defines BoD was vector #1 but RRF #3.

    Pure and DB-free, same reason as select_cited_chunks below.
    """
    if best_id in candidate_ids[:limit]:
        return candidate_ids[:limit]
    return candidate_ids[: limit - 1] + [best_id]


def select_cited_chunks(
    scored_chunks: list[tuple[RetrievedChunk, float]], threshold: float
) -> list[RetrievedChunk]:
    """The chunks individually relevant enough to ground and cite an answer.

    A chunk riding into the TOP_K window only because a stronger candidate
    pulled the RRF/rerank cut there is retrieval noise, not support for the
    answer — citing it asserts grounding CONTRIBUTING.md rule 1/2 says it doesn't
    have. TOP_K is the ceiling on this list, never a floor to pad it to.

    Pure and DB-free like reciprocal_rank_fusion() and refusal_threshold(),
    for the same reason: cheaply unit-testable without a live retrieval call.
    """
    return [chunk for chunk, score in scored_chunks if score >= threshold]


def _to_chunk(row: asyncpg.Record) -> RetrievedChunk:
    return RetrievedChunk(
        file_name=row["file_name"],
        section=row["section"],
        policy_version=row["policy_version"],
        effective_date=row["effective_date"],
        chunk_index=row["chunk_index"],
        content=row["content"],
    )


async def retrieve(pool: asyncpg.Pool, query: str) -> RetrievalResult:
    # Query expansion gates everything downstream — embedding needs the whole
    # phrasing list before it can batch — so it is a serial LLM round-trip in
    # FRONT of retrieval, not one overlapped with it. Flagged in the summary
    # so the audit can price that serialization.
    with timing.stage("query_expansion"):
        phrasings = await expand_query(query)  # phrasings[0] is always `query` itself
    timing.note(
        phrasings=len(phrasings),
        query_expansion_enabled=settings.query_expansion_enabled,
        query_expansion_blocking=True,
    )
    # embed_texts() and rerank() are synchronous torch calls that take seconds
    # on the CPU-only pilot VM. Run directly on the event loop they block EVERY
    # other request, every in-flight SSE stream, and even /health for their full
    # duration — one question makes the whole service look hung. to_thread keeps
    # the loop free; it does not make an individual query faster.
    with timing.stage("query_embedding"):
        phrasing_embeddings = await asyncio.to_thread(embed_texts, phrasings)
    query_embedding = phrasing_embeddings[0]

    rows_by_id: dict[tuple[str, str, int], asyncpg.Record] = {}
    ranked_id_lists: list[list[tuple[str, str, int]]] = []

    async with pool.acquire() as conn:
        await register_vector(conn)
        for index, (phrasing, phrasing_embedding) in enumerate(
            zip(phrasings, phrasing_embeddings)
        ):
            with timing.stage("vector_search", phrasing=index):
                vector_rows = await conn.fetch(
                    _VECTOR_SQL, phrasing_embedding, settings.retrieval_candidate_n, query_embedding
                )
            with timing.stage("fts_search", phrasing=index):
                fts_rows = await conn.fetch(
                    _FTS_SQL, phrasing, settings.retrieval_candidate_n, query_embedding
                )

            for row in vector_rows:
                rows_by_id.setdefault(_pk(row), row)
            for row in fts_rows:
                rows_by_id.setdefault(_pk(row), row)

            ranked_id_lists.append([_pk(r) for r in vector_rows])
            ranked_id_lists.append([_pk(r) for r in fts_rows])

    with timing.stage("rrf_merge"):
        rrf_scores = reciprocal_rank_fusion(ranked_id_lists, k=RRF_K)
        merged_ids = sorted(rrf_scores, key=lambda i: rrf_scores[i], reverse=True)

    # Reranking sees a wider net (RERANK_TOP_N) than the final answer (TOP_K)
    # so it has real candidates to reorder; disabled, this is just today's
    # TOP_K cut straight from RRF order (rerank() below is then a no-op).
    candidate_n = settings.rerank_top_n if settings.rerank_enabled else settings.top_k
    candidate_ids = merged_ids[:candidate_n]
    if candidate_ids and not settings.rerank_enabled:
        best_id = max(rows_by_id, key=lambda i: rows_by_id[i]["cosine_similarity"])
        candidate_ids = include_best_match(candidate_ids, best_id, candidate_n)

    if not candidate_ids:
        return RetrievalResult(chunks=[], top_score=0.0, refuse=True)

    candidates = [(_to_chunk(rows_by_id[i]), rrf_scores[i]) for i in candidate_ids]
    timing.note(candidates_merged=len(merged_ids), candidates_reranked=len(candidates))
    with timing.stage("rerank", candidates=len(candidates)):
        top_chunks = (await asyncio.to_thread(rerank, query, candidates))[: settings.top_k]

    scored_chunks = [
        (chunk, _own_score(chunk, score, rows_by_id)) for chunk, score in top_chunks
    ]

    # Each branch's score is gated by the threshold for its own scale — see
    # refusal_threshold() above. The BEST score in the window, not the first:
    # with rerank off the window is in RRF order, and gating on whichever
    # chunk RRF happened to put first made the verdict depend on that order
    # — which query expansion's rephrasing reshuffles between runs, so the
    # same question measurably flipped between answering (0.57) and refusing
    # (0.48). With include_best_match above, this is the original question's
    # single best cosine match, independent of expansion. It also keeps
    # refuse == (cited_chunks is empty) exactly.
    top_score = max(score for _chunk, score in scored_chunks)
    threshold = refusal_threshold()
    refuse = top_score < threshold

    chunks = [chunk for chunk, _score in scored_chunks]
    cited_chunks = select_cited_chunks(scored_chunks, threshold)
    return RetrievalResult(
        chunks=chunks, cited_chunks=cited_chunks, top_score=top_score, refuse=refuse
    )
