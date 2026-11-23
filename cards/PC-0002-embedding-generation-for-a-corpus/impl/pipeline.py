"""Shape A, composed — the pipeline the card recommends, end to end.

Order is not stylistic. It is the decomposition's topological order:

    chunk (1) -> bucket+pad (3) -> masked pool (2) -> normalise (5) -> cache by identity (4)

Batching sits between chunking and pooling because you cannot pad until you know the units,
and you cannot pool correctly until you know what was padding. Identity is last because the
key must cover every decision made above it.

`embed_fn` is injected. No model runs here, and that is deliberate: every property this
module guarantees (mask correctness, order restoration, key completeness) is a property of
the PLUMBING, and plumbing is exactly what is testable without a GPU.
"""
from __future__ import annotations

import hashlib
import random

from . import chunking, identity, metric, pooling

Vector = list[float]

DEFAULT_CFG = {
    "model": "fake-embed-v1",
    "revision": "a1b2c3",
    "pooling": "masked-mean",
    "window": 512,
    "overlap": 32,
    "normalize": True,
    "dim": 64,
}


def fake_embed(padded_tokens: list[str], dim: int = 64) -> list[Vector]:
    """A deterministic stand-in for a model forward pass.

    Token vectors depend on the token string, so identical text yields identical vectors --
    which is what makes cache behaviour testable. Off-origin (centroid 0.35) because real
    transformer outputs are not zero-mean, and that is what makes pad contamination bite.
    """
    out = []
    for tok in padded_tokens:
        # NOT builtins.hash(): str hashing is salted per process (PYTHONHASHSEED), so that
        # would make every vector, every cache hit and every published number differ
        # between runs. A card whose `[executed]` figures are not reproducible has no
        # `[executed]` figures.
        seed = int(hashlib.sha256(tok.encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(seed)
        out.append([rng.gauss(0.35, 1.0) for _ in range(dim)])
    return out


def embed_corpus(corpus: list[str], cfg: dict | None = None, *, batch_size: int = 32,
                 embed_fn=fake_embed, cache: dict | None = None) -> tuple[list[Vector], dict]:
    """Embed a corpus. Returns one L2-normalised vector per input document, in INPUT ORDER.

    "In input order" is a guarantee, not a coincidence -- see `throughput.restore`. It is
    stated here because the bucketing that makes this fast is also the thing that would
    silently misalign every vector if the permutation were dropped.
    """
    cfg = dict(cfg or DEFAULT_CFG)
    window, overlap, dim = cfg["window"], cfg["overlap"], cfg["dim"]
    cache = cache if cache is not None else {}

    units: list[tuple[int, list[str]]] = []
    for doc_i, doc in enumerate(corpus):
        for piece in chunking.chunk(chunking.tokenize(doc), window, overlap):
            units.append((doc_i, piece))

    order = sorted(range(len(units)), key=lambda i: len(units[i][1]))
    chunk_vectors: list[Vector | None] = [None] * len(units)
    paid_slots = hits = misses = 0

    for start in range(0, len(order), batch_size):
        idxs = order[start:start + batch_size]
        rows = [units[i][1] for i in idxs]
        width = max(len(r) for r in rows)
        paid_slots += width * len(rows)

        for slot, i in enumerate(idxs):
            tokens = rows[slot]
            key = identity.embedding_key(" ".join(tokens), cfg)
            if key in cache:
                chunk_vectors[i] = cache[key]
                hits += 1
                continue
            padded = tokens + ["<pad>"] * (width - len(tokens))
            mask = [1] * len(tokens) + [0] * (width - len(tokens))
            pooled = pooling.mean_pool(embed_fn(padded, dim), mask)
            vec = metric.l2_normalize(pooled) if cfg["normalize"] else pooled
            chunk_vectors[i] = vec
            cache[key] = vec
            misses += 1

    per_doc: list[list[Vector]] = [[] for _ in corpus]
    for (doc_i, _), vec in zip(units, chunk_vectors):
        per_doc[doc_i].append(vec)

    doc_vectors: list[Vector] = []
    for vecs in per_doc:
        summed = [sum(col) for col in zip(*vecs)]
        doc_vectors.append(metric.l2_normalize(summed))

    return doc_vectors, {
        "documents": len(corpus),
        "chunks": len(units),
        "chunks_per_doc": len(units) / len(corpus) if corpus else 0.0,
        "paid_slots": paid_slots,
        "useful_tokens": sum(len(u[1]) for u in units),
        "wasted_fraction": (paid_slots - sum(len(u[1]) for u in units)) / paid_slots
                           if paid_slots else 0.0,
        "cache_hits": hits,
        "cache_misses": misses,
    }
