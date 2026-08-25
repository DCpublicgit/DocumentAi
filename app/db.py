import asyncpg

from app.config import settings

_pool: asyncpg.Pool | None = None

# Grain: one row per (file_name, policy_version, chunk_index).
# PK: (file_name, policy_version, chunk_index). Per docs/DATA_CONTRACT.md.
CREATE_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_chunks (
    file_name       text NOT NULL,
    section         text,
    policy_version  text NOT NULL,
    effective_date  date,
    is_current      boolean NOT NULL,
    chunk_index     int NOT NULL,
    content         text NOT NULL,
    content_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    embedding       vector(1024) NOT NULL,
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (file_name, policy_version, chunk_index)
);

-- Partial on is_current, matching the WHERE clause both retrieval queries use.
-- An unpartitioned HNSW index searches superseded rows too: with pgvector's
-- default hnsw.ef_search and a LIMIT of RETRIEVAL_CANDIDATE_N, the ANN scan can
-- burn its candidate budget on old versions and return fewer current rows than
-- asked for — or miss the best current chunk. Harmless while every row is
-- current; it bites on the first version bump, which is exactly when a wrong
-- answer cites a superseded policy.
CREATE INDEX IF NOT EXISTS policy_chunks_embedding_hnsw_current_idx
    ON policy_chunks USING hnsw (embedding vector_cosine_ops)
    WHERE is_current;

CREATE INDEX IF NOT EXISTS policy_chunks_content_tsv_gin_current_idx
    ON policy_chunks USING gin (content_tsv)
    WHERE is_current;

-- Both partial indexes are deliberately named differently from the full
-- indexes they replace. CREATE INDEX IF NOT EXISTS matches on NAME only, so
-- reusing a name would silently keep the old non-partial definition on any
-- already-deployed database — the change would appear applied and do nothing.
-- Renaming forces creation; these DROPs then retire the originals so they stop
-- consuming memory and competing with the planner.
DROP INDEX IF EXISTS policy_chunks_embedding_hnsw_idx;
DROP INDEX IF EXISTS policy_chunks_content_tsv_gin_idx;
"""

# Grain: one row per (doc_number, policy_version, file_name) — file_name is part of
# the key because doc_number alone can collide across distinct source files (see
# data_quality_flags: duplicate_doc_number). PK: (doc_number, policy_version, file_name).
# Per docs/DATA_CONTRACT.md.
CREATE_REGISTRY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS policy_documents (
    doc_number          text NOT NULL,
    policy_version       text NOT NULL,
    doc_level            text NOT NULL,
    department           text,
    title_mn             text NOT NULL,
    file_name            text NOT NULL,
    effective_date        date,
    mandatory_from        date,
    iso_clause            text,
    owner_unit            text NOT NULL,
    is_current            boolean NOT NULL,
    data_quality_flags    text[] NOT NULL DEFAULT '{}',
    ingested_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_number, policy_version, file_name)
);

-- Grain: one row per (source_doc_number, source_version, source_file_name,
-- target_doc_number, link_type). PK: same tuple. Per docs/DATA_CONTRACT.md.
CREATE TABLE IF NOT EXISTS policy_document_links (
    source_doc_number    text NOT NULL,
    source_version         text NOT NULL,
    source_file_name       text NOT NULL,
    target_doc_number      text NOT NULL,
    link_type               text NOT NULL,
    ingested_at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_doc_number, source_version, source_file_name, target_doc_number, link_type)
);
"""


# Grain: one row per answered /v1/chat/completions request — streaming and
# non-streaming alike, refusals included (a wrongly-refused question is exactly
# what gets investigated). PK: request_id.
#
# This is the record of what the bot told an employee and what it based that on.
# retrieved_chunks stores policy_chunks' own grain (file_name, policy_version,
# chunk_index) rather than the chunk text, so an answer can be traced back to
# the exact rows — including which policy VERSION was in force at the time,
# which is the point of keeping superseded versions around at all.
#
# No user column: the pilot has no auth by design (PRODUCT.md). Add a nullable
# user_id when SSO lands rather than guessing its shape now.
CREATE_AUDIT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS answer_audit (
    request_id        uuid PRIMARY KEY,
    asked_at          timestamptz NOT NULL,
    question          text NOT NULL,
    answer            text NOT NULL,
    refused           boolean NOT NULL,
    top_score         double precision,
    retrieved_chunks  jsonb NOT NULL,
    citations         text[] NOT NULL,
    llm_provider      text NOT NULL,
    llm_model         text NOT NULL,
    finish_reason     text NOT NULL,
    latency_ms        integer NOT NULL,
    streamed          boolean NOT NULL
);

-- Audit reads are "what happened recently" and "what happened on date X".
CREATE INDEX IF NOT EXISTS answer_audit_asked_at_idx ON answer_audit (asked_at DESC);
"""


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def create_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(CREATE_SCHEMA_SQL)


async def create_registry_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(CREATE_REGISTRY_SCHEMA_SQL)


async def create_audit_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(CREATE_AUDIT_SCHEMA_SQL)
