# Problem Card schema

The authoring contract for depth-KBs. A card is a **problem**, not a package — it exists
to let an AI system recognise a situation, choose between real alternatives, decompose the
work, and know when it has gone wrong.

Cards do **not** depend on a codebase existing. They carry their own runnable code. Where
real internal code strengthens a point it is cited, but no card's value rests on it.

## Why every rule here is a gate, not a guideline

Measured in the sibling 31-KB portfolio in this same workspace:

| Finding | Consequence for this schema |
| --- | --- |
| **18 of 31 KBs** decayed to ~30-char evidence that names no file and can be checked against nothing | §1 minimum section size; evidence classes |
| **33% of double-assessed rows were factually wrong**, every one flagged `verified` | evidence classes are per-*claim*, and `reasoned` is counted and displayed |
| **3 KBs had zero counter-examples**; one accepted 143 of 143 repos | ≥1 anti-pattern and ≥1 rejected alternative are **mandatory** |
| A KB deferred to a sibling that *rejected* the package — a pointer to nowhere | decomposition edges must resolve |
| A hardcoded total went stale in 31 generated files | the evidence ledger is **generated** (`--sync-ledger`) |
| Two flagship KBs claimed 86–89% coverage on 49–59% anchor strength | claimed vs evidenced are separate fields, never merged |

The 13 KBs that stayed deep are indistinguishable in intent from the 18 that did not.
**The only difference was that nothing forced them.** Hence: gates.

## Directory layout

```
problem-cards/
  SCHEMA.md                  this file
  validate_cards.py          the depth gate  (--strict, --sync-ledger)
  test_validate_cards.py     tests for the gate itself (106)
  cards/
    PC-NNNN-slug/
      CARD.md                the 12 required sections
      card.json              machine-readable record for AI consumption
      impl/                  runnable reference implementation
      tests/                 tests that MUST pass, with __init__.py
```

`PC-NNNN` is permanent and referenced by other cards. Never renumber.

> **Do not name a card directory after another toolchain's glob.** In the workspace this
> schema was first used in, a sibling tool globbed for its own directory suffix and swept
> any match into seven CI gates that then failed on missing files. Check what patterns
> neighbouring tooling matches before naming.

## The 12 required sections

Each must exceed **200 characters** of substance. A heading is not depth.

| # | Section | Must contain |
| --- | --- | --- |
| 1 | **Problem statement** | The situation, and *what specifically is hard* — not a topic label |
| 2 | **Recognition signals** | **Observable** triggers checkable without knowing the pattern's name. "p99 grows while p50 is flat", not "when performance matters" |
| 3 | **Why the naive approach fails** | The obvious approach, and its failure *quantified*. Cite real code where possible |
| 4 | **Solution shapes** | **≥2**, each with an explicit `choose_when`. One option means no decision to make |
| 5 | **Alternatives rejected** | What lost, and why. Include peers rejected for scope, marked as peers — not everything rejected is worse |
| 6 | **Decomposition** | Sub-problems with **in→out interfaces**, cost, and the risk each owns. Typed edges in `card.json` |
| 7 | **Cost & scale model** | Formulas and **≥1 quantified breakpoint**. Unquantified means "it depends", which is useless to a planner |
| 8 | **Code** | The call, runnable as written |
| 9 | **Verification** | Claim → the test that proves it. Plus how a *reader* verifies against their own data |
| 10 | **Anti-patterns** | **≥1**, each with a *diagnostic*. Plus an explicit "when NOT to use this card" |
| 11 | **Escalation** | Symptom → next move, including "leave this card" |
| 12 | **Evidence ledger** | Generated counts + **every `reasoned` claim enumerated by name** |

## The core bet is no longer untested

The open question was whether an AI can plan over `card.json`. It was tested: two fresh
agents, **`card.json` only** — no `CARD.md`, no repo access — against scenarios containing
seeded traps.

- **Planning** (800K product descriptions; SHA-256 "runs clean"; an engineer proposing
  all-pairs + union-find + keep-first): the agent identified the problem from
  `recognition_signals`, quantified naive cost from `cost_model.wall_clock`, caught all
  three seeded defects **by ID**, selected Shape A while explicitly flagging Shape C as an
  unanswered prerequisite — correct, since the selection rule tests C first — and built its
  monitoring section from A5. It separated `[executed]` anchors from `[reasoned]` heuristics
  from its own extrapolations. **The evidence-class design did what it was built for.**
- **Refusal** (1,800 contracts, per-pair auditability required): answered "No" first, cited
  both independent blockers, took the escalation exit — and repurposed the edge annotation
  *"scoring without blocking IS the naive algorithm"* to justify running stage 2
  exhaustively at small N. That is **reasoning over graph structure**, not prose recall, and
  it is the strongest evidence that typed edges with a `why` are worth their cost.

Caveats, stated by the tester: 2 scenarios, one consumer class, and the scenarios were
written with knowledge of the card. An independently-authored scenario would be harsher.

**The consumer test also found a card defect** — C3 recommended `num_perm=144` for
threshold 0.7 while publishing measured errors only for the 0.6 pairings, and the agent
correctly declined to fully trust it. That a consumer surfaced a gap *by planning over the
card* is itself evidence the format works. All three pairings now carry measured errors.

## Executing a claim has corrected authoritative-sounding prose three times

This is the schema's empirical core, and at three instances it is no longer an anecdote.
Each time, well-written confident prose survived review and was corrected only by being
executed:

| # | The prose said | Execution said | Error |
| --- | --- | --- | --- |
| 1 | naive all-pairs at N=1M ≈ **6 days** | **500 s** (8.3 min) at 1 ns/comparison | **1000×** — the 6-day figure is the microsecond case |
| 2 | evidence ledger: **8** `reasoned` claims | **4** — the counter was scoring the legend and the ledger's own rows | **2×**, and the ledger check then enforced agreement with the wrong number |
| 3 | C3: use `num_perm` **120 / 144 / 180** for thresholds 0.6 / 0.7 / 0.8 | at 0.7 the default 128 is **already adequate** (err 0.0071); 144 is a 2.2× gain against **15× and 39×** | not a wrong number — a **wrong emphasis** |

**The third is the most instructive, and it names the failure mode precisely.** Nothing in
C3 was false. Every suggested value was correct. The defect was that prose presents a list
of three recommendations in parallel grammar, and parallel grammar implies parallel
motivation. Two of those recommendations fix a 15×/39× error; one is a rounding preference.
A reader — human or model — allocates attention by the structure of the sentence, and the
sentence lied about the structure of the problem.

So the argument for `[executed]` is stronger than "unexecuted claims may be wrong":

> **Unexecuted claims fail in a predictable direction: they flatten. They present unequal
> things as equally motivated, because prose has no cheap way to express a 39×-versus-2.2×
> difference and every cheap way to express a list.** Numbers do not flatten. A measured
> table forces the disparity into view whether the author noticed it or not.

This is why the cost model must contain real numbers (gate 6) and why `[executed]` is
ranked above `[cited]`. A cited claim inherits its source's emphasis; an executed one has
none to inherit.

Corollary for authors: **when a card recommends N things, measure all N.** Publishing a
measurement for a subset and generalising the recommendation across the whole set is how
instance 3 happened — and it was caught by a consumer, not by the author or the gate.

### Detecting flattening before you can measure it

Flattening has a review heuristic that costs seconds and needs no execution:

> **Any list of N recommendations where fewer than N carry a number is suspect by
> construction.** The unnumbered ones are riding on the credibility of the numbered ones.

This is deliberately **not gated**. It is a strong signal, not a rule: some lists are
legitimately qualitative, and a check that forced a number onto every bullet would produce
decorative numbers, which is worse than none. It is a prompt for the author before
publishing and for the consumer before trusting — apply it to C3 as it originally stood and
it fires immediately.

### The same failure, one level down: units and corpora

A second consumer run found two more instances, both in `card.json` only:

| Field | As published | What the consumer did |
| --- | --- | --- |
| `breakpoints[0]` | `{"below": 5000}` | compared **1,619,100 comparisons** against a **5,000-item** threshold — right answer by luck of magnitude |
| `C1` | `measured: 0.6133` + its parameters | quoted **"recall is only ~61%"** onto 1,800 legal contracts, as a property of the algorithm |

Same shape as instance 3: **a bare number flattens away its unit; a measured value flattens
away its corpus.** Both now fixed (`unit` on every breakpoint, `measured_on` + an explicit
`generalizes: NO` on C1) and both gated — a breakpoint without `unit` is an **error**, a
measured value without `measured_on` is a **warning**.

The telling detail: **CARD.md said "below N≈5,000" and was never ambiguous.** The defect
existed only in the record that consumer was restricted to. Two records of one card do not
degrade identically, which is the argument for testing consumers on the JSON alone.

## Consumer scenarios (`scenarios.json`) — required

The only check that tests a card's **purpose** rather than its shape, and the only one that
padding cannot game.

A model cannot run inside a gate, so the two halves are split:

- **Statically gated:** every rubric expectation must resolve to a real element of
  `card.json`. A rubric cannot demand an anti-pattern, shape, constraint, edge or JSON path
  that does not exist. This proves the card *contains the basis* for the expected decision.
- **Recorded, manual:** the `observed` block holds the actual run. Absent ⇒ warning: the
  static rubric passes but the card has never been planned over.

**≥1 scenario of `kind: "refusal"` is mandatory.** A card that can never be declined is the
single-card version of a corpus that rejected nothing — the blind spot measured in 3
sibling KBs, one of which accepted 143 of 143 repos.

### Each recorded run must carry its `conditions` — enforced

A result without its conditions is not comparable to the next result, and comparability
over time is the entire value of a fixture. Required (**error** if absent):

- `model_class` — a run by a different class of consumer is a different experiment.
- `input_scope` — whether the consumer saw only `card.json`, or also `CARD.md`, `impl/`,
  or the repo. Both PC-0001 runs were **`card.json` only**; a run with repo access wearing
  the same scenario id would silently corrupt the comparison.

- `consumer_prior_exposure` — whether the consumer had already seen the card or the review
  that produced it. **Currency is not independence.** A run whose exposure does not begin
  with `none` is recorded in full but never counted as a baseline.

Recommended, and **warned** if absent, because without it staleness cannot be detected:

- `card_state_at_run.card_json_sha256` — compared against a live hash of `card.json`.

### The author cannot produce a naive baseline

This is structural, not a matter of care. Any agent the card's author delegates to inherits
the authoring conversation, which contains the expected answers. When the author ran SC-02
this way the agent self-reported no prior knowledge, and its reasoning route genuinely
differed from run 1's — weak corroboration — but **the author cannot verify a self-report of
prior knowledge.** That run is therefore recorded with
`consumer_prior_exposure: "UNVERIFIED …"` and does not count.

**Naive baselines must come from outside.** That is why the first two runs came from a
reviewer, not from the author, and why this is a required condition rather than a note.

### Staleness is keyed on a hash, not a version number

The first version keyed staleness on `tests_count`. That was wrong, and its own replacement
proved it: **two `card.json` defects were fixed without the test count changing at all**, so
a run recorded at that count would have looked current against a materially different input.
Consumers read `card.json`, so its bytes are the key.

The hash must be captured **at run time**. It was not, for the SC-02 re-run: the run
happened before the defects it surfaced were fixed, the file was overwritten in place, and
the hash of the bytes that consumer actually read is **unrecoverable**. A harness should
capture it; reconstruction after the fact is not possible.

### The fixture must be able to say that it is stale

Recording the conditions immediately exposed something the prose version had hidden:
**both PC-0001 runs predate the card they are filed under.** They ran against a 32-test
card; the card now has 34. SC-01's finding *was the reason* the card changed, so it is
explicitly **not reproducible** — a consumer today cannot rediscover the C3 gap, because
it is fixed.

The gate therefore prints, on every run:

```
scenarios=2 (refusal=1) runs-recorded=2 runs-against-current-card=0
```

`runs-against-current-card=0` is the honest description of PC-0001's present state. This
is a **warning, not an error**, and the reason is stronger than "staleness happens":

> **A successful consumer run destroys its own comparability.** Any run that surfaces a card
> weakness which then gets fixed invalidates itself as a baseline — the card it was run
> against no longer exists. So the steady state of a working fixture is *most runs stale,
> few current*, and **the most valuable runs are precisely the ones that go stale fastest.**

Failing the build on staleness would therefore punish the fixture for working, and pressure
authors to delete inconvenient history. But it must be *visible*, because **a fixture that cannot tell you it is stale is
worse than no fixture: it looks like evidence.** Each run also carries a prose
`reproducibility` verdict for what the count cannot capture.

Rubric keys the gate resolves: `must_flag_anti_patterns[]` · `must_cite_constraints[]` ·
`must_select_shape` · `must_not_select_shape` ·
`must_flag_unanswered_prerequisite_shape` · `must_build_monitoring_from` ·
`must_flag_naive_scan_via_edge{from,to}` · `must_take_escalation_exit` ·
`must_quantify_naive_cost_from` (dotted path).

## A domain prior is flat. Only the card knows the disparities.

The sharpest result from running the fixture, and it collapses two threads into one.

PC-0002's planning consumer disclosed that it already knew **all five anti-patterns
qualitatively** from general ML knowledge — and then drew the line itself: *direction from the
prior, but every **number**, the **conditionality** of A2, the 8-field identity tuple, and the
2⊸5 interaction from the card.*

That is the flattening thesis restated from the consumer's side:

> **A strong prior knows the list. It does not know the disparities.** "Don't truncate blindly,
> mask your pooling, normalise, key your cache properly, batch by length" is available to any
> competent practitioner. That the bucketing gain **peaks at 128 and falls at 512**, that
> unmasked pooling is **exactly harmless** over zero padding, that a 30-document sample
> understates chunks/doc by **11%** — none of that is in the prior, and all of it changes the plan.

**Consequences for the fixture, which are practical rather than philosophical:**

1. **`consumer_domain_prior` and `consumer_prior_exposure` are different fields.** Exposure to
   *the card* is contamination. Knowledge of *the domain* is not — it is the baseline the card
   has to beat, and a consumer with none of it would be useless. The first version of this
   schema conflated them, which would have disqualified two good runs.
2. **The contamination-resistant scoring signal is citation of values only the card contains.**
   A consumer reciting a prior produces the right list with no numbers. A consumer that has read
   the card cites the curve, the condition and the exception. Runs now record
   `card_specific_content_cited` for exactly this.

## Consumer runs are a discovery mechanism, not a validation one

**Two for two: every planning run, across both cards, found a real card defect.** That is no
longer a bonus — it is the reason the fixture is worth its cost.

| Run | Defect found | Would any gate have caught it? |
| --- | --- | --- |
| PC-0001 SC-01 | C3 recommended 3 `num_perm` values, measured 1 | No — every published number was correct |
| PC-0001 SC-02 #2 | `breakpoints` stated a bare `5000`, no unit | Not before it was observed; now gated |
| PC-0001 SC-02 #2 | `C1` published a measured value with no corpus | Not before it was observed; now gated |
| PC-0002 SC-01 | `chunks/doc` measured on 30 docs while everything else used 2000 | No — it was a real `[executed]` number, just under-sampled |

The fourth is the most instructive because **the number was not wrong, it was under-evidenced.**
`1.07` was genuinely measured and genuinely reproducible. It was measured on a 30-document
fixture, which is the low outlier of a converging series (1.067 / 1.120 / 1.196 / 1.184 at
n = 30 / 100 / 500 / 2000), and the full-corpus value 1.1840 is **11% higher** — real
under-provisioning for anyone sizing a job. A gate can check that a number exists and that a
test pins it. **It cannot ask whether the sample deserves the claim.** A consumer planning
real capacity asks that immediately.

### A rubric can be valid against the card and wrong for its own scenario

PC-0002's SC-01 carried `must_identify_from: recognition_signals`, copied from PC-0001's
diagnosis scenario. But SC-01 is a **proposal review** — nothing has shipped, so no symptom
exists to recognise. The consumer did the right thing (identified from the anti-pattern
catalogue, and cited a recognition signal as a *predicted* symptom), and **a strict scoring of
that line would have failed a correct answer.**

The static gate cannot catch this by construction: the expectation resolved to a real card
element, which is all the gate can check. **Rubric-to-scenario fit is only observable by
running the scenario.** Fixed by rewording the line to ask for a predicted symptom.

## Two self-reference traps, both live

**1. Run history must not live in `card.json`.** PC-0002 shipped a limitation reading *"this
card has never been planned over"*. Removing it after two consumers planned over it requires
editing `card.json` — and staleness is keyed on `card.json`'s bytes, so **recording that the
card was tested invalidates the runs that tested it.** Run history now lives only in
`scenarios.json`, and `card.json` points there.

**2. A generated value that measures its own file needs a fixed point.** The authoring-cost
table reports `CARD.md`'s line count, so writing it changes the number it just wrote. One pass
leaves the gate red — and since CI runs `--strict` and never syncs, **the sync tool itself would
have caused a red build.** `sync_cost_table` now iterates to convergence (two passes in
practice) and raises if it ever oscillates.

## Scoreboard: consumer runs 4, gate 0

Every defect below was found by a consumer planning over `card.json`, and **none of them
was findable by any check in this gate**:

| Defect | Found by | Would a gate catch it? |
| --- | --- | --- |
| C3 recommended `num_perm` for 3 thresholds, measured 1 | consumer, run 1 | No — every published number was correct |
| `breakpoints` stated a bare `5000` with no unit | consumer, run 2 | Not before it was observed; now gated |
| `C1` published a measured value with no corpus | consumer, run 2 | Not before it was observed; now gated |

Two of the four are now gated — but only *after* a consumer named them, and the fourth
(under-sampling) is **not gateable at all**: a gate can verify that a number is measured and
pinned, never that its sample deserves its claim.

That is the argument for keeping the fixture even though every run is expensive and manual:
**the gate enforces properties someone already knew to demand. The consumer test is the only
part of this apparatus that can tell you what you did not know to check.**

**Line counts are generated too, as of this revision.** I hand-wrote the authoring-cost table
twice and was wrong both times — once from estimates written before the files were final, once
as a typo (385 for 386) — in the section arguing that unexecuted numbers are untrustworthy.
Generating it also revealed the *baseline* had drifted: PC-0001 was quoted for a whole session
at 1453 lines / 0.97 and is actually 1534 / 0.98, because its own `scenarios.json` grew as runs
were recorded. A stale table is now a gate error.

## Twin consistency — CARD.md ↔ card.json

The two files are two records of one card. **The test count was once the only thing
cross-checked, and the flagship card drifted anyway** — its header said 30 tests while
`card.json` said 32 and 32 ran. Everything else agreed by luck.

Now cross-checked and failing on mismatch: `### Shape` headings ↔ `solution_shapes` ·
`**AN` ids ↔ `anti_patterns` · rejected table rows ↔ `rejected` · `**CN` ↔
`cost_model.constraints` · the `**Tests** | N` header cell ↔ `tests.count`.

**The test count is derived, not stated.** `--sync-ledger` runs the suite and writes the
real number into both twins. `tests.passing` was **removed** — the gate re-runs the suite,
so a hand-kept boolean can only ever be wrong.

## Two evidence records, deliberately not equal

`CARD.md` tags **prose claims**; `card.json`'s per-item `evidence` fields tag **structured
items**. Different populations — PC-0001 carries `12/3/4` in markdown and `10/9/0` in JSON.
Forcing equality would be wrong.

What *is* enforced: both must use the valid vocabulary, both are printed side by side so
divergence is visible, and **an id present in both must carry the same class** — A1 cannot
be `executed` in one record and `reasoned` in the other.

## Evidence classes

Tag every substantive claim:

| Tag | Means | Trust |
| --- | --- | --- |
| `[executed]` | a test in `tests/` fails if the claim is false | highest |
| `[cited]` | read from named real code, quoted | high — but see below |
| `[reasoned]` | argued from the other two, **not independently verified** | **lowest — treat as hypothesis** |

`[cited]` is *not* automatically safe. In the portfolio review, **every wrong row cited a
real file** — the path existed and the interpretation was wrong. Citing means "I read
this", never "therefore my conclusion is right".

**Convention:** tags annotate claims only. Do not write a tag in prose *about* the
classes — the counter excludes the blockquote legend and the ledger section, but not
arbitrary prose, so a mention elsewhere inflates the count. Say "unverifiable" instead.

## `card.json` required keys

`id` · `title` · `domains` · `one_line` · `recognition_signals[]` ·
`solution_shapes[]` (≥2, with `choose_when`) · `selection_rule` · `rejected[]` (≥1) ·
`decomposition{nodes[],edges[]}` · `cost_model{formula,constraints[],breakpoints[]}` ·
`anti_patterns[]` (≥1, with `diagnostic`) · `do_not_use_when[]` · `escalation[]` ·
`cited_evidence[]` · `tests{command,count}` · `related_cards[]`

**Edge types:** `requires` (ordering) · `splits-into` (sub-problems) ·
`composes-with` (output→input, may cross cards) · `conflicts-with` (mutually exclusive).
Every edge needs a `why`. Integer `to` must be a declared node; a string `to` names an
external pattern.

## What the gate enforces

`python3 validate_cards.py --strict` fails on:

1. a missing or <200-char required section
2. a `python` fence that does not parse
3. no `tests/`, tests that fail, zero collected, or a count ≠ `card.json`
4. zero anti-patterns, or zero rejected alternatives
5. fewer than 2 solution shapes
6. a cost model with almost no digits, or no breakpoints
7. an evidence ledger disagreeing with the actual tag counts
8. a decomposition edge to an undeclared node, an edge with no `why`, or no nodes
9. a `cited_evidence` path that does not exist **on disk**
10. malformed `card.json`

11. twin drift between `CARD.md` and `card.json` (shapes, anti-patterns, rejected,
    constraints, header test count)
12. an invalid `evidence` class in `card.json`, no per-item evidence at all, or an id whose
    class disagrees between the two records
13. missing `scenarios.json`, no `refusal` scenario, a scenario with no prompt or no
    rubric, a rubric expectation that does not resolve to a real card element, or a
    recorded run missing `conditions` / `model_class` / `input_scope` /
    `consumer_prior_exposure`
14. a `cost_model.breakpoints` entry stating a bare number with no `unit`

**Warns** (visible, not fatal): >50% of claims `reasoned`; no shape marked implemented; a
scenario with no recorded run; a header with no `**Tests** | N` cell; a recorded run whose
`card_json_sha256` is absent or stale; a run whose consumer had prior exposure; a constraint
publishing a `measured` value with no `measured_on`.

### In CI — `--strict` only, never `--sync-ledger`

Gate 7 of 8 in `portfolio_ci.sh` runs `--strict` and the gate's own 42 tests. **CI must
never sync.** `sync` regenerates derived values from ground truth — an *authoring* action.
A CI job that repairs drift instead of failing on it converts a correctness gate into a
freshness gate, which is the precise confusion that let a false claim ship into all 31
`llms.txt` files. Red build, then a deliberate author-run sync.

## Authoring workflow

```bash
# 1. write impl/ first, and tests alongside it. If it will not run, it is not a card.
python3 -m unittest discover -s tests -t .

# 2. MEASURE every number the card quotes. Do not write a cost claim you have not computed.
# 3. write CARD.md and card.json, tagging each claim.
# 4. generate the ledger (never hand-write the counts -- they drift within the hour)
python3 ../../validate_cards.py --sync-ledger

# 5. gate it
python3 ../../validate_cards.py --strict
```

Step 2 is not optional. The first draft of PC-0001 claimed "~6 days at one comparison per
nanosecond" for N=10⁶. Wrong by **1000×** — that is the *microsecond* figure. It read as
authoritative and nothing could check it. It is now computed by
`naive.estimated_wall_clock` and pinned by a test. **If a cost claim in a card cannot be
executed, distrust it.**

## A hazard that bit this file's own test suite

While tidying a duplicated `if __name__ == "__main__":` block, a two-line cleanup deleted an
entire test class — **3 tests silently removed.** The suite then reported `Ran 53 tests OK`,
the gate reported `errors=0 warnings=0`, and nothing anywhere indicated a loss.

It was found **only** by mutation-checking: two gate checks were disabled and the suite
still passed, which is impossible if their tests exist. The lesson is not "be careful with
string surgery":

> **A passing suite is evidence about the tests that ran, and says nothing about tests that
> no longer exist.** Test count is a claim like any other — it needs a second source.
> Mutation-checking is that source, because a check with no failing test is indistinguishable
> from a check with no test at all.

## Failure modes to avoid

- **Depth theatre.** Long prose that asserts rather than demonstrates. The gate counts
  characters; only tests count as evidence.
- **`reasoned` creep.** Easiest tier to write, worthless to a planner. Keep it under a
  third, and always enumerate which claims it covers.
- **One-shape cards.** A card with a single solution cannot answer "optimally".
- **Missing negative knowledge.** An AI without anti-patterns will confidently recommend
  the wrong thing. This is why ≥1 is mandatory and not merely encouraged.
- **Citing without reading.** Do not infer a fact about code from an index, a filename, or
  a search result. *An index is not the disk* — a real error made in the sibling review:
  a package was declared "absent from the portfolio" when it was a subtree of the very
  repo under discussion, in four places.
