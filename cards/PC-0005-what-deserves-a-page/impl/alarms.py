"""A model of alarms firing against a stream of real incidents and benign anomalies.

WHAT IS AND IS NOT MODELLED HERE
--------------------------------
This is a SIMULATOR, in the sense check 17 now makes explicit: it is a model of an external
phenomenon, not the phenomenon. Executing it proves the card's numbers faithfully preserve this
model. It says nothing about whether the model matches any real service.

What it deliberately does NOT model: alarm evaluation windows, metric aggregation lag, retry
storms, or anything about the operator's skill. Those are all real and all omitted, which is
why every claim derived from this file is grounded `simulator` and the card declares its
claim strength accordingly.

The one thing it DOES model faithfully is the accounting identity that makes this problem
non-algorithmic: a page is a claim on a finite human, and two alarms firing on one root cause
produce two claims for one problem.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Alarm:
    """One configured alarm.

    A FIELD THAT USED TO BE HERE. `precision` was declared on this dataclass, set on every
    fixture, quoted in the experiment names -- and **never read by any simulation logic**.
    `fire()` uses `recall` and `covers`; nothing consumed precision. A claim phrased "adding a
    LOW-PRECISION alarm harms" was therefore mislabelled: the two alarms being compared differed
    in precision (0.20 vs 0.75) AND in benign rate (3.0/wk vs 0.30/wk), and only the second did
    anything. Any reader would have concluded precision drove the result.

    Removed rather than implemented, because it was also REDUNDANT: precision is a consequence
    of `recall`, `covers` and `benign_rate_per_week` against the incident stream, so declaring
    it independently lets the label contradict the simulation. `measure.py` reports OBSERVED
    precision instead, which is the honest form -- and the only form an operator can get.

    Same shape as the gate's dead `must_cite_do_not_use_when`: a field that looked enforced
    and was not.
    recall    -- P(this alarm fires | an incident it covers is happening).
    covers    -- which failure modes this alarm can detect, by name. Two alarms sharing a
                 failure mode are CORRELATED, which is the source of page storms; a naive
                 count of alarms treats them as independent coverage.
    benign_rate_per_week -- how often it fires with no incident behind it at all.
    parent    -- name of an alarm that, when also firing, makes this one redundant. The
                 suppression hierarchy: not a filter on noise, a statement about causality.
    actionable_at_3am -- whether a woken human can actually do something. An alarm that is
                 true, precise, and un-actionable is still not a page.
    """
    name: str
    # (no `precision` -- see the docstring above; it was decorative and is now derived)
    recall: float
    covers: frozenset[str]
    benign_rate_per_week: float
    parent: str | None = None
    actionable_at_3am: bool = True


@dataclass
class Incident:
    week: int
    failure_mode: str
    detected_by: list[str] = field(default_factory=list)
    acted_on: bool = False


@dataclass
class Firing:
    week: int
    alarm: str
    real: bool                 # was there an incident behind it
    incident_index: int | None


def incident_stream(weeks: int, per_week: float, modes: tuple[str, ...],
                    seed: int) -> list[Incident]:
    """Poisson-ish incident arrivals over `weeks`, uniformly spread across failure modes."""
    rng = random.Random(seed)
    out: list[Incident] = []
    for w in range(weeks):
        n = _poisson(rng, per_week)
        for _ in range(n):
            out.append(Incident(week=w, failure_mode=rng.choice(modes)))
    return out


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth's method. Stdlib has no Poisson and the arrival count must be integral."""
    if lam <= 0:
        return 0
    import math
    l_, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l_:
            return k
        k += 1


def fire(alarms: list[Alarm], incidents: list[Incident], weeks: int,
         seed: int) -> list[Firing]:
    """Every firing, real and benign, in arrival order.

    Correlation is explicit: one incident is offered to EVERY alarm covering its failure mode,
    and each fires independently with its own recall. That is what produces N pages for one
    root cause -- the effect that makes 'add another alarm' a non-monotone decision.
    """
    rng = random.Random(seed)
    out: list[Firing] = []
    for i, inc in enumerate(incidents):
        for a in alarms:
            if inc.failure_mode in a.covers and rng.random() < a.recall:
                out.append(Firing(inc.week, a.name, True, i))
                inc.detected_by.append(a.name)
    for a in alarms:
        for w in range(weeks):
            for _ in range(_poisson(rng, a.benign_rate_per_week)):
                out.append(Firing(w, a.name, False, None))
    out.sort(key=lambda f: (f.week, f.alarm))
    return out


def suppress(alarms: list[Alarm], firings: list[Firing]) -> list[Firing]:
    """Drop a firing when its declared parent is firing in the same week.

    THE ZERO DETECTION COST IS STRUCTURAL, NOT MEASURED. `fire()` appends to `inc.detected_by`
    when an alarm fires; this function only filters the FIRING list and never touches
    `incidents`. `detected_fraction` is therefore computed from pre-suppression data and cannot
    change no matter what is suppressed. Publishing "detection cost 0.000" as an experimental
    result would be a tautology dressed as evidence -- precisely the failure this portfolio's
    mutation sweeps exist to find.

    What IS true and worth stating: suppression removes interruptions while leaving the parent
    to surface the incident, whereas every other way of reducing pages -- raising a threshold,
    widening a window, deleting an alarm -- removes a detection path. That asymmetry is real.
    The 0.000 is not evidence for it.

    Note also that suppression is WEEK-granular: if the parent fires on Monday for one incident
    and the child on Friday for an unrelated one, the child is still suppressed. It is a coarse
    temporal mute, not per-incident causal filtering.
    """
    by_name = {a.name: a for a in alarms}
    firing_weeks: dict[str, set[int]] = {}
    for f in firings:
        firing_weeks.setdefault(f.alarm, set()).add(f.week)
    kept = []
    for f in firings:
        parent = by_name[f.alarm].parent
        if parent and f.week in firing_weeks.get(parent, set()):
            continue
        kept.append(f)
    return kept


def dedupe(firings: list[Firing], per_week: bool = True) -> list[Firing]:
    """Collapse repeat firings of the SAME alarm within a week to one page."""
    seen, out = set(), []
    for f in firings:
        key = (f.alarm, f.week) if per_week else (f.alarm, f.week, f.incident_index)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def pages(alarms: list[Alarm], firings: list[Firing]) -> list[Firing]:
    """Only firings that would actually wake someone: actionable alarms.

    An un-actionable alarm is not a page even when it is correct. Modelling this separately
    from precision matters because they are different defects with different fixes: low
    precision is a tuning problem, un-actionability is a design problem.
    """
    ok = {a.name for a in alarms if a.actionable_at_3am}
    return [f for f in firings if f.alarm in ok]


def containment_holds(alarms: list[Alarm]) -> dict[str, bool]:
    """The CONTAINMENT TEST, executable: does each parent cover every mode its child covers?

    Contributed by a naive consumer that had never seen this card, while refusing a plan to expand a
    suppression hierarchy:

        "Does the parent detect every failure mode the child detects? If yes, the child is genuinely a
         consequence and muting it during the parent's incident is correct. If no, the child is an
         independent detector, and muting it is deleting coverage without recording the deletion. Most
         real hierarchies are built on co-firing -- these alarms tend to go off together -- and
         co-firing is correlation. Suppression requires containment."

    The card had no precondition on S3 at all, so this is a genuine gap it filled. `covers` is a
    frozenset, so the test is one operator: parent.covers >= child.covers.
    """
    by_name = {a.name: a for a in alarms}
    return {a.name: by_name[a.parent].covers >= a.covers
            for a in alarms if a.parent and a.parent in by_name}


def suppress_by_incident(alarms: list[Alarm], firings: list[Firing]) -> list[Firing]:
    """Suppress a child ONLY when its parent fired for the SAME INCIDENT.

    The card's `suppress()` is WEEK-granular, which is what makes it lossy: a parent firing on Monday
    for one incident mutes a child firing on Friday for an unrelated one. This is the per-incident
    alternative, and the comparison between the two is what prices the containment test.

    Note the honest cost, which is why this is not free: a BENIGN child firing has no
    `incident_index`, so it can never be matched to a parent incident and is therefore never
    suppressed. Incident-scoping saves strictly fewer pages than week-granular muting. It buys
    correctness with volume, not for free.
    """
    by_name = {a.name: a for a in alarms}
    fired_for: dict[str, set[int]] = {}
    for f in firings:
        if f.incident_index is not None:
            fired_for.setdefault(f.alarm, set()).add(f.incident_index)
    kept = []
    for f in firings:
        parent = by_name[f.alarm].parent
        if (parent and f.incident_index is not None
                and f.incident_index in fired_for.get(parent, set())):
            continue
        kept.append(f)
    return kept


def orphaned_incidents(incidents: list[Incident],
                       kept: list[Firing]) -> tuple[int, int]:
    """(orphaned, detected) -- incidents detected pre-suppression whose EVERY detector was muted.

    This is the metric C6 could not have. `suppress()` never touches `incidents`, so
    `detected_fraction` is structurally frozen and reporting it as suppression's cost is a tautology.
    Orphaning is not: it reads `inc.detected_by` (pre-suppression) and asks whether ANY of those
    detecting firings survived. An orphaned incident is one the monitoring genuinely stopped
    reporting, and nothing in a detection-side dashboard will show it.
    """
    survived = {(f.incident_index, f.alarm) for f in kept
                if f.real and f.incident_index is not None}
    orphaned = detected = 0
    for i, inc in enumerate(incidents):
        if not inc.detected_by:
            continue
        detected += 1
        if not any((i, name) in survived for name in inc.detected_by):
            orphaned += 1
    return orphaned, detected
