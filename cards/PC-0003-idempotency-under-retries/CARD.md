# PC-0003 — Idempotency under retries

| | |
|---|---|
| **Card** | PC-0003 |
| **One line** | A retried operation must not apply twice, and the shape that guarantees it is chosen by the **effect algebra** — not by the transport, the retry rate, or the queue's delivery guarantee. |
| **Domains** | distributed-systems · api-design · data-integrity · queue-consumers |
| **Shapes** | 4 (all implemented) |
| **Tests** | 36 |
| **Measured on** | a deterministic at-least-once delivery simulator, seed 20260906, 4,000 logical operations, 4,667 deliveries |
| **Composes with** | PC-0001 (near-duplicate detection) · PC-0002 (embedding generation) |

---

## Problem statement

A caller sends an operation and does not hear back. It cannot distinguish *never arrived*
from *applied, and the acknowledgement was lost*. So it retries. Every retry in this card's
simulator is of the second kind: the effect **already happened**, and the duplicate is the
cost of the caller's uncertainty rather than of any failure in the transport. `[executed]`

That framing decides everything downstream, and getting it backwards is what makes people
skip idempotency entirely: model duplicates as *lost requests being resent* and retries look
harmless, because in that model the effect never applied. Measured on 4,000 operations with a
15% acknowledgement-loss rate and at most 4 attempts, 667 of 4,667 deliveries were duplicates
(0.1668 per operation) and 573 operations (14.32%) were retried at least once. `[executed]`

The question this card answers is not "how do I deduplicate" but "**what does the effect
do**, and therefore which of four shapes is available to me". Three of the four cost nothing
in durable state; one costs a row per operation; and the wrong choice is measurably worse
than doing nothing at all.

## Recognition signals

- The caller retries on timeout — and a timeout is indistinguishable from a lost reply.
- The transport is at-least-once: SQS, Kafka, a webhook sender, a pipeline replay, or simply
  a client with a retry policy. `[reasoned]`
- Totals, balances or row counts drift **upward** after an incident and nobody can say by how
  much.
- The same operation appears twice in an audit log under two different request ids.
- Someone asks "is this safe to replay?" and the answer is a discussion rather than a
  property of the code.
- An at-least-once queue is being treated as exactly-once because its documentation used the
  phrase "exactly-once" about *delivery into the consumer*. `[reasoned]`

**Do not use this card when** the effect is a pure read; when the operation is already an
assignment and duplicate application is the only worry (measured: 667 duplicates applied, **0
of 1,334 rows wrong**); when what you need is exactly-once *delivery* or ordering rather than
exactly-once *effect*; when the retry window is unbounded so no TTL can be sized; or when
concurrency on one row is the real problem, which wants isolation levels rather than tokens.

## Why the naive approach fails

It fails **conditionally**, and that is what makes it dangerous. The identical delivery
stream through the identical handler is correct under one effect algebra and corrupting under
the other: `[executed]`

| effect | duplicate applications | rows wrong | verdict |
|---|---|---|---|
| `state[k] = v` (assignment) | 667 | 0 of 1,334 | **CORRECT** |
| `state[k] += v` (increment) | 667 | 501 of 1,334 | **WRONG** |

So "we get duplicates" is not a finding, and a duplicate-delivery dashboard cannot tell you
whether you have a problem. The number that matters is what the duplicates *did*.

The failure is also silent. A naive increment handler returns `ok` for all 4,667 deliveries;
nothing raises, no status differs, and the corruption is visible only by comparing totals
against an oracle that most systems do not have. `[executed]`

## Solution shapes

### Shape A — natural idempotency: express the effect as an assignment

Rewrite the operation so that applying it twice leaves the same state. No key, no store, no
TTL, no client cooperation. Measured under the assignment algebra: 667 duplicate
applications, **0 rows wrong, 0 durable writes**. `[executed]`

Available only when the effect does not depend on the prior value. Forcing it onto an
increment is anti-pattern **A5**, and it is the most damaging single mistake in this card.

### Shape B — reservation carrying a request hash and a committed flag

The client supplies a stable token. The server reserves it, applies the effect, then marks the
reservation committed and stores the response beside it. A retry that finds an **uncommitted**
reservation for its own request hash *resumes* the work; one that finds a committed
reservation replays the stored response. With a crash injected into the first delivery of
every one of the 573 retried operations: **0 lost, 0 duplicated, 0 rows wrong**. `[executed]`

This shape is the reason the card's recommendation changed mid-authoring — see Verification.
It is also the only shape here that detects a reused token carrying a *different* request.

### Shape C — conditional write (compare-and-set) on the row version

The client reads the row version, then writes conditionally on it. The first attempt matches
and applies; the retry carries a stale version and is rejected. Measured: **667 conflicts —
exactly the 667 duplicate deliveries** — with 0 duplicate applications, 0 lost operations and
**0 durable dedupe rows**. `[executed]`

The cost is ambiguity rather than state: a losing CAS cannot distinguish "my own earlier
attempt already applied this" from "a different writer got there first". All 667 rejections
carry that ambiguity, so this shape is wrong when the caller must be told which happened.

### Shape D — content hash scoped to the target row

Derive the key from `hash(row, payload)` when no client token and no row version exist.
Scoping to the row cut the false-merge rate from **0.7545 to 0.0003** at 1,000 distinct
payload values — but left **0.0570** when a quarter of operations were legitimately
identical. `[executed]`

A fallback, never a default: no function of the request content can separate a retry from a
genuine repeat, because they differ in neither row nor bytes.

**Selection rule.** Ask what the effect *does* before asking how it arrives. Assignment →
**A**. Otherwise, client token available → **B**. No token but a row version → **C**. Neither,
plus high-entropy payloads *and* no possibility of legitimate duplicates → **D**.

## Alternatives rejected

| alternative | why it was rejected |
|---|---|
| **R1 — rely on the transport's exactly-once delivery** | The guarantee covers delivery into the consumer, not application of your side effect. A consumer that reads once and dies before committing still needs a replay-safe effect, so the guarantee relocates the problem instead of solving it. `[reasoned]` |
| **R2 — hold a per-row lock for the operation's duration** | Serialises unrelated operations on the same row, converting a correctness problem into an availability one. It also fails the crash case outright: a lock lost on process death leaves no record of whether the effect applied. `[reasoned]` |
| **R3 — never expire dedupe keys** | Removes TTL sizing by making the key space grow without bound, a capacity problem with no ceiling. Real internal code picks a long TTL (7 days) rather than none, which is the honest version of this tradeoff. `[cited]` |

## Decomposition

1. **Determine the effect algebra** — assignment or not. This single answer eliminates three
   of four shapes and is the only step that cannot be skipped.
2. **Determine whether the client can supply a stable token** — if not, Shape B is unavailable
   regardless of how much you want it.
3. **Choose the shape** — A, B, C or D.
4. **Make the dedupe record resumable** — a reservation with `committed` and a request hash,
   or one atomic transaction. Skipping this is anti-pattern A1.
5. **Size the TTL from the total retry window**, not the retry interval.
6. **Store the response, not just the key.**
7. **Monitor for the silent failures** — lost operations and reused tokens, neither of which
   shows up in business-state checks.

Edge 1→3 carries the weight: an assignment effect makes every other shape pure cost. Edge
4→6 is where the response has to live, because the reservation is the only record that
outlives the request. Edge 6→7 exists because a replay returning no body leaves business
state **correct**, so no data-quality alarm can ever see it. `[executed]`

## Cost & scale model

**C1 — duplicate deliveries are a property of the retry policy, not an exception.**
4,667 deliveries for 4,000 operations; 667 duplicates (0.1668); 573 operations retried
(0.1432); attempts histogram `{1: 3427, 2: 488, 3: 76, 4: 9}`. `[executed]`

**C2 — the effect algebra decides whether duplicates matter at all.**
Same stream, same handler: 501 of 1,334 rows wrong under increment, 0 under assignment.
`[executed]`

**C3 — a crash between the two writes is wrong in one of two opposite directions, unless the
reservation is resumable.** Key-first lost 573 operations; effect-first duplicated 573; both
left **501 rows wrong**. A resumable reservation and a single atomic transaction both scored
0/0/0. Atomicity is *sufficient but not necessary*. `[executed]`

**C4 — the TTL must exceed the total retry window, and the failure is a staircase.**
With a 20-tick retry interval and 4 attempts: TTL ≤ 20 → **all** 667 duplicates re-execute;
21–40 → 0.1274; 41–60 → 0.0135; ≥ 61 → 0. Sizing the TTL to the *interval* still
re-executes 12.74% of duplicates. `[executed]`

**C5 — a content-derived key merges operations it should not, for two independent reasons.**
At 1,000 distinct payload values with **zero** legitimate duplicates, an unscoped hash lost
0.7545 of operations to birthday collision alone; scoping to the row cut that to 0.0003. At
high entropy with a 25% legitimate-duplicate rate, unscoped lost 0.2420 and scoped still lost
0.0570. An unscoped key conflates the two causes. `[executed]`

**C6 — the shapes differ by a whole class of durable state.**
Shape B: 4,000 durable writes and 4,000 extra rows for 4,000 operations. Shapes A and C: 0
and 0. Under assignment, that 4,000-row store buys nothing — the naive handler was already 0
rows wrong. `[executed]`

**C7 — a reused token carrying a different request is answered with the first request's
response.** A $250 operation received the $100 body, was never applied, and no status
distinguished it: `reuse_detected = false`. The reservation shape rejected it. `[executed]`

**Breakpoints.** TTL 61 ticks = (attempts−1) × interval + 1. Legitimate-duplicate rate above
**0** disqualifies Shape D. 1 durable row per operation is Shape B's price. 667 ambiguous
rejections per 4,000 operations is Shape C's.

## Code

All four shapes and all three write orderings are implemented in `impl/`, stdlib only, so
`[executed]` means "re-runs wherever the gate runs".

```python
def reserve_then_commit(store, req, *, crash=False, ttl=100):
    rh = request_hash(req)
    res = store.get_reservation(req.idem_key)
    if res is None:
        store.put_reservation(req.idem_key, req.logical_id, rh, ttl)
        if crash:
            raise Crash("crashed after reserving, before applying -- but resumable")
        store.apply(req)
        store.commit_reservation(req.idem_key, req.payload)
        return Response("ok", req.payload)
    if res.request_hash != rh:
        return Response("key-reuse-rejected", None)
    if res.committed:
        return Response("ok-replayed", res.response)
    store.apply(req)                      # reserved but never committed: resume it
    store.commit_reservation(req.idem_key, req.payload)
    return Response("ok-resumed", req.payload)
```

The two-line difference that makes a handler silently wrong:

```python
if self.algebra == INCREMENT and not force_assign:
    self.total[req.logical_id] = self.total.get(req.logical_id, 0) + req.amount
else:
    self.total[req.logical_id] = req.amount        # force_assign: 1333 rows wrong
```

Reproduce every number with `python3 -m impl.measure`.

## Verification

36 tests, run by the depth gate. Every published number is pinned, including the staircase
treads and both content-hash causes separately.

**Real code changed the recommendation.** The simulator's first conclusion was that the
dedupe write and the effect must be **atomic**, because both orderings measured wrong (573
lost or 573 duplicated). Reading a real internal reservation store —
`IdempotencyReservationDao` — showed a `tryReserve` conditional put stamping a `requestHash`
"so a replay can detect a reused token carrying a different request", plus a
`releaseIfOwnedBy` compensation path and a 7-day TTL. That implies the weaker and more
achievable requirement actually needed: the reservation must be **resumable**, not atomic.
Shape B was then implemented and measured at 0/0/0. `[cited]`

**Three measurements were discarded as simulator artifacts rather than published:**

1. A 75% content-hash loss rate that was a birthday collision from a 999-value payload space.
   Publishing it would have described the fixture rather than the technique. Payload entropy
   is now an explicit parameter and is stated with every number that depends on it.
2. A CAS handler that compared an attempt counter against a row version shared by three
   operations, reporting 2,355 false losses. The number was plausible, which is exactly why
   it was dangerous.
3. A boolean `CORRECT`/`WRONG` verdict that could not distinguish over-counting from
   computing a different function — it hid the A5 finding entirely until replaced by a
   per-row count.

## Anti-patterns

**A1 — a dedupe write that is neither atomic with the effect nor resumable.** After a crash,
totals are short or inflated depending on an ordering nobody documented. Measured: 573 lost
(key-first) or 573 duplicated (effect-first), **501 rows wrong either way**. `[executed]`

**A2 — deriving the dedupe key from the payload.** Deduplication appears to work while a
fraction of real operations silently never happen. Measured: 0.7545 lost at 1,000 payload
values with zero legitimate duplicates; 0.2420 at high entropy with a 25% legitimate rate.
`[executed]`

**A3 — storing the key but not the response.** All 667 replays returned no body, while
`rows_wrong` stayed **0**. The data is right and the API is wrong, so no data-quality alarm
can detect it. `[executed]`

**A4 — sizing the TTL to the retry interval instead of the total retry window.** Duplicates
reappear only for the slowest retries, so it looks intermittent and load-related. Measured:
0.1274 re-executed at TTL 21–40 against a 20-tick interval. `[executed]`

**A5 — retrofitting assignment semantics onto an increment effect.** No error, no duplicate,
and every total with more than one operation quietly wrong: **1,333 of 1,334 rows, 2.66×
more damage than the 501 the naive handler causes.** The cheap fix is worse than no fix.
`[executed]`

**A6 — adding a dedupe store to a workload that is already idempotent.** 4,000 durable
writes and 4,000 extra rows against a naive handler that was already 0 rows wrong under the
same 667 duplicate applications. `[executed]`

**A7 — accepting a reused token without comparing the request.** The client receives a stale
success for an operation that never ran; `reuse_detected` was false and nothing in the
response distinguished it. `[executed]`

## Escalation

| symptom | action |
|---|---|
| Totals drifted upward and the size is unknown | Check whether the dedupe write is resumable. A non-atomic effect-first ordering duplicates exactly the retried operations — a countable, recoverable set. |
| Operations are **missing** rather than duplicated | Suspect a key-first non-resumable ordering, or a content-derived key merging distinct operations. Both lose work silently and neither raises. |
| Clients report retries returning success with no body | The response is not stored beside the key. Business state is fine and no data alarm will fire; fix the record shape rather than hunting the data. |
| Duplicates appear only under load | Compare the TTL against (attempts − 1) × retry interval, not against the interval. |
| A rejection cannot be explained to the caller | If the shape is a conditional write, the ambiguity is inherent — 667 of 667 conflicts were indistinguishable from another writer's. Move to a reservation if the caller needs to know. |
| Nobody can say whether the effect is an assignment or an increment | **Stop.** That question decides the entire design, and answering it wrong costs more than doing nothing at all. |

## Evidence ledger

| class | count |
|---|---|
| `[executed]` | 24 |
| `[cited]` | 2 |
| `[reasoned]` | 4 |

Reasoned claims, named so they can be attacked: the at-least-once transport list
(R1's argument about delivery-vs-effect), the per-row lock critique (R2), and the assertion
that queue documentation is routinely misread. None of the three is measured here; the first
two are architectural arguments and the third is an observation about readers, not code.
