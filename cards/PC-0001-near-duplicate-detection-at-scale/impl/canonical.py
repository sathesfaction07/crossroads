# KB-AUTHORED REFERENCE IMPLEMENTATION — PC-0001
"""Sub-problem 4 of 4: choose which member of a duplicate set survives.

Easy to overlook and consequential: "keep the first" makes the output depend on
INPUT ORDER, so the same corpus in a different shuffle yields a different dataset.
That is the defect visible in the cited internal implementation (CARD.md).
"""
from __future__ import annotations
from .naive import jaccard


def pick_earliest(cluster: set[int], sets: list[set]) -> int:
    """Lowest index. Cheap, and ORDER-DEPENDENT -- present so the card can name it."""
    return min(cluster)


def pick_longest(cluster: set[int], sets: list[set]) -> int:
    """Most tokens; ties broken by index so the result is deterministic."""
    return max(sorted(cluster), key=lambda i: (len(sets[i]), -i))


def pick_medoid(cluster: set[int], sets: list[set]) -> int:
    """Member with the highest total similarity to the rest of its cluster.

    Order-independent and the most defensible default: it returns the item that best
    REPRESENTS the group rather than the one that happened to arrive first.
    """
    idx = sorted(cluster)
    return max(idx, key=lambda i: (sum(jaccard(sets[i], sets[j])
                                       for j in idx if j != i), -i))


STRATEGIES = {"earliest": pick_earliest, "longest": pick_longest, "medoid": pick_medoid}


def select_canonical(clusters: list[set[int]], sets: list[set],
                     strategy: str = "medoid") -> dict[int, list[int]]:
    """Return {canonical_index: [dropped indices]} for each cluster."""
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; expected {sorted(STRATEGIES)}")
    fn = STRATEGIES[strategy]
    out = {}
    for c in clusters:
        keep = fn(c, sets)
        out[keep] = sorted(c - {keep})
    return out
