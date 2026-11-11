from collections import defaultdict
from typing import TypeVar

T = TypeVar("T")


def reciprocal_rank_fusion(rankings: list[list[T]], k: int = 60) -> list[tuple[T, float]]:
    """Fuse several best-first rankings of the same item type into one.

    Item x gets score sum(1 / (k + rank_i(x) + 1)) over every ranking i it appears in
    (rank 0 = best). Items absent from a given ranking simply contribute nothing for it.
    Returns (item, score) pairs sorted by score descending; ties keep each item's first
    encountered order (stable sort over insertion order).
    """
    scores: dict[T, float] = defaultdict(float)
    order: dict[T, int] = {}
    position = 0
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] += 1.0 / (k + rank + 1)
            if item not in order:
                order[item] = position
                position += 1
    return sorted(scores.items(), key=lambda kv: (-kv[1], order[kv[0]]))
