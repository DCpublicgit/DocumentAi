"""BGE-M3 dense embeddings (dim 1024). Shared by app.ingest (chunk embedding
at load time) and app.retrieve (query embedding at search time) — one model,
one place, so index and query vectors are always comparable.
"""

from sentence_transformers import SentenceTransformer

from app.config import settings

EMBEDDING_DIM = 1024

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.embedding_model)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _get_model()
    vectors = model.encode(
        texts,
        batch_size=settings.embed_batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vectors]


def warm_up() -> None:
    """Forces model load + first-inference on this process's own time, not a
    live user's first question. See app.retrieve.reranker.warm_up."""
    embed_texts(["warm up"])
