"""Sub-problem 2 — POOLING. Many token vectors in, one vector out.

The defect this module measures is, in my experience, the single most common silent bug in
hand-rolled embedding pipelines: **mean-pooling across the padded axis.** It produces
vectors that are plausible, finite, correctly-shaped, and wrong -- and wrong by an amount
that depends on how full the batch row was, so short documents are damaged most.

Nothing here needs a model. The contamination is pure arithmetic over whatever the pad
position holds, which is why it is `[executed]` rather than `[reasoned]`.
"""
from __future__ import annotations

import random

from . import metric

Vector = list[float]


def mean_pool(token_vectors: list[Vector], mask: list[int] | None = None) -> Vector:
    """Mean over token positions. `mask` is 1 for real tokens, 0 for padding.

    With `mask=None` this is the BUGGY form -- it averages over padding too. It is kept,
    rather than deleted, because the card's job is to make the failure measurable, and a
    correct-only implementation cannot demonstrate the size of the error.
    """
    if not token_vectors:
        raise ValueError("cannot pool an empty sequence")
    dim = len(token_vectors[0])
    if mask is None:
        mask = [1] * len(token_vectors)
    if len(mask) != len(token_vectors):
        raise ValueError(f"mask length {len(mask)} != rows {len(token_vectors)}")
    kept = sum(mask)
    if kept == 0:
        raise ValueError("mask selects no tokens")
    out = [0.0] * dim
    for vec, m in zip(token_vectors, mask):
        if m:
            for i in range(dim):
                out[i] += vec[i]
    return [x / kept for x in out]


def synthetic_token_vectors(n: int, dim: int, seed: int, centroid: float = 0.0) -> list[Vector]:
    """Deterministic stand-in for a model's token outputs.

    `centroid` shifts the whole cloud off the origin, which is what real transformer
    outputs look like -- they are not zero-mean. That detail is load-bearing: if token
    vectors were zero-mean AND the pad vector were zero, unmasked pooling would only
    rescale the result and cosine would not move at all. Real pipelines fail because
    neither is true.
    """
    rng = random.Random(seed)
    return [[rng.gauss(centroid, 1.0) for _ in range(dim)] for _ in range(n)]


def pad_contamination(true_len: int, padded_len: int, dim: int = 64,
                      seed: int = 7, pad_value: float = 0.0,
                      centroid: float = 0.35) -> dict:
    """Cosine between the correctly-masked vector and the unmasked one.

    Returns the fill ratio alongside the error, because the error is a FUNCTION of fill
    ratio and reporting a single number would be exactly the flattening this project keeps
    finding: "pad contamination costs 0.02 cosine" is meaningless without saying at what
    occupancy.
    """
    if not 0 < true_len <= padded_len:
        raise ValueError("require 0 < true_len <= padded_len")
    real = synthetic_token_vectors(true_len, dim, seed, centroid)
    # pad_value=0.0 is the case everyone assumes. It is also the ONLY case in which this
    # bug is direction-preserving -- see the measured table in the card. A real encoder
    # emits non-zero values at pad positions unless attention is masked, so both cases are
    # measurable here and the card publishes both.
    pad = [[pad_value] * dim for _ in range(padded_len - true_len)]
    rows = real + pad
    mask = [1] * true_len + [0] * (padded_len - true_len)

    correct = mean_pool(rows, mask)
    buggy = mean_pool(rows, None)
    return {
        "true_len": true_len,
        "padded_len": padded_len,
        "fill_ratio": true_len / padded_len,
        "cosine_correct_vs_buggy": metric.cosine(correct, buggy),
        "norm_ratio_buggy_over_correct": metric.l2_norm(buggy) / metric.l2_norm(correct),
    }


def contamination_changes_ranking(batch_lengths: list[int], padded_len: int,
                                  dim: int = 64, seed: int = 11) -> dict:
    """Does the bug change WHO is nearest, or only the numbers?

    Cosine drift is only alarming if it reorders results, so this measures the consequence
    directly: pool a batch both ways, then for each document ask whether its nearest
    neighbour changes. A cosine shift that never reorders anything would be a curiosity;
    one that reorders is a retrieval defect.
    """
    correct: list[Vector] = []
    buggy: list[Vector] = []
    for i, n in enumerate(batch_lengths):
        real = synthetic_token_vectors(n, dim, seed + i, centroid=0.35)
        rows = real + [[0.0] * dim] * (padded_len - n)
        mask = [1] * n + [0] * (padded_len - n)
        correct.append(mean_pool(rows, mask))
        buggy.append(mean_pool(rows, None))

    changed = 0
    for i in range(len(correct)):
        others = [j for j in range(len(correct)) if j != i]
        near_c = max(others, key=lambda j: metric.cosine(correct[i], correct[j]))
        near_b = max(others, key=lambda j: metric.cosine(buggy[i], buggy[j]))
        if near_c != near_b:
            changed += 1
    return {
        "docs": len(batch_lengths),
        "nearest_neighbour_changed": changed,
        "rate": changed / len(batch_lengths),
        "unit": "fraction of documents whose nearest neighbour changes",
    }
