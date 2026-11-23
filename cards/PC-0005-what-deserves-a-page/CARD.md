# PC-0005 — Deciding what deserves to wake a human

| | |
| --- | --- |
| **Card** | PC-0005 |
| **Domains** | on-call design · observability · operational readiness · alarm portfolios |
| **Tests** | 31 |
| **Run** | `cd cards/PC-0005-what-deserves-a-page && python3 -m impl.measure` |
| **Related** | PC-0003 (retries generate pages) · PC-0004 (silent corruption needs symptom alarms) |
| **Claim strength** | `direction` — simulator magnitudes; the shapes transfer, the decimals do not |

> Evidence tags: `[executed]` a test in `tests/` fails if the claim is false · `[cited]` read
> from named real code · `[reasoned]` argued from the other two and not independently verified.

---

## 1 · Problem statement

Every incident review ends with "we should have had an alarm for that", and the alarm gets added.
Nobody's review ends with "we should delete four alarms". The portfolio therefore grows in one
direction only, and each individual addition is defensible: it is a real signal, it did fire
during a real incident, and someone senior asked for it `[reasoned]`.

The reason this compounds into harm is that the resource being spent is not storage or CPU but a
person's capacity to take a page seriously at 3am. That resource is consumed by every page,
including the ones that turn out to be nothing. So the cost of an alarm is not paid by the alarm —
it is paid by every *other* alarm, in the form of a responder who is fractionally less likely to
act on the next one `[executed]`.

This card exists because the decision has no context-free answer. The same alarm, unchanged,
measurably harms one team and measurably helps another; the thing that differs is not the alarm
but how loaded the responders already are `[executed]`. A card that just said "avoid noisy
alarms" would be wrong for a large class of readers, and this one measures where the line falls.

## 2 · Recognition signals

- The alarm count for a service only ever goes up, and no one owns deletion.
- Pages are routinely acknowledged and closed without any action taken — the "ack and go back to
  sleep" reflex.
- A recent incident was *detected* by an alarm that fired, and still ran long, because the page
  arrived in a batch with several others.
- Someone proposes an alarm on a **cause** (connection count, queue depth, CPU) for a failure
  mode already covered by a **symptom** alarm (error rate, latency, availability).
- You have a suppression / parent-child hierarchy and believe it is free.
- People argue about the right *number* of alarms without reference to how many pages per week the
  rotation currently absorbs.
- Alarm review is a coverage exercise — "which failure modes lack an alarm?" — with no matching
  question about what the existing ones cost.
- The team can state its detection coverage but not its pages per responder per week.

**Do not use this card when:** the signal does not interrupt a human (dashboards, async reports,
autoscaling triggers); the response is fully automated with no human in the loop; you are
designing the *automation* rather than the interrupt; the service has no on-call rotation; or you
need a defensible absolute alarm count — this card measured that no such number exists.

## 3 · Why the naive approach fails

The naive approach evaluates each alarm on its own merits: is it correct, is it precise, does it
cover a real failure mode? Every alarm that passes gets added. This fails for three measured
reasons.

**It optimises the metric that has already saturated.** Detection coverage is the number everyone
reports, and it barely moves. Over 20 seeds, going from 3 alarms to 33 raises the fraction of
incidents *detected* from **0.948 to 0.996** — a gain of 0.048 — while the fraction actually
*acted on* falls from **0.882 to 0.598**, a loss of 0.284 `[executed]`. Roughly a 6:1 trade
against, invisible to anyone tracking coverage.

**An alarm's cost is not a property of the alarm.** Holding portfolio and page volume fixed at
3.01 pages/week and varying only the responder's capacity, the *same* marginal alarm moves from
−0.091 handling (capacity 2) to **+0.014 (capacity 50)** — a sign flip, monotone across five
points `[executed]`. The folk rule "noisy alarms cause missed incidents" is not merely unproven
for a team with slack; in this simulator it is **false** there.

**Isolated judgement cannot express an interaction.** Because the harm depends on
load-versus-capacity, no per-alarm threshold — "precision must exceed 0.9", "no more than 10
alarms" — can encode the decision `[reasoned]`. The quantity that determines the sign is a
property of the *portfolio and the rotation together*, and is not visible from any single alarm's
definition.

There is also a trap in how people validate this. A single on-call rotation's lived experience is
one sample. Across 12 seeds the effect of adding one noisy alarm ranged from **−0.234 to +0.056**,
harming in 8 of 12 `[executed]`. One rotation can honestly report the opposite of the population
effect.

## 4 · Solution shapes

### Shape A — S1 · Symptom-first minimal portfolio

**Choose when** load/capacity is already high, or you are starting fresh. One alarm per
customer-visible failure mode; causes get dashboards, not pages.

Measured at 3 alarms: **0.69 pages/week, detected 0.948, acted 0.882 ± 0.011, actionable fraction
0.56** `[executed]`. **Limit:** detection is 0.948, not 1.0 — this shape knowingly trades ~5
points of coverage for handling, and if a failure mode is genuinely uncovered it does not tell you
to skip it.

### Shape B — S2 · Route by actionability, not by correctness

**Choose when** a signal is correct and precise but nothing can be done about it at 3am. It
becomes a ticket or a dashboard; `pages()` filters on `actionable_at_3am`, so the signal still
exists and still records detection — it just stops consuming attention.

Measured: moving one such alarm off the page path saved **0.57 pages/week** `[executed]`.
**Limit:** the handling effect is **not powered** (single seed, ~2 incidents) and is deliberately
not claimed. Real routing is also graded across five severities where this model is binary
`[cited]`.

### Shape C — S3 · Declared suppression hierarchy

**Choose when** there is genuine causal structure: a downstream alarm is a consequence of a known
upstream cause. Mute children while the parent fires.

Measured: saves **0.37 pages/week** `[executed]`. Its cost is real and invisible in the usual
metric — see **A4**. **Read that number as a decision:** 0.37 is roughly one third of one page per
week, which against a loaded rotation's 9–14 pages per responder per week is a rounding error — so
**suppression is not a volume lever.** If page volume is the problem this shape does not touch it, and
deletion or re-routing is the only thing that does; the saving lands in windows where a parent is
already paging, which is exactly where one more page costs least. **Limit:** do not use as a
substitute for deleting alarms.

### Shape D — S4 · Raise capacity instead of pruning

**Choose when** the alarms are genuinely all valuable and the rotation is the bottleneck. Add
responders, reduce non-page toil, or move work out of the rotation. This is the lever people skip.

Measured at fixed load: capacity 2 → −0.091, capacity 10 → −0.014 (unmeasurable), capacity 50 →
**+0.014** `[executed]`. **Limit:** capacity is a model parameter chosen, not fitted to any real
team, so this shape is the one most exposed to that limitation.

### Shape E — S5 · Track the actionable fraction as the health signal

**Choose when** you can adopt only one thing. The share of pages with a real incident behind them
needs no ground truth about missed incidents — it is computable from existing ticket history.

Measured to fall **0.56 → 0.19 → 0.12** at 3, 9 and 27 alarms, monotonically `[executed]`.
**Limit:** it is a proxy, and a low actionable fraction on a rotation with slack is not
necessarily harmful (see Shape D).

## 5 · Alternatives rejected

| alternative | why it was rejected |
| --- | --- |
| **R1 · Per-alarm precision or recall thresholds** | The harmful quantity is not a per-alarm property. The identical alarm measures −0.091 at capacity 2 and +0.014 at capacity 50, so no threshold on the alarm alone can produce the right answer `[executed]`. This was also this card's own first framing, and it was wrong — the simulator's `precision` field turned out never to be read by any logic. |
| **R2 · A fixed alarm budget, "at most N per service"** | There is no distinguishable interior optimum to budget against. The best portfolio measured was the smallest tested (3 alarms, 0.882 ± 0.011) and it was not separable from its neighbour `[executed]`. Any specific N would be fabricated. This corrects an earlier draft of this card, which named 6 from a single seed. |
| **R3 · Optimising detection coverage** | Coverage saturates far earlier than anyone budgets for: 3 → 33 alarms raises detection 0.948 → 0.996 and lowers handling 0.882 → 0.598 `[executed]`. Roughly 6:1 against, and entirely invisible to a team tracking coverage. |

## 6 · Decomposition

1. **Enumerate customer-visible failure modes** → the things a page could legitimately be about.
   Causes are not on this list.
2. **Measure current pages per responder per week** → `load`, in pages·week⁻¹.
3. **Estimate capacity** → the page rate at which triage begins to degrade, in the same unit.
4. **Compute load ÷ capacity** → the regime. *This determines the sign of every decision below.*
5. **Measure the actionable fraction of recent pages** → the ground-truth-free health signal.
6. **For each proposed alarm, ask what it covers that nothing else does** → coverage delta,
   usually zero for cause-level alarms.
7. **Choose routing per alarm** → page / ticket / dashboard.
8. **If load ÷ capacity is high, choose between pruning and raising capacity** → both are levers.

Edges: **2→4** and **3→4** (the ratio is undefined without both, in the same unit — the most
common place the analysis silently breaks); **4→6** (the sign of "is this alarm worth it" is set
by the regime, so per-alarm judgement *cannot* be answered first — this edge is the card's main
structural claim); **1→6** (coverage delta is defined against the failure-mode list, not the
existing alarm list; comparing against existing alarms is how cause-level duplicates get
justified); **4→8** (the prune-versus-capacity choice only arises in the loaded regime);
**5→8** (the actionable fraction is what tells you pruning worked, because detection will not
move); **6→7** (an alarm with zero coverage delta can still be worth keeping as a ticket).

## 7 · Cost & scale model

```
triage(load) = floor + (1 - floor) / (1 + (load / capacity) ** k)
```

`capacity` is *defined* as the load at which triage falls halfway to the floor. `floor` exists
because a buried responder still catches something; without it the model predicts total blindness
and every high-volume claim becomes unfalsifiable. Headline runs use `capacity=5.0, k=2.0,
floor=0.15` — **chosen, not fitted**.

**C1 · a marginal high-benign-rate alarm measurably harms a small portfolio.** −0.044 / −0.059 /
−0.052 at 3 / 6 / 9 alarms, SE 0.011 / 0.018 / 0.013, 40 seeds `[executed]`. Does not generalise
as a magnitude; the transferable content is that the cost is real and paid in *handling*.

**C2 · the same alarm has no measurable effect once the portfolio is large.** Deltas −0.007 …
+0.019 across 12–27 alarms, all within 2×SE, 40 seeds `[executed]`. The claim is the *absence* of
a measurable effect, not a zero.

**C3 · detection saturates almost immediately while handling collapses.** detected 0.948 → 0.996
(+0.048); acted 0.882 → 0.598 (−0.284) over 3 → 33 alarms, 20 seeds `[executed]`.

**C4 · there is no distinguishable interior optimum.** Peak 0.882 ± 0.011 at 3 alarms, one point
within noise, `peak_is_distinguishable = false`, 20 seeds across 31 sizes `[executed]`. A negative
result, and the one that most changes behaviour — it forbids the alarm-budget answer.

**C5 · the actionable fraction tracks the collapse and needs no ground truth.** 0.56 → 0.19 →
0.12 at 3 / 9 / 27 alarms, 40 seeds `[executed]`.

**C6 · suppression's cost is invisible in detection and real in handling.** Detection cost 0.000
is *structural*; the handling gap is mean **+0.0120**, max **+0.0588**, and exactly **0.0000** with
suppression off — 30 seeds at infinite capacity, so fatigue cannot contribute `[executed]`.

**C7 · the effect is regime-conditional and its sign flips with responder slack.** −0.091 /
−0.059 / −0.014 / +0.010 / +0.014 at capacity 2 / 5 / 10 / 20 / 50, SE 0.016 / 0.018 / 0.009 /
0.007 / 0.005, monotone across all five, 40 seeds with page volume held fixed `[executed]`. Five
monotone points are stronger evidence than any one clearing 2×SE.

**C8 · attention coupling is the mechanism, not a correlate.** Over 40 strided seeds on both arms:
with the mechanism live the harm is claimable (**−0.0442**, SE 0.0114); with `couple_load=False`
the delta is **not distinguishable from zero** (+0.0135, SE 0.0076) `[executed]`. An effect that
survived its own mechanism being switched off would be a coincidence. Note the disabled arm is not
*exactly* zero — the honest claim is indistinguishability, not absence. This was raised from a
single seed because the gate objected that the experiment validating the mechanism was held to a
weaker standard than the experiments measuring it.

**C9 · suppression needs containment, or better, incident scoping.** A parent/child pair is only safe
if the parent covers **every** failure mode the child covers. Real hierarchies are usually built on
*co-firing* — "these always go off together" — which is correlation, not containment. Over 30 seeds
with the child held fixed and only the parent's coverage varying, at week granularity co-firing
**orphans 12.5%** of detected incidents against **2.9%** under containment `[executed]`; an incident is
*orphaned* when every alarm that detected it was muted, which no detection-side dashboard can show.
But **incident-scoped** muting drives orphaning to **exactly 0.0000 in both rows** — so containment is
a mitigation for coarse temporal muting, not the underlying requirement. Scoping is not free: it cannot
mute benign child firings (a benign firing has no incident to match against) and gives up **44%** of
the page relief, 0.150 vs 0.265 pages/week. Orphaning is a **different quantity** from C6's 1.2%
handling gap and must not be quoted as a revision of it. *Contributed by a naive consumer that had
never seen this card; the 2×2 that demoted containment to a mitigation came from pricing it.*

**Breakpoints** (units stated because a bare number here is a trap):

| quantity | value | unit | meaning |
| --- | --- | --- | --- |
| load ÷ capacity | **≥ 0.60** | ratio of pages·week⁻¹ to pages·week⁻¹ | adding a high-benign-rate alarm measurably costs handling (−0.059, SE 0.018) |
| load ÷ capacity | **≤ 0.30** | same | no measurable effect either way (−0.014, SE 0.009) |
| load ÷ capacity | **≈ 0.06** | same | the same alarm measurably *helps* (+0.014, SE 0.005) |
| portfolio size | **3** | alarms | detection is already 0.948; saturation is this early |
| actionable fraction | **< 0.20** | fraction of pages with a real incident behind them | the degraded band, reached at 9+ alarms in this fixture |

**Honest limit on the axes.** The first three breakpoints come from the capacity sweep, which
measures load/capacity *after* the treatment alarm is added; the last two come from the portfolio
sweep, which reports page rate *before*. **They are not interchangeable and must not be fused
into one unified threshold.** They agree only that the sign is not context-free.

## 8 · Code

`impl/` is stdlib-only Python and depends on no codebase existing.

- **`alarms.py`** — `Alarm` (recall, covered failure modes, `benign_rate_per_week`, optional
  `parent`, `actionable_at_3am`), `Incident`, `Firing`; `incident_stream`, `fire`, `suppress`,
  `dedupe` (keyed `(alarm, week)` — one wake-up per alarm per week), `pages`.
- **`attention.py`** — `Attention` (the curve above), `weekly_load`, `outcome`, `run`. `run` takes
  `use_suppression` and `couple_load`; the latter is the **ablation switch** that makes benign
  pages free, so the mechanism can be turned off and the effect shown to vanish.
- **`measure.py`** — E1–E10 plus the 45-cell parameter sweep. Nothing in this card states a number
  this file has not printed.

There is deliberately **no** `precision` field. It was there, set on every fixture, quoted in
experiment names — and no simulation logic ever read it, so "adding a low-precision alarm harms"
attributed the effect to a field that did nothing. The real lever is `benign_rate_per_week` (3.0
against 0.30). It was removed rather than implemented because it is derivable, and a declared copy
of a derived quantity can silently contradict the model `[reasoned]`.

## 9 · Verification

`tests/test_pc0005.py` — **31 tests**, each naming the claim it makes falsifiable.

Ten are **exact invariants** holding for any parameters, so they test the model's shape rather
than the chosen settings: `triage(0) == 1.0`, the floor is never breached, monotone decrease,
`capacity` really is the halfway point, dedupe keying, actionability filtering,
`acted ≤ detected`, and — with suppression off — `acted == detected` exactly at infinite capacity.

Twelve pin **published numbers** with tolerances from measured standard errors (0.005–0.020) at
roughly 3×SE. Seeds are strided by 3 because `run(seed=S)` consumes S, S+1 and S+2; stepping by 1
made consecutive trials share two of three RNG streams and understated every standard error by
~38%.

Four cover **C9's containment/scoping result**: that the containment test is a subset test on `covers`,
that incident-scoped muting cannot orphan an incident (asserted for both containment and co-firing
parents across ten seeds, since the zero is exact by construction), that co-firing orphans strictly
more than containment at week granularity, and that incident-scoping saves strictly fewer pages.


Five are **regressions** for authoring defects: attribution conflation, the decorative `precision`
field, the single-seed sign flip, seed spread exceeding the effect, and capacity being inert.

**Mutation status, stated precisely rather than rounded up.** The original **27** were mutation-verified
as a set: seven defects were reintroduced one at a time — including making `capacity` inert, the direct
attack on C7 — and the suite failed on every one, then returned byte-identical and green. The **four**
C9 tests were verified by one targeted mutant: degrading `suppress_by_incident` back to week
granularity, which killed exactly the two scoping-dependent tests and left the other 29 passing. So 29
of 31 have an individually demonstrated killing mutant; the two ordering tests are covered only as part
of that set.

**What verification does not establish.** These tests prove the simulator behaves as described and
that the numbers reproduce. They cannot establish that it resembles a real on-call rotation.
`capacity`, `k` and `floor` are chosen, not fitted, and C7 shows the headline's *sign* depends on
`capacity`. That is why `claim_strength` is `direction` `[reasoned]`.

## 10 · Anti-patterns

**A1 · the post-incident ratchet** — *Diagnostic:* an alarm is added after every review; the count
rises monotonically and nobody owns deletion. 3 → 33 alarms takes actionable fraction 0.56 → 0.12
and handling 0.882 → 0.598 `[executed]`. *Fix:* every addition names an uncovered failure mode
from step 1, or it is a dashboard.

**A2 · judging an alarm in isolation** — *Diagnostic:* review asks "is this alarm good?" and never
"what is our load ÷ capacity?" Identical alarm, −0.091 at capacity 2 and +0.014 at capacity 50
`[executed]`. *Fix:* compute the ratio first; the ratio sets the sign.

**A3 · optimising coverage** — *Diagnostic:* the alarm review is a gap analysis with no cost side.
+0.048 detection for −0.284 handling `[executed]`. *Fix:* track handling, or its observable proxy
in Shape E.

**A4 · believing suppression is free** — *Diagnostic:* "the hierarchy means we lose nothing." The
detection cost of 0.000 is a **tautology** — detection is recorded before suppression runs, so it
cannot move. The real cost is in handling: at infinite capacity, where nothing is lost to fatigue,
week-granular suppression still loses a mean **1.2%** of incidents (max 5.9% over 30 seeds),
because the muted child was sometimes the incident's only page `[executed]`. *Fix:* scope
suppression to the incident, not the week, and never quote a zero that is structural. **And read the
size as a decision, because it is why this anti-pattern survives:** a mean 1.2% loss with a 5.9% worst
case is *small in absolute terms*, and that smallness is not reassurance — it is the mechanism of the
trap. A loss that rare always arrives as one memorable incident with no pattern around it, so every
honest team that hits it classifies it as a one-off and is wrong. Do not wait for a rate to become
visible; at this magnitude it will not. Treat the **first** orphaned incident as the mechanism firing.

**A5 · generalising from one rotation** — *Diagnostic:* "we added it and nothing bad happened."
Across 12 seeds the delta ranged −0.234 to +0.056, harming in 8 of 12 `[executed]`. *Fix:* treat
one rotation's experience as a single sample from a distribution wider than the effect.

**A6 · paging on a correct but un-actionable signal** — *Diagnostic:* a page whose runbook says
"file a ticket in the morning". Re-routing saved 0.57 pages/week `[executed]`. *Fix:* route by
what can be done at 3am. The handling benefit of this move is **unmeasured** — single seed.

**A7 · setting an alarm budget** — *Diagnostic:* "max 10 alarms per service." No distinguishable
interior optimum; the best portfolio tested was the smallest and not separable from its neighbour
`[executed]`. *Fix:* budget the page rate against capacity, which has units and a measured
breakpoint, rather than the alarm count, which does not.

**A8 · building a suppression hierarchy on co-firing instead of containment** — *Diagnostic:* the
parent/child pairs were chosen because "these alarms always go off together", and an incident is
eventually found late by something other than monitoring. Co-firing parents orphan **12.5%** of
detected incidents versus **2.9%** under containment, and detection-side metrics report **0.000** cost
in every one of those cases `[executed]`. *Fix:* run the containment test on every existing pair; any
failure is a deletion decision or a standalone alarm, not a child. Better, re-key the mute to the
**incident** rather than the week, which zeroes orphaning regardless of containment and makes the test
moot — budgeting for roughly half the volume relief.

**A9 · never auditing for children that have never fired** — *Diagnostic:* a child alarm nobody has
seen fire in months is assumed to be quiet, and the suppression hierarchy is exactly what makes its
silence indistinguishable from being broken. *Fix:* audit for children that have **never fired** — a
child nobody has seen fire is more often broken than quiet, and the hierarchy hides it. Run this on the
existing hierarchy before expanding it: a never-fired child is either dead configuration or a detector
whose failure mode has not occurred yet, and those need opposite responses. The hierarchy cannot tell
you which, because a muted child and a broken child produce the same evidence — nothing. `[reasoned]`
— **no measured magnitude**; argued from the same asymmetry C6 measures. *Contributed verbatim by a
naive consumer, twice, unprompted, and missed by every arm of every run while it sat inside A8.*

## 11 · Escalation

| symptom | action |
| --- | --- |
| Actionable fraction below 0.2 and falling | Stop adding alarms. Prune or raise capacity before any new coverage work. |
| An incident was detected but ran long, and other pages fired in the same window | This is the handling failure this card is about; audit page volume in that window, not alarm coverage. |
| load ÷ capacity above 0.6 and pruning is politically blocked | Escalate as a staffing and toil decision (Shape D), not an observability one. The measured lever is capacity. |
| Suppression hierarchy in place and incidents are being missed | Check whether a muted child was the only detector; week-granular suppression mutes across unrelated incidents. |
| A proposed alarm covers a mode already covered | Route to dashboard or ticket by default; require a named uncovered failure mode for a page. |
| Nobody can state the rotation's pages per week | Stop. Steps 2–4 are prerequisites; without them every later judgement has an undetermined sign. |
| Someone quotes a number from this card onto a real rotation | **Refuse.** These are simulator magnitudes at `claim_strength: direction`; the transferable content is the ordering and the shapes, not the decimals. |

## 12 · Evidence ledger

**Executed** — C1 through C8 in §7, each pinned by a test that fails if the claim is false
`[executed]`. Sample sizes: 40 seeds (C1, C2, C5, C7), 30 (C6), 20 (C3, C4). Every run is 104
weeks at 0.5 incidents/week over 4 failure modes, so ~52 incidents per run — which is why a delta
of 0.019 is *one incident* and why nothing single-seed is published.

**Cited, external to this portfolio** `[cited]` — corroborates *relevance*, not magnitude:

- Real production CDK alarm portfolios cluster at **10–12 per monitoring stack** — five
  monitoring stacks read across two ML-platform organizations (source private to their
  owners): alarm counts 12, 11, 11, 11, 10. Real services sit
  in exactly the band where the powered curve shows handling already down to 0.68–0.75 from 0.882.
  *Honest limit:* this establishes the **regime** is real, not that the magnitudes are. Counting
  `new *Alarm(` per file is also a proxy — some stacks compose alarms in loops or factories.
- A production page-versus-ticket alarm-routing module (same corpus, source private) —
  severity-graded routing across four levels with an owning-team escalation target. Confirms Shape B
  is existing practice with first-class tooling, and shows real routing is **graded** where this
  model is binary. *Honest limit:* that mismatch is a limitation of the simulator, not the
  practice — a five-level dial can express "wake someone slowly", which this model cannot
  represent at all.

**Measured and deliberately NOT published**

- E1 at seed 17 gave **+0.056** ("the noisy alarm helps"); 40 seeds give −0.044. Same experiment,
  opposite sign, because one incident out of ~52 is 0.019. Kept as a regression test.
- E6's "FIRST HARM at 7 alarms / 2.55 pages per week" — a single-seed sequence swinging −0.148,
  −0.037, −0.148, −0.315, 0.000, +0.019. Noise with a decimal point.
- E7's "peak acted 0.907 at 6 alarms" — **overturned** by the powered run. 6 had been drafted as
  the recommended portfolio size; with power the peak is at the smallest size tested and is not
  separable from its neighbour.
- E3's "detection cost 0.000" as a *measurement* — structural, see **A4**.
- E5's handling delta (−0.037) — one seed, ~2 incidents. Only the 0.57 pages/week saving is
  reported.
- The 45-cell parameter sweep's per-cell verdicts ("harms in 9/45") — one seed per cell. Only the
  coarse pattern was trusted, and only after the capacity sweep reproduced it with 40 seeds.

**Authoring note.** Measured first, written second. Six defects were found before any prose
existed — including an attribution bug that made redundant alarms appear to *help*, a fixture
sitting in a regime where the intended effect was unmeasurable, and a decorative field the
experiments were named after. Two drafted claims were overturned. One test failed for demanding
less power of itself than the claim demanded; one failed because its **premise** was wrong, and
investigating rather than loosening it produced C6 — the card's most useful finding `[reasoned]`.
