"""Offline ingest pipeline: policies/ -> extract -> normalize -> chunk ->
embed -> atomic load.

Exposes a single run_ingest(policy_dir) entrypoint (see docs/ARCHITECTURE.md
"Ingestion note") so it can later become a Dagster asset in the main
platform; for the pilot it runs standalone via CLI/cron.
"""

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pgvector.asyncpg import register_vector

from app.config import settings
from app.db import close_pool, create_schema, get_pool
from app.embedding import EMBEDDING_DIM, embed_texts
from app.ingest.chunker import Chunk, chunk_document
from app.ingest.dq import DQSummary, FileDQ
from app.ingest.extract import SUPPORTED_EXTENSIONS, extract_text
from app.ingest.frontmatter import strip_front_matter
from app.ingest.loader import load_document
from app.ingest.naming import parse_filename
from app.ingest.normalize import normalize_text
from app.ingest.registry import parse_effective_date

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PreparedDocument:
    """One file's fully-computed load payload, held between the pure phase
    and the single write transaction."""

    file_name: str
    policy_version: str
    effective_date: date | None
    chunks: list[Chunk]
    embeddings: list[list[float]]


async def run_ingest(policy_dir: str | Path) -> DQSummary:
    policy_path = Path(policy_dir)
    if not policy_path.is_dir():
        raise FileNotFoundError(f"policy_dir does not exist: {policy_path}")

    files = sorted(
        p
        for p in policy_path.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    # Phase 1 — extract/normalize/chunk/embed every file before writing
    # anything. All of it is pure, so a malformed file fails here rather than
    # part-way through the writes (CONTRIBUTING.md: "Never leave the index
    # half-written").
    prepared: list[_PreparedDocument] = []
    per_file: list[FileDQ] = []

    for path in files:
        logger.info("preparing %s", path.name)
        parsed = parse_filename(path)
        normalized = normalize_text(extract_text(path))
        # The filename convention is the primary source of effective_date, but
        # most of the corpus doesn't follow it — fall back to the document's own
        # "Мөрдөж эхлэх огноо" cover-page date so citations don't render
        # "огноогүй" for a document whose date we can actually read. Parsed from
        # the normalized text BEFORE stripping, since that's the block the date
        # lives in.
        effective_date = parsed.effective_date or parse_effective_date(normalized)
        text = strip_front_matter(normalized)
        chunks = chunk_document(text, settings.chunk_size_tokens)

        if not chunks:
            logger.warning("no chunks produced for %s — nothing to load", path.name)
            per_file.append(FileDQ(parsed.file_name, parsed.policy_version, 0, 0))
            continue

        embeddings = embed_texts([c.content for c in chunks])
        null_embeddings = sum(
            1 for e in embeddings if e is None or len(e) != EMBEDDING_DIM
        )

        prepared.append(
            _PreparedDocument(
                file_name=parsed.file_name,
                policy_version=parsed.policy_version,
                effective_date=effective_date,
                chunks=chunks,
                embeddings=embeddings,
            )
        )
        per_file.append(
            FileDQ(parsed.file_name, parsed.policy_version, len(chunks), null_embeddings)
        )

    await create_schema()
    pool = await get_pool()

    try:
        # Phase 2 — one transaction for the whole run, so the index either
        # reflects the full corpus or is left untouched. At corpus scale
        # (~hundreds of rows) this is cheap; revisit if the corpus grows by
        # orders of magnitude.
        async with pool.acquire() as conn:
            await register_vector(conn)
            async with conn.transaction():
                for doc in prepared:
                    logger.info("loading %s (%s)", doc.file_name, doc.policy_version)
                    await load_document(
                        conn,
                        doc.file_name,
                        doc.policy_version,
                        doc.effective_date,
                        doc.chunks,
                        doc.embeddings,
                    )

        summary = DQSummary(
            files_found=len(files),
            files_processed=len(per_file),
            total_chunks=sum(f.chunk_count for f in per_file),
            total_null_embeddings=sum(f.null_embeddings for f in per_file),
            per_file=per_file,
        )
        summary.log()
        summary.check()
        return summary
    finally:
        await close_pool()
