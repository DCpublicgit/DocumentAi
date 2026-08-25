"""Tests for app/ingest/loader.py's is_current derivation against the real
Postgres (DATABASE_URL — same DB the app uses), since they assert on-disk row
state. Rows are scoped to a "TEST_" file_name and cleaned up afterward.

policy_chunks is the table retrieval filters on (is_current = true), so a
wrong flip here silently serves superseded policy — this is the compliance
path, not just bookkeeping.

Embeddings are synthetic fixed vectors, not real BGE-M3 output: these tests
assert row/flag state, never similarity, so loading a 1.6GB model would only
make them slower.
"""

from datetime import date

import pytest
from pgvector.asyncpg import register_vector

from app.db import close_pool, create_schema, get_pool
from app.embedding import EMBEDDING_DIM
from app.ingest.chunker import Chunk
from app.ingest.loader import load_document

FILE_NAME = "TEST_loader_versioned.txt"


def _chunks(n: int = 2) -> list[Chunk]:
    return [
        Chunk(chunk_index=i, section=f"НЭГ. ХЭСЭГ {i}", content=f"Туршилтын агуулга {i}.")
        for i in range(n)
    ]


def _embeddings(n: int = 2) -> list[list[float]]:
    return [[0.1] * EMBEDDING_DIM for _ in range(n)]


async def _load(version: str, chunk_count: int = 2) -> None:
    """load_document takes a Connection and does NOT open its own transaction
    — the caller owns it (app/ingest/pipeline.py wraps the whole run in one),
    so these tests supply the transaction the same way."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await register_vector(conn)
        async with conn.transaction():
            await load_document(
                conn,
                FILE_NAME,
                version,
                date(2025, 1, 1),
                _chunks(chunk_count),
                _embeddings(chunk_count),
            )


async def _current_state() -> set[tuple[str, bool]]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT DISTINCT policy_version, is_current FROM policy_chunks WHERE file_name = $1",
        FILE_NAME,
    )
    return {(r["policy_version"], r["is_current"]) for r in rows}


@pytest.fixture(autouse=True)
async def _clean_slate():
    await create_schema()
    pool = await get_pool()
    await pool.execute("DELETE FROM policy_chunks WHERE file_name = $1", FILE_NAME)
    yield
    pool = await get_pool()
    await pool.execute("DELETE FROM policy_chunks WHERE file_name = $1", FILE_NAME)
    await close_pool()


async def test_single_version_is_current():
    await _load("v1")
    assert await _current_state() == {("v1", True)}


async def test_newer_version_supersedes_older():
    await _load("v1")
    await _load("v2")
    assert await _current_state() == {("v1", False), ("v2", True)}


async def test_reingesting_older_version_does_not_resurrect_it():
    """Regression: is_current used to be flipped by ingest order, so
    re-ingesting v1 after v2 demoted v2 and made superseded v1 current —
    retrieval would then serve withdrawn policy as authoritative."""
    await _load("v1")
    await _load("v2")
    await _load("v1")
    assert await _current_state() == {("v1", False), ("v2", True)}


async def test_versions_arriving_out_of_order_still_resolve_to_newest():
    await _load("v2")
    await _load("v1")
    assert await _current_state() == {("v1", False), ("v2", True)}


async def test_v10_beats_v2_despite_lexical_filename_order():
    """v10 sorts BEFORE v2 as a string, so the pipeline's sorted() iteration
    ingests v10 first and v2 last — the flip must still pick v10."""
    await _load("v10")
    await _load("v2")
    assert await _current_state() == {("v2", False), ("v10", True)}


async def test_reingest_same_version_is_idempotent_and_replaces_chunks():
    await _load("v1", chunk_count=3)
    await _load("v1", chunk_count=2)

    pool = await get_pool()
    count = await pool.fetchval(
        "SELECT count(*) FROM policy_chunks WHERE file_name = $1 AND policy_version = $2",
        FILE_NAME,
        "v1",
    )
    assert count == 2, "re-ingest must replace rows, not accumulate them"
    assert await _current_state() == {("v1", True)}


async def test_chunk_embedding_count_mismatch_fails_loudly():
    """A silent zip would drop the tail and index a partial document."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await register_vector(conn)
        with pytest.raises(ValueError, match="refusing to load a partial document"):
            async with conn.transaction():
                await load_document(
                    conn, FILE_NAME, "v1", date(2025, 1, 1), _chunks(3), _embeddings(2)
                )


async def test_exactly_one_version_is_current_across_many():
    for version in ["v1", "v3", "v2", "v10"]:
        await _load(version)

    state = await _current_state()
    current = [v for v, is_current in state if is_current]
    assert current == ["v10"]
    assert len(state) == 4
