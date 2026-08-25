"""app.query_guard.is_gibberish gates keyboard-mash input before retrieval
ever runs (see app.answering._retrieve_and_prepare). A false positive here
is much worse than a false negative — it wrongly tells an employee their
real question doesn't make sense — so the regression test below is the one
that matters most: every real question in app/eval/questions.yaml, including
its off-topic-but-fluent "should_refuse" cases, must pass through untouched.
"""

from pathlib import Path

import pytest
import yaml

from app.config import settings
from app.query_guard import is_gibberish

QUESTIONS = Path(__file__).resolve().parents[1] / "app" / "eval" / "questions.yaml"


@pytest.fixture
def restore_threshold():
    original = settings.gibberish_max_consonant_run
    yield
    settings.gibberish_max_consonant_run = original


def test_no_eval_question_is_flagged_as_gibberish():
    """Zero false positives against the real corpus, tuned to this exact
    number (see app/query_guard.py's _VOWELS comment — the first cut of this
    heuristic flagged ~40% of these before 'ы'/'й' were added as vowels)."""
    cases = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    flagged = [c["question"] for c in cases if is_gibberish(c["question"])]

    assert flagged == [], f"{len(flagged)}/{len(cases)} real eval questions flagged as gibberish"


@pytest.mark.parametrize(
    "text",
    [
        "kjshdf lkjashdf lkasjdhf",
        "jjjjjjjjjjjjjj",
        "aawdwad45h64",
    ],
)
def test_keyboard_mash_is_flagged(text):
    assert is_gibberish(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "123",
        "???",
        "IT",
        "HR бодлого",
        "сайн байна уу",
        "ISO 27001",
        "4.2-р зүйл",
        "P1",
        "CVSS 9.8",
        "VPN хэрхэн холбох вэ?",
        "Ажлын долоо хоногийн ажлын цаг хэд вэ?",
    ],
)
def test_real_or_benign_input_is_not_flagged(text):
    assert not is_gibberish(text)


def test_consonant_run_threshold_is_configurable(restore_threshold):
    settings.gibberish_max_consonant_run = 3

    # "CVSS" is a 4-consonant run — safely under the default threshold of 5,
    # but a lowered threshold must actually take effect, not silently no-op.
    assert is_gibberish("CVSS оноо хэд вэ?")
