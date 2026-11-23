"""The synthetic corpus every measured number in PC-0002 is measured ON.

This module exists so that `measured_on` can name a real, regenerable artifact instead of
saying "a fixture". PC-0001 published `measured: 0.6133` without its corpus and a consumer
read it as a property of the algorithm; that defect is not repeated here.

WHAT THIS IS: a deterministic, seeded, synthetic corpus with a right-skewed token-length
distribution, which is the property that drives every cost result in this card (truncation
loss, padding waste, batching gains).

WHAT THIS IS NOT: real text. There is no semantic content, so nothing here supports any
claim about embedding QUALITY. Length-distribution claims transfer to any corpus with a
similar shape; quality claims do not exist in this card at all.
"""
from __future__ import annotations

import random

SEED = 20260906


def synthetic_corpus(n: int = 2000, seed: int = SEED) -> list[str]:
    """n documents whose token counts are right-skewed, like real document corpora.

    Uses a log-normal-ish shape built from stdlib `random.gauss`, floored at 8 tokens.
    Deterministic for a given (n, seed) so every measurement in this card is reproducible
    by anyone who runs the suite.
    """
    rng = random.Random(seed)
    docs = []
    for i in range(n):
        # mu/sigma chosen so the bulk sits under 512 tokens with a long tail past 2000 --
        # the regime where truncation decisions actually matter
        length = int(min(6000, max(8, rng.lognormvariate(5.2, 0.9))))
        docs.append(" ".join(f"t{i}w{j}" for j in range(length)))
    return docs


def token_lengths(corpus: list[str]) -> list[int]:
    return [len(d.split()) for d in corpus]


def length_profile(corpus: list[str]) -> dict:
    """Descriptive stats, computed not asserted. The skew is the whole point: mean and
    median differ substantially, which is exactly why fixed-size batching wastes slots.
    """
    lens = sorted(token_lengths(corpus))
    n = len(lens)

    def pct(p: float) -> int:
        return lens[min(n - 1, int(p * n))]

    return {
        "n": n,
        "total_tokens": sum(lens),
        "min": lens[0],
        "p50": pct(0.50),
        "p90": pct(0.90),
        "p99": pct(0.99),
        "max": lens[-1],
        "mean": sum(lens) / n,
    }
