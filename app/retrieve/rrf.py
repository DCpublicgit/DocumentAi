"""Reciprocal Rank Fusion — pure, DB-free so it's cheaply unit-testable.

RRF(d) = sum over each ranked list containing d of 1 / (k + rank_in_list(d)),
rank_in_list is 1-indexed. Per docs/DATA_CONTRACT.md, k=60 (app.contract.RRF_K).
"""

from typing import Hashable, Sequence, TypeVar

Id = TypeVar("Id", bound=Hashable)


def reciprocal_rank_fusion(ranked_lists: Sequence[Sequence[Id]], k: int) -> dict[Id, float]:
    scores: dict[Id, float] = {}
    for ranked in ranked_lists:
        for position, item in enumerate(ranked, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + position)
    return scores
