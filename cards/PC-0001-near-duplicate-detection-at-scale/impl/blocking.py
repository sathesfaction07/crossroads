# KB-AUTHORED REFERENCE IMPLEMENTATION — PC-0001
"""Sub-problem 1 of 4: turn O(N^2) into O(N) candidate generation (MinHash + LSH).

Pure stdlib on purpose: the card must be runnable anywhere, with no numpy/datasketch,
so that "runnable + tested" is a fact rather than a claim about someone's environment.
"""
from __future__ import annotations
import hashlib
from collections import defaultdict
from functools import lru_cache

_MAX = (1 << 64) - 1


def shingles(text: str, k: int = 5) -> set[str]:
    """Character k-shingles. Short strings yield one shingle rather than none."""
    t = " ".join(text.split())
    if len(t) <= k:
        return {t} if t else set()
    return {t[i:i + k] for i in range(len(t) - k + 1)}


def _h(perm: int, token: str) -> int:
    d = hashlib.sha1(f"{perm}:{token}".encode()).digest()
    return int.from_bytes(d[:8], "big")


def minhash_signature(tokens: set[str], num_perm: int = 128) -> tuple[int, ...]:
    """min over tokens of h_i(token), for each of num_perm hash permutations."""
    if not tokens:
        return tuple([_MAX] * num_perm)
    return tuple(min(_h(i, tok) for tok in tokens) for i in range(num_perm))


def estimated_jaccard(sig_a: tuple[int, ...], sig_b: tuple[int, ...]) -> float:
    """Fraction of agreeing signature positions -- an unbiased Jaccard estimate."""
    if not sig_a:
        return 0.0
    return sum(1 for x, y in zip(sig_a, sig_b) if x == y) / len(sig_a)


def detection_probability(similarity: float, bands: int, rows: int) -> float:
    """P(pair becomes a candidate) = 1 - (1 - s^r)^b.

    This is the whole cost model. It is why bands/rows is a TUNING DECISION and not
    a constant: it sets the recall/candidate-volume tradeoff the card quantifies.
    """
    return 1.0 - (1.0 - similarity ** rows) ** bands


def achievable_knees(num_perm: int = 128) -> list[tuple[int, int, float]]:
    """Every (bands, rows, knee) reachable for a signature of length num_perm.

    CORRECTED. This function previously required bands*rows == num_perm and therefore
    enumerated only the DIVISOR pairs -- 8 of them for num_perm=128. That was wrong, and
    the error propagated into card constraints C1, C3 and A4 and into six passing tests.

    The real constraint is bands*rows <= num_perm: you may leave hashes unused. That gives
    645 reachable pairs at num_perm=128 and 1466 at 256, so the knee space is DENSE and
    there is no quantization gap and no "unreachable" threshold. Verified against real
    datasketch 2.0.0; see grounding/PHASE-D2b-RESULT.json.
    """
    out = []
    for bands in range(1, num_perm + 1):
        for rows in range(1, num_perm // bands + 1):
            out.append((bands, rows, (1.0 / bands) ** (1.0 / rows)))
    return sorted(out, key=lambda t: t[2])


def _selection_error(threshold: float, bands: int, rows: int,
                     fp_weight: float = 0.5, fn_weight: float = 0.5) -> float:
    """datasketch's actual objective: a weighted FP/FN integral, not nearest-knee.

    Reproduces datasketch.lsh._optimal_param's integration (step 0.001) in pure stdlib.
    The card previously assumed the library picks the CLOSEST KNEE. It does not, and the
    difference is not cosmetic -- it is why threshold 0.70 at num_perm=128 selects (14,9)
    rather than the nearest-knee (16,8).
    """
    step = 0.001
    fp = 0.0
    s = 0.0
    while s < threshold:
        fp += (1.0 - (1.0 - (s + 0.5 * step) ** rows) ** bands) * step
        s += step
    fn = 0.0
    s = threshold
    while s < 1.0:
        fn += (1.0 - (s + 0.5 * step) ** rows) ** bands * step
        s += step
    return fp * fp_weight + fn * fn_weight


@lru_cache(maxsize=None)
def recommend_bands_rows(threshold: float, num_perm: int = 128) -> tuple[int, int]:
    """(bands, rows) datasketch would actually select for this threshold.

    Minimises the weighted FP/FN integral over every (bands, rows) with
    bands*rows <= num_perm. Agreement with real datasketch is asserted by
    test_selection_agrees_with_real_datasketch, which is the check that would have
    caught the original error and did not exist.
    """
    best = None
    for bands in range(1, num_perm + 1):
        for rows in range(1, num_perm // bands + 1):
            err = _selection_error(threshold, bands, rows)
            if best is None or err < best[0]:
                best = (err, bands, rows)
    return best[1], best[2]


def knee_error(threshold: float, num_perm: int = 128) -> float:
    """How far the SELECTED pair's knee sits from the threshold you asked for.

    Still a real effect -- you do not get exactly what you asked for -- but roughly 0.06
    at num_perm=128, not the 0.107 the card previously published, and with no gap where a
    threshold is unreachable.
    """
    b, r = recommend_bands_rows(threshold, num_perm)
    return abs((1.0 / b) ** (1.0 / r) - threshold)


# suggest_num_perm() was DELETED, not corrected.
#
# It recommended num_perm=120 at threshold 0.60 (claiming a 15x error improvement) and 180
# at 0.80 (39x). Under the real selector those switches make the gap WORSE: 0.60 goes
# 0.0617 -> 0.0671 and 0.80 goes 0.0445 -> 0.0473. The function advised spending more
# memory for less accuracy, and its entire premise -- that highly-divisible signature
# lengths offer more knees -- dissolves once bands*rows <= num_perm is the real constraint.
# Divisibility of num_perm is irrelevant. Do not reintroduce it.


def candidate_pairs(signatures: list[tuple[int, ...]], bands: int, rows: int) -> set[frozenset]:
    """Band the signatures; any two items colliding in ANY band become a candidate."""
    if signatures and bands * rows > len(signatures[0]):
        raise ValueError(
            f"bands*rows={bands * rows} exceeds signature length {len(signatures[0])}")
    cands: set[frozenset] = set()
    for b in range(bands):
        buckets: dict[tuple, list[int]] = defaultdict(list)
        lo, hi = b * rows, (b + 1) * rows
        for idx, sig in enumerate(signatures):
            buckets[sig[lo:hi]].append(idx)
        for members in buckets.values():
            if len(members) > 1:
                for i in range(len(members)):
                    for j in range(i + 1, len(members)):
                        cands.add(frozenset((members[i], members[j])))
    return cands
