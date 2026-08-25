"""Atomic, idempotent load of one parsed document + its related links into
policy_documents / policy_document_links.

Grain/PK: policy_documents (doc_number, policy_version, file_name);
policy_document_links (source_doc_number, source_version, source_file_name,
target_doc_number, link_type) — see docs/DATA_CONTRACT.md. One transaction
per document: upsert the row, recompute is_current across every version of
the SAME file_name (mirrors the flip pattern in app/ingest/loader.py for
policy_chunks — is_current is derived by comparing versions, so re-ingesting
an old version does not resurrect it as current), then replace that
document's related-link rows outright — the related list can shrink between
re-ingests, so delete + insert rather than diffing.
"""

import asyncpg

from app.ingest.naming import latest_version
from app.ingest.registry import ParsedDocument

_UPSERT_DOCUMENT_SQL = """
INSERT INTO policy_documents
    (doc_number, policy_version, doc_level, title_mn, file_name, effective_date,
     mandatory_from, iso_clause, owner_unit, is_current, data_quality_flags)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8, $9, false, $10)
ON CONFLICT (doc_number, policy_version, file_name) DO UPDATE SET
    doc_level = EXCLUDED.doc_level,
    title_mn = EXCLUDED.title_mn,
    effective_date = EXCLUDED.effective_date,
    mandatory_from = EXCLUDED.mandatory_from,
    iso_clause = EXCLUDED.iso_clause,
    owner_unit = EXCLUDED.owner_unit,
    data_quality_flags = EXCLUDED.data_quality_flags,
    ingested_at = now()
"""

_SELECT_VERSIONS_SQL = (
    "SELECT DISTINCT policy_version FROM policy_documents WHERE file_name = $1"
)

# Order-independent and idempotent — same derivation as app/ingest/loader.py.
_SET_CURRENT_VERSION_SQL = """
UPDATE policy_documents
SET is_current = (policy_version = $2)
WHERE file_name = $1
"""

_DELETE_LINKS_SQL = """
DELETE FROM policy_document_links
WHERE source_doc_number = $1 AND source_version = $2 AND source_file_name = $3
"""

_INSERT_LINK_SQL = """
INSERT INTO policy_document_links
    (source_doc_number, source_version, source_file_name, target_doc_number, link_type)
VALUES
    ($1, $2, $3, $4, 'related')
"""


async def upsert_document(
    pool: asyncpg.Pool,
    doc: ParsedDocument,
    policy_version: str,
    file_name: str,
) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                _UPSERT_DOCUMENT_SQL,
                doc.doc_number,
                policy_version,
                doc.doc_level,
                doc.title_mn,
                file_name,
                doc.effective_date,
                doc.mandatory_from,
                doc.iso_clause,
                doc.owner_unit,
                doc.data_quality_flags,
            )

            rows = await conn.fetch(_SELECT_VERSIONS_SQL, file_name)
            current_version = latest_version([row["policy_version"] for row in rows])
            await conn.execute(_SET_CURRENT_VERSION_SQL, file_name, current_version)

            await conn.execute(_DELETE_LINKS_SQL, doc.doc_number, policy_version, file_name)
            await conn.executemany(
                _INSERT_LINK_SQL,
                [
                    (doc.doc_number, policy_version, file_name, target)
                    for target in doc.related_links
                ],
            )
