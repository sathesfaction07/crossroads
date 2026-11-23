"""The finite human. This is the file that makes the problem non-algorithmic.

Every other card in this portfolio has a cost model denominated in something a machine spends:
comparisons, bytes, deploys, wire-format cells. This one is denominated in attention, and
attention has a property none of those have -- **it is consumed by the WRONG answers too**.

A false positive costs nothing in a search index; a stale candidate pair is discarded for free.
A false positive here consumes the same scarce resource as a true one, which is why adding a
detector can make detection WORSE. That is not an algorithmic effect and no amount of tuning
the detector fixes it.

HONESTY ABOUT THE CURVE
-----------------------
`triage_probability` is a MODEL and its exact shape is not measured from anything. It is chosen
to satisfy three properties that are not in dispute -- p=1 at zero load, monotone decreasing,
and bounded below by a floor because a responder never stops entirely -- and to be
parameterised so that every claim built on it can be swept across the parameters rather than
asserted at one convenient setting. `measure.py` does exactly that sweep, and reports the
region where each finding holds AND where it fails.

A claim that survives only at one (capacity, k, floor) is an artifact of this file, not a
finding about paging. The sweep is how the two are told apart.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import alarms as A


@dataclass(frozen=True)
class Attention:
    """A responder's weekly capacity for being interrupted.

    capacity -- pages per week at which triage quality is halfway to the floor. Not a hard
                limit; there is no hard limit, which is precisely the trap.
    k        -- how sharply quality collapses past capacity. k=1 is a gentle slide, k=4 is a
                cliff. Both are defensible and they give different answers, so both are swept.
    floor    -- the irreducible probability a page is handled even under a flood. Never 0: a
                buried responder still catches something.
    """
    capacity: float = 5.0
    k: float = 2.0
    floor: float = 0.15

    def triage_probability(self, load: float) -> float:
        if load <= 0:
            return 1.0
        return self.floor + (1.0 - self.floor) / (1.0 + (load / self.capacity) ** self.k)


def weekly_load(pages: list[A.Firing]) -> dict[int, int]:
    out: dict[int, int] = {}
    for f in pages:
        out[f.week] = out.get(f.week, 0) + 1
    return out


def outcome(alarms: list[A.Alarm], incidents: list[A.Incident],
            page_list: list[A.Firing], real_firings: list[A.Firing],
            att: Attention, seed: int) -> dict:
    """Run the pages past a finite human and report what actually got handled.

    LOAD and ATTRIBUTION are deliberately separated, and the first version conflated them --
    a defect the measurement caught before any claim was written.

    That version counted load from the de-duplicated page list and then credited `acted_on` to
    the single incident attached to the surviving firing. De-duplication is keyed on
    `(alarm, week)`, so when two incidents in one week were caught by the same alarm the second
    lost its only detection. Worse, N correlated alarms produce N distinct dedupe keys and hence
    N independent chances to act -- so `acted_fraction` ROSE with the number of redundant
    alarms, 0.537 -> 0.870 across 1..6 alarms on ONE failure mode. That reads as "redundancy
    helps" and it is pure book-keeping.

    The honest model: a responder woken once for alarm X in week W investigates and resolves
    everything X saw that week. So `page_list` (deduplicated) sets the LOAD, while attribution
    walks the FULL real firing list. Interruptions and resolutions are different quantities and
    must be counted from different lists.
    """
    import random
    rng = random.Random(seed)
    load = weekly_load(page_list)

    # One decision per interruption, not per underlying incident.
    handled: dict[tuple[str, int], bool] = {}
    for f in page_list:
        p = att.triage_probability(load.get(f.week, 0))
        handled[(f.alarm, f.week)] = rng.random() < p

    paged_alarms = {f.alarm for f in page_list}
    for f in real_firings:
        if f.alarm not in paged_alarms or f.incident_index is None:
            continue
        if handled.get((f.alarm, f.week)):
            incidents[f.incident_index].acted_on = True

    n_inc = len(incidents)
    detected = sum(1 for i in incidents if i.detected_by)
    acted = sum(1 for i in incidents if i.acted_on)
    weeks = max(load) + 1 if load else 1
    real_pages = sum(1 for f in page_list if f.real)
    return {
        "incidents": n_inc,
        "detected_by_some_alarm": detected,
        "acted_on": acted,
        # The headline metric. Detection is not the goal; a detected incident nobody handled is
        # an outage with a paper trail.
        "acted_fraction": (acted / n_inc) if n_inc else 0.0,
        "detected_fraction": (detected / n_inc) if n_inc else 0.0,
        "pages_total": len(page_list),
        "pages_per_week": len(page_list) / weeks,
        "pages_real": real_pages,
        # What an operator experiences and can measure without knowing ground truth.
        "actionable_fraction_of_pages": (real_pages / len(page_list)) if page_list else 0.0,
        "peak_week_pages": max(load.values()) if load else 0,
        "mean_triage_probability": (
            sum(att.triage_probability(load.get(w, 0)) for w in range(weeks)) / weeks),
    }


def run(alarm_set: list[A.Alarm], *, weeks: int = 104, incidents_per_week: float = 0.5,
        modes: tuple[str, ...] = ("db_saturation", "dependency_timeout", "bad_deploy",
                                  "disk_full"),
        att: Attention | None = None, seed: int = 17,
        use_suppression: bool = True, couple_load: bool = True) -> dict:
    """One end-to-end experiment. `couple_load=False` is the ablation of the mechanism."""
    att = att or Attention()
    incs = A.incident_stream(weeks, incidents_per_week, modes, seed)
    firings = A.fire(alarm_set, incs, weeks, seed + 1)
    if use_suppression:
        firings = A.suppress(alarm_set, firings)
    real_firings = [f for f in firings if f.real]
    page_list = A.pages(alarm_set, A.dedupe(firings))
    if not couple_load:
        # Ablation: charge the responder only for real pages, as though benign ones were free.
        total = len(page_list)
        res = outcome(alarm_set, incs, [f for f in page_list if f.real], real_firings,
                      att, seed + 2)
        res["pages_total"] = total
        res["ablation"] = "benign pages consume no attention"
        return res
    return outcome(alarm_set, incs, page_list, real_firings, att, seed + 2)
