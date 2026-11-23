# PC-0001 · Near-duplicate detection at scale

> **⚠️ KB-AUTHORED PROBLEM CARD.** The reference implementation in `impl/` was written
> for this card, not discovered internally. Every claim carries an evidence class:
> `[executed]` a test in `tests/` proves it · `[cited]` read from named real code ·
> `[reasoned]` argued from the first two, not independently verified.

| | |
| --- | --- |
| **Card ID** | `PC-0001` |
| **Domains** | ai-ml-engineering · software-engineering |
| **Sub-problems** | 4 |
| **Tests** | 34, all passing (`python3 -m unittest discover -s tests -t .`) |
| **Snippet status** | runnable + tested, stdlib only (no numpy/datasketch) |

---

## 1 · Problem statement

Given N items (documents, images-as-embeddings, records, training examples), find the
groups that are *near*-duplicates — not byte-identical — and reduce each group to one
survivor, without comparing every pair.

The hard part is not the similarity function. It is that **the obvious formulation is
quadratic**, and that the three stages after candidate generation each have a failure
mode that produces plausible, silently-wrong output.

## 2 · Recognition signals

You are in this problem when **any** of these hold. These are observable, not
descriptive — you can check them without already knowing the pattern's name.

| Signal | Why it points here |
| --- | --- |
| A dedup/cleanup job's runtime grows ~4× when input doubles | quadratic in N `[reasoned]` |
| Hash/`DISTINCT`/`set()` dedup runs clean but duplicates remain downstream | duplicates are *near*, not exact — hashing cannot see them |
| A dedup step's output changes when you shuffle the input | order-dependent survivor choice (§10 A3) `[executed]` |
| One "duplicate cluster" contains items a human says are unrelated | transitive chaining (§10 A1) `[executed]` |
| Training-set dedup removes far more (or less) than expected after a threshold nudge | operating on the LSH knee, where recall ≈ 0.44 not ≈ 1.0 (§7) `[executed]` |
| Cost is dominated by embedding *comparison*, not embedding *generation* | candidate generation is missing |

## 3 · Why the naive approach fails

The naive form is a full pairwise scan. Read in a real production embedding-deduplication
utility (source private to its owner; paraphrased here with variable names changed, logic
preserved) — `[cited]`:

```python
for i in range(n):
    if removed[i]:
        continue
    if exclusion_vec @ emb[i] < thresh:
        keep.append(i)
    removed |= (emb @ emb[i]) >= thresh     # full N-vector dot per kept item
```

Three distinct defects, all present in that one function `[cited]`:

1. **Quadratic.** One N-length dot product per kept item → O(N·K), worst case O(N²).
2. **Greedy, not clustering.** "Keep the first, drop later similars" makes the output a
   function of **input order**. Reshuffle the corpus, get a different dataset.
3. **A silently ignored argument.** The utility's public wrapper accepts three arguments
   `(embeddings, threshold, exclusion_list)` and its whole body forwards only the first
   two — the exclusion list is accepted and discarded. Any caller passing one is being
   ignored without error.

Measured cost of staying naive `[executed]` (`test_naive_comparison_count_is_exact`):

| N | pairwise comparisons |
| --- | --- |
| 1,000 | 499,500 |
| 100,000 | 4,999,950,000 |
| 1,000,000 | **499,999,500,000** |
| 10,000,000 | 49,999,995,000,000 |

Wall clock, computed by `naive.estimated_wall_clock` and pinned by
`test_wall_clock_estimates_are_exact` `[executed]`:

| N | @ 1 ns/cmp (optimistic C/SIMD) | @ 1 µs/cmp (realistic Python set op) |
| --- | --- | --- |
| 1,000,000 | 500 s (**8.3 min**) | 500,000 s (**5.79 days**) |
| 10,000,000 | 50,000 s (13.9 h) | **578.7 days** |

> **Correction, kept deliberately.** The first draft of this card said "~6 days at one
> comparison per nanosecond" for N=1M. That is wrong by 1000× — 6 days is the *microsecond*
> figure. The claim read as authoritative and nothing could check it, which is precisely
> the failure mode this format exists to prevent. It is now computed and pinned by a test.
> If a cost claim in a card cannot be executed, distrust it.

## 4 · Solution shapes

### Shape A — MinHash + LSH banding *(implemented here)*
Signature each item, band the signatures, and treat any band collision as a *candidate*.
Set-similarity (Jaccard) semantics.
**Choose when:** items are naturally sets/tokens/shingles; you want a tunable
recall/cost knob; you need it to run without a vector DB.

### Shape B — ANN index (HNSW / IVF-PQ) over embeddings
Build an approximate-nearest-neighbour index, query top-k per item.
**Choose when:** you already have dense embeddings and cosine is the right metric;
N is large enough to amortise index build; a vector store already exists.

### Shape C — Blocking on a cheap deterministic key
Group by a business key (normalised title, first-8-chars, publisher+year), compare only
within blocks.
**Choose when:** a high-precision key exists. Cheapest by far — and often overlooked
because it is unglamorous.

### Shape D — Sorted-neighbourhood
Sort by a key, slide a fixed window, compare only inside the window.
**Choose when:** streaming or memory-bound; you can accept window-boundary misses.

Selection rule `[reasoned]`: **if a deterministic blocking key exists, use C** — it beats
A and B on cost and explainability. Reach for A when similarity is set-shaped, B when it
is vector-shaped. D only under memory pressure.

## 5 · Alternatives rejected, and why

| Rejected | Why it loses |
| --- | --- |
| **Exact hashing** (`sha256`, `DISTINCT`) | Cannot see near-duplicates at all. A one-character edit changes the hash completely. This is why the problem exists. |
| **Sort by similarity, take runs** | Similarity is not a total order; there is nothing to sort by. |
| **Lower the threshold until enough is caught** | Trades a recall problem for a chaining problem (§10 A1); the giant cluster it creates is invisible in aggregate metrics. |
| **SimHash instead of MinHash** | Fine choice for *Hamming*/cosine-ish text; rejected **here** only because Jaccard-on-shingles is exactly checkable against a naive ground truth, which is what makes executable claims possible. Not a quality judgement. |
| **Just use a vector DB** (Shape B) | Not rejected — it is a peer. Rejected as the *card's* implementation because it cannot be demonstrated with stdlib only, so its claims could not be executed. |

## 6 · Decomposition

Four sub-problems. The interfaces are the contract — each stage can be replaced
independently, which is the actual value of decomposing this.

```
texts ──▶ [1 BLOCKING] ──▶ candidate pairs ──▶ [2 SCORING] ──▶ scored edges
                                                                    │
                                        clusters ◀── [3 CLUSTERING] ◀┘
                                            │
                                            └──▶ [4 CANONICAL] ──▶ {survivor: [dropped]}
```

| # | Sub-problem | In → Out | Cost | Owns the risk of |
| --- | --- | --- | --- | --- |
| 1 | **Blocking** `impl/blocking.py` | `list[set]` → `set[frozenset]` | O(N · num_perm) | missed pairs (recall) |
| 2 | **Scoring** `impl/scoring.py` | candidates → `(i,j,score)` desc | O(C) | false positives |
| 3 | **Clustering** `impl/clustering.py` | edges → `list[set]` | O(C·α) | **chaining** |
| 4 | **Canonical** `impl/canonical.py` | cluster → survivor | O(Σk²) | order-dependence |

**Typed edges** (machine-readable in `card.json`):

- `1 splits-into` → nothing (leaf); `requires` a similarity notion chosen in advance
- `2 requires 1` — scoring without blocking *is* the naive algorithm
- `3 requires 2` — clustering on unscored candidates imports LSH's false-positive rate
- `4 requires 3` — and `conflicts-with` "greedy keep-first", which fuses 3 and 4 and
  thereby loses both cluster structure and determinism
- `composes-with` **PC-0002: embedding generation** — Shape B's upstream

**Why this order is forced** `[reasoned]`: each stage strictly narrows the input to the
next. Reordering 2 and 3 means clustering on unverified pairs; fusing 3 and 4 is exactly
the greedy defect in §3.

## 7 · Cost & scale model

The tuning knob is `(bands, rows)` with `bands × rows ≤ num_perm` (they need *not*
multiply to it exactly — see the C3 retraction below):

```
P(pair becomes a candidate) = 1 − (1 − s^rows)^bands        knee ≈ (1/bands)^(1/rows)
```

**C1 — Recall at your threshold is a coin flip you will lose more often than win**
`[executed]`. For `threshold=0.7`, `num_perm=128`, the auto-selected banding is
`(bands=14, rows=9)` and the measured `expected_recall_at_threshold` is **0.4382** —
~56% of pairs sitting exactly at the cutoff are missed. (An earlier draft published
0.6133, which was the figure for a different banding, `16×8`, and thereby *understated*
the miss rate.) Detection only becomes near-certain well *above* the cutoff:
P(s=0.90) > 0.99 `[executed]`. If you need high recall *at* the boundary, move the knee
below your threshold and let stage 2 reject the extra.

**C2 — Measured reduction** `[executed]`, 80-document fixture, threshold 0.7, at the
selected `(14, 9)` banding:

| metric | value |
| --- | --- |
| naive comparisons | 3,160 |
| candidates generated | 56 |
| **reduction factor** | **56.4×** |
| confirmed pairs | 35 |
| recall vs exhaustive ground truth | ≥ 0.90 (asserted); 35/40 groups found — the 5 misses are pinned too |

(An earlier draft published 97 candidates / 32.6× / 38/40, measured at the wrong `16×8`
banding.)

**C3 — RETRACTED: "reachable knees are quantized by the divisors of `num_perm`."**
The original claim — that `num_perm=128` leaves a hole with no knee between 0.420 and
0.707, so a 0.6 target misses by 0.107 and highly-divisible signature lengths (120, 144,
180) should be preferred — rested on requiring `bands × rows == num_perm` exactly. Under
the real constraint `bands × rows ≤ num_perm`, the knee space is **dense, not quantized**:
128 permutations admit **645** reachable `(bands, rows)` pairs, 0.6 *is* reachable, and
divisor count governs nothing `[executed]`
(`test_there_is_NO_unreachable_threshold_hole`, `test_divisibility_of_num_perm_is_irrelevant`).
The old advice was worse than doing nothing — at threshold 0.6, the recommended
`num_perm=120` gives knee error 0.0671 against 128's 0.0617 — and the helper that issued
it (`suggest_num_perm`) was **deleted rather than corrected**; a test now asserts its
absence.

What survives of C3 is only this `[executed]`: **you do not get exactly the threshold you
ask for.** Measured knee error at `num_perm=128`: 0.0617 at threshold 0.6, 0.0459 at 0.7,
0.0445 at 0.8; worst observed across 0.5–0.95 is ~0.062. Read `stats["knee_error"]`
instead of assuming.

> **Why this retraction is displayed rather than deleted:** the refuted claim was itself
> `[executed]` — pinned by a passing test that encoded the same wrong constraint as the
> code it checked. An executed claim is one a reader *can* re-check, not one that is
> thereby true. This card keeps its corrections visible for the same reason it keeps the
> 1000×-wrong wall-clock estimate in §3.

**Breakpoints** `[reasoned]`: below N≈5,000 the naive scan is simpler and fast enough —
use it. Above N≈10⁶, stage 1 should move to a distributed shuffle keyed on band buckets;
stages 2–4 are then embarrassingly parallel per bucket.

## 8 · Code

Runnable now, no dependencies:

```python
from impl import pipeline

out = pipeline.deduplicate(texts, threshold=0.7, strategy="medoid")
out["kept"]            # indices to keep
out["dropped"]         # indices removed
out["stats"]["reduction_factor"]   # verify you actually saved work
out["stats"]["knee_error"]         # how far the real knee sits from your threshold (C3)
```

`stats` is deliberately part of the return contract: a mistuned `(bands, rows)` degrades
silently to near-naive cost *or* poor recall, and both look like success from outside.

## 9 · Verification

| Claim | Test |
| --- | --- |
| pipeline finds what O(N²) finds | `test_recall_against_exhaustive_search` (≥0.90 vs exhaustive) |
| blocking actually saves work | `test_blocking_actually_reduces_work` (>5×) |
| no cluster is chained | `test_every_cluster_is_internally_similar` (max intra-distance < 0.45) |
| survivors and dropped are disjoint | `test_no_survivor_is_also_dropped` |
| cost table is exact | `test_naive_comparison_count_is_exact` |
| the 0.6 "hole" was an artefact — the knee space is dense | `test_there_is_NO_unreachable_threshold_hole` |
| the knee gap is small but real (~0.05–0.06) | `test_gap_to_requested_threshold_is_small_but_real` |
| degenerate inputs are safe | `test_empty_and_single_item_inputs_do_not_crash` |

**Adopting this?** Run `test_recall_against_exhaustive_search` against a sample of *your*
corpus. Recall is a property of your data's similarity distribution, not of this code.

## 10 · Anti-patterns

**A1 — Union-find over "similar" pairs (transitive chaining).** THE subtle one.
Single-linkage is transitive: A~B=0.9, B~C=0.9, A~C=0.2 yields one cluster `{A,B,C}`
`[executed]`. On real corpora this collapses whole regions into one blob, and nothing
fails. `representative_link` merges only when the item is similar to the cluster's
**representative**, giving `{A,B}` and leaving C alone `[executed]`.
*Diagnostic:* `max_intra_cluster_distance` ≫ (1 − threshold) means chaining, not similarity.

**A2 — Treating a band collision as a duplicate.** LSH is a *recall device*; skipping
stage 2 imports its false-positive rate into your data permanently.

**A3 — "Keep the first."** Makes output a function of input order `[executed]`. The
cited internal code does this `[cited]`. `pick_medoid` is order-independent.

**A4 — Tuning the threshold without checking where the knee actually landed.** You do not
get exactly the threshold you ask for — gaps up to ~0.06 at `num_perm=128` (C3). Read
`stats["knee_error"]` before trusting a threshold nudge.

**A5 — Reporting only how many duplicates were removed.** That number is high for both a
well-tuned run and a chaining catastrophe. Report cluster count, max cluster size, and
max intra-cluster distance.

### When NOT to use this card
- N < ~5,000 — the naive scan is simpler and fast enough.
- Exact duplicates only — hashing is correct and cheaper.
- A high-precision deterministic blocking key exists — Shape C wins.
- Similarity is genuinely vector/cosine-shaped with an existing index — Shape B wins.
- Pairwise *decisions* must be auditable per pair — LSH's misses are probabilistic and
  hard to explain to an auditor.

## 11 · Escalation

| Symptom | Next move |
| --- | --- |
| Recall too low at acceptable cost | Move the knee *below* threshold (more bands, fewer rows); let stage 2 reject extras |
| Candidate volume explodes | Raise the knee, or add a cheap pre-block (Shape C) *before* stage 1 |
| One giant cluster | A1. Switch to `representative_link`; check `max_intra_cluster_distance` |
| Knee lands too far from your threshold | read `stats["knee_error"]`; adjust `(bands, rows)` — the space is dense (C3) |
| N > 10⁶ | Distribute stage 1 by band bucket; 2–4 parallelise per bucket |
| Recall must be *provable*, not probabilistic | Leave this card. Exact blocking + full within-block comparison, accepting the cost |

## 12 · Evidence ledger

| Class | Count | Meaning |
| --- | --- | --- |
| `[executed]` | 13 | A test in `tests/` fails if the claim is false |
| `[cited]` | 3 | Read from a real production dedup utility (source private; paraphrased in §3) |
| `[reasoned]` | 4 | Argued, **not** independently verified — the weakest tier |

The unverified claims, enumerated so they can be attacked — this is the whole reason
the ledger exists:

1. **Recognition signal "runtime grows ~4× when input doubles"** — the right shape for a
   quadratic, but not measured on a real job.
2. **Shape-selection rule** ("if a deterministic key exists, use C") — a judgement, no
   benchmark behind it.
3. **"Why this order is forced"** — an argument from the interfaces, not a proof. A fused
   2+3 stage might be made to work; I have not tried.
4. **Breakpoints N≈5,000 and N≈10⁶** — plausible from the cost table, **never benchmarked
   on real hardware**. The N≈10⁶ distributed-shuffle recommendation rests on it.

Anti-patterns A2 and A5 are also argued rather than executed. **Treat all of the above as
hypotheses**, and note that the counts in the table above are generated by
`validate_cards.py --sync-ledger`, not maintained by hand — they drifted on all three
classes within an hour of this card being written.
