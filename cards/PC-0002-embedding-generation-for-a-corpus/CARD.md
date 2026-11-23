# PC-0002 — Embedding generation for a corpus

| | |
| --- | --- |
| **Id** | PC-0002 |
| **Domains** | ai-ml-engineering, software-engineering |
| **Tests** | 46 |
| **Status** | written |
| **Composes with** | PC-0001 (near-duplicate detection at scale) |

> **Evidence tags.** `[executed]` — a test in `tests/` proves it, and you can re-run it.
> `[cited]` — read from named real code, which is *not* the same as correct.
> `[reasoned]` — argued, not verified. Treat as a hypothesis.

**Scope warning, up front:** this card is about the *plumbing* of embedding generation. It
contains **no measurement of embedding quality** and cannot tell you which model to use. That
is not a gap awaiting work — it is outside the scope by construction, because quality cannot
be measured without a real model, and this suite deliberately runs on the standard library
alone. See §11.

---

## 1 · Problem statement

You have a corpus. You need one dense vector per document, good enough to drive retrieval,
clustering or dedup. The obvious implementation — loop over documents, call the model with
default arguments, store what comes back — produces vectors that are **silently wrong for a
predictable slice of the corpus** and costs several times more than necessary.

Every failure in this card shares one signature: **nothing raises.** Shapes are right, values
are finite, cosine scores look plausible, and the pipeline reports success. The defects show
up as mediocre retrieval that gets blamed on the model, and as a bill nobody can attribute.

The five sub-problems are not independent, and two of them *interact*: a pooling bug that is
completely harmless under one metric is catastrophic under another. That interaction is the
most useful thing in this card and it is not visible from either sub-problem alone. `[executed]`

## 2 · Recognition signals

You are in this problem, rather than a model-selection problem, when:

- Retrieval is fine on short documents and poor on long ones. Length, not topic, predicts
  quality — the distribution is being truncated. `[executed]`
- Similarity scores are compressed into a narrow high band and rankings feel arbitrary.
- **The cache hit rate is near 100% immediately after a model upgrade.** This is impossible
  if the vectors changed, so it means the key does not include the model. `[executed]`
- Embedding spend far exceeds what your token count implies, with no obvious hot spot.
- Short documents cluster together regardless of topic.
- Re-embedding the same corpus twice yields different vectors. `[executed]`

The last one deserves emphasis because it happened *in this card's own implementation*: the
first version seeded token vectors from `builtins.hash(token)`, which is salted per process.
Same input, different vectors, every run — and a same-process equality check passes happily.
Only a second interpreter catches it, so there is now a test that spawns one. `[executed]`

## 3 · Why the naive approach fails

The naive pipeline is not slow — it is *wrong in four independent ways at once*, measured on
the fixture corpus (2000 documents, 551,579 tokens, right-skewed: p50 182, p99 1390):

| Naive choice | Measured consequence |
| --- | --- |
| `truncation=True, max_length=512` | **16.34%** of all corpus tokens discarded |
| arrival-order batching at 32 | **76.96%** of paid token slots carry no data |
| unnormalised vectors + dot product | **69.5%** of queries return a different top-1 |
| cache keyed on text | **100%** stale-serve rate after any config change |

None of these is a model problem, so none is fixed by a better model — a better model
inherits all four. `[executed]`

The deepest one is the fourth, because it *inverts the usual signal*: a cache that is working
correctly shows a **drop** in hit rate after an upgrade. A hit rate that stays high is the
bug. Teams read the high number as good news. `[executed]`

## 4 · Solution shapes

### Shape A — chunk, bucket, masked-pool, normalise, cache by full identity

The implemented shape (`impl/pipeline.py`), composed in the decomposition's topological
order. Use when corpus p99 length exceeds the model window.

**chunks/doc is a curve in the window, not a constant** — measured on the full 2000-document
corpus at overlap 32: **1.6485** (window 256), **1.1840** (512), **1.0290** (1024). Use these
for capacity planning. `[executed]`

This figure was previously published as **1.07 from a 30-document fixture, and that was
wrong** — a consumer sizing a 4M-document job refused to plan on it, correctly: the 30-doc
sample understates forward passes by **11%** and is the low outlier of a converging series
(1.067 / 1.120 / 1.196 / 1.184 at n = 30 / 100 / 500 / 2000). `[executed]`

The 30-document pipeline figures — 32 chunks, 10,592 paid slots, 35.21% waste at batch 16,
every vector unit-norm, warm cache converting all 32 chunks to hits — are an **end-to-end
smoke test of the composed pipeline, not a capacity estimate.** `[executed]`

### Shape B — truncate to the window, one vector per document

Correct, not lazy, **when p99 fits the window**. There is nothing to chunk, so Shape A would
add cost and buy no recall. The selection rule tests this first for exactly that reason. On
*this* corpus it would discard 16.34% of tokens at window 512, which is how you tell the
shape is inappropriate here rather than in general. `[executed]`

### Shape C — multi-vector / late interaction

Keep chunk vectors; never aggregate. Use when you need to know *which* passage matched, or
when aggregation is washing out long documents. Changes retrieval semantics to
max-over-chunks and multiplies storage and query cost by chunks/document. `[reasoned]`

### Shape D — hierarchical summarise-then-embed

Summarise, then embed the summary. Appropriate when documents are far longer than the window
and a single lossy vector is genuinely wanted. Adds an LLM call per document and that call's
own failure modes, which this card does not measure. `[reasoned]`

## 5 · Alternatives rejected

| Option | Why rejected |
| --- | --- |
| **Train or fine-tune a bespoke embedding model** | None of the four measured failures is a model-quality problem. A better model inherits every one of them. This is the most expensive way to not fix the bug. `[reasoned]` |
| **Mean-pool the whole document, ignoring the window** | Not an alternative — a bug. Tokens past the window were never encoded, so they contribute nothing. The output looks like a document vector and is a prefix vector. `[executed]` |
| **Store raw vectors, normalise at query time** | Pays normalisation on every query instead of once per write, and leaves every dot-product consumer with norm-biased ranking: **69.5%** of queries change top-1. `[executed]` |

## 6 · Decomposition

Five sub-problems, one module each, so the code layout *is* the breakdown:

| # | Sub-problem | Module | The question it answers |
| --- | --- | --- | --- |
| 1 | Units | `impl/chunking.py` | what do you actually embed? |
| 2 | Pooling | `impl/pooling.py` | many token vectors → one |
| 3 | Throughput | `impl/throughput.py` | what does a batch cost? |
| 4 | Identity | `impl/identity.py` | what *is* an embedding, for caching? |
| 5 | Metric pairing | `impl/metric.py` | which similarity, on which vectors? |

Ordering constraints that matter:

- **3 requires 1** — you cannot pad until you know the units. A corpus of documents and a
  corpus of chunks are different length distributions with different waste.
- **2 requires 3** — padding is what *creates* the need for a mask. Pooling is only
  ambiguous because batching introduced positions that are not data.
- **4 requires 1 and 2** — the key must cover window, overlap and pooling. Omitting any of
  them gives a **100%** stale-serve rate once that field changes. `[executed]`
- **2 conflicts-with 5** — the sharpest edge in the card, and the one worth reading twice.

That last edge: unmasked pooling over zero padding rescales the vector by *exactly* the fill
ratio and leaves its direction untouched. Under cosine that is **completely harmless**. Under
an unnormalised dot product a 1/16-full row is down-weighted 16×. **Neither node is wrong
alone; the pair is.** `[executed]`

Note also that the import direction between modules 2 and 5 is the *reverse* of the problem
dependency — `pooling` imports `metric` for arithmetic, while the problem needs pooling
decided first. Import graphs and problem graphs are different graphs.

## 7 · Cost & scale model

Measured on `impl/corpus.py::synthetic_corpus(2000, seed=20260906)` — 2000 documents,
551,579 whitespace tokens, p50 182, p90 616, p99 1390, max 3291. Right-skewed, which is the
property every result depends on. Synthetic, so each constraint states separately whether its
**shape** or its **values** generalise.

**C1 — truncation loss is bigger in tokens than in documents, at every window.** `[executed]`

| window | documents affected | **tokens lost** |
| --- | --- | --- |
| 256 | 34.85% | **37.28%** |
| 512 | 14.05% | **16.34%** |
| 1024 | 2.70% | **3.68%** |
| 2048 | 0.15% | **0.36%** |

`docs_over` is the smaller number at every window, so it is the flattering one to quote.
Shape generalises to any right-skewed corpus; the values are this corpus's.

**C2 — overlap ≥ k−1 preserves every k-token span exactly, and more overlap buys nothing.**
8-gram recall by overlap: 0 → 0.996384, 4 → 0.998450, **7 → 1.000000**, 8/16/32 → 1.000000.
Token overhead by overlap: 0 → 0%, 8 → 0.51%, 32 → 2.13%, 64 → 4.39%, 128 → 9.49%.
The common "overlap 10–20% of the window" rule means 51–102 tokens here, costing 4.4–9.5%
for **zero** additional 8-gram preservation over overlap 7 at 0.51%. The threshold is exact
index arithmetic and generalises; the overheads are corpus-specific. `[executed]`

**C3 — bucketing gain PEAKS at batch 128. It is not monotonic.** `[executed]`

| batch | arrival waste | bucketed waste | slot reduction |
| --- | --- | --- | --- |
| 8 | 63.59% | 2.78% | 2.67× |
| 32 | 76.96% | 7.84% | 4.00× |
| 128 | 84.11% | 29.14% | **4.46×** |
| 512 | 89.09% | 70.37% | 2.72× |

Measuring one batch size would have yielded *"bucketing gives 4×, so batch as large as you
can."* At 512 the gain falls **below** its value at 32. Unit is token slots
(`max_len × rows`), not seconds.

**C4 — the pooling anti-pattern is conditional.** With **zero** padding, unmasked mean
pooling gives cosine `1.000000` at every occupancy and changes **0** nearest neighbours; the
norm ratio equals the fill ratio exactly. With `pad_value=0.35` it degrades — 0.996270,
0.980156, 0.952602, 0.916795 at fill 1/2, 1/4, 1/8, 1/16 — and **91.67%** of nearest
neighbours change. The zero-pad algebra is exact and general; the non-zero magnitudes depend
on the angle between pad and data. `[executed]`

**C5 — normalise once and dot becomes cosine.** Max `|cosine − dot|` after L2-normalising:
`1.11e-16`. Skip it and 69.5% of queries change top-1 at a 29.4× norm spread; normalise and
the flip rate is exactly 0. The norm spread is published beside the flip rate because the
rate is a function of it. `[executed]` A real internal pipeline states the same invariant in
a comment — *"L2-normalise once so that dot = cosine"*. `[cited]`

**C6 — identity is `(text, model, revision, pooling, window, overlap, normalize, dim)`.**
Text-only key → **100%** stale serves. Full key → **0%**. Omitting *any single field*, varied
one at a time: **100%** stale in all seven cases. There is no safe subset; the fields that
look harmless are the ones you have not changed yet. A stale **hit** is the dangerous
outcome — a miss only costs money. `[executed]`

**Breakpoints.** Below p99 ≈ 512 **tokens** (vs the model window) take Shape B. Above ~10⁷
**chunks**, the cache and bucketing queue stop fitting one process; shard by chunk-key hash.
Both `[reasoned]` — neither has been run at that scale.

## 8 · Code

Stdlib only. `numpy`, `torch` and `transformers` were all importable in the environment this
card was written in and are deliberately unused, so that `[executed]` means *"runs wherever
the gate runs"* rather than *"ran once on the author's machine"*.

The two measurements that decide the pooling question:

```python
from impl import pooling

# ZERO padding: a pure scalar multiple -- direction untouched
for true_len in (512, 256, 128, 64, 32):
    r = pooling.pad_contamination(true_len, 512, dim=64, pad_value=0.0)
    assert abs(r["cosine_correct_vs_buggy"] - 1.0) < 1e-12
    assert abs(r["norm_ratio_buggy_over_correct"] - r["fill_ratio"]) < 1e-12

# NON-ZERO padding: direction genuinely corrupted
r = pooling.pad_contamination(32, 512, dim=64, pad_value=0.35)
assert round(r["cosine_correct_vs_buggy"], 6) == 0.916795
```

The identity result, which is the cheapest defect to prevent and the most expensive to
discover late:

```python
from impl import identity

cfg = {"model": "e5-base", "revision": "r1", "pooling": "masked-mean",
       "window": 512, "overlap": 32, "normalize": True, "dim": 768}

# every field, varied one at a time, omitted from the key -> total staleness
for field, rate in identity.field_sensitivity(corpus, cfg).items():
    assert rate == 1.0, field
```

And the non-monotonic throughput result:

```python
from impl import throughput

gains = {bs: throughput.bucketing_gain(lengths, bs)["slot_reduction"]
         for bs in (8, 32, 128, 512)}
assert max(gains, key=gains.get) == 128       # not 512
assert gains[512] < gains[32]                 # the gain goes DOWN
```

## 9 · Verification

**42 tests, all passing, 1.14 s.** Every number published in §7 is asserted against an actual
run; the card is written from the measurement output, not the reverse.

Two tests exist because **executing falsified the claim this card was going to make**:

1. `test_zero_pad_unmasked_pooling_is_direction_preserving` — the planned A2 said unmasked
   pooling corrupts embeddings. Over zero padding it does not, at all.
2. `test_bucketing_gain_is_not_monotonic_in_batch_size` — the planned C3 said bucketing gives
   ~4×. The gain peaks at 128 and then falls.

Two more guard bugs found while building:

3. `test_vectors_are_identical_across_SEPARATE_PROCESSES` — `builtins.hash` is salted, so
   the first implementation was non-reproducible across runs. A same-process check passed.
4. `test_overlap_costs_tokens_not_chunks` — chunk *count* is identical for overlap 0 and 32
   on this corpus, which reads as "overlap is free". Tokens sent is the honest measure.

## 10 · Anti-patterns

**A1 — truncate and forget.** `max_length=512, truncation=True`, never measured. Nothing
errors; long documents become prefix vectors. Diagnostic:
`chunking.truncation_loss(corpus, window)` and report `tokens_lost`, not `docs_over`.
Measured: **16.34%** of tokens at window 512. `[executed]`

**A2 — mean-pooling across the padded axis.** **Conditional**, and this card was going to
state it unconditionally. Over zero padding it only rescales, and cosine is untouched. It is
a real defect under an unnormalised dot product, or when pad positions are non-zero — where
**91.67%** of nearest neighbours change. Diagnostic: `pooling.pad_contamination` at several
fill ratios *and* your actual pad vector, then `contamination_changes_ranking`. `[executed]`

**A3 — caching embeddings by text.** Returns vectors from a configuration you no longer run,
with a high hit rate and no error. Diagnostic: `identity.stale_serve_rate(..., text_only_key)`
→ measured **1.0**. The tell is a hit rate that *stays* high after an upgrade. `[executed]`

**A4 — dot product on unnormalised vectors.** Dot is norm-biased and systematically prefers
large-norm documents, which are often just the long ones. Diagnostic:
`metric.ranking_flip_rate` beside `metric.norm_spread` → **69.5%** of queries change top-1 at
29.4× spread, **0%** after normalising. `[executed]`

**A5 — batching in arrival order, or bucketing and losing the permutation.** Two failures,
one cause. Arrival order wastes **76.96%** of slots at batch 32 (bucketed: 7.84%); bucketing
fixes that and reorders the corpus, so zipping results against the original list attaches
**every** vector to the wrong document, silently. Diagnostic:
`throughput.bucketing_gain` for cost, and assert `restore(order)` round-trips for
correctness. `[executed]`

## 11 · Escalation

| Symptom | Action |
| --- | --- |
| retrieval poor, truncation loss already ~0 | **leave this card** — the problem is model choice or the task, and neither is measured here |
| you need to know which passage matched | Shape C; accept the storage multiple |
| aggregation washing out long documents | Shape C, or Shape D if one lossy vector is genuinely wanted |
| hit rate near 100% right after a config change | A3 — the key is incomplete; expect to re-embed |
| scores compressed, rankings arbitrary | check normalisation first (C5) — one line, 69.5% of top-1 results |
| you must justify one similarity score to an auditor | PC-0001's escalation on provable vs probabilistic recall |

**Do not use this card when** you need to choose an embedding model; when p99 already fits
the window (take Shape B); when you need per-pair explainability; or when the real question
is multilingual or domain-shift coverage, which is model selection wearing a pipeline costume.

## 12 · Evidence ledger

| Class | Count | Meaning |
| --- | --- | --- |
| `[executed]` | 27 | a test in `tests/` proves it; re-runnable |
| `[cited]` | 1 | read from named real code — not thereby correct |
| `[reasoned]` | 4 | argued, not verified — hypotheses |

**The `[reasoned]` claims, named so they can be attacked:** Shape C and Shape D (neither
implemented); the p99 breakpoint; and the 10⁷-chunk sharding breakpoint. Nothing about them
has been run.

**What this card cannot tell you, restated because it is the most likely misuse:** which
model to pick, whether your embeddings are semantically good, or how any of this behaves
multilingually. Zero of the 42 tests touch a real model. A consumer asking "which embedder
should we use?" must be told **no**, and pointed at the escalation table.

**Cost of authoring, measured — and my first published figures for it were wrong.** I wrote
estimates into this section before the files were final, which is exactly the unexecuted claim
this card argues against. The measured values:

<!-- COST-TABLE:BEGIN (generated by validate_cards.py --sync-ledger) -->
| | PC-0001 | PC-0002 | PC-0003 | PC-0004 | PC-0005 |
| --- | --- | --- | --- | --- | --- |
| `impl/` | 432 | 755 | 658 | 687 | 911 |
| `tests/` | 437 | 467 | 380 | 432 | 428 |
| `CARD.md` | 318 | 382 | 299 | 393 | 411 |
| `card.json` | 431 | 530 | 533 | 469 | 769 |
| `scenarios.json` | 257 | 202 | 165 | 212 | 403 |
| **total** | **1875** | **2336** | **2035** | **2193** | **2922** |
| tests-to-impl | 1.01 | 0.62 | 0.58 | 0.63 | 0.47 |
| doc-to-code | 0.86 | 0.75 | 0.80 | 0.77 | 0.88 |
<!-- COST-TABLE:END -->

**These numbers are generated, because I got them wrong by hand twice.** First from
estimates written before the files were final (impl 649, `CARD.md` 291, `scenarios.json` 96,
total 1698 — wrong on four of five). Then, correcting them, I hand-typed `tests/` as 385 when
it was 386. In the section that argues unexecuted numbers are untrustworthy. They are now
regenerated by `--sync-ledger` and a stale table is a gate **error**, which is the same rule
already applied to the evidence ledger and the test count.

Generating them also showed the **baseline itself had drifted**: PC-0001 was quoted all
session at 1453 lines / 0.97, and is actually 1534 / 0.98, because PC-0001's own
`scenarios.json` grew as consumer runs were recorded into it.

**The tripwire did not trip, and the drop survives a check for the obvious confound.**
Doc-to-code counts `CARD.md` + `card.json` against `impl` + `tests`, so prose that moves
*into docstrings* would deflate it without any real change. That happened: impl prose rose
from 33% to 40% of lines, 108 → 230 lines. Recomputing with all prose in the numerator
wherever it lives gives **2.03 → 1.55** — still a fall, but −24% rather than −38%. So the
naive ratio overstates the improvement by about 14 points, and the schema still did not strain.

**Why it fell rather than rose**, which was not the expectation going in: the premise was
that a problem where `[executed]` is hard to earn would force prose to carry the argument.
Instead the executable surface turned out to be *the plumbing* — chunk arithmetic, mask
handling, slot counting, key composition — and the plumbing is where the defects actually
live. The unexecutable part (model quality) did not need prose because it needed **exclusion**:
one scope statement and a refusal scenario, not an essay.
