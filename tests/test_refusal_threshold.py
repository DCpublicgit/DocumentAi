"""The refusal gate must compare each score against the threshold that
matches its scale. RERANK_ENABLED changes which score retrieval produces
(sigmoid cross-encoder relevance vs. raw cosine similarity), so the two get
separate env values — flipping the flag must not silently change how strict
refusal is (CONTRIBUTING.md rule 1: refusing correctly is the compliance surface).
"""

import pytest

from app.config import settings
from app.retrieve.retriever import refusal_threshold


@pytest.fixture
def restore_threshold_settings():
    original = (
        settings.rerank_enabled,
        settings.score_threshold,
        settings.rerank_score_threshold,
    )
    yield
    (
        settings.rerank_enabled,
        settings.score_threshold,
        settings.rerank_score_threshold,
    ) = original


def test_rerank_on_gates_on_the_cross_encoder_threshold(restore_threshold_settings):
    settings.rerank_enabled = True
    settings.score_threshold = 0.35
    settings.rerank_score_threshold = 0.5

    assert refusal_threshold() == 0.5


def test_rerank_off_gates_on_the_cosine_threshold(restore_threshold_settings):
    settings.rerank_enabled = False
    settings.score_threshold = 0.35
    settings.rerank_score_threshold = 0.5

    assert refusal_threshold() == 0.35


def test_tuning_one_threshold_does_not_move_the_other(restore_threshold_settings):
    """Regression: both scales used to read SCORE_THRESHOLD, so calibrating
    the reranked gate silently re-tuned the cosine gate too (and vice versa)."""
    settings.score_threshold = 0.35
    settings.rerank_score_threshold = 0.9

    settings.rerank_enabled = True
    assert refusal_threshold() == 0.9
    settings.rerank_enabled = False
    assert refusal_threshold() == 0.35
