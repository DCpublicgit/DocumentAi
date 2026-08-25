"""select_cited_chunks and _own_score are pure and DB-free by design (see
their docstrings in app.retrieve.retriever) so the citation-filtering logic
is unit-testable without a live retrieval call.
"""

from datetime import date

from app.config import settings
from app.retrieve.models import RetrievedChunk
from app.retrieve.retriever import _own_score, select_cited_chunks


def _chunk(file_name: str, index: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        file_name=file_name,
        section="1. Ерөнхий зүйл",
        policy_version="v1",
        effective_date=date(2025, 1, 1),
        chunk_index=index,
        content="агуулга",
    )


def test_select_cited_chunks_drops_scores_below_threshold():
    relevant = _chunk("a.txt")
    noise = _chunk("b.txt")
    scored = [(relevant, 0.6), (noise, 0.2)]

    cited = select_cited_chunks(scored, threshold=0.35)

    assert cited == [relevant]


def test_select_cited_chunks_keeps_a_score_exactly_at_the_threshold():
    chunk = _chunk("a.txt")

    cited = select_cited_chunks([(chunk, 0.35)], threshold=0.35)

    assert cited == [chunk]


def test_select_cited_chunks_can_return_fewer_than_top_k():
    """TOP_K is a ceiling retrieval considers, not a floor the citation list
    must be padded up to — a question with only one genuinely relevant chunk
    among five retrieved should cite exactly one."""
    relevant = _chunk("a.txt")
    scored = [(relevant, 0.9)] + [(_chunk("noise.txt", i), 0.1) for i in range(1, 5)]

    cited = select_cited_chunks(scored, threshold=0.35)

    assert cited == [relevant]


def test_own_score_uses_rerank_score_when_reranking_is_enabled(monkeypatch):
    monkeypatch.setattr(settings, "rerank_enabled", True)
    chunk = _chunk("a.txt")

    assert _own_score(chunk, rerank_score=0.77, rows_by_id={}) == 0.77


def test_own_score_looks_up_this_chunks_own_cosine_similarity_when_reranking_is_disabled():
    """Regression: top_chunks is in RRF order when reranking is off, which
    does not track cosine-similarity order, so a chunk's own row (not the
    window's top entry, and not the rerank_score argument) must be the
    source of truth for whether IT clears the bar."""
    original = settings.rerank_enabled
    settings.rerank_enabled = False
    try:
        chunk = _chunk("a.txt", index=3)
        rows_by_id = {("a.txt", "v1", 3): {"cosine_similarity": 0.42}}

        # rerank_score is a stale RRF score on a different scale — must be ignored.
        assert _own_score(chunk, rerank_score=999.0, rows_by_id=rows_by_id) == 0.42
    finally:
        settings.rerank_enabled = original
