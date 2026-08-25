"""Retrieval result types."""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class RetrievedChunk:
    file_name: str
    section: str | None
    policy_version: str
    effective_date: date | None
    chunk_index: int
    content: str


@dataclass(frozen=True)
class RetrievalResult:
    """`chunks` is every candidate retrieval surfaced, up to TOP_K — kept for
    the audit trail's "why did it refuse" question (app.audit), which needs
    the near-misses too, not just what cleared the bar.

    `cited_chunks` is the subset of `chunks` whose OWN score individually
    clears the refusal threshold (app.retrieve.retriever.refusal_threshold).
    A chunk can ride into the TOP_K window on the strength of the best
    candidate without being independently relevant itself — TOP_K is a
    ceiling on how many chunks retrieval considers, not a floor guaranteeing
    that many are actually grounding material. This is what generation and
    citation are built from (CONTRIBUTING.md rule 1/2): citing a chunk that never
    cleared its own relevance bar asserts grounding the answer doesn't have.
    """

    chunks: list[RetrievedChunk] = field(default_factory=list)
    cited_chunks: list[RetrievedChunk] = field(default_factory=list)
    top_score: float = 0.0
    refuse: bool = True
