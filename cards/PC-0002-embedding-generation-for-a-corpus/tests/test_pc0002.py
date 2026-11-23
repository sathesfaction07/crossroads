"""PC-0002 — every number the card publishes, pinned to an actual run.

Two claims in this suite exist because EXECUTING FALSIFIED THE PLANNED CLAIM:

  * `test_zero_pad_unmasked_pooling_is_direction_preserving` — the card was going to say
    that unmasked mean pooling corrupts embeddings. Over ZERO padding it does not: it
    rescales by exactly the fill ratio and changes no cosine ranking whatsoever.
  * `test_bucketing_gain_is_not_monotonic_in_batch_size` — the gain peaks and then falls.
    Measuring only one batch size would have produced a confident, wrong recommendation.

Stdlib only. numpy/torch/transformers are importable in this environment and deliberately
unused, so `[executed]` means "runs wherever the gate runs".
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from impl import (chunking, corpus, identity, metric,  # noqa: E402
                  pipeline, pooling, throughput)

CORPUS = corpus.synthetic_corpus(2000)
SLICE200 = CORPUS[:200]
LENS = corpus.token_lengths(CORPUS)
CFG = {"model": "e5-base", "revision": "r1", "pooling": "masked-mean",
       "window": 512, "overlap": 32, "normalize": True, "dim": 768}


def _scaled_vectors():
    """Vectors with a wide norm spread -- the precondition for dot/cosine disagreement."""
    rng = random.Random(5)
    vecs = [[rng.gauss(0.3, 1) for _ in range(16)] for _ in range(60)]
    scaled = [[x * (1 + i * 0.35) for x in v] for i, v in enumerate(vecs)]
    queries = [[rng.gauss(0.3, 1) for _ in range(16)] for _ in range(200)]
    return vecs, scaled, queries


class TestCorpus(unittest.TestCase):
    def test_the_corpus_is_right_skewed_which_is_what_drives_every_cost_result(self):
        p = corpus.length_profile(CORPUS)
        self.assertEqual(p["n"], 2000)
        self.assertEqual(p["total_tokens"], 551579)
        self.assertEqual((p["p50"], p["p90"], p["p99"], p["max"]), (182, 616, 1390, 3291))
        self.assertGreater(p["mean"], p["p50"], "mean above median == right skew")

    def test_the_corpus_is_deterministic_so_every_published_number_is_reproducible(self):
        self.assertEqual(corpus.token_lengths(corpus.synthetic_corpus(50, seed=1)),
                         corpus.token_lengths(corpus.synthetic_corpus(50, seed=1)))


class TestTruncation(unittest.TestCase):
    def test_all_four_published_windows_are_measured(self):
        """The card recommends thinking in terms of these four windows, so all four carry a
        measurement -- no subset generalised across the set."""
        expected = {256: (0.3485, 0.3728), 512: (0.1405, 0.1634),
                    1024: (0.0270, 0.0368), 2048: (0.0015, 0.0036)}
        for window, (docs_over, tokens_lost) in expected.items():
            r = chunking.truncation_loss(CORPUS, window)
            self.assertAlmostEqual(r["docs_over"], docs_over, places=4, msg=f"w={window}")
            self.assertAlmostEqual(r["tokens_lost"], tokens_lost, places=4, msg=f"w={window}")

    def test_documents_affected_understates_content_lost(self):
        """The two numbers diverge, and `docs_over` is the smaller one at every window --
        so quoting it is the flattering choice. At w=512: 14.1% of documents, 16.3% of
        tokens."""
        for window in (256, 512, 1024, 2048):
            r = chunking.truncation_loss(CORPUS, window)
            self.assertLess(r["docs_over"], r["tokens_lost"], f"w={window}")

    def test_truncation_loss_falls_monotonically_as_the_window_grows(self):
        losses = [chunking.truncation_loss(CORPUS, w)["tokens_lost"]
                  for w in (256, 512, 1024, 2048)]
        self.assertEqual(losses, sorted(losses, reverse=True))


class TestChunking(unittest.TestCase):
    def test_overlap_of_k_minus_one_preserves_every_k_gram_exactly(self):
        """Not a heuristic -- an exact threshold. A k-gram is destroyed only if every chunk
        boundary cuts it, so overlap >= k-1 is sufficient, and 1.0 is reached AT k-1."""
        k = 8
        self.assertEqual(chunking.corpus_ngram_recall(SLICE200, 512, k - 1, k), 1.0)
        self.assertEqual(chunking.corpus_ngram_recall(SLICE200, 512, k, k), 1.0)
        self.assertLess(chunking.corpus_ngram_recall(SLICE200, 512, k - 2, k), 1.0)

    def test_all_published_overlaps_are_measured(self):
        expected = {0: 0.996384, 4: 0.998450, 7: 1.0, 8: 1.0, 16: 1.0, 32: 1.0}
        for overlap, recall in expected.items():
            self.assertAlmostEqual(
                chunking.corpus_ngram_recall(SLICE200, 512, overlap, 8), recall, places=6,
                msg=f"overlap={overlap}")

    def test_overlap_costs_tokens_not_chunks(self):
        """Chunk COUNT nearly fooled this card: at window=512 the counts for overlap 0 and
        32 are identical on this corpus, which reads as 'overlap is free'. Tokens sent is
        the honest measure."""
        self.assertEqual(chunking.chunks_per_corpus(SLICE200, 512, 0),
                         chunking.chunks_per_corpus(SLICE200, 512, 32))
        expected = {0: 0.0, 8: 0.0051, 32: 0.0213, 64: 0.0439, 128: 0.0949}
        for overlap, overhead in expected.items():
            self.assertAlmostEqual(chunking.chunk_token_cost(CORPUS, 512, overlap)["overhead"],
                                   overhead, places=4, msg=f"overlap={overlap}")

    def test_the_cheapest_sufficient_overlap_beats_the_usual_advice(self):
        """overlap=7 preserves every 8-gram for 0.51% extra tokens. The common '10-20% of
        the window' rule means overlap 51-102 here, costing 4-9% -- 7-18x the price for no
        additional phrase preservation."""
        cheap = chunking.chunk_token_cost(CORPUS, 512, 7)["overhead"]
        usual = chunking.chunk_token_cost(CORPUS, 512, 64)["overhead"]
        self.assertEqual(chunking.corpus_ngram_recall(SLICE200, 512, 7, 8), 1.0)
        self.assertEqual(chunking.corpus_ngram_recall(SLICE200, 512, 64, 8), 1.0)
        self.assertGreater(usual / cheap, 7.0)

    def test_an_overlap_at_or_above_the_window_is_rejected_not_hung(self):
        with self.assertRaises(ValueError):
            chunking.chunk_spans(100, 10, 10)
        with self.assertRaises(ValueError):
            chunking.chunk_spans(100, 10, 11)

    def test_spans_cover_the_whole_document(self):
        for length in (1, 7, 512, 513, 3291):
            spans = chunking.chunk_spans(length, 512, 32)
            self.assertEqual(spans[0][0], 0)
            self.assertEqual(spans[-1][1], length)


class TestChunksPerDocSampleSize(unittest.TestCase):
    """Added because a CONSUMER refused to plan capacity on the published figure.

    SC-01 declined to size a 4M-ticket job on `chunks/doc = 1.07`, on the grounds that it
    was measured on a 30-document fixture while every other number in the card came from the
    2000-document corpus. It was right, and the error is material: the 30-doc sample
    understates forward passes by 11%.
    """

    def test_the_30_doc_fixture_understates_chunks_per_doc_by_11_percent(self):
        small = chunking.chunks_per_corpus(corpus.synthetic_corpus(30, seed=99), 512, 32) / 30
        full = chunking.chunks_per_corpus(CORPUS, 512, 32) / 2000
        self.assertAlmostEqual(small, 1.0667, places=4)
        self.assertAlmostEqual(full, 1.1840, places=4)
        self.assertGreater(full / small - 1, 0.10, "the understatement is material, not noise")

    def test_the_30_doc_sample_is_the_outlier_and_the_estimate_converges(self):
        """1.067 -> 1.120 -> 1.196 -> 1.184. The published figure was the low tail of a
        small sample, not a stable estimate."""
        got = [round(chunking.chunks_per_corpus(corpus.synthetic_corpus(n, seed=s), 512, 32) / n, 4)
               for n, s in ((30, 99), (100, 99), (500, 20260906), (2000, 20260906))]
        self.assertEqual(got, [1.0667, 1.1200, 1.1960, 1.1840])
        self.assertEqual(min(got), got[0], "the 30-doc figure is the lowest of the four")

    def test_chunks_per_doc_is_a_curve_in_the_window_not_a_constant(self):
        """Publishing one value would flatten a 1.6x range into a point -- the same failure
        the card documents for C3. All three windows the card discusses are measured."""
        expected = {256: 1.6485, 512: 1.1840, 1024: 1.0290}
        for window, per_doc in expected.items():
            self.assertAlmostEqual(chunking.chunks_per_corpus(CORPUS, window, 32) / 2000,
                                   per_doc, places=4, msg=f"window={window}")


class TestPoolingTheFalsifiedClaim(unittest.TestCase):
    """The card's planned A2 was wrong, and the measurement is why it is now conditional."""

    def test_zero_pad_unmasked_pooling_is_direction_preserving(self):
        """FALSIFIED THE PLANNED CLAIM. Over zero padding, unmasked mean pooling is a pure
        SCALAR multiple of the correct vector: cosine is exactly 1.0 at every occupancy, and
        the norm ratio equals the fill ratio exactly. Cosine retrieval is therefore
        completely unharmed."""
        for true_len in (512, 256, 128, 64, 32, 16):
            r = pooling.pad_contamination(true_len, 512, dim=64, pad_value=0.0)
            self.assertAlmostEqual(r["cosine_correct_vs_buggy"], 1.0, places=12,
                                   msg=f"fill={r['fill_ratio']}")
            self.assertAlmostEqual(r["norm_ratio_buggy_over_correct"], r["fill_ratio"],
                                   places=12, msg="norm ratio IS the fill ratio")

    def test_zero_pad_changes_no_cosine_ranking_at_all(self):
        r = pooling.contamination_changes_ranking([16, 32, 64, 128, 256, 512] * 8, 512,
                                                  dim=32)
        self.assertEqual(r["nearest_neighbour_changed"], 0)

    def test_but_a_non_zero_pad_vector_genuinely_corrupts_direction(self):
        """Real encoders emit non-zero values at pad positions unless attention is masked.
        Then the bug is real: cosine falls to 0.92 at 1/16 occupancy."""
        expected = {256: 0.996270, 128: 0.980156, 64: 0.952602, 32: 0.916795}
        for true_len, cos in expected.items():
            r = pooling.pad_contamination(true_len, 512, dim=64, pad_value=0.35)
            self.assertAlmostEqual(r["cosine_correct_vs_buggy"], cos, places=6,
                                   msg=f"true_len={true_len}")

    def test_non_zero_pad_degrades_monotonically_as_occupancy_falls(self):
        cosines = [pooling.pad_contamination(n, 512, dim=64, pad_value=0.35)
                   ["cosine_correct_vs_buggy"] for n in (512, 256, 128, 64, 32)]
        self.assertEqual(cosines, sorted(cosines, reverse=True))

    def test_non_zero_pad_reorders_almost_every_neighbour(self):
        """91.7% of documents get a different nearest neighbour -- the number that makes
        this a retrieval defect rather than a numerical curiosity."""
        lens = [16, 32, 64, 128, 256, 512] * 8
        correct, buggy = [], []
        for i, n in enumerate(lens):
            real = pooling.synthetic_token_vectors(n, 32, 11 + i, 0.35)
            rows = real + [[0.35] * 32] * (512 - n)
            mask = [1] * n + [0] * (512 - n)
            correct.append(pooling.mean_pool(rows, mask))
            buggy.append(pooling.mean_pool(rows, None))
        changed = 0
        for i in range(len(correct)):
            others = [j for j in range(len(correct)) if j != i]
            a = max(others, key=lambda j: metric.cosine(correct[i], correct[j]))
            b = max(others, key=lambda j: metric.cosine(buggy[i], buggy[j]))
            changed += (a != b)
        self.assertAlmostEqual(changed / len(lens), 44 / 48, places=6)


class TestPoolingContracts(unittest.TestCase):
    def test_masked_pooling_equals_the_mean_of_the_real_rows_only(self):
        rows = [[1.0, 2.0], [3.0, 4.0], [99.0, 99.0]]
        self.assertEqual(pooling.mean_pool(rows, [1, 1, 0]), [2.0, 3.0])

    def test_pooling_rejects_the_shapes_that_produce_silent_nonsense(self):
        with self.assertRaises(ValueError):
            pooling.mean_pool([])
        with self.assertRaises(ValueError):
            pooling.mean_pool([[1.0]], [1, 1])
        with self.assertRaises(ValueError):
            pooling.mean_pool([[1.0], [2.0]], [0, 0])


class TestMetric(unittest.TestCase):
    def test_after_normalising_dot_is_cosine_to_floating_point_noise(self):
        vecs, _, _ = _scaled_vectors()
        self.assertLess(metric.cosine_equals_dot_after_normalising(vecs[:25]), 1e-15)

    def test_unnormalised_dot_and_cosine_disagree_on_most_queries(self):
        """69.5% of queries get a different top-1 result, at a 29x norm spread. 'Cosine and
        dot are basically the same' is true only for unit vectors."""
        _, scaled, queries = _scaled_vectors()
        spread = metric.norm_spread(scaled)
        self.assertAlmostEqual(spread["ratio"], 29.448, places=3)
        r = metric.ranking_flip_rate(scaled, queries)
        self.assertAlmostEqual(r["flip_rate"], 0.695, places=3)

    def test_normalising_first_removes_the_disagreement_entirely(self):
        _, scaled, queries = _scaled_vectors()
        unit = [metric.l2_normalize(v) for v in scaled]
        self.assertEqual(metric.ranking_flip_rate(unit, queries)["flips"], 0)

    def test_a_zero_vector_is_rejected_rather_than_producing_a_nan(self):
        with self.assertRaises(ValueError):
            metric.l2_normalize([0.0, 0.0])

    def test_dimension_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            metric.dot([1.0], [1.0, 2.0])


class TestThroughput(unittest.TestCase):
    def test_all_four_published_batch_sizes_are_measured(self):
        expected = {8: (0.6359, 0.0278, 2.6704), 32: (0.7696, 0.0784, 4.0009),
                    128: (0.8411, 0.2914, 4.4595), 512: (0.8909, 0.7037, 2.7172)}
        for bs, (arrival, bucketed, reduction) in expected.items():
            g = throughput.bucketing_gain(LENS, bs)
            self.assertAlmostEqual(g["arrival_wasted_fraction"], arrival, places=4, msg=f"bs={bs}")
            self.assertAlmostEqual(g["bucketed_wasted_fraction"], bucketed, places=4, msg=f"bs={bs}")
            self.assertAlmostEqual(g["slot_reduction"], reduction, places=3, msg=f"bs={bs}")

    def test_bucketing_gain_is_not_monotonic_in_batch_size(self):
        """FALSIFIED THE PLANNED CLAIM. The gain PEAKS at batch size 128 (4.46x) and falls
        to 2.72x at 512, because a bucketed batch that large again spans a wide length
        range. Measuring one batch size would have produced 'bucketing gives 4x, so batch
        as large as you can' -- confident and wrong."""
        gains = {bs: throughput.bucketing_gain(LENS, bs)["slot_reduction"]
                 for bs in (8, 32, 128, 512)}
        self.assertEqual(max(gains, key=gains.get), 128)
        self.assertLess(gains[512], gains[128])
        self.assertLess(gains[512], gains[32])

    def test_bucketing_never_costs_more_slots_than_arrival_order(self):
        for bs in (1, 8, 32, 128, 512, 2048):
            g = throughput.bucketing_gain(LENS, bs)
            self.assertGreaterEqual(g["slot_reduction"], 1.0, f"bs={bs}")

    def test_the_gain_collapses_to_exactly_one_once_a_batch_holds_the_whole_corpus(self):
        """The far end of the C3 curve is an identity, not a measurement.

        Once batch_size >= len(lengths) there is a single batch, and its max is the same under
        every ordering, so bucketing cannot save a single slot. Pinned as EXACT equality rather
        than the >= 1.0 the neighbouring test asserts, because this endpoint is the one point on
        the curve that transfers to any corpus whatsoever -- and because a docstring in
        throughput.py now states it as an identity, which nothing was checking.
        """
        for bs in (len(LENS), len(LENS) + 1, len(LENS) * 3):
            g = throughput.bucketing_gain(LENS, bs)
            self.assertEqual(g["slot_reduction"], 1.0, f"bs={bs}")
            self.assertEqual(g["arrival_slots"], g["bucketed_slots"], f"bs={bs}")
            self.assertEqual(g["arrival_slots"], max(LENS) * len(LENS), f"bs={bs}")

    def test_the_permutation_round_trips_or_every_vector_is_misattributed(self):
        lens = [5, 1, 9, 3]
        _, order = throughput.bucketed_with_restore(lens, 2)
        self.assertEqual(throughput.restore([lens[i] for i in order], order), lens)

    def test_restoring_with_a_mismatched_permutation_is_rejected(self):
        with self.assertRaises(ValueError):
            throughput.restore([1, 2], [0, 1, 2])


class TestIdentity(unittest.TestCase):
    def test_a_text_only_cache_key_serves_stale_vectors_for_every_document(self):
        r = identity.stale_serve_rate(CORPUS[:500], CFG, dict(CFG, revision="r2"),
                                      identity.text_only_key)
        self.assertEqual(r["stale_serve_rate"], 1.0)

    def test_the_full_identity_key_serves_none(self):
        r = identity.stale_serve_rate(CORPUS[:500], CFG, dict(CFG, revision="r2"))
        self.assertEqual(r["stale_serve_rate"], 0.0)

    def test_omitting_any_identity_field_gives_a_total_stale_serve_rate(self):
        """Uniform across all seven fields: there is no subset you can safely drop. The
        fields that look harmless are the ones you have not changed yet."""
        sens = identity.field_sensitivity(CORPUS[:500], CFG)
        self.assertEqual(set(sens), set(identity.IDENTITY_FIELDS))
        for field, rate in sens.items():
            self.assertEqual(rate, 1.0, f"omitting {field} must go 100% stale")

    def test_a_config_field_outside_the_identity_is_rejected_not_ignored(self):
        with self.assertRaises(ValueError):
            identity.canonical_config(dict(CFG, temperature=0.7))

    def test_key_is_stable_under_dict_ordering(self):
        a = identity.embedding_key("x", {k: CFG[k] for k in sorted(CFG)})
        b = identity.embedding_key("x", {k: CFG[k] for k in reversed(sorted(CFG))})
        self.assertEqual(a, b)


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.small = corpus.synthetic_corpus(30, seed=99)
        self.cfg = dict(pipeline.DEFAULT_CFG, dim=16)

    def test_shape_a_end_to_end_matches_the_published_stats(self):
        _, st = pipeline.embed_corpus(self.small, self.cfg, batch_size=16)
        self.assertEqual(st["documents"], 30)
        self.assertEqual(st["chunks"], 32)
        self.assertEqual(st["paid_slots"], 10592)
        self.assertEqual(st["useful_tokens"], 6863)
        self.assertAlmostEqual(st["wasted_fraction"], 0.3521, places=4)
        self.assertEqual((st["cache_hits"], st["cache_misses"]), (0, 32))

    def test_every_output_vector_is_unit_norm(self):
        vecs, _ = pipeline.embed_corpus(self.small, self.cfg, batch_size=16)
        for v in vecs:
            self.assertAlmostEqual(metric.l2_norm(v), 1.0, places=12)

    def test_output_is_in_input_order_not_bucketed_order(self):
        """The guarantee that bucketing would silently break. Two documents whose lengths
        force different buckets must still come back in the order they were passed in."""
        docs = [" ".join(f"a{i}" for i in range(600)), "b b b", " ".join(f"c{i}" for i in range(200))]
        vecs, _ = pipeline.embed_corpus(docs, self.cfg, batch_size=2)
        solo = [pipeline.embed_corpus([d], self.cfg, batch_size=1)[0][0] for d in docs]
        for i, (got, want) in enumerate(zip(vecs, solo)):
            self.assertAlmostEqual(metric.cosine(got, want), 1.0, places=9, msg=f"doc {i}")

    def test_a_warm_cache_turns_every_chunk_into_a_hit(self):
        cache: dict = {}
        pipeline.embed_corpus(self.small, self.cfg, batch_size=16, cache=cache)
        _, st = pipeline.embed_corpus(self.small, self.cfg, batch_size=16, cache=cache)
        self.assertEqual(st["cache_misses"], 0)
        self.assertEqual(st["cache_hits"], 32)

    def test_a_changed_config_invalidates_the_cache_instead_of_serving_stale(self):
        cache: dict = {}
        pipeline.embed_corpus(self.small, self.cfg, batch_size=16, cache=cache)
        _, st = pipeline.embed_corpus(self.small, dict(self.cfg, revision="next"),
                                      batch_size=16, cache=cache)
        self.assertEqual(st["cache_hits"], 0)

    def test_vectors_are_identical_across_SEPARATE_PROCESSES(self):
        """Guards a bug that was live in this module: `builtins.hash` on str is salted per
        process, so the first version produced different vectors on every run. A same-process
        equality check passes happily; only a second interpreter catches it."""
        script = (
            "import sys,json,hashlib;sys.path.insert(0,%r);"
            "from impl import corpus,pipeline;"
            "c=corpus.synthetic_corpus(8,seed=99);"
            "cfg=dict(pipeline.DEFAULT_CFG,dim=8);"
            "v,_=pipeline.embed_corpus(c,cfg,batch_size=4);"
            "print(hashlib.sha256(json.dumps(v).encode()).hexdigest())"
            % os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        outs = {subprocess.run([sys.executable, "-c", script], capture_output=True,
                               text=True, check=True).stdout.strip() for _ in range(2)}
        self.assertEqual(len(outs), 1, f"non-reproducible across processes: {outs}")


class TestTokenizerProxyIsVisible(unittest.TestCase):
    """PC-0002's equivalent of PC-0001's test_selection_agrees_with_real_datasketch.

    The card is validated entirely against a WORD-count proxy. Nothing in impl/ or tests/
    imported a real tokenizer, so the substitution was invisible from inside the package --
    the same closed loop that let PC-0001 ship a retracted claim under 34 green tests.
    """

    def test_tokenize_is_words_not_tokens(self):
        """Pin the proxy so it cannot be mistaken for real tokenisation."""
        self.assertEqual(chunking.tokenize("hello world foo"), ["hello", "world", "foo"])
        self.assertEqual(len(chunking.tokenize("un-be-liev-able")), 1,
                         "a real subword tokenizer would split this; text.split() does not")

    def test_word_window_and_token_window_are_different_operating_points(self):
        """The claim the old docstring denied: ratios are NOT invariant to rescaling.

        The window is a fixed model constant, so it does not scale with the subword factor.
        Measuring at 512 WORDS is not measuring at 512 TOKENS.
        """
        docs = corpus.synthetic_corpus()
        lens = corpus.token_lengths(docs)

        def over_and_lost(window):
            over = sum(1 for x in lens if x > window) / len(lens)
            lost = sum(max(x - window, 0) for x in lens) / sum(lens)
            return over, lost

        o512, l512 = over_and_lost(512)
        o379, l379 = over_and_lost(379)          # 512 tokens at k=1.35
        self.assertAlmostEqual(o512, 0.1405, places=4, msg="the card's published docs_over")
        self.assertAlmostEqual(l512, 0.1634, places=4, msg="the card's published tokens_lost")
        self.assertGreater(o379, o512 * 1.4,
                           "the true operating point is materially worse; the published "
                           "figures are a LOWER BOUND, not the answer")
        self.assertGreater(l379, l512 * 1.4)

    def test_fixture_subword_factor_against_a_real_tokenizer(self):
        """Makes the fixture's unrealism measurable instead of assumed.

        Skipped rather than silently passed when transformers is unavailable, so an absent
        library can never look like a passing check.
        """
        try:
            from transformers import AutoTokenizer
        except ImportError:
            self.skipTest("transformers not installed; cannot cross-check the proxy")
        try:
            tok = AutoTokenizer.from_pretrained("bert-base-uncased")
        except Exception as exc:                                     # offline, rate-limited
            self.skipTest(f"tokenizer unavailable: {type(exc).__name__}")
        docs = corpus.synthetic_corpus()[:120]
        words = [len(d.split()) for d in docs]
        toks = [len(tok.encode(d, add_special_tokens=False, truncation=False)) for d in docs]
        k = sum(toks) / sum(words)
        # This fixture is synthetic and fragments heavily: k is ~5.6, NOT the 1.2-1.5 of
        # English prose. Pinned loosely so the point survives tokenizer version drift.
        self.assertGreater(k, 3.0,
                           "if k ever approaches 1.3 the fixture has become prose-like and "
                           "the card's word-level figures may be quoted as token figures")
        per = [t / w for t, w in zip(toks, words)]
        self.assertGreater(max(per) - min(per), 1.0,
                           "k is NOT uniform across documents, so the old docstring's "
                           "'roughly uniform rescaling' premise fails on its own terms")


if __name__ == "__main__":
    unittest.main()
