#!/usr/bin/env python3
"""Tests for PC-0005. Every test names the claim in CARD.md it makes falsifiable.

Structure follows the rest of the portfolio: exact invariants first (they cannot be satisfied by
luck), then the stochastic headline numbers pinned with a tolerance derived from their MEASURED
standard error, then a regression for each defect found while authoring.

Six defects were found before any prose was written. Four have a regression test here; the other
two were fixture-regime problems that the powered experiments now encode structurally.

Run:  python3 -m unittest discover -s tests -t .
"""
from __future__ import annotations

import unittest

from impl import alarms as A
from impl import measure as M
from impl.attention import Attention, run, weekly_load


class TestTriageCurveInvariants(unittest.TestCase):
    """Exact properties of the fatigue model. These hold for ANY parameters, so they test the
    model's shape rather than the particular (capacity, k, floor) the card happens to use --
    the distinction between a property and an artifact."""

    PARAMS = [(2.0, 1.0, 0.05), (5.0, 2.0, 0.15), (10.0, 4.0, 0.40), (50.0, 1.0, 0.01)]

    def test_zero_load_is_certainty(self):
        for cap, k, floor in self.PARAMS:
            self.assertEqual(Attention(cap, k, floor).triage_probability(0), 1.0)

    def test_floor_is_never_breached(self):
        """A buried responder still catches something. Without a floor the model would predict
        total blindness, which is both false and would make every high-volume claim unfalsifiable."""
        for cap, k, floor in self.PARAMS:
            att = Attention(cap, k, floor)
            for load in (0.1, 1, 5, 20, 100, 10_000):
                self.assertGreaterEqual(att.triage_probability(load), floor,
                                        f"cap={cap} k={k} floor={floor} load={load}")

    def test_monotone_decreasing_in_load(self):
        for cap, k, floor in self.PARAMS:
            att = Attention(cap, k, floor)
            probs = [att.triage_probability(x) for x in (0, 1, 2, 5, 10, 20, 50, 200)]
            self.assertEqual(probs, sorted(probs, reverse=True), f"cap={cap} k={k}")

    def test_capacity_is_the_halfway_point_to_the_floor(self):
        """The one thing `capacity` is DEFINED as. If this drifts, every breakpoint the card
        states in pages/week silently means something else."""
        for cap, k, floor in self.PARAMS:
            att = Attention(cap, k, floor)
            self.assertAlmostEqual(att.triage_probability(cap), floor + (1 - floor) / 2,
                                   places=9, msg=f"cap={cap}")


class TestAccountingInvariants(unittest.TestCase):
    """Exact book-keeping. The defect that made `acted_fraction` rise with redundant alarms
    lived here, so these are the highest-value tests in the file."""

    @staticmethod
    def _alarm(name, **kw):
        kw.setdefault("recall", 1.0)
        kw.setdefault("covers", frozenset({"m"}))
        kw.setdefault("benign_rate_per_week", 0.0)
        return A.Alarm(name, **kw)

    def test_dedupe_collapses_one_alarm_week_to_one_page(self):
        f = [A.Firing(0, "a", True, 0), A.Firing(0, "a", True, 1), A.Firing(1, "a", True, 2)]
        self.assertEqual(len(A.dedupe(f)), 2, "two distinct (alarm, week) keys")

    def test_one_page_resolves_every_incident_that_alarm_saw_that_week(self):
        """REGRESSION for the attribution defect.

        `outcome()` counted LOAD from the de-duplicated page list and then credited `acted_on`
        to the single incident attached to the surviving firing. Dedupe is keyed (alarm, week),
        so the second incident in a week lost its only detection -- and N correlated alarms
        produced N dedupe keys, hence N independent chances to act. `acted_fraction` ROSE
        0.537 -> 0.870 across 1..6 alarms on ONE failure mode, which reads as 'redundancy helps'
        and was pure book-keeping.

        Two incidents, one alarm, one week, infinite capacity: BOTH must be resolved by the
        single page. Under the old code exactly one was.
        """
        alarms = [self._alarm("a")]
        incs = [A.Incident(0, "m"), A.Incident(0, "m")]
        real = [A.Firing(0, "a", True, 0), A.Firing(0, "a", True, 1)]
        pages = A.dedupe(real)
        self.assertEqual(len(pages), 1, "the responder is woken once")
        from impl.attention import outcome
        out = outcome(alarms, incs, pages, real, Attention(capacity=1e9), seed=1)
        self.assertEqual(out["acted_on"], 2,
                         "one page must resolve both incidents it saw, not one")
        self.assertEqual(out["pages_total"], 1, "and it is still only ONE interruption")

    def test_load_counts_benign_pages_but_attribution_does_not(self):
        """The mechanism, asserted rather than trusted: benign pages raise LOAD and can never
        resolve anything. If these two were ever read from the same list the card's entire
        argument would be circular."""
        alarms = [self._alarm("a", benign_rate_per_week=0.0)]
        incs = [A.Incident(0, "m")]
        real = [A.Firing(0, "a", True, 0)]
        pages = real + [A.Firing(0, "b", False, None)]
        self.assertEqual(weekly_load(pages)[0], 2, "both pages consume attention")
        self.assertEqual(sum(1 for f in pages if f.real), 1, "only one can resolve anything")

    def test_infinite_capacity_makes_handling_equal_detection(self):
        """The upper bound -- but ONLY with suppression off, and finding out why was a result.

        This test was written asserting acted == detected at infinite capacity and it FAILED:
        0.9444 against 0.9630, a gap of one incident. The premise was wrong, not the code.
        With suppression enabled an incident can be detected and never paged, because its only
        alarm was the CHILD and the PARENT happened to fire that week for an UNRELATED incident.
        Suppression is week-granular, so it mutes across incidents.

        With suppression off the invariant is exact, across every seed tried. So any gap here is
        attributable to attention or to suppression, and to nothing else.
        """
        att = Attention(capacity=1e9, floor=1.0)
        r = run(list(M.BASELINE), att=att, seed=17, use_suppression=False)
        self.assertAlmostEqual(r["acted_fraction"], r["detected_fraction"], places=9)

    def test_suppression_costs_HANDLING_even_though_detection_is_unchanged(self):
        """C6. The claim that survived two corrections, and the one an operator can act on.

        First I nearly published 'suppression buys quiet at detection cost 0.000' as a
        measurement. It is a tautology: `fire()` records detection before `suppress()` runs, so
        detected_fraction cannot move.

        Then this test found the real cost. Detection is genuinely unchanged -- and HANDLING is
        not: at infinite capacity, where nothing is lost to fatigue, week-granular suppression
        still loses a mean 1.2% of incidents (max 5.9% over 30 seeds), because the muted child
        was sometimes the incident's ONLY page.

        So the cost of suppression is invisible in the metric everyone reports and real in the
        metric that matters. That is the card's claim, not the zero.
        """
        att = Attention(capacity=1e9, floor=1.0)
        on_gaps, off_gaps = [], []
        for s in range(101, 101 + 20 * 3, 3):
            on = run(list(M.BASELINE), att=att, seed=s, use_suppression=True)
            off = run(list(M.BASELINE), att=att, seed=s, use_suppression=False)
            self.assertEqual(on["detected_fraction"], off["detected_fraction"],
                             "detection is identical BY CONSTRUCTION")
            on_gaps.append(on["detected_fraction"] - on["acted_fraction"])
            off_gaps.append(off["detected_fraction"] - off["acted_fraction"])
        self.assertEqual(max(off_gaps), 0.0, "with no suppression, nothing detected is unhandled")
        mean_on = sum(on_gaps) / len(on_gaps)
        self.assertGreater(mean_on, 0.003,
                           f"suppression must show a real handling cost; got {mean_on:+.4f}")
        self.assertLess(mean_on, 0.05, f"and it must be small, not catastrophic: {mean_on:+.4f}")

    def test_acted_never_exceeds_detected(self):
        for n_extra in (0, 5, 15):
            extra = [self._alarm(f"x{i}", covers=frozenset({M.MODES[i % 4]}),
                                 recall=0.35, benign_rate_per_week=0.55)
                     for i in range(n_extra)]
            r = run(list(M.BASELINE) + extra, seed=23)
            self.assertLessEqual(r["acted_fraction"], r["detected_fraction"] + 1e-12,
                                 f"{n_extra} extra alarms")


class TestSuppressionAndRouting(unittest.TestCase):
    def test_suppression_is_a_noop_when_the_parent_never_fires(self):
        alarms = [A.Alarm("child", recall=1.0, covers=frozenset({"m"}),
                          benign_rate_per_week=0.0, parent="ghost")]
        f = [A.Firing(0, "child", True, 0)]
        self.assertEqual(A.suppress(alarms, f), f)

    def test_suppression_cannot_change_detection_BY_CONSTRUCTION(self):
        """The card must NOT publish 'detection cost 0.000' as an experimental result.

        `fire()` appends to `inc.detected_by`; `suppress()` only filters the firing list and
        never touches incidents, so detection is computed from pre-suppression data and cannot
        move. This test pins that as an ARCHITECTURAL property -- which is the honest claim --
        and exists so nobody later mistakes the zero for evidence.
        """
        on = run(list(M.BASELINE) + [M.TUNED], seed=17, use_suppression=True)
        off = run(list(M.BASELINE) + [M.TUNED], seed=17, use_suppression=False)
        self.assertEqual(on["detected_fraction"], off["detected_fraction"],
                         "identical by construction, not by measurement")
        self.assertLess(on["pages_per_week"], off["pages_per_week"],
                        "what suppression actually buys is fewer interruptions")

    def test_pages_excludes_exactly_the_unactionable(self):
        alarms = [A.Alarm("p", recall=1.0, covers=frozenset({"m"}), benign_rate_per_week=0.0),
                  A.Alarm("t", recall=1.0, covers=frozenset({"m"}), benign_rate_per_week=0.0,
                          actionable_at_3am=False)]
        f = [A.Firing(0, "p", True, 0), A.Firing(0, "t", True, 0)]
        self.assertEqual([x.alarm for x in A.pages(alarms, f)], ["p"])

    def test_the_decorative_precision_field_stays_gone(self):
        """REGRESSION. `precision` was declared, set on every fixture, quoted in the experiment
        names -- and never read by any simulation logic, so 'adding a LOW-PRECISION alarm harms'
        attributed the effect to a field that did nothing. The real lever is
        benign_rate_per_week (3.0 vs 0.30). It is removed rather than implemented because it is
        DERIVABLE, and a declared copy can contradict the model."""
        self.assertNotIn("precision", A.Alarm.__dataclass_fields__,
                         "a field that looks load-bearing and is not")
        self.assertIn("benign_rate_per_week", A.Alarm.__dataclass_fields__)


class TestPublishedNumbers(unittest.TestCase):
    """The stochastic claims, pinned with tolerances derived from their MEASURED standard errors
    (0.011-0.020). Tolerances are ~3x SE: tight enough to catch a real regression, loose enough
    not to fail on the RNG. Seeds are strided by 3 because `run(seed=S)` consumes S, S+1, S+2 --
    stepping by 1 made consecutive trials share two of three RNG streams and understated every
    standard error by ~38%."""

    @classmethod
    def setUpClass(cls):
        # 40 seeds, because 40 is what the published claim used. At 20 the standard error at 9
        # alarms grows to 0.020 and |-0.036| no longer clears 2*SE -- the test failed, correctly,
        # for asking less power of itself than the card asks of the claim.
        cls.boundary = M.boundary_multiseed(seeds=40, max_extra=12, step=3)
        cls.peak = M.peak_multiseed(seeds=12, max_extra=30)

    def test_a_noisy_alarm_measurably_harms_a_SMALL_portfolio(self):
        """C1. The headline, and the opposite of the folk rule. At 3/6/9 alarms the marginal
        high-benign-rate alarm costs 4-6 points of handling, each >2x its own standard error."""
        for row in self.boundary[:3]:
            self.assertLess(row["delta_mean"], 0, f"{row['alarms']} alarms")
            self.assertTrue(row["sign_is_claimable"],
                            f"{row['alarms']} alarms: |{row['delta_mean']:.3f}| vs "
                            f"2*SE={2 * row['delta_se']:.3f}")
            self.assertLess(row["delta_mean"], -0.02, f"{row['alarms']} alarms")

    def test_the_same_alarm_has_no_measurable_effect_once_saturated(self):
        """C2. Not 'harms less' -- NO MEASURABLE EFFECT. By 12 alarms handling has already
        collapsed to ~0.68 and there is nothing left for one more alarm to take."""
        row = self.boundary[-1]
        self.assertGreaterEqual(row["alarms"], 12)
        self.assertFalse(row["sign_is_claimable"],
                         f"{row['alarms']} alarms: delta={row['delta_mean']:+.3f} "
                         f"SE={row['delta_se']:.3f}")

    def test_detection_saturates_almost_immediately(self):
        """C3, first half. Three alarms already detect ~95% of incidents."""
        first = self.peak["first"]
        self.assertEqual(first["alarms"], 3)
        self.assertGreater(first["detected"], 0.92, f"detected={first['detected']:.3f}")

    def test_handling_declines_while_detection_barely_improves(self):
        """C3, the trade, and the number a reader should act on: going from 3 to 33 alarms buys
        a few points of detection and costs a quarter of all handling."""
        first, last = self.peak["first"], self.peak["last"]
        detection_gain = last["detected"] - first["detected"]
        handling_loss = first["acted"] - last["acted"]
        self.assertLess(detection_gain, 0.08, f"gain={detection_gain:+.3f}")
        self.assertGreater(handling_loss, 0.20, f"loss={handling_loss:+.3f}")
        self.assertGreater(handling_loss, 3 * detection_gain,
                           "the trade must be lopsided, or the card has no advice to give")

    def test_there_is_NO_distinguishable_interior_optimum(self):
        """C4, and a correction to a claim I nearly published. The single-seed run reported
        'peak acted=0.907 at 6 alarms'. With power the maximum sits at the SMALLEST portfolio
        tested and is not statistically separable from its neighbour, so the honest statement is
        a monotone decline, not a sweet spot. A card that named 6 as the optimum would have been
        inventing a recommendation out of one seed."""
        self.assertEqual(self.peak["peak"]["alarms"], self.peak["first"]["alarms"],
                         "the best portfolio tested is the smallest one")
        self.assertFalse(self.peak["peak_is_distinguishable"],
                         "must not be sold as a located optimum")

    def test_actionable_fraction_collapses_and_is_observable_without_ground_truth(self):
        """C5. The one signal an operator can actually measure: the share of pages that had a
        real incident behind them. It falls from ~0.55 to ~0.15 over the same range."""
        self.assertGreater(self.boundary[0]["actionable_fraction"], 0.45)
        self.assertLess(self.boundary[-1]["actionable_fraction"], 0.25)

    def test_switching_the_mechanism_off_removes_the_harm(self):
        """C8, at the same power as every other claim. If benign pages cost no attention the
        effect must vanish; an effect that survives its own mechanism being disabled is a
        coincidence.

        Was a single seed asserting delta >= 0. The gate objected that the experiment VALIDATING
        the mechanism was held to a weaker standard than the ones measuring it, which is the most
        self-serving possible version of the single-seed mistake. Now 40 strided seeds on both
        arms: live must be claimably negative, disabled must NOT be claimable in either
        direction. The disabled arm is +0.0135, so the honest assertion is indistinguishability
        from zero rather than equality with it.
        """
        r = M.ablation_multiseed(seeds=40)
        live, off = r["mechanism_live"], r["mechanism_off"]
        self.assertLess(live["mean"], 0, "the harm must reproduce with the mechanism live")
        self.assertTrue(live["claimable"],
                        f"live: {live['mean']:+.4f} vs 2*SE={2 * live['se']:.4f}")
        self.assertFalse(off["claimable"],
                         f"disabled arm must not be claimable either way: "
                         f"{off['mean']:+.4f} vs 2*SE={2 * off['se']:.4f}")
        self.assertGreater(off["mean"], live["mean"],
                           "disabling the mechanism must move the delta upward")


class TestTheEffectIsRegimeConditional(unittest.TestCase):
    """E10. The card's scope condition, and the reason it can give advice rather than a slogan.

    `sweep_e1` hinted at this at one seed per cell -- harm in only 9 of 45 settings, every
    harming cell at capacity 2 or 5 -- but a single-seed cell is one incident wide, so the hint
    was not publishable. With 40 seeds per point it holds, and sharpens into a sign flip.
    """

    @classmethod
    def setUpClass(cls):
        # 40 seeds, matching the power the published claim uses.
        cls.rows = {r["capacity"]: r for r in M.capacity_regime(seeds=40)}

    def test_harm_is_claimable_ONLY_when_the_responder_lacks_slack(self):
        for cap in (2.0, 5.0):
            r = self.rows[cap]
            self.assertLess(r["delta_mean"], 0, f"capacity={cap}")
            self.assertTrue(
                r["sign_is_claimable"],
                f"capacity={cap}: {r['delta_mean']:+.3f} vs 2*SE={2 * r['delta_se']:.3f}")
        for cap in (10.0, 20.0):
            self.assertFalse(self.rows[cap]["sign_is_claimable"],
                             f"capacity={cap}: must NOT be claimable either way")

    def test_at_high_slack_the_noisy_alarm_MEASURABLY_HELPS(self):
        """The folk rule is not merely unproven for a team with slack -- it is FALSE there.

        At capacity 50 (load/capacity 0.06) the redundant alarm buys coverage and costs nothing,
        and the sign is claimable. A card that said 'never add a noisy alarm' would be giving
        these readers advice this simulator measures as wrong.
        """
        r = self.rows[50.0]
        self.assertGreater(r["delta_mean"], 0, "the sign genuinely flips")
        self.assertTrue(r["sign_is_claimable"],
                        f"+{r['delta_mean']:.3f} vs 2*SE={2 * r['delta_se']:.3f}")

    def test_the_dose_response_is_monotone_in_capacity(self):
        """Why this is a mechanism and not five coincidences: the delta rises monotonically
        across all five capacities. Five independent points landing in order is far stronger
        evidence than any single one of them clearing 2x its own standard error."""
        deltas = [self.rows[c]["delta_mean"] for c in (2.0, 5.0, 10.0, 20.0, 50.0)]
        self.assertEqual(deltas, sorted(deltas),
                         f"not monotone: {[f'{d:+.3f}' for d in deltas]}")
        self.assertLess(deltas[0], 0)
        self.assertGreater(deltas[-1], 0)

    def test_load_is_held_fixed_so_capacity_is_the_only_thing_varying(self):
        """The control. If page volume moved with capacity the experiment would be confounded
        and the monotone trend above would be uninterpretable."""
        ppw = {round(r["pages_per_week"], 6) for r in self.rows.values()}
        self.assertEqual(len(ppw), 1, f"page volume must not vary with capacity: {ppw}")



class TestOneSeedIsAnAnecdote(unittest.TestCase):
    def test_a_single_seed_reports_the_OPPOSITE_sign(self):
        """REGRESSION for the defect that would have set the card's headline.

        Seed 17 alone gives delta = +0.056: 'the noisy alarm HELPS'. Twenty independent seeds
        give a negative mean several times its standard error. Same experiment, same magnitude,
        opposite sign -- because a delta of 0.019 is ONE incident out of ~52.
        """
        single = M.e1_adding_an_alarm(seed=17)["delta_acted_noisy"]
        many = M.boundary_multiseed(seeds=20, max_extra=0, step=3)[0]["delta_mean"]
        self.assertGreater(single, 0.0, "seed 17 says it helps")
        self.assertLess(many, 0.0, "the population says it harms")
        self.assertTrue(single * many < 0, "the signs must genuinely disagree")

    def test_seed_spread_is_wider_than_the_effect_being_claimed(self):
        """Why a tolerance is mandatory: across 12 seeds the delta ranges over ~0.29, while the
        effect itself is ~0.05. Any single-seed number in this card would be unfalsifiable."""
        ss = M.seed_stability(n=12)
        self.assertGreater(ss["max"] - ss["min"], 0.15,
                           f"range=[{ss['min']:+.3f}, {ss['max']:+.3f}]")
        self.assertLess(ss["mean"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

class TestContainmentAndScoping(unittest.TestCase):
    """C9/A8 — the containment test, contributed by a consumer, then priced by measurement.

    S3 had no precondition at all. An opus-5 session with no access to this card supplied one:
    "suppression requires containment, and most real hierarchies are built on co-firing". Measuring it
    showed the consumer was right about the hazard and incomplete about the remedy.
    """

    MODES = ("m_db", "m_dep", "m_deploy", "m_disk")
    CHILD = A.Alarm("child", 0.85, frozenset({"m_db", "m_disk"}), 0.25, parent="parent")
    P_CONTAINED = A.Alarm("parent", 0.85, frozenset({"m_db", "m_dep", "m_disk"}), 0.25)
    P_COFIRING = A.Alarm("parent", 0.85, frozenset({"m_db", "m_dep"}), 0.25)
    OTHER = A.Alarm("other", 0.80, frozenset({"m_deploy"}), 0.20)

    def _orphan_rate(self, parent, scoped, seed):
        alarms = [parent, self.CHILD, self.OTHER]
        inc = A.incident_stream(104, 0.6, self.MODES, seed)
        fir = A.fire(alarms, inc, 104, seed)
        kept = (A.suppress_by_incident if scoped else A.suppress)(alarms, fir)
        o, d = A.orphaned_incidents(inc, kept)
        return o / d if d else 0.0

    def test_containment_is_a_subset_test_on_covers(self):
        self.assertEqual(A.containment_holds([self.P_CONTAINED, self.CHILD]), {"child": True})
        self.assertEqual(A.containment_holds([self.P_COFIRING, self.CHILD]), {"child": False})

    def test_incident_scoping_CANNOT_orphan_regardless_of_containment(self):
        """The exact-zero claim, and it is exact by construction, not by luck.

        A child is muted only if the parent fired FOR THAT INCIDENT, so that incident retains the
        parent as a detector. This is the finding that demotes containment from 'the requirement' to
        'a mitigation for coarse temporal muting'.
        """
        for parent in (self.P_CONTAINED, self.P_COFIRING):
            for seed in range(1000, 1010):
                self.assertEqual(self._orphan_rate(parent, True, seed), 0.0)

    def test_cofiring_orphans_MORE_than_containment_at_week_granularity(self):
        """The consumer's claim, confirmed as an ordering rather than a magnitude."""
        co = sum(self._orphan_rate(self.P_COFIRING, False, 1000 + s) for s in range(30)) / 30
        cont = sum(self._orphan_rate(self.P_CONTAINED, False, 1000 + s) for s in range(30)) / 30
        self.assertGreater(co, cont)
        self.assertGreater(cont, 0.0, "week-granularity orphans even under containment")

    def test_scoping_gives_up_volume_because_benign_firings_have_no_incident(self):
        """The cost side. Incident-scoping is safer and strictly weaker as a volume lever."""
        alarms = [self.P_CONTAINED, self.CHILD, self.OTHER]
        inc = A.incident_stream(104, 0.6, self.MODES, 1000)
        fir = A.fire(alarms, inc, 104, 1000)
        base = len(A.dedupe(A.pages(alarms, fir)))
        wk = base - len(A.dedupe(A.pages(alarms, A.suppress(alarms, fir))))
        sc = base - len(A.dedupe(A.pages(alarms, A.suppress_by_incident(alarms, fir))))
        self.assertGreater(wk, sc, "week-granular muting must save more pages than incident-scoped")
