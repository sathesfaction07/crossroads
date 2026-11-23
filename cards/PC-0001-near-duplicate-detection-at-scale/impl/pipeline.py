# KB-AUTHORED REFERENCE IMPLEMENTATION — PC-0001
"""The composition of all four sub-problems, with its work reported rather than assumed.

    shingle -> minhash -> LSH band  (blocking)   O(N)   recall device
      -> exact score candidates     (scoring)    O(C)   the decision
      -> representative-link        (clustering) O(C)   chain-resistant grouping
      -> canonical selection        (canonical)  O(sum k^2) deterministic survivor

`stats` is part of the contract: a caller must be able to see the reduction factor it
actually got, because a badly tuned (bands, rows) silently degrades to either
near-naive cost or poor recall, and both look like success from the outside.
"""
from __future__ import annotations
from . import blocking, scoring, clustering, canonical


def deduplicate(texts: list[str], threshold: float = 0.7, num_perm: int = 128,
                k: int = 5, strategy: str = "medoid",
                bands_rows: tuple[int, int] | None = None) -> dict:
    sets = [blocking.shingles(t, k=k) for t in texts]
    bands, rows = bands_rows or blocking.recommend_bands_rows(threshold, num_perm)

    sigs = [blocking.minhash_signature(s, num_perm) for s in sets]
    cands = blocking.candidate_pairs(sigs, bands, rows)
    edges = scoring.score_candidates(cands, sets, threshold)
    clusters = clustering.representative_link(edges, len(texts), sets, threshold)
    survivors = canonical.select_canonical(clusters, sets, strategy)

    dropped = {i for lost in survivors.values() for i in lost}
    return {
        "clusters": clusters,
        "canonical": survivors,
        "kept": sorted(set(range(len(texts))) - dropped),
        "dropped": sorted(dropped),
        "stats": {
            "items": len(texts),
            "bands": bands,
            "rows": rows,
            "knee": round((1.0 / bands) ** (1.0 / rows), 4),
            "knee_error": round(abs((1.0 / bands) ** (1.0 / rows) - threshold), 4),
            "expected_recall_at_threshold": round(
                blocking.detection_probability(threshold, bands, rows), 4),
            **scoring.candidate_efficiency(len(cands), len(texts)),
            "confirmed_pairs": len(edges),
        },
    }
