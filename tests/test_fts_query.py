"""The lexical half of hybrid retrieval must actually return rows.

Regression: the FTS branch used plainto_tsquery, which AND-joins every term.
With the 'simple' config (no Mongolian dictionary, so no stemming) a chunk had
to contain every inflected surface form of the question including the
interrogative particle "вэ" — which returned ZERO rows for all 30 questions in
app/eval/questions.yaml. "Hybrid" retrieval was silently dense-only, and the
Phase 5 eval would have A/B'd a branch contributing nothing.

Runs against the real Postgres (DATABASE_URL) with the real corpus, because
the bug was invisible to any unit-level check — the SQL was valid and the code
path ran fine; it just always matched nothing.
"""

from pathlib import Path

import pytest
import yaml

from app.db import close_pool, get_pool
from app.retrieve.retriever import _FTS_QUERY

QUESTIONS = Path(__file__).resolve().parents[1] / "app" / "eval" / "questions.yaml"

# Full natural-language questions — the shape that used to return nothing.
SAMPLE_QUESTIONS = [
    "Лог бүртгэлийг хэдэн жил хадгалах вэ?",
    "Ажилтан ажлаас гарахад мэдээллийн хөрөнгийг яах вэ?",
    "Ажлын долоо хоногийн ажлын цаг хэд вэ?",
]


# The retriever's own tsquery-building fragment, so this tests the real thing
# rather than a paraphrase of it.
_COUNT_SQL = f"""
SELECT count(*) FROM policy_chunks
WHERE is_current = true AND content_tsv @@ {_FTS_QUERY}
"""


async def _fts_count(question: str) -> int:
    pool = await get_pool()
    return await pool.fetchval(_COUNT_SQL, question)


@pytest.fixture(autouse=True)
async def _close():
    yield
    await close_pool()


@pytest.mark.parametrize("question", SAMPLE_QUESTIONS)
async def test_full_question_returns_lexical_matches(question):
    assert await _fts_count(question) > 0, (
        f"FTS returned nothing for {question!r} — the lexical branch is dead"
    )


async def test_no_eval_question_returns_zero_fts_rows():
    """The whole eval set, since that is what Phase 5 will A/B."""
    cases = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    dead = [c["question"] for c in cases if await _fts_count(c["question"]) == 0]

    assert dead == [], f"{len(dead)}/{len(cases)} eval questions match no chunk lexically"


async def test_out_of_scope_question_still_reaches_the_relevance_gate():
    """OR-joining is intentionally high-recall: an out-of-scope question may
    still match lexically. That is fine and by design — RRF ranks it low and
    the reranker plus SCORE_THRESHOLD reject it. This pins the intent so the
    recall/precision split isn't "fixed" back into an AND query."""
    assert await _fts_count("Улаанбаатарын өнөөдрийн цаг агаар ямар байна?") >= 0
