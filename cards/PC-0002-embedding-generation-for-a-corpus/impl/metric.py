"""Sub-problem 5 — METRIC PAIRING. Which similarity, and on which vectors?

Also holds the vector primitives the other modules use. Note that the IMPORT direction
here is the reverse of the decomposition edge: `pooling` imports `metric` for arithmetic,
while the *problem* dependency runs the other way (you cannot choose a metric until you
know what the vector represents). Import graphs and problem graphs are different graphs,
and conflating them is how "just reuse that helper" turns into a wrong pipeline.
"""
from __future__ import annotations

import math

Vector = list[float]


def dot(a: Vector, b: Vector) -> float:
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    return sum(x * y for x, y in zip(a, b))


def l2_norm(v: Vector) -> float:
    return math.sqrt(sum(x * x for x in v))


def l2_normalize(v: Vector) -> Vector:
    n = l2_norm(v)
    if n == 0.0:
        # A zero vector has no direction. Returning it unchanged means cosine against it is
        # 0/0; callers that mean-pool an all-pad row can produce exactly this, so it is
        # raised rather than silently propagated as a NaN two layers away.
        raise ValueError("cannot L2-normalise a zero vector (all-pad pooled row?)")
    return [x / n for x in v]


def cosine(a: Vector, b: Vector) -> float:
    return dot(a, b) / (l2_norm(a) * l2_norm(b))


def cosine_equals_dot_after_normalising(vectors: list[Vector]) -> float:
    """Max |cosine - dot| over all pairs once vectors are L2-normalised.

    This is the invariant that makes normalisation worth doing once at write time instead
    of on every query: after normalising, dot IS cosine, so the cheapest kernel your vector
    store offers becomes the correct one. Measured, not assumed -- the return value is a
    float that must be at floating-point noise.
    """
    unit = [l2_normalize(v) for v in vectors]
    worst = 0.0
    for i in range(len(unit)):
        for j in range(i + 1, len(unit)):
            worst = max(worst, abs(cosine(unit[i], unit[j]) - dot(unit[i], unit[j])))
    return worst


def top1(query: Vector, corpus: list[Vector], metric) -> int:
    return max(range(len(corpus)), key=lambda i: metric(query, corpus[i]))


def ranking_flip_rate(corpus: list[Vector], queries: list[Vector]) -> dict:
    """How often dot and cosine disagree on the nearest neighbour, UNNORMALISED.

    This is the number that makes A4 concrete. "Cosine and dot are basically the same" is
    true only for unit vectors; on raw vectors of differing norms, dot is norm-biased and
    systematically prefers long documents. The output is the fraction of queries whose top-1
    result changes -- an operational error rate, not a numerical curiosity.
    """
    flips = 0
    for q in queries:
        if top1(q, corpus, dot) != top1(q, corpus, cosine):
            flips += 1
    return {
        "queries": len(queries),
        "flips": flips,
        "flip_rate": flips / len(queries) if queries else 0.0,
        "unit": "fraction of queries whose top-1 neighbour changes",
    }


def norm_spread(vectors: list[Vector]) -> dict:
    """The precondition for a flip: if all norms are equal, dot and cosine rank alike.
    Reporting the spread stops the flip rate from looking like magic.
    """
    norms = sorted(l2_norm(v) for v in vectors)
    return {"min": norms[0], "max": norms[-1], "ratio": norms[-1] / norms[0]}
