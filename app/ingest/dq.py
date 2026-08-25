"""Data-quality checks and summary for an ingest run.

Per CONTRIBUTING.md: log chunk count / null-embedding rate / per-file coverage,
and fail loudly on zero rows — a silently empty or half-embedded index is
worse than a loud crash.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class IngestError(RuntimeError):
    """Raised when the DQ gate fails the whole run."""


@dataclass
class FileDQ:
    file_name: str
    policy_version: str
    chunk_count: int
    null_embeddings: int


@dataclass
class DQSummary:
    files_found: int
    files_processed: int
    total_chunks: int
    total_null_embeddings: int
    per_file: list[FileDQ] = field(default_factory=list)

    @property
    def null_embedding_rate(self) -> float:
        if self.total_chunks == 0:
            return 0.0
        return self.total_null_embeddings / self.total_chunks

    def log(self) -> None:
        logger.info(
            "ingest DQ summary: files_found=%d files_processed=%d total_chunks=%d "
            "null_embedding_rate=%.4f",
            self.files_found,
            self.files_processed,
            self.total_chunks,
            self.null_embedding_rate,
        )
        for f in self.per_file:
            level = logging.WARNING if f.chunk_count == 0 else logging.INFO
            logger.log(
                level,
                "  file=%s version=%s chunks=%d null_embeddings=%d",
                f.file_name,
                f.policy_version,
                f.chunk_count,
                f.null_embeddings,
            )

    def check(self) -> None:
        if self.total_chunks == 0:
            raise IngestError("Ingest produced zero chunk rows across all files — aborting.")
