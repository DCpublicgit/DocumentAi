"""Offline registry ingest pipeline: policies/*.txt -> parse_document_metadata
-> atomic upsert into policy_documents / policy_document_links.

Exposes run_registry_ingest(policy_dir) (see docs/ARCHITECTURE.md "Ingestion
note"). Additive to the existing policy_chunks ingest path in
app/ingest/pipeline.py — does not touch that table or its grain/PK.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg

from app.db import close_pool, create_registry_schema, get_pool
from app.ingest.naming import parse_filename
from app.ingest.registry import (
    NoRegistryMetadata,
    ParsedDocument,
    RegistryParseError,
    parse_document_metadata,
)
from app.ingest.registry_loader import upsert_document

logger = logging.getLogger(__name__)


@dataclass
class RegistrySummary:
    files_found: int
    files_processed: int
    files_skipped: int = 0
    docs_by_level: Counter = field(default_factory=Counter)
    flagged_doc_count: int = 0
    docs_with_dangling_references: int = 0

    def log(self) -> None:
        logger.info(
            "registry ingest summary: files_found=%d files_processed=%d files_skipped=%d "
            "docs_by_level=%s flagged_docs=%d docs_with_dangling_references=%d",
            self.files_found,
            self.files_processed,
            self.files_skipped,
            dict(self.docs_by_level),
            self.flagged_doc_count,
            self.docs_with_dangling_references,
        )


async def _count_docs_with_dangling_references(
    pool: asyncpg.Pool, parsed_docs: list[ParsedDocument]
) -> int:
    rows = await pool.fetch("SELECT DISTINCT doc_number FROM policy_documents")
    known = {row["doc_number"] for row in rows}
    return sum(
        1
        for doc in parsed_docs
        if any(target not in known for target in doc.related_links)
    )


async def run_registry_ingest(policy_dir: str | Path) -> RegistrySummary:
    policy_path = Path(policy_dir)
    if not policy_path.is_dir():
        raise FileNotFoundError(f"policy_dir does not exist: {policy_path}")

    files = sorted(
        p for p in policy_path.iterdir() if p.is_file() and p.suffix.lower() == ".txt"
    )

    # Parse EVERY file before writing anything. Each upsert_document() is its
    # own committed transaction, so a parse failure discovered mid-loop would
    # leave the register half-written (CONTRIBUTING.md: "Never leave the index
    # half-written"). Parsing is pure and cheap, so validate the whole batch
    # up front and fail before the first write — reporting every malformed
    # file at once rather than only the first one hit.
    parsed: list[tuple[ParsedDocument, str, str]] = []
    skipped: list[str] = []
    malformed: list[str] = []

    for path in files:
        logger.info("parsing registry metadata for %s", path.name)
        try:
            doc = parse_document_metadata(path)
        except NoRegistryMetadata as exc:
            # Not a registry document (no doc_number) — the corpus legitimately
            # contains policy files predating the ISO document set. Skipped
            # loudly and counted, never silently.
            logger.warning("skipping %s: %s", path.name, exc)
            skipped.append(path.name)
            continue
        except RegistryParseError as exc:
            # Declares a doc_number but is missing a required field — a real
            # defect in a document that IS meant to be in the register.
            malformed.append(str(exc))
            continue

        named = parse_filename(path)
        parsed.append((doc, named.policy_version, named.file_name))

    if malformed:
        raise RegistryParseError(
            f"{len(malformed)} of {len(files)} file(s) have malformed registry "
            "metadata — aborting before any writes:\n  " + "\n  ".join(malformed)
        )

    await create_registry_schema()
    pool = await get_pool()

    try:
        summary = RegistrySummary(
            files_found=len(files),
            files_processed=0,
            files_skipped=len(skipped),
        )

        for doc, policy_version, file_name in parsed:
            await upsert_document(pool, doc, policy_version, file_name)

            summary.files_processed += 1
            summary.docs_by_level[doc.doc_level] += 1
            if doc.data_quality_flags:
                summary.flagged_doc_count += 1

        summary.docs_with_dangling_references = await _count_docs_with_dangling_references(
            pool, [doc for doc, _version, _name in parsed]
        )
        summary.log()
        return summary
    finally:
        await close_pool()
