"""The experiments. Nothing in CARD.md may state a number this file has not printed.

Each experiment answers one question and reports where its answer STOPS holding. The sweep and
the ablation are not decoration: a claim that survives only at one (capacity, k, floor) is an
artifact of `attention.py`, and a mechanism that cannot be switched off is a coincidence rather
than an explanation.
"""
from __future__ import annotations

from . import alarms as A
from .attention import Attention, run

MODES = ("db_saturation", "dependency_timeout", "bad_deploy", "disk_full")

# A deliberately small, symptom-first set: one alarm per failure mode a customer would notice.
BASELINE = [
    A.Alarm("slo_error_rate", recall=0.90,
            covers=frozenset({"db_saturation", "dependency_timeout", "bad_deploy"}),
            benign_rate_per_week=0.15),
    A.Alarm("slo_latency_p99", recall=0.60,
            covers=frozenset({"db_saturation", "dependency_timeout"}),
            benign_rate_per_week=0.30, parent="slo_error_rate"),
    A.Alarm("disk_free_pct", recall=0.95,
            covers=frozenset({"disk_full"}), benign_rate_per_week=0.05),
]

# The alarm everyone adds after an incident review: a cause-level metric that fires often on
# nothing (3.0/wk), covering a failure mode ALREADY covered by slo_error_rate.
NOISY = A.Alarm("db_connection_count", recall=0.70,
                covers=frozenset({"db_saturation"}), benign_rate_per_week=3.0)

# Same coverage, same recall, but tuned: fires a tenth as often on nothing.
TUNED = A.Alarm("db_connection_count_tuned", recall=0.65,
                covers=frozenset({"db_saturation"}), benign_rate_per_week=0.30,
                parent="slo_error_rate")

# Correct, precise, and nobody can do anything at 3am: a slow disk-growth trend.
UNACTIONABLE = A.Alarm("disk_growth_trend", recall=0.80,
                       covers=frozenset({"disk_full"}), benign_rate_per_week=0.60)


def e1_adding_an_alarm(att: Attention | None = None, seed: int = 17) -> dict:
    """Does adding a HIGH-BENIGN-RATE alarm to an already-covered failure mode help?

    Was phrased 'low-precision' until a review found `precision` was never read by the
    simulation. The lever is benign_rate_per_week: 3.0 for NOISY against 0.30 for TUNED.
    """
    base = run(list(BASELINE), att=att, seed=seed)
    plus = run(list(BASELINE) + [NOISY], att=att, seed=seed)
    tuned = run(list(BASELINE) + [TUNED], att=att, seed=seed)
    return {"baseline": base, "plus_noisy": plus, "plus_tuned": tuned,
            "delta_acted_noisy": plus["acted_fraction"] - base["acted_fraction"],
            "delta_acted_tuned": tuned["acted_fraction"] - base["acted_fraction"],
            "delta_detected_noisy": plus["detected_fraction"] - base["detected_fraction"]}


def e2_ablation(seed: int = 17) -> dict:
    """Switch the mechanism off. If the effect persists, the mechanism is not the cause."""
    base = run(list(BASELINE), seed=seed, couple_load=False)
    plus = run(list(BASELINE) + [NOISY], seed=seed, couple_load=False)
    return {"baseline": base, "plus_noisy": plus,
            "delta_acted_noisy": plus["acted_fraction"] - base["acted_fraction"]}


def e3_suppression(seed: int = 17) -> dict:
    """Does a declared parent/child hierarchy buy quiet without costing detection?"""
    on = run(list(BASELINE) + [TUNED], seed=seed, use_suppression=True)
    off = run(list(BASELINE) + [TUNED], seed=seed, use_suppression=False)
    return {"with_suppression": on, "without": off,
            "pages_saved_per_week": off["pages_per_week"] - on["pages_per_week"],
            "detection_cost": off["detected_fraction"] - on["detected_fraction"]}


def e4_correlated_alarms(n: int = 6, seed: int = 17) -> dict:
    """N independent alarms on ONE failure mode. Pages scale with N; coverage does not."""
    out = {}
    for count in range(1, n + 1):
        alarm_set = [
            A.Alarm(f"db_signal_{i}", recall=0.6,
                    covers=frozenset({"db_saturation"}), benign_rate_per_week=0.4)
            for i in range(count)
        ]
        r = run(alarm_set, modes=("db_saturation",), seed=seed)
        out[count] = {"pages_per_week": r["pages_per_week"],
                      "detected_fraction": r["detected_fraction"],
                      "acted_fraction": r["acted_fraction"]}
    return out


def e5_route_the_unactionable(seed: int = 17) -> dict:
    """A correct, precise alarm nobody can act on at 3am. Page it, or ticket it?"""
    as_page = list(BASELINE) + [UNACTIONABLE]
    as_ticket = list(BASELINE) + [
        A.Alarm(UNACTIONABLE.name, UNACTIONABLE.recall,
                UNACTIONABLE.covers, UNACTIONABLE.benign_rate_per_week,
                actionable_at_3am=False)]
    p = run(as_page, seed=seed)
    t = run(as_ticket, seed=seed)
    return {"paged": p, "ticketed": t,
            "delta_acted": t["acted_fraction"] - p["acted_fraction"],
            "delta_pages_per_week": t["pages_per_week"] - p["pages_per_week"]}


def e6_regime_boundary(seed: int = 17, max_extra: int = 22) -> list[dict]:
    """WHERE does the sign of 'should I add this alarm?' flip? This is the card's real content.

    E1 through E5 all returned 'more alarms help', and the reason was not subtle: the baseline
    portfolio produces 0.78 pages/week against a capacity of 5, so triage probability never
    falls below ~0.97 and attention is effectively free. In that regime redundancy is close to
    costless and the advice everyone repeats -- 'noisy alarms cause missed incidents' -- is
    simply FALSE.

    Finding the boundary is a different question from proving a prejudice, which is why this is
    a sweep over page volume rather than a re-tuned single point. Load is raised the way it
    actually rises on a real service: by accumulating more alarms, each individually defensible,
    each with a modest benign rate.
    """
    rows = []
    for m in range(0, max_extra + 1, 2):
        extra = [
            A.Alarm(f"cause_metric_{i}", recall=0.35,
                    covers=frozenset({MODES[i % len(MODES)]}), benign_rate_per_week=0.55)
            for i in range(m)
        ]
        base_set = list(BASELINE) + extra
        base = run(base_set, seed=seed)
        plus = run(base_set + [NOISY], seed=seed)
        rows.append({
            "extra_alarms": m,
            "alarms": len(base_set),
            "pages_per_week": base["pages_per_week"],
            "mean_triage": base["mean_triage_probability"],
            "actionable_fraction": base["actionable_fraction_of_pages"],
            "acted": base["acted_fraction"],
            "acted_plus_noisy": plus["acted_fraction"],
            "delta_acted": plus["acted_fraction"] - base["acted_fraction"],
            "delta_detected": plus["detected_fraction"] - base["detected_fraction"],
        })
    return rows


def e7_peak_acted(seed: int = 17, max_extra: int = 30) -> dict:
    """Does acted_fraction have an interior MAXIMUM in portfolio size?

    If more alarms always help, a card recommending restraint is wrong and should say so. If
    there is a peak, its location is the number a reader actually needs.
    """
    best = None
    curve = []
    for m in range(0, max_extra + 1):
        extra = [
            A.Alarm(f"cause_metric_{i}", recall=0.35,
                    covers=frozenset({MODES[i % len(MODES)]}), benign_rate_per_week=0.55)
            for i in range(m)
        ]
        r = run(list(BASELINE) + extra, seed=seed)
        curve.append((len(BASELINE) + m, round(r["pages_per_week"], 2),
                      round(r["detected_fraction"], 3), round(r["acted_fraction"], 3)))
        if best is None or r["acted_fraction"] > best[1]:
            best = (len(BASELINE) + m, r["acted_fraction"], r["pages_per_week"])
    return {"curve": curve, "peak_alarms": best[0], "peak_acted": best[1],
            "peak_pages_per_week": best[2], "final": curve[-1]}


def sweep_e1(seed: int = 17) -> list[dict]:
    """Where does 'adding a noisy alarm hurts' hold, and where does it stop?

    Reported as a region, not a point. Any (capacity, k, floor) at which the sign flips is a
    boundary condition the card must state, because a reader whose team has that capacity is
    entitled to the opposite advice.
    """
    rows = []
    for capacity in (2.0, 5.0, 10.0, 20.0, 50.0):
        for k in (1.0, 2.0, 4.0):
            for floor in (0.05, 0.15, 0.40):
                att = Attention(capacity=capacity, k=k, floor=floor)
                r = e1_adding_an_alarm(att=att, seed=seed)
                rows.append({"capacity": capacity, "k": k, "floor": floor,
                             "delta_acted_noisy": r["delta_acted_noisy"],
                             "delta_detected_noisy": r["delta_detected_noisy"],
                             "harms": r["delta_acted_noisy"] < 0})
    return rows


def boundary_multiseed(seeds: int = 40, max_extra: int = 24, step: int = 3) -> list[dict]:
    """E6 again, with enough power to have a sign.

    E6 at one seed reported 'FIRST HARM at 7 alarms' and then a delta sequence that flipped
    -0.148, -0.037, -0.148, -0.315, 0.000, +0.019, -0.148, -0.037, 0.000, +0.130. At 0.5
    incidents/week over 104 weeks there are only ~52 incidents in the whole run, so a delta of
    0.019 IS ONE INCIDENT. The sequence was noise with a decimal point, and the boundary it
    appeared to locate was an artifact of seed 17.

    Averaging over seeds is the fix, and reporting the standard error is what makes the sign
    claimable. A mean delta smaller than its own standard error is not a finding in either
    direction, and the card must say 'no measurable effect' rather than pick the sign that
    suits the story.
    """
    import math
    rows = []
    for m in range(0, max_extra + 1, step):
        extra = [
            A.Alarm(f"cause_metric_{i}", recall=0.35,
                    covers=frozenset({MODES[i % len(MODES)]}), benign_rate_per_week=0.55)
            for i in range(m)
        ]
        base_set = list(BASELINE) + extra
        deltas, acteds, ppw, actionable = [], [], [], []
        for s in range(101, 101 + seeds * 3, 3):
            b = run(base_set, seed=s)
            p = run(base_set + [NOISY], seed=s)
            deltas.append(p["acted_fraction"] - b["acted_fraction"])
            acteds.append(b["acted_fraction"])
            ppw.append(b["pages_per_week"])
            actionable.append(b["actionable_fraction_of_pages"])
        n = len(deltas)
        mean = sum(deltas) / n
        var = sum((d - mean) ** 2 for d in deltas) / (n - 1) if n > 1 else 0.0
        se = math.sqrt(var / n)
        rows.append({
            "alarms": len(base_set),
            "pages_per_week": sum(ppw) / n,
            "actionable_fraction": sum(actionable) / n,
            "acted": sum(acteds) / n,
            "delta_mean": mean,
            "delta_se": se,
            # "significant" here means only: the mean is at least twice its own standard error.
            # It is not a p-value and the runs are not independent of the model.
            "sign_is_claimable": abs(mean) > 2 * se,
        })
    return rows


def peak_multiseed(seeds: int = 20, max_extra: int = 30) -> dict:
    """E7 with power. The single-seed version was an anecdote by my own argument.

    e7_peak_acted() reported 'peak acted=0.907 at 6 alarms' and 'detected=1.000 at 33 alarms'
    from seed 17 alone. Having just rejected E6's single-seed boundary as ~1-incident noise,
    publishing these would have applied one standard to a number I disliked and another to two
    I wanted. Same stride-3 seeding as boundary_multiseed, so trials do not share RNG streams.

    Returns the curve with standard errors, the peak, and -- the honest part -- whether the
    peak is distinguishable from its neighbours at all.
    """
    import math
    curve = []
    for m in range(0, max_extra + 1):
        extra = [
            A.Alarm(f"cause_metric_{i}", recall=0.35,
                    covers=frozenset({MODES[i % len(MODES)]}), benign_rate_per_week=0.55)
            for i in range(m)
        ]
        acted, det, ppw = [], [], []
        for s in range(101, 101 + seeds * 3, 3):
            r = run(list(BASELINE) + extra, seed=s)
            acted.append(r["acted_fraction"])
            det.append(r["detected_fraction"])
            ppw.append(r["pages_per_week"])
        n = len(acted)
        mean = sum(acted) / n
        var = sum((a - mean) ** 2 for a in acted) / (n - 1) if n > 1 else 0.0
        curve.append({"alarms": len(BASELINE) + m,
                      "pages_per_week": sum(ppw) / n,
                      "detected": sum(det) / n,
                      "acted": mean,
                      "acted_se": math.sqrt(var / n)})
    peak = max(curve, key=lambda r: r["acted"])
    # Is the peak real, or is every point within noise of it?
    rivals = [r for r in curve
              if r is not peak
              and r["acted"] + 2 * r["acted_se"] >= peak["acted"] - 2 * peak["acted_se"]]
    return {"curve": curve, "peak": peak, "n_within_noise_of_peak": len(rivals),
            "peak_is_distinguishable": len(rivals) == 0,
            "first": curve[0], "last": curve[-1]}


def seed_stability(n: int = 12) -> dict:
    """The same experiment across n seeds. One seed is an anecdote."""
    deltas = [e1_adding_an_alarm(seed=s)["delta_acted_noisy"]
              for s in range(11, 11 + n * 3, 3)]
    harmed = sum(1 for d in deltas if d < 0)
    return {"seeds": n, "harmed_in": harmed,
            "min": min(deltas), "max": max(deltas),
            "mean": sum(deltas) / len(deltas)}


def capacity_regime(seeds: int = 40, n_extra: int = 3) -> list[dict]:
    """E10 -- does the headline effect SURVIVE a responder with slack? Powered.

    `sweep_e1` said the marginal noisy alarm harms in only 9 of 45 parameter settings, and that
    every harming cell had capacity 2.0 or 5.0. But that sweep is ONE seed per cell, and at ~52
    incidents per run a delta of 0.019 is a single incident, so its per-cell verdicts are noise.
    The coarse pattern was worth testing properly, because if it holds it is the card's scope
    condition: the advice applies only where attention is actually scarce.

    Fixed portfolio, varying capacity, 40 independent seeds per point. `load_ratio` is the honest
    x-axis -- pages per week divided by the responder's capacity -- because 'capacity 5' means
    nothing without knowing the volume it is absorbing.
    """
    import math
    rows = []
    extra = [
        A.Alarm(f"cause_metric_{i}", recall=0.35,
                covers=frozenset({MODES[i % len(MODES)]}), benign_rate_per_week=0.55)
        for i in range(n_extra)
    ]
    base_set = list(BASELINE) + extra
    for cap in (2.0, 5.0, 10.0, 20.0, 50.0):
        att = Attention(capacity=cap)
        deltas, ppw, triage = [], [], []
        for s in range(101, 101 + seeds * 3, 3):
            b = run(base_set, att=att, seed=s)
            p = run(base_set + [NOISY], att=att, seed=s)
            deltas.append(p["acted_fraction"] - b["acted_fraction"])
            ppw.append(p["pages_per_week"])
            triage.append(p["mean_triage_probability"])
        n = len(deltas)
        mean = sum(deltas) / n
        var = sum((d - mean) ** 2 for d in deltas) / (n - 1) if n > 1 else 0.0
        se = math.sqrt(var / n)
        rows.append({
            "capacity": cap,
            "pages_per_week": sum(ppw) / n,
            "load_ratio": (sum(ppw) / n) / cap,
            "mean_triage": sum(triage) / n,
            "delta_mean": mean,
            "delta_se": se,
            "sign_is_claimable": abs(mean) > 2 * se,
        })
    return rows


def ablation_multiseed(seeds: int = 40) -> dict:
    """C8 with the same power as every other published claim.

    The gate objected -- correctly -- that the ablation was reported on n=1 while this card's
    other claims use n=40 of the same population. A single-seed ablation could show 'the effect
    vanished' by luck, which is exactly the reasoning this card rejects everywhere else. Applying
    a weaker standard to the experiment that VALIDATES the mechanism than to the ones that measure
    it would be the most self-serving version of that mistake.

    Reports the delta with the mechanism live and with it switched off, over the same strided
    seeds. The claim is that the second is not distinguishable from zero.
    """
    import math
    live, off = [], []
    for s in range(101, 101 + seeds * 3, 3):
        b = run(list(BASELINE), seed=s)
        p = run(list(BASELINE) + [NOISY], seed=s)
        live.append(p["acted_fraction"] - b["acted_fraction"])
        bo = run(list(BASELINE), seed=s, couple_load=False)
        po = run(list(BASELINE) + [NOISY], seed=s, couple_load=False)
        off.append(po["acted_fraction"] - bo["acted_fraction"])

    def stat(xs):
        n = len(xs)
        m = sum(xs) / n
        v = sum((x - m) ** 2 for x in xs) / (n - 1) if n > 1 else 0.0
        se = math.sqrt(v / n)
        return {"mean": m, "se": se, "claimable": abs(m) > 2 * se, "n": n}

    return {"mechanism_live": stat(live), "mechanism_off": stat(off)}


def main() -> None:
    def show(label, r):
        print(f"    {label:<26} pages/wk={r['pages_per_week']:5.2f}  "
              f"actionable={r['actionable_fraction_of_pages']:.2f}  "
              f"detected={r['detected_fraction']:.3f}  acted={r['acted_fraction']:.3f}  "
              f"peak={r['peak_week_pages']}")

    print("=" * 92)
    print("E1  adding a HIGH-BENIGN-RATE alarm to an ALREADY-COVERED failure mode")
    print("=" * 92)
    e1 = e1_adding_an_alarm()
    show("baseline (3 alarms)", e1["baseline"])
    show("+ noisy (benign 3.0/wk)", e1["plus_noisy"])
    show("+ tuned (benign 0.30/wk)", e1["plus_tuned"])
    print(f"    delta acted, noisy = {e1['delta_acted_noisy']:+.3f}   "
          f"delta DETECTED, noisy = {e1['delta_detected_noisy']:+.3f}")
    print(f"    delta acted, tuned = {e1['delta_acted_tuned']:+.3f}")

    print("\n" + "=" * 92)
    print("E2  ABLATION -- benign pages consume no attention (mechanism switched off)")
    print("=" * 92)
    e2 = e2_ablation()
    show("baseline", e2["baseline"])
    show("+ noisy", e2["plus_noisy"])
    print(f"    delta acted, noisy = {e2['delta_acted_noisy']:+.3f}  "
          f"(if this is no longer negative, attention coupling IS the mechanism)")

    print("\n" + "=" * 92)
    print("E3  suppression hierarchy: quiet without losing detection?")
    print("=" * 92)
    e3 = e3_suppression()
    show("with suppression", e3["with_suppression"])
    show("without", e3["without"])
    print(f"    pages/wk saved = {e3['pages_saved_per_week']:+.2f}   "
          f"detection cost = {e3['detection_cost']:+.3f}")

    print("\n" + "=" * 92)
    print("E4  N correlated alarms on ONE failure mode")
    print("=" * 92)
    print(f"    {'alarms':<8}{'pages/wk':>10}{'detected':>11}{'acted':>9}")
    for n, r in sorted(e4_correlated_alarms().items()):
        print(f"    {n:<8}{r['pages_per_week']:>10.2f}{r['detected_fraction']:>11.3f}"
              f"{r['acted_fraction']:>9.3f}")

    print("\n" + "=" * 92)
    print("E5  a correct, precise, UN-ACTIONABLE alarm: page it or ticket it?")
    print("=" * 92)
    e5 = e5_route_the_unactionable()
    show("routed to a page", e5["paged"])
    show("routed to a ticket", e5["ticketed"])
    print(f"    delta acted = {e5['delta_acted']:+.3f}   "
          f"delta pages/wk = {e5['delta_pages_per_week']:+.2f}")

    print("\n" + "=" * 92)
    print("SWEEP  where does E1's finding hold? (45 parameter settings)")
    print("=" * 92)
    rows = sweep_e1()
    harms = [r for r in rows if r["harms"]]
    print(f"    harms in {len(harms)}/{len(rows)} settings")
    ok = [r for r in rows if not r["harms"]]
    if ok:
        print("    it does NOT harm at:")
        for r in ok:
            print(f"      capacity={r['capacity']:<5} k={r['k']:<4} floor={r['floor']:<5} "
                  f"delta={r['delta_acted_noisy']:+.3f}")
    caps = sorted({r["capacity"] for r in harms})
    print(f"    capacities where it harms: {caps}")

    print("E6  REGIME BOUNDARY -- where does adding an alarm start to COST detection?")
    print("=" * 92)
    print(f"    {'alarms':>7}{'pages/wk':>10}{'triage':>8}{'actionable':>12}"
          f"{'acted':>8}{'+noisy':>8}{'delta':>8}")
    flip = None
    for r in e6_regime_boundary():
        print(f"    {r['alarms']:>7}{r['pages_per_week']:>10.2f}{r['mean_triage']:>8.3f}"
              f"{r['actionable_fraction']:>12.2f}{r['acted']:>8.3f}"
              f"{r['acted_plus_noisy']:>8.3f}{r['delta_acted']:>+8.3f}")
        if flip is None and r["delta_acted"] < 0:
            flip = r
    if flip:
        print(f"    FIRST HARM at {flip['alarms']} alarms / "
              f"{flip['pages_per_week']:.2f} pages per week")
    else:
        print("    never harms in this range -- the prejudice is not reproducible here")

    print("\n" + "=" * 92)
    print("E7  is there an interior MAXIMUM in portfolio size?")
    print("=" * 92)
    e7 = e7_peak_acted()
    print(f"    peak acted={e7['peak_acted']:.3f} at {e7['peak_alarms']} alarms "
          f"({e7['peak_pages_per_week']:.2f} pages/wk)")
    print(f"    at the end of the range: alarms={e7['final'][0]} pages/wk={e7['final'][1]} "
          f"detected={e7['final'][2]} acted={e7['final'][3]}")


    print("\n" + "=" * 92)
    print(f"E8  BOUNDARY WITH POWER -- 40 seeds per point (E6 at one seed was ~1-incident noise)")
    print("=" * 92)
    print(f"    {'alarms':>7}{'pages/wk':>10}{'actionable':>12}{'acted':>8}"
          f"{'delta':>9}{'std err':>9}   verdict")
    for r in boundary_multiseed():
        verdict = ("HARMS" if r["delta_mean"] < 0 else "helps") if r["sign_is_claimable"] \
            else "no measurable effect"
        print(f"    {r['alarms']:>7}{r['pages_per_week']:>10.2f}"
              f"{r['actionable_fraction']:>12.2f}{r['acted']:>8.3f}"
              f"{r['delta_mean']:>+9.3f}{r['delta_se']:>9.3f}   {verdict}")

    print("\n" + "=" * 92)
    print("E9  PEAK / SATURATION WITH POWER  (20 independent seeds; E7 used seed 17 alone)")
    print("=" * 92)
    pm = peak_multiseed()
    print(f"    {'alarms':>7}{'pages/wk':>10}{'detected':>10}{'acted':>8}{'se':>8}")
    for r in pm["curve"]:
        if r["alarms"] % 3 == 0 or r is pm["peak"]:
            star = "  <- peak" if r is pm["peak"] else ""
            print(f"    {r['alarms']:>7}{r['pages_per_week']:>10.2f}{r['detected']:>10.3f}"
                  f"{r['acted']:>8.3f}{r['acted_se']:>8.3f}{star}")
    p = pm["peak"]
    print(f"    peak acted={p['acted']:.3f}+-{p['acted_se']:.3f} at {p['alarms']} alarms "
          f"({p['pages_per_week']:.2f} pages/wk)")
    print(f"    points within noise of the peak: {pm['n_within_noise_of_peak']}  "
          f"-> peak {'IS' if pm['peak_is_distinguishable'] else 'is NOT'} distinguishable")
    print(f"    first={pm['first']['alarms']} alarms acted={pm['first']['acted']:.3f}  "
          f"last={pm['last']['alarms']} alarms detected={pm['last']['detected']:.3f} "
          f"acted={pm['last']['acted']:.3f}")


    print("SEED STABILITY  (one seed is an anecdote)")
    print("=" * 92)

    ss = seed_stability()
    print(f"    harmed in {ss['harmed_in']}/{ss['seeds']} seeds   "
          f"delta range [{ss['min']:+.3f}, {ss['max']:+.3f}]  mean {ss['mean']:+.3f}")

    print("\n" + "=" * 92)
    print("E10 IS THE EFFECT REGIME-CONDITIONAL? capacity swept with power (40 seeds/point)")
    print("=" * 92)
    print(f"    {'capacity':>9}{'pages/wk':>10}{'load/cap':>10}{'triage':>8}"
          f"{'delta':>9}{'std err':>9}   verdict")
    cr = capacity_regime()
    for r in cr:
        verdict = ("HARMS" if r["delta_mean"] < 0 else "helps") if r["sign_is_claimable"] \
            else "no measurable effect"
        print(f"    {r['capacity']:>9.1f}{r['pages_per_week']:>10.2f}{r['load_ratio']:>10.2f}"
              f"{r['mean_triage']:>8.3f}{r['delta_mean']:>+9.3f}{r['delta_se']:>9.3f}   {verdict}")
    harming = [r for r in cr if r["sign_is_claimable"] and r["delta_mean"] < 0]
    if harming:
        print(f"    harm is claimable only at capacity <= {max(r['capacity'] for r in harming):.0f}"
              f"  (load/cap >= {min(r['load_ratio'] for r in harming):.2f})")
    else:
        print("    no capacity shows claimable harm -- the headline would not survive")


if __name__ == "__main__":
    main()
