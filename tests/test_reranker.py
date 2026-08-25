import pytest

from app.config import settings
from app.retrieve.models import RetrievedChunk
from app.retrieve.reranker import rerank


def _chunk(name: str) -> RetrievedChunk:
    return RetrievedChunk(
        file_name=name, section=None, policy_version="v1", effective_date=None, chunk_index=0, content="content"
    )


@pytest.fixture
def restore_rerank_enabled():
    original = settings.rerank_enabled
    yield
    settings.rerank_enabled = original


def test_disabled_rerank_returns_candidates_unchanged(restore_rerank_enabled):
    settings.rerank_enabled = False
    candidates = [(_chunk("a.txt"), 0.9), (_chunk("b.txt"), 0.5)]

    assert rerank("query", candidates) == candidates


def test_disabled_rerank_with_no_candidates_returns_empty_list(restore_rerank_enabled):
    settings.rerank_enabled = False

    assert rerank("query", []) == []


def test_enabled_rerank_with_no_candidates_is_still_a_noop(restore_rerank_enabled):
    settings.rerank_enabled = True

    assert rerank("query", []) == []
