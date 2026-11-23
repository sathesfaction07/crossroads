# KB-AUTHORED REFERENCE IMPLEMENTATION — PC-0001
"""Sub-problem 2 of 4: score only the candidates, exactly.

LSH is a RECALL device, not a decision. It over-generates on purpose. Skipping this
stage -- treating a band collision as a duplicate -- is the most common way this
pattern is got wrong, because it silently imports LSH's false-positive rate into
your data. See CARD.md anti-pattern A2.
"""
from __future__ import annotations
from .naive import jaccard


def score_candidates(candidates: set[frozenset], sets: list[set],
                     threshold: float) -> list[tuple[int, int, float]]:
    """Exact-score each candidate pair; keep those at/above threshold.

    Returns (i, j, score) with i < j, sorted by score DESCENDING -- clustering
    depends on that order (see clustering.representative_link).
    """
    scored = []
    for pair in candidates:
        i, j = sorted(pair)
        s = jaccard(sets[i], sets[j])
        if s >= threshold:
            scored.append((i, j, s))
    scored.sort(key=lambda t: (-t[2], t[0], t[1]))
    return scored


def candidate_efficiency(n_candidates: int, n_items: int) -> dict:
    """How much work the blocking stage actually saved. Reported, not assumed."""
    naive = n_items * (n_items - 1) // 2
    return {
        "candidates": n_candidates,
        "naive_comparisons": naive,
        "reduction_factor": (naive / n_candidates) if n_candidates else float("inf"),
        "fraction_of_naive": (n_candidates / naive) if naive else 0.0,
    }
