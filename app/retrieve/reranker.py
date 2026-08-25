"""Cross-encoder reranking over the widened RERANK_TOP_N hybrid-search
candidate pool, before truncation to TOP_K. Env-gated per
docs/DATA_CONTRACT.md (RERANK_ENABLED) so it's an A/B-able dimension in the
Phase 5 eval, not baked-in behavior.

Same lazy module-level singleton pattern as app.embedding's BGE-M3 model:
loaded once at first use, not per request.
"""

from sentence_transformers import CrossEncoder

from app.config import settings
from app.retrieve.models import RetrievedChunk

_model: CrossEncoder | None = None


def _get_model() -> CrossEncoder:
    global _model
    if _model is None:
        _model = CrossEncoder(settings.rerank_model)
    return _model


def rerank(
    query: str, candidates: list[tuple[RetrievedChunk, float]]
) -> list[tuple[RetrievedChunk, float]]:
    """Reorders (chunk, score) candidates by cross-encoder relevance to
    `query`, descending. RERANK_ENABLED=false (or an empty candidate list)
    is a no-op: candidates are returned exactly as given, i.e. still in the
    RRF order the caller passed in — today's behavior, unchanged."""
    if not settings.rerank_enabled or not candidates:
        return candidates

    model = _get_model()
    pairs = [(query, chunk.content) for chunk, _score in candidates]
    scores = model.predict(pairs)
    reranked = [(chunk, float(score)) for (chunk, _old_score), score in zip(candidates, scores)]
    return sorted(reranked, key=lambda pair: pair[1], reverse=True)


def warm_up() -> None:
    """Forces model load + first-inference at process startup instead of on a
    live user's first question — the cross-encoder alone measured ~130s cold
    on the CPU-only pilot VM (see app.timing's per-stage logs). A
    no-op when RERANK_ENABLED=false: nothing would ever load it anyway."""
    if not settings.rerank_enabled:
        return
    _get_model().predict([("warm up", "warm up")])
