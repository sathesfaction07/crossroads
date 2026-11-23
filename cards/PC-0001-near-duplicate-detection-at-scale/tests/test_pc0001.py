#!/usr/bin/env python3
"""Tests for PC-0001. Every test states the claim in CARD.md that it makes checkable.

This file is the reason the card may use the `executed` evidence class. If it does not
run, the card's claims drop to `reasoned` and validate_cards.py must say so.

Run:  python3 -m unittest discover -s tests -t .
"""
from __future__ import annotations
import random
import unittest

from impl import blocking, scoring, clustering, canonical, naive, pipeline


class TestJaccard(unittest.TestCase):
    def test_identical_and_disjoint(self):
        self.assertEqual(naive.jaccard({"a", "b"}, {"a", "b"}), 1.0)
        self.assertEqual(naive.jaccard({"a"}, {"b"}), 0.0)

    def test_known_value(self):
        # |{b,c}| / |{a,b,c,d}| = 0.5
        self.assertAlmostEqual(naive.jaccard({"a", "b", "c"}, {"b", "c", "d"}), 0.5)

    def test_empty_vs_empty_is_defined(self):
        """Left undefined this raises ZeroDivisionError deep inside a batch job."""
        self.assertEqual(naive.jaccard(set(), set()), 1.0)


class TestCostModel(unittest.TestCase):
    def test_naive_comparison_count_is_exact(self):
        """CARD.md quotes these numbers; if the formula drifts the card lies."""
        self.assertEqual(naive.comparison_count(1_000), 499_500)
        self.assertEqual(naive.comparison_count(1_000_000), 499_999_500_000)

    def test_wall_clock_estimates_are_exact(self):
        """REGRESSION: CARD.md first claimed ~6 days at 1 ns/comparison for N=1e6.

        Wrong by 1000x -- that is the 1 MICROsecond figure. Both rates are pinned here
        so the card cannot drift back to an unexecutable cost claim.
        """
        ns = naive.estimated_wall_clock(1_000_000, 1e-9)
        us = naive.estimated_wall_clock(1_000_000, 1e-6)
        self.assertEqual(ns["comparisons"], 499_999_500_000)
        self.assertAlmostEqual(ns["seconds"], 499.9995, places=3)
        self.assertAlmostEqual(ns["minutes"], 8.333325, places=4)
        self.assertAlmostEqual(us["days"], 5.787, places=2)
        self.assertLess(ns["days"], 0.01, "1 ns/comparison is minutes, not days")

    def test_ten_million_is_years_at_microsecond_rate(self):
        """The breakpoint that actually motivates the pattern."""
        us = naive.estimated_wall_clock(10_000_000, 1e-6)
        self.assertAlmostEqual(us["days"], 578.70, places=1)
        # The card publishes N=1e7 comparisons too, and only `days` was asserted -- so the
        # comparison count could drift while the day figure stayed put. 1e7*(1e7-1)/2.
        self.assertEqual(us["comparisons"], 49_999_995_000_000)

    def test_detection_probability_is_monotonic_in_similarity(self):
        ps = [blocking.detection_probability(s / 10, 16, 8) for s in range(11)]
        self.assertEqual(ps, sorted(ps))
        self.assertAlmostEqual(ps[0], 0.0)
        self.assertAlmostEqual(ps[-1], 1.0)

    def test_bands_rows_need_not_multiply_to_num_perm(self):
        """CORRECTED. This test previously asserted b*r == num_perm for every threshold.

        That was the false premise behind the retracted C3/A4 and behind the wrong figures
        in C1 and C2. The real constraint is b*r <= num_perm -- unused hashes are allowed --
        and the selected pair is USUALLY NOT a divisor pair.
        """
        exact = 0
        for thr in (0.5, 0.6, 0.7, 0.8, 0.9):
            b, r = blocking.recommend_bands_rows(thr, 128)
            self.assertLessEqual(b * r, 128, f"threshold {thr}")
            if b * r == 128:
                exact += 1
        self.assertLess(exact, 5, "if every selection were a divisor pair the old model "
                                 "would be right; it is not")

    def test_selection_agrees_with_real_datasketch(self):
        """THE CHECK THAT DID NOT EXIST, and whose absence let the error survive.

        The implementation is deliberately stdlib-only, which is what allowed card, impl and
        tests to form a closed loop that was perfectly self-consistent and entirely wrong.
        This test breaks the loop by comparing against the real library. Skipped, not
        silently passed, when datasketch is unavailable.
        """
        try:
            from datasketch import MinHashLSH
        except ImportError:
            self.skipTest("datasketch not installed; cannot cross-check against reality")
        for num_perm in (128, 256):
            for thr in (0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9):
                lsh = MinHashLSH(threshold=thr, num_perm=num_perm)
                self.assertEqual(blocking.recommend_bands_rows(thr, num_perm),
                                 (lsh.b, lsh.r),
                                 f"num_perm={num_perm} threshold={thr}")

    def test_selection_minimises_fp_fn_not_knee_distance(self):
        """CORRECTED. The old test asserted the library picks the CLOSEST ACHIEVABLE KNEE.

        It does not -- it minimises a weighted FP/FN integral, and the two objectives
        disagree. At threshold 0.70 with num_perm=128 the selected pair is (14,9) at 0.7459,
        while the nearest knee overall is (6,5) at 0.6988 and the nearest DIVISOR-pair knee
        is (16,8) at 0.7071. C1 measured recall at (16,8) and was wrong by 45%.
        """
        b, r = blocking.recommend_bands_rows(0.70, 128)
        self.assertEqual((b, r), (14, 9))
        # The nearest knee in the REAL (dense) space is (6,5) at 0.6988 -- not (16,8) at
        # 0.7071. I initially asserted (16,8) here, carrying over the old belief; (16,8) is
        # merely the nearest DIVISOR-PAIR knee. So the old model was wrong twice over: the
        # library does not optimise for knee distance, AND (16,8) was not even the closest
        # knee once the divisor restriction is lifted.
        nearest = min(blocking.achievable_knees(128), key=lambda t: abs(t[2] - 0.70))
        self.assertEqual((nearest[0], nearest[1]), (6, 5))
        self.assertAlmostEqual(nearest[2], 0.6988, places=3)

        divisor_only = [t for t in blocking.achievable_knees(128) if t[0] * t[1] == 128]
        nearest_divisor = min(divisor_only, key=lambda t: abs(t[2] - 0.70))
        self.assertEqual((nearest_divisor[0], nearest_divisor[1]), (16, 8),
                         "this is what the old divisor-only model saw, and why C1 measured "
                         "recall at (16,8)")

        self.assertNotEqual((b, r), (nearest[0], nearest[1]),
                           "the two objectives must be shown to differ, or the old "
                           "nearest-knee model would be harmless")

    def test_there_is_NO_unreachable_threshold_hole(self):
        """CORRECTED, and this is the inversion of the worst test in the old suite.

        The old test asserted a gap with no knee between 0.420 and 0.707, concluded 0.6 was
        'simply not reachable', and pinned it as a regression with the note 'the naive
        assumption is seductive'. The belief it called NAIVE -- that any threshold is
        tunable -- is the TRUE one. There are 645 reachable pairs at num_perm=128, not 8.
        """
        knees = [k for _, _, k in blocking.achievable_knees(128)]
        self.assertGreater(len(knees), 600, "the space is dense, not quantized by divisors")
        near_06 = [k for k in knees if 0.55 < k < 0.65]
        self.assertTrue(near_06, "0.6 IS reachable; the old 'hole' was an artefact")
        self.assertLess(blocking.knee_error(0.6, 128), 0.07,
                        "the real miss at 0.6 is ~0.062, not the 0.107 the card published")

    def test_gap_to_requested_threshold_is_small_but_real(self):
        """CORRECTED. Replaces test_at_0_7_the_default_128_is_already_adequate, which
        asserted knee_error(0.7,128) < 0.01. The real gap at 0.7 is 0.0459.

        What survives from C3 is only this: you do not get exactly what you asked for.
        """
        self.assertAlmostEqual(blocking.knee_error(0.7, 128), 0.0459, places=3)
        self.assertAlmostEqual(blocking.knee_error(0.6, 128), 0.0617, places=3)
        self.assertAlmostEqual(blocking.knee_error(0.8, 128), 0.0445, places=3)
        for thr in (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95):
            self.assertLess(blocking.knee_error(thr, 128), 0.07,
                            f"worst observed gap is ~0.062; threshold {thr}")

    def test_divisibility_of_num_perm_is_irrelevant(self):
        """CORRECTED. Replaces test_a_highly_divisible_num_perm_closes_the_hole, which
        asserted 120 (16 divisors) beats 128 (8 divisors) at threshold 0.6.

        Under the real constraint b*r <= num_perm, divisor count does not govern anything,
        and the old advice was WORSE than doing nothing: 120 gives 0.0671 against 128's
        0.0617. suggest_num_perm() was deleted rather than corrected.
        """
        self.assertFalse(hasattr(blocking, "suggest_num_perm"),
                         "suggest_num_perm recommended changes that reduce accuracy")
        self.assertGreater(blocking.knee_error(0.6, 120), blocking.knee_error(0.6, 128))
        self.assertGreater(blocking.knee_error(0.8, 180), blocking.knee_error(0.8, 128))

    def test_high_similarity_is_almost_certainly_caught(self):
        """CARD.md claims >=0.99 detection at s=0.9 for the 0.7 tuning."""
        b, r = blocking.recommend_bands_rows(0.7, 128)
        self.assertGreater(blocking.detection_probability(0.90, b, r), 0.99)


class TestMinHash(unittest.TestCase):
    def test_identical_token_sets_give_identical_signatures(self):
        a = blocking.minhash_signature({"x", "y", "z"}, 64)
        b = blocking.minhash_signature({"z", "y", "x"}, 64)
        self.assertEqual(a, b, "signature must not depend on set iteration order")

    def test_signature_estimates_jaccard(self):
        """The estimator is unbiased; assert it lands near truth on a real pair."""
        random.seed(11)
        universe = [f"t{i}" for i in range(400)]
        a = set(universe[:200])
        b = set(universe[100:300])           # true Jaccard = 100/300
        est = blocking.estimated_jaccard(
            blocking.minhash_signature(a, 256), blocking.minhash_signature(b, 256))
        self.assertAlmostEqual(est, 1 / 3, delta=0.08)

    def test_empty_set_signature_is_stable(self):
        self.assertEqual(blocking.minhash_signature(set(), 8),
                         blocking.minhash_signature(set(), 8))

    def test_shingles_handles_strings_shorter_than_k(self):
        """Returning an empty set here makes short records silently unmatchable."""
        self.assertEqual(blocking.shingles("ab", k=5), {"ab"})
        self.assertEqual(blocking.shingles("", k=5), set())

    def test_bands_rows_exceeding_signature_length_is_rejected(self):
        sigs = [blocking.minhash_signature({"a"}, 8)]
        with self.assertRaises(ValueError):
            blocking.candidate_pairs(sigs, bands=4, rows=4)  # 16 > 8


class TestChaining(unittest.TestCase):
    """The card's headline anti-pattern (A1), made demonstrable."""

    @staticmethod
    def _abc():
        # A~B high, B~C high, A~C low: the classic chain
        a = set("abcdefghij")
        b = set("abcdefghiZ")            # ~ 0.82 to A
        c = set("Zklmnopqrs")            # ~ 0.05 to A, ~0.1 to B
        return [a, b, c]

    def test_single_link_chains_dissimilar_items_together(self):
        sets = self._abc()
        edges = [(0, 1, naive.jaccard(sets[0], sets[1])),
                 (1, 2, naive.jaccard(sets[1], sets[2]))]
        got = clustering.single_link(edges, 3)
        self.assertEqual(got, [{0, 1, 2}],
                         "union-find is transitive: this is the failure, not a bug")

    def test_representative_link_refuses_the_chain(self):
        sets = self._abc()
        edges = sorted([(0, 1, naive.jaccard(sets[0], sets[1])),
                        (1, 2, naive.jaccard(sets[1], sets[2]))],
                       key=lambda t: -t[2])
        got = clustering.representative_link(edges, 3, sets, threshold=0.5)
        self.assertEqual(got, [{0, 1}], "C must not join a cluster it is unlike")

    def test_intra_cluster_distance_exposes_a_chained_cluster(self):
        sets = self._abc()
        chained = clustering.max_intra_cluster_distance({0, 1, 2}, sets)
        honest = clustering.max_intra_cluster_distance({0, 1}, sets)
        self.assertGreater(chained, 0.9)
        self.assertLess(honest, 0.2)


class TestUnionFind(unittest.TestCase):
    def test_union_is_idempotent_and_reports_merges(self):
        uf = clustering.UnionFind(4)
        self.assertTrue(uf.union(0, 1))
        self.assertFalse(uf.union(1, 0), "already joined")
        self.assertEqual(uf.find(0), uf.find(1))
        self.assertNotEqual(uf.find(0), uf.find(2))

    def test_singletons_are_not_reported_as_clusters(self):
        self.assertEqual(clustering.single_link([], 5), [])


class TestCanonical(unittest.TestCase):
    def test_medoid_picks_the_most_representative_member(self):
        # 0 and 1 near-identical, 2 an outlier: medoid must be 0 or 1, never 2
        sets = [set("abcdefghij"), set("abcdefghik"), set("abZZZZZZZZ")]
        self.assertIn(canonical.pick_medoid({0, 1, 2}, sets), (0, 1))

    def test_earliest_is_order_dependent_and_medoid_is_not(self):
        """The defect named in CARD.md's cited evidence, shown rather than described."""
        sets = [set("abZZZZZZZZ"), set("abcdefghij"), set("abcdefghik")]
        self.assertEqual(canonical.pick_earliest({0, 1, 2}, sets), 0)   # the outlier wins
        self.assertIn(canonical.pick_medoid({0, 1, 2}, sets), (1, 2))

    def test_longest_breaks_ties_deterministically(self):
        sets = [{"a", "b"}, {"c", "d"}]
        self.assertEqual(canonical.pick_longest({0, 1}, sets),
                         canonical.pick_longest({1, 0}, sets))

    def test_unknown_strategy_is_rejected_loudly(self):
        with self.assertRaises(ValueError):
            canonical.select_canonical([{0, 1}], [{"a"}, {"a"}], strategy="vibes")

    def test_select_canonical_maps_survivor_to_dropped(self):
        sets = [set("abcdefghij"), set("abcdefghik")]
        got = canonical.select_canonical([{0, 1}], sets, "longest")
        self.assertEqual(sum(len(v) for v in got.values()), 1)
        self.assertEqual(len(got), 1)


class TestPipelineAgainstNaiveGroundTruth(unittest.TestCase):
    """The equivalence claim: the decomposition must find what O(N^2) finds."""

    @staticmethod
    def _corpus(n_groups=40, seed=7):
        random.seed(seed)
        texts, truth = [], []
        for g in range(n_groups):
            base = " ".join(random.choice(("alpha", "beta", "gamma", "delta", "epsilon",
                                           "zeta", "eta", "theta", "iota", "kappa"))
                            for _ in range(24)) + f" grp{g}"
            group = [len(texts)]
            texts.append(base)
            words = base.split()
            edited = list(words)
            edited[3] = "MUTATED"                      # small edit -> still near-dup
            group.append(len(texts))
            texts.append(" ".join(edited))
            truth.append(set(group))
        return texts, truth

    def test_recall_against_exhaustive_search(self):
        texts, _ = self._corpus()
        sets = [blocking.shingles(t) for t in texts]
        truth = {frozenset((i, j))
                 for i, j, _ in naive.naive_duplicate_pairs(sets, 0.7)}
        out = pipeline.deduplicate(texts, threshold=0.7)
        found = {frozenset((i, j)) for i, j, _ in
                 scoring.score_candidates(
                     blocking.candidate_pairs(
                         [blocking.minhash_signature(s) for s in sets],
                         out["stats"]["bands"], out["stats"]["rows"]),
                     sets, 0.7)}
        self.assertTrue(truth, "fixture must actually contain duplicates")
        recall = len(truth & found) / len(truth)
        # CORRECTED: was assertGreaterEqual(recall, 0.90). The card's 0.95 (38/40) was
        # measured at (16,8), the nearest-knee pair the library does not select. Under the
        # real (14,9) recall is 0.875 -- the pair is more selective, so recall is LOWER and
        # the reduction factor is HIGHER. Pinned to the true value.
        self.assertAlmostEqual(recall, 0.875, places=3,
                               msg=f"recall {recall:.4f} of {len(truth)} pairs")

    def test_blocking_actually_reduces_work(self):
        """The entire point. If reduction <= 1 the pattern bought nothing.

        Two DIFFERENT claims live here and both are needed:

          * the INEQUALITY (reduction > 5) is the portable claim -- it should hold on any
            corpus, and it is what a reader is entitled to rely on.
          * the EQUALITIES below are the fixture pins. CORRECTED: C2 published 3160 -> 97
            candidates, 32.6x, 38 confirmed pairs, 38/40 groups. FOUR OF THOSE FIVE WERE
            MEASURED AT (16,8) -- the nearest-knee pair the library does not select -- and
            are wrong. The real (14,9) gives 56 candidates, 56.43x, 35 confirmed, 35/40.
            Only 3160 survives, because C(80,2) does not depend on the banding.

        Same defect trace_claims.py found in C3: a property was asserted, the values were not.
        The fix is not to replace the property with the value -- it is to assert both. The
        inequality generalises; the equality detects drift.
        """
        texts, truth = self._corpus()
        out = pipeline.deduplicate(texts, threshold=0.7)
        st = out["stats"]
        self.assertGreater(st["reduction_factor"], 5.0, st)

        # C2, pinned. Fixture-specific by construction (the card says so): reduction grows
        # with N, so these are a drift detector for THIS corpus, not a general law.
        self.assertEqual(len(texts), 80, "C2 is measured on n=80")
        self.assertEqual(st["items"], 80)
        self.assertEqual(st["naive_comparisons"], 3160)
        self.assertEqual(st["candidates"], 56, "was 97 at the wrong (16,8) banding")
        self.assertEqual(st["confirmed_pairs"], 35, "was 38 at (16,8)")
        self.assertAlmostEqual(st["reduction_factor"], 56.43, places=1,
                               msg="HIGHER than the published 32.6: (14,9) is more "
                                   "selective, so fewer candidates survive banding")
        # C1's measured value, corrected. 0.6133 was the detection probability for a pair
        # sitting AT threshold 0.7 under 16x8 banding. datasketch selects (14,9), where the
        # real figure is 0.4382 -- so the card UNDERSTATED its own miss rate: ~56% of
        # borderline pairs are missed, not ~39%.
        self.assertAlmostEqual(st["expected_recall_at_threshold"], 0.4382, places=4,
                               msg="C1: detection probability AT the threshold, at (14,9)")
        self.assertAlmostEqual(st["knee"], 0.7459, places=3)
        self.assertAlmostEqual(st["knee_error"], 0.0459, places=3)
        # groups_found, corrected to 35/40. The five it misses are the honest part of the
        # claim -- pin the miss, not only the hit.
        self.assertEqual(len(truth), 40, "fixture plants 40 groups")
        self.assertEqual(len(out["clusters"]), 35,
                         "C2 published 38/40 measured at (16,8); the true figure at the "
                         "selected (14,9) is 35/40")

    def test_no_survivor_is_also_dropped(self):
        texts, _ = self._corpus()
        out = pipeline.deduplicate(texts, threshold=0.7)
        self.assertEqual(set(out["canonical"]) & set(out["dropped"]), set())

    def test_every_cluster_is_internally_similar(self):
        """Guards silent regression to single-link chaining.

        REGRESSION -- this test did not do what its own docstring claimed, and a mutation
        sweep proved it: replacing `representative_link` with `single_link` in pipeline.py
        left the ENTIRE suite green. Two independent reasons, both measured:

          1. `_corpus()` is 40 disjoint PAIRS. Max cluster size is 2 and no cluster has >2
             members, so single-link has nothing to chain -- the two strategies produce
             byte-identical output on it. The card's headline anti-pattern (A1) was
             exercised only by TestChaining's hand-built 3-set fixture, never through the
             pipeline on a realistic corpus.
          2. Even where chaining DOES occur, the 0.45 distance bound is too loose to see it:
             the chained cluster below has max intra-cluster distance 0.376, which passes.

        A distance threshold is the wrong instrument. The exact property is: no cluster may
        contain a pair whose TRUE similarity is under the threshold. That is asserted here,
        on a corpus deliberately built to contain a chain.
        """
        texts, _ = self._corpus()
        sets = [blocking.shingles(t) for t in texts]
        out = pipeline.deduplicate(texts, threshold=0.7)
        for c in out["clusters"]:
            self.assertLess(clustering.max_intra_cluster_distance(c, sets), 0.45,
                            f"cluster {sorted(c)} looks chained")

        # A real chain, through the real pipeline. Jaccard distance is a metric, so
        # sim(A,B)=sim(B,C)=s forces sim(A,C) >= 2s-1: a chain only exists in a narrow band.
        # A and B differ in DISJOINT slices of a shared base, which is what holds A~B and
        # B~C above 0.7 while A~C sags below it. Measured: 0.802 / 0.789 / 0.624.
        base = [f"w{i:03}" for i in range(120)]
        d = 16
        chain = [" ".join([f"x{i}" for i in range(d)] + base[d:]),   # A
                 " ".join(base),                                     # B (the middle)
                 " ".join(base[:d] + [f"y{i}" for i in range(d)] + base[2 * d:])]  # C
        csets = [blocking.shingles(t) for t in chain]
        self.assertGreater(naive.jaccard(csets[0], csets[1]), 0.7, "A~B must be confirmable")
        self.assertGreater(naive.jaccard(csets[1], csets[2]), 0.7, "B~C must be confirmable")
        self.assertLess(naive.jaccard(csets[0], csets[2]), 0.7,
                        "A~C must be BELOW threshold or there is no chain to refuse")

        cout = pipeline.deduplicate(chain, threshold=0.7)
        self.assertEqual([sorted(c) for c in cout["clusters"]], [[0, 1]],
                         "the pipeline must refuse C: single-link would return [[0, 1, 2]]")
        for c in cout["clusters"]:
            for i in sorted(c):
                for j in sorted(c):
                    if i < j:
                        self.assertGreaterEqual(
                            naive.jaccard(csets[i], csets[j]), 0.7,
                            f"cluster {sorted(c)} contains pair ({i},{j}) below threshold -- "
                            f"this is chaining, and a distance bound of 0.45 does not see it")

    def test_empty_and_single_item_inputs_do_not_crash(self):
        for texts in ([], ["only one"]):
            out = pipeline.deduplicate(texts)
            self.assertEqual(out["clusters"], [])
            self.assertEqual(out["dropped"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
