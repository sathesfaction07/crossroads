# KB-AUTHORED REFERENCE IMPLEMENTATION — PC-0001
"""The naive baseline: all-pairs comparison. Kept in the card ON PURPOSE.

It is the ground truth the decomposed pipeline is measured against, and it is the
shape found in real internal code (see CARD.md "Cited evidence"), so the card can
show *what it is replacing* rather than asserting that a replacement is needed.
"""
from __future__ import annotations
from itertools import combinations


def jaccard(a: set, b: set) -> float:
    """Exact Jaccard similarity. |A n B| / |A u B|; empty-vs-empty defined as 1.0."""
    if not a and not b:
        return 1.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def naive_duplicate_pairs(sets: list[set], threshold: float) -> list[tuple[int, int, float]]:
    """Every pair scored. O(N^2) comparisons -- the thing that does not scale."""
    out = []
    for i, j in combinations(range(len(sets)), 2):
        s = jaccard(sets[i], sets[j])
        if s >= threshold:
            out.append((i, j, s))
    return out


def comparison_count(n: int) -> int:
    """n(n-1)/2 -- the number the cost model in CARD.md is built from."""
    return n * (n - 1) // 2


def estimated_wall_clock(n: int, seconds_per_comparison: float) -> dict:
    """Wall-clock cost of the naive scan, COMPUTED rather than asserted.

    This exists because the first draft of CARD.md claimed "~6 days at one comparison
    per nanosecond" for N=1e6. That was wrong by 1000x -- 6 days is the figure for one
    MICROsecond; a nanosecond gives 500 seconds. A prose cost claim nobody can execute
    is exactly the unfalsifiable shape this KB format exists to prevent, so the number
    is now derived and pinned by a test.
    """
    total = comparison_count(n) * seconds_per_comparison
    return {
        "comparisons": comparison_count(n),
        "seconds": total,
        "minutes": total / 60,
        "hours": total / 3600,
        "days": total / 86400,
    }
