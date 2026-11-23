"""Tests for PC-0003. Every measured value the card publishes is pinned here.

The card's numbers are only worth the tests behind them: `[executed]` has to mean "this
re-runs", not "it ran once while I was writing". Each test names the claim it defends.
"""
from __future__ import annotations

import unittest

from impl import handlers as H
from impl.delivery import Request, delivery_stream
from impl.store import (ASSIGN, INCREMENT, Clock, Store, distinct_keys,
                        expected_totals)

SEED = 20260906
N = 4000
ENTROPY = 10 ** 9


def stream(**kw):
    kw.setdefault("seed", SEED)
    kw.setdefault("p_ack_lost", 0.15)
    kw.setdefault("max_attempts", 4)
    kw.setdefault("amount_space", ENTROPY)
    return delivery_stream(kw.pop("n", N), **kw)


def run(s, handler, algebra, *, retry_gap=0, **kw):
    st = Store(algebra=algebra, clock=Clock())
    out = []
    for r in s.deliveries:
        if retry_gap and r.attempt > 1:
            st.clock.tick(retry_gap)
        out.append(handler(st, r, **kw))
    return st, out


def rows_wrong(st, s, algebra):
    exp = expected_totals(s, algebra)
    return sum(1 for k, v in exp.items() if st.total.get(k) != v)


class TestDeliveryStream(unittest.TestCase):
    def test_the_stream_is_reproducible_from_the_seed(self):
        """PC-0002 shipped non-reproducible vectors because builtins.hash is salted per
        process. A simulator whose numbers move between runs cannot pin a card."""
        a, b = stream(), stream()
        self.assertEqual([r.idem_key for r in a.deliveries],
                         [r.idem_key for r in b.deliveries])
        self.assertEqual([r.payload for r in a.deliveries],
                         [r.payload for r in b.deliveries])

    def test_C1_exact_stream_shape(self):
        s = stream()
        self.assertEqual(len(s.deliveries), 4667)
        self.assertEqual(s.n_logical, 4000)
        self.assertEqual(s.n_duplicate_deliveries, 667)
        self.assertAlmostEqual(s.duplicate_ratio, 0.1668, places=4)
        self.assertEqual(dict(sorted(s.attempts_histogram.items())),
                         {1: 3427, 2: 488, 3: 76, 4: 9})

    def test_C1_retried_operation_count(self):
        s = stream()
        retried = sum(v for k, v in s.attempts_histogram.items() if k >= 2)
        self.assertEqual(retried, 573)
        self.assertAlmostEqual(retried / N, 0.1432, places=4)

    def test_a_retry_reuses_the_token_and_a_new_operation_does_not(self):
        """If retries did not share a token, every shape here would be untestable."""
        s = stream()
        by_key = {}
        for r in s.deliveries:
            by_key.setdefault(r.idem_key, []).append(r)
        multi = [v for v in by_key.values() if len(v) > 1]
        self.assertTrue(multi)
        for group in multi:
            self.assertEqual(len({r.payload for r in group}), 1,
                             "a retry must carry the same payload")
            self.assertEqual([r.attempt for r in group], list(range(1, len(group) + 1)))

    def test_entropy_is_a_parameter_not_an_accident(self):
        """The first simulator drew amounts from 999 values and produced a 75% false-merge
        rate that described the fixture, not the technique."""
        low = stream(amount_space=1000)
        high = stream(amount_space=10 ** 9)
        n_low = len({r.payload for r in low.deliveries})
        n_high = len({r.payload for r in high.deliveries})
        self.assertLess(n_low, 1000)
        self.assertGreater(n_high, n_low * 3)


class TestEffectAlgebra(unittest.TestCase):
    def test_C2_the_same_duplicates_are_harmless_under_assign_and_corrupting_under_increment(self):
        s = stream()
        inc, _ = run(s, H.naive, INCREMENT)
        asg, _ = run(s, H.naive, ASSIGN)
        self.assertEqual(inc.duplicate_applications(), 667)
        self.assertEqual(asg.duplicate_applications(), 667,
                         "the same duplicates are applied in both cases")
        self.assertEqual(rows_wrong(inc, s, INCREMENT), 501)
        self.assertEqual(rows_wrong(asg, s, ASSIGN), 0,
                         "under assignment a naive handler is already correct")

    def test_C2_row_count(self):
        s = stream()
        self.assertEqual(len(set(r.logical_id for r in s.deliveries)), 1334)

    def test_A5_forcing_assignment_onto_increment_is_worse_than_doing_nothing(self):
        """The card's sharpest number: the cheap fix corrupts 2.66x more rows than no fix."""
        s = stream()
        naive, _ = run(s, H.naive, INCREMENT)
        forced, _ = run(s, H.natural_idempotent, INCREMENT)
        self.assertEqual(rows_wrong(naive, s, INCREMENT), 501)
        self.assertEqual(rows_wrong(forced, s, INCREMENT), 1333)
        self.assertGreater(rows_wrong(forced, s, INCREMENT),
                           rows_wrong(naive, s, INCREMENT))
        self.assertAlmostEqual(1333 / 501, 2.66, places=2)

    def test_A5_it_raises_nothing(self):
        """Silence is the whole hazard: a loud failure would not need a card."""
        s = stream(n=30)
        st, out = run(s, H.natural_idempotent, INCREMENT)
        self.assertTrue(all(r.status == "ok" for r in out))


class TestShapesAreCorrect(unittest.TestCase):
    def test_key_dedupe_is_correct_under_increment(self):
        s = stream()
        st, _ = run(s, H.key_dedupe, INCREMENT)
        self.assertEqual(st.duplicate_applications(), 0)
        self.assertEqual(st.lost_operations(distinct_keys(s)), 0)
        self.assertEqual(rows_wrong(st, s, INCREMENT), 0)

    def test_C3_conditional_write_is_correct_and_costs_no_durable_state(self):
        s = stream()
        st, out = run(s, H.conditional_write, INCREMENT, expected={})
        self.assertEqual(st.duplicate_applications(), 0)
        self.assertEqual(st.lost_operations(distinct_keys(s)), 0)
        self.assertEqual(rows_wrong(st, s, INCREMENT), 0)
        self.assertEqual(st.dedupe_writes, 0)

    def test_C3_cas_conflicts_equal_the_duplicate_deliveries_exactly(self):
        """Not approximately: every duplicate delivery is rejected and nothing else is."""
        s = stream()
        _, out = run(s, H.conditional_write, INCREMENT, expected={})
        self.assertEqual(sum(1 for r in out if r.status == "conflict"),
                         s.n_duplicate_deliveries)

    def test_C6_key_dedupe_costs_one_durable_row_per_operation(self):
        s = stream()
        st, _ = run(s, H.key_dedupe, INCREMENT)
        self.assertEqual(st.dedupe_writes, 4000)
        self.assertEqual(len(st.dedupe), 4000)

    def test_A6_under_assignment_the_dedupe_store_buys_nothing(self):
        s = stream()
        naive, _ = run(s, H.naive, ASSIGN)
        keyed, _ = run(s, H.key_dedupe, ASSIGN)
        self.assertEqual(rows_wrong(naive, s, ASSIGN), 0)
        self.assertEqual(rows_wrong(keyed, s, ASSIGN), 0)
        self.assertEqual(naive.dedupe_writes, 0)
        self.assertEqual(keyed.dedupe_writes, 4000)


class TestCrashOrdering(unittest.TestCase):
    """E3. The counts are exact because the crash is injected deterministically."""

    def _crash_run(self, fn):
        s = stream()
        from collections import Counter
        retried = {k for k, c in Counter(r.idem_key for r in s.deliveries).items() if c > 1}
        st = Store(algebra=INCREMENT, clock=Clock())
        for r in s.deliveries:
            try:
                fn(st, r, crash=(r.attempt == 1 and r.idem_key in retried))
            except H.Crash:
                pass
        return s, st

    def test_C3_key_first_loses_every_retried_operation(self):
        s, st = self._crash_run(H.key_then_effect)
        self.assertEqual(st.lost_operations(distinct_keys(s)), 573)
        self.assertEqual(st.duplicate_applications(), 0)
        self.assertEqual(rows_wrong(st, s, INCREMENT), 501)

    def test_C3_effect_first_duplicates_every_retried_operation(self):
        s, st = self._crash_run(H.effect_then_key)
        self.assertEqual(st.duplicate_applications(), 573)
        self.assertEqual(st.lost_operations(distinct_keys(s)), 0)
        self.assertEqual(rows_wrong(st, s, INCREMENT), 501)

    def test_C3_the_two_wrong_orderings_are_wrong_in_opposite_directions(self):
        """Equally wrong, oppositely wrong: 501 rows either way. Choosing between them by
        intuition is choosing which failure to have."""
        s1, a = self._crash_run(H.key_then_effect)
        s2, b = self._crash_run(H.effect_then_key)
        self.assertEqual(rows_wrong(a, s1, INCREMENT), rows_wrong(b, s2, INCREMENT))
        self.assertNotEqual(a.lost_operations(distinct_keys(s1)),
                            b.lost_operations(distinct_keys(s2)))

    def test_C3_a_resumable_reservation_needs_no_atomicity(self):
        """The finding that came from reading real code: atomicity is SUFFICIENT, not
        NECESSARY. A reservation that records whether it committed can be resumed."""
        s, st = self._crash_run(H.reserve_then_commit)
        self.assertEqual(st.lost_operations(distinct_keys(s)), 0)
        self.assertEqual(st.duplicate_applications(), 0)
        self.assertEqual(rows_wrong(st, s, INCREMENT), 0)

    def test_C3_atomic_is_also_correct(self):
        s, st = self._crash_run(H.atomic)
        self.assertEqual(st.lost_operations(distinct_keys(s)), 0)
        self.assertEqual(st.duplicate_applications(), 0)
        self.assertEqual(rows_wrong(st, s, INCREMENT), 0)

    def test_the_resumed_path_is_actually_taken(self):
        """Without this, the previous test could pass because the crash never fired."""
        st = Store(algebra=INCREMENT, clock=Clock())
        r1 = Request("row", "tok", (("amount", 5),), 1, 0)
        r2 = Request("row", "tok", (("amount", 5),), 2, 1)
        with self.assertRaises(H.Crash):
            H.reserve_then_commit(st, r1, crash=True)
        self.assertEqual(st.total.get("row"), None, "the effect must not have applied")
        out = H.reserve_then_commit(st, r2)
        self.assertEqual(out.status, "ok-resumed")
        self.assertEqual(st.total["row"], 5)


class TestTTL(unittest.TestCase):
    """E4. These treads size the TTL to cover the total retry window, and that is correct
    HERE because the fixture's store exposes the TTL as a free parameter.

    Scope, per card A4 SCOPED_by_fleet_grounding: this holds for HAND-ROLLED dedupe stores
    only. On a managed idempotency-token platform the dedupe window is a fixed constant the
    platform chooses (published windows span >2 orders of magnitude between services), so the
    caller cannot size the TTL at all and must instead size the RETRY WINDOW to fit inside it.
    Same constraint, opposite lever. A reader of these treads alone would carry the wrong
    direction to SQS FIFO or DynamoDB TransactWriteItems.
    """

    def _dup(self, ttl):
        s = stream()
        st, _ = run(s, H.key_dedupe, INCREMENT, retry_gap=20, ttl=ttl)
        return st.duplicate_applications(), s

    def test_C4_a_ttl_below_the_retry_interval_protects_nothing(self):
        dup, s = self._dup(20)
        self.assertEqual(dup, 667)
        self.assertAlmostEqual(dup / s.n_duplicate_deliveries, 1.0, places=4)

    def test_C4_the_staircase(self):
        """The card claims a staircase, not a decay. Each tread is pinned."""
        self.assertEqual(self._dup(21)[0], 85)
        self.assertEqual(self._dup(40)[0], 85)
        self.assertEqual(self._dup(41)[0], 9)
        self.assertEqual(self._dup(60)[0], 9)
        self.assertEqual(self._dup(61)[0], 0)

    def test_C4_the_breakpoint_is_the_total_window_not_the_interval(self):
        """Sizing the TTL to the 20-tick interval still re-executes 12.74% of duplicates."""
        dup21, s = self._dup(21)
        self.assertAlmostEqual(dup21 / s.n_duplicate_deliveries, 0.1274, places=4)
        self.assertEqual(self._dup(3 * 20 + 1)[0], 0)

    def test_an_expired_record_is_indistinguishable_from_never_seen(self):
        st = Store(clock=Clock())
        st.put_dedupe("k", (("amount", 1),), ttl=5)
        self.assertIsNotNone(st.get_dedupe("k"))
        st.clock.tick(5)
        self.assertIsNone(st.get_dedupe("k"))


class TestContentHash(unittest.TestCase):
    def test_C5_low_entropy_alone_causes_massive_false_merges(self):
        """0.7545 with ZERO legitimate duplicates: this is birthday collision, and the card
        must attribute it to entropy rather than to the technique in general."""
        s = stream(amount_space=1000, identical_payload_rate=0.0)
        st, _ = run(s, H.content_hash_dedupe, INCREMENT)
        k = distinct_keys(s)
        self.assertAlmostEqual(st.lost_operations(k) / len(k), 0.7545, places=4)

    def test_C5_scoping_to_the_row_almost_eliminates_the_entropy_cause(self):
        s = stream(amount_space=1000, identical_payload_rate=0.0)
        st, _ = run(s, H.content_hash_scoped, INCREMENT)
        k = distinct_keys(s)
        self.assertAlmostEqual(st.lost_operations(k) / len(k), 0.0003, places=4)

    def test_C5_high_entropy_with_no_legitimate_duplicates_is_clean(self):
        s = stream(amount_space=10 ** 9, identical_payload_rate=0.0)
        st, _ = run(s, H.content_hash_dedupe, INCREMENT)
        self.assertEqual(st.lost_operations(distinct_keys(s)), 0)

    def test_C5_scoping_does_not_fix_legitimate_duplicates(self):
        """The residual is the point: no function of the content can separate a retry from a
        genuine repeat, which is the whole argument for a client-supplied key."""
        s = stream(amount_space=10 ** 9, identical_payload_rate=0.25)
        un, _ = run(s, H.content_hash_dedupe, INCREMENT)
        sc, _ = run(s, H.content_hash_scoped, INCREMENT)
        k = distinct_keys(s)
        self.assertAlmostEqual(un.lost_operations(k) / len(k), 0.2420, places=4)
        self.assertAlmostEqual(sc.lost_operations(k) / len(k), 0.0570, places=4)
        self.assertGreater(sc.lost_operations(k), 0)


class TestResponseCaching(unittest.TestCase):
    def test_A3_storing_the_key_without_the_response_breaks_every_replay(self):
        s = stream()
        st, out = run(s, H.key_dedupe, INCREMENT, cache_response=False)
        nobody = [r for r in out if r.status == "duplicate-no-body"]
        self.assertEqual(len(nobody), 667)
        self.assertEqual(len(nobody), s.n_duplicate_deliveries)

    def test_A3_and_the_business_state_stays_correct_so_no_data_alarm_fires(self):
        """This is why it survives in production: the data is right and the API is wrong."""
        s = stream()
        st, _ = run(s, H.key_dedupe, INCREMENT, cache_response=False)
        self.assertEqual(rows_wrong(st, s, INCREMENT), 0)

    def test_caching_the_response_returns_the_original_body(self):
        s = stream()
        _, out = run(s, H.key_dedupe, INCREMENT, cache_response=True)
        replayed = [r for r in out if r.status == "ok-replayed"]
        self.assertEqual(len(replayed), 667)
        self.assertTrue(all(r.body is not None for r in replayed))


class TestReusedToken(unittest.TestCase):
    """C7 / A7. The failure no content-based shape can see."""

    def _pair(self):
        return [Request("order-9", "tok-1", (("amount", 100), ("currency", "USD")), 1, 0),
                Request("order-9", "tok-1", (("amount", 250), ("currency", "USD")), 1, 1)]

    def test_C7_plain_key_dedupe_answers_the_wrong_request_with_a_stale_success(self):
        st = Store(algebra=INCREMENT, clock=Clock())
        out = [H.key_dedupe(st, r) for r in self._pair()]
        self.assertEqual(out[1].status, "ok-replayed")
        self.assertEqual(dict(out[1].body)["amount"], 100,
                         "the SECOND request asked for 250 and was told 100 succeeded")
        self.assertEqual(st.total["order-9"], 100)

    def test_C7_the_reservation_rejects_it(self):
        st = Store(algebra=INCREMENT, clock=Clock())
        out = [H.reserve_then_commit(st, r) for r in self._pair()]
        self.assertEqual(out[1].status, "key-reuse-rejected")
        self.assertIsNone(out[1].body)
        self.assertEqual(st.total["order-9"], 100)

    def test_a_genuine_retry_is_still_replayed_not_rejected(self):
        """A reuse check that rejected honest retries would break the primary purpose."""
        st = Store(algebra=INCREMENT, clock=Clock())
        r = Request("order-9", "tok-1", (("amount", 100),), 1, 0)
        again = Request("order-9", "tok-1", (("amount", 100),), 2, 1)
        H.reserve_then_commit(st, r)
        out = H.reserve_then_commit(st, again)
        self.assertEqual(out.status, "ok-replayed")
        self.assertEqual(st.applications["tok-1"], 1)


class TestExpectedTotals(unittest.TestCase):
    def test_expected_totals_defines_exactly_once_as_an_outcome(self):
        s = stream(n=12)
        exp = expected_totals(s, INCREMENT)
        manual: dict[str, int] = {}
        seen = set()
        for r in s.deliveries:
            if r.idem_key in seen:
                continue
            seen.add(r.idem_key)
            manual[r.logical_id] = manual.get(r.logical_id, 0) + r.amount
        self.assertEqual(exp, manual)

    def test_the_oracle_is_not_trivially_equal_to_the_naive_result(self):
        """If the oracle matched the naive handler, every correctness test would be vacuous."""
        s = stream()
        st, _ = run(s, H.naive, INCREMENT)
        self.assertNotEqual(st.total, expected_totals(s, INCREMENT))


if __name__ == "__main__":
    unittest.main()
