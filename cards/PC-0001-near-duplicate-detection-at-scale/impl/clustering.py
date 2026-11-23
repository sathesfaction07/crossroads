# KB-AUTHORED REFERENCE IMPLEMENTATION — PC-0001
"""Sub-problem 3 of 4: group pairs into duplicate sets -- and refuse to chain.

THE SUBTLE FAILURE. Union-find over "similar" edges is single-linkage clustering,
which is TRANSITIVE: A~B and B~C puts A and C in one cluster even when A and C are
not similar at all. On real data this collapses large regions into one giant
cluster, and because the code "works", nothing surfaces it.

Both algorithms are provided so the difference is demonstrable, not asserted:
  single_link          -- the naive/transitive version (what union-find alone gives)
  representative_link  -- merges only when the item is similar to the cluster's
                          representative, which breaks the chain
"""
from __future__ import annotations


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]   # path halving
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        return True


def _groups(uf: UnionFind, n: int) -> list[set[int]]:
    buckets: dict[int, set[int]] = {}
    for i in range(n):
        buckets.setdefault(uf.find(i), set()).add(i)
    return sorted((g for g in buckets.values() if len(g) > 1), key=lambda g: sorted(g))


def single_link(edges: list[tuple[int, int, float]], n: int) -> list[set[int]]:
    """Plain union-find. Transitive by construction -- included to be compared against."""
    uf = UnionFind(n)
    for i, j, _ in edges:
        uf.union(i, j)
    return _groups(uf, n)


def representative_link(edges: list[tuple[int, int, float]], n: int,
                        sets: list[set], threshold: float) -> list[set[int]]:
    """Chain-resistant clustering.

    Edges MUST arrive sorted by descending score (scoring.score_candidates does that):
    the strongest pair seeds a cluster and fixes its representative, and a later item
    joins only if it is >= threshold to that representative. So A~B=0.9, B~C=0.9,
    A~C=0.2 yields {A,B} and leaves C out, instead of {A,B,C}.
    """
    from .naive import jaccard
    rep_of: dict[int, int] = {}      # member -> representative
    members: dict[int, set[int]] = {}  # representative -> members

    for i, j, _ in edges:
        ci, cj = rep_of.get(i), rep_of.get(j)
        if ci is None and cj is None:
            rep_of[i] = rep_of[j] = i
            members[i] = {i, j}
        elif ci is not None and cj is None:
            if jaccard(sets[j], sets[ci]) >= threshold:
                rep_of[j] = ci
                members[ci].add(j)
        elif ci is None and cj is not None:
            if jaccard(sets[i], sets[cj]) >= threshold:
                rep_of[i] = cj
                members[cj].add(i)
        elif ci != cj:
            # merge two clusters only if their REPRESENTATIVES are themselves similar
            if jaccard(sets[ci], sets[cj]) >= threshold:
                keep, drop = (ci, cj) if len(members[ci]) >= len(members[cj]) else (cj, ci)
                for m in members[drop]:
                    rep_of[m] = keep
                members[keep] |= members.pop(drop)
    return sorted((g for g in members.values() if len(g) > 1), key=lambda g: sorted(g))


def max_intra_cluster_distance(cluster: set[int], sets: list[set]) -> float:
    """Worst-case dissimilarity inside a cluster: 1 - min pairwise similarity.

    The diagnostic for chaining. A cluster whose max distance far exceeds
    (1 - threshold) was produced by transitivity, not by similarity.
    """
    from .naive import jaccard
    idx = sorted(cluster)
    if len(idx) < 2:
        return 0.0
    return 1.0 - min(jaccard(sets[a], sets[b])
                     for n, a in enumerate(idx) for b in idx[n + 1:])
