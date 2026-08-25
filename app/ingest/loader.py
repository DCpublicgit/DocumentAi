"""Idempotent load of one document's chunks into policy_chunks.

Grain/PK: (file_name, policy_version, chunk_index) — see docs/DATA_CONTRACT.md.
Deletes any existing rows for this exact (file_name, policy_version) — making
re-ingest idempotent even if the chunk count changed — inserts the new rows,
then recomputes is_current across every version of this file.

Takes a Connection, not a Pool: the CALLER owns the transaction, so a whole
ingest run commits or rolls back as one unit rather than per file (see
app/ingest/pipeline.py). Never leaves the index half-written.

is_current is derived, not assumed: DATA_CONTRACT.md defines it as "true
unless a NEWER policy_version of this same file_name has superseded it", so
the flip compares versions (app.ingest.naming.latest_version) rather than
trusting ingest order. Re-ingesting an old version must NOT resurrect it as
current, and a file whose versions arrive out of order (v10 sorts before v2
by filename) must still end up with the right row current.
"""

from datetime import date

import asyncpg

from app.ingest.chunker import Chunk
from app.ingest.naming import latest_version

_DELETE_SQL = "DELETE FROM policy_chunks WHERE file_name = $1 AND policy_version = $2"

_INSERT_SQL = """
INSERT INTO policy_chunks
    (file_name, section, policy_version, effective_date, is_current, chunk_index, content, embedding)
VALUES
    ($1, $2, $3, $4, false, $5, $6, $7)
"""

_SELECT_VERSIONS_SQL = (
    "SELECT DISTINCT policy_version FROM policy_chunks WHERE file_name = $1"
)

# Order-independent and idempotent: sets exactly the winning version's rows
# current and every other version's rows not-current, in one statement.
_SET_CURRENT_VERSION_SQL = """
UPDATE policy_chunks
SET is_current = (policy_version = $2)
WHERE file_name = $1
"""


async def load_document(
    conn: asyncpg.Connection,
    file_name: str,
    policy_version: str,
    effective_date: date | None,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> int:
    # strict=True below turns a chunk/embedding count mismatch into a loud
    # error; a plain zip would silently drop the tail, quietly indexing a
    # partial document.
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"{file_name} ({policy_version}): {len(chunks)} chunks but "
            f"{len(embeddings)} embeddings — refusing to load a partial document."
        )

    await conn.execute(_DELETE_SQL, file_name, policy_version)
    # One round trip for the whole document rather than one per chunk — the
    # corpus is small today, but this is the statement count that grows with
    # 10x docs.
    await conn.executemany(
        _INSERT_SQL,
        [
            (
                file_name,
                chunk.section,
                policy_version,
                effective_date,
                chunk.chunk_index,
                chunk.content,
                embedding,
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ],
    )

    rows = await conn.fetch(_SELECT_VERSIONS_SQL, file_name)
    current_version = latest_version([row["policy_version"] for row in rows])
    await conn.execute(_SET_CURRENT_VERSION_SQL, file_name, current_version)
    return len(chunks)
