# PC-0004 — Evolving a serialized contract without silently corrupting data

| | |
| --- | --- |
| **Card** | PC-0004 |
| **Domains** | schema evolution · serialization · backward compatibility · rolling deploys |
| **Tests** | 37 |
| **Run** | `cd cards/PC-0004-schema-evolution-compatibility && python3 -m impl.measure` |
| **Related** | PC-0003 (request identity) · PC-0002 (cache-key identity) |

> Evidence tags: `[executed]` a test in `tests/` fails if the claim is false · `[cited]` read
> from named real code · `[reasoned]` argued from the other two and not independently verified.

---

## 1 · Problem statement

A field needs to change in a contract that already has data behind it and more than one
version of the code live at once. The diff is one line. The review has no way to tell whether
it is safe, and the compatibility checker in CI may pass it and be right to.

What is specifically hard is not the change, it is that **safety is not a property of the
change at all**. It is a property of the change *against the codec*, and the codec does not
appear in the diff. The same one-line edit — rename a field — is completely safe on a
tag-keyed format and destroys the field on a name-keyed one `[executed]`. Renumbering is the
exact mirror. So "is renaming safe?" is not a question with an answer, and any advice that
gives it one is wrong roughly half the time.

The second hard part is the failure *mode*. Of 15 broken (change, codec, direction)
combinations measured here, 12 decode **successfully** into a wrong value and only 3 raise
`[executed]`. There is no exception, no elevated error rate and nothing in a log. The signal
arrives weeks later as a reconciliation that does not balance, by which time the corrupted
rows are indistinguishable from correct ones without the original bytes.

## 2 · Recognition signals

Observable without knowing this pattern's name:

- A schema diff is one line and nobody in the review can say whether it is safe.
- A field was added weeks ago and a fraction of rows still hold its default — **with no errors
  logged anywhere**.
- The error rate is flat and unremarkable while a reconciliation reports rows that do not add up.
- **The same change was applied to two services and only one of them broke.** This is the
  strongest single signal, because it points directly at the codec rather than the change.
- A field was removed, its number or column position was reused later, and old records now
  decode into the new field.
- A rolling deploy is clean in staging — where only one version is ever live at a time, so
  staging cannot exercise either direction.
- **A compatibility checker passed the change and the data is wrong anyway.**
- An old reader edits one field of a record and the fields it does not know about come back empty.

## 3 · Why the naive approach fails

The naive approach is the one nearly everyone uses, and it is not laziness — it is a true
premise with a false conclusion:

> "Unknown fields are ignored on read, so adding fields is safe and removing them is
> tolerated."

The premise is true. The conclusion does not follow, because **ignoring a field on the way in
means omitting it on the way out.** A reader that does not know a field cannot re-emit it, and
read-modify-write is the ordinary shape of almost every service.

Measured: an old reader reads a record containing a new field, edits one unrelated field, and
writes it back. On name-keyed and positional codecs, **1000 of 1000 records lost the new
field, with 0 errors raised** `[executed]`. 100% data loss at a 0% error rate — the worst
available combination, because nothing is available to alarm on.

The loss is **codec-dependent, not universal** `[executed]` — an earlier draft claimed total
loss "on all three codecs", which was wrong and is retracted: a tag-keyed codec retains
unknown tags automatically, losing **0 of 1000 with no application-level help**, a behaviour
cross-checked against real protobuf (`test_tagged_retention_matches_real_protobuf`).
Enabling application-level unknown-field retention takes the name-keyed codec to **0 of
1000** as well `[executed]`. On a positional codec retention is **structurally impossible**:
an unknown field there has no identity to carry, only an offset the old schema does not
possess `[executed]`.

The second naive move is to trust a schema-registry compatibility check. It will pass an
`int64 → int32` narrowing, correctly by its own lights, because **narrowing's safety is a
property of the values and a registry sees only schemas** `[executed]`. Measured with 10% of
rows above the boundary: 100 of 1000 rows silently wrong, 0 raised. The single-record matrix
reports the same change as SAFE, and both results are correct.

A real instance of the migrate step, from the tooling this corpus was built with (the
experiment recorder is not shipped in this edition): its record command moves a scenario's
single `observed` object into an `observed_history` list on first write `[cited]`. It
exists because an earlier version simply dropped the first run when a second was recorded —
runs-recorded fell from 2 to 1, with complete output and no error.

## 4 · Solution shapes

### Shape A — S1 · Expand / migrate / contract, three deploys, never fewer

**Choose when** the matrix reports IMPOSSIBLE for your change on your codec: neither deploy
order is safe, so no single-step version of the change exists. Add the new field, dual-write,
backfill, move readers, and only then remove the old one.

Measured: **6 of 27** (change, codec) pairs are IMPOSSIBLE in one step, across **5** distinct
changes `[executed]`. IMPOSSIBLE is a stronger statement than "be careful about ordering" —
no sequence of two deploys is safe, so the change must be decomposed into more of them.

**Limit:** requires that both fields can coexist. A positional codec cannot hold a widened row
without that itself being an insert, so Shape A degrades to Shape C there `[reasoned]`.

### Shape B — S2 · Additive-only with permanently frozen fields

**Choose when** one or more readers are outside your control, so the contract can never be
narrowed and "we will migrate them later" is not available to you.

Measured: `add_optional` is the only structural change SAFE in all 6 cells `[executed]`.
`remove_field` also measures SAFE in a single hop — **which is exactly what makes it a trap**,
because the single-hop measurement is clean and the damage appears only in the
read-modify-write path.

**Limit:** monotonic growth is a real cost that arrives later as dead fields nobody dares
delete. It buys safety with permanent surface area.

### Shape C — S3 · Versioned envelope, readers branch on an explicit version

**Choose when** the change is IMPOSSIBLE *and* you cannot sequence deploys, or the codec is
positional and therefore has no safe structural edit at all.

On a positional codec, 4 of 9 changes are IMPOSSIBLE and retention is structurally
unavailable, so the envelope is the only remaining option rather than a preference
`[executed]`.

**Limit:** every reader carries every historical branch forever, and each is a path that must
stay tested. **Not implemented in `impl/`** — this shape is `[reasoned]` from the measured
positional results, and it is the only shape here without its own test.

### Shape D — S4 · Unknown-field retention on read-modify-write paths

**Choose when** any reader reads a record, edits part of it and writes it back. That is not an
exotic case; it is the ordinary shape of almost every service.

Measured: without retention, 1000/1000 lost on name-keyed and positional; a tag-keyed codec
already retains (0/1000 with no application help). With retention, 0/1000 on name-keyed;
structurally impossible on positional `[executed]`.

**Limit:** this is **orthogonal to A–C, not an alternative.** Retention prevents loss on
write-back and does nothing whatever about a change being unsafe to deploy. A safe change with
an unprotected read-modify-write path still loses data.

**Selection rule.** Establish what the codec keys on **first** — name, number, or position —
because every later answer changes with it. Then look up the change. `either` → ship it.
`writers` → ship writers first. `IMPOSSIBLE` → decompose into Shape A, or adopt Shape C.
Independently of all of that: if any reader does read-modify-write, Shape D is mandatory.

## 5 · Alternatives rejected

| Alternative | Verdict |
| --- | --- |
| **R1 — coordinate one simultaneous deploy of every reader and writer** | **PEER, not worse.** If you own every reader and can stop the world, this is genuinely correct and cheaper than three deploys. Rejected as a *general* answer because the measured asymmetry does not need it: 18 of 27 pairs are safe in either order and 3 more need only writers-first, so **21 of 27 require no coordination at all** `[executed]`. Buying a stop-the-world for those is a large price for nothing. |
| **R2 — version the endpoint instead: `/v1`, `/v2` side by side** | **PEER**, and correct for a public HTTP API whose consumers upgrade on their own schedule. Rejected for a *storage* contract because the records already written do not move to `/v2`: one physical store still holds both shapes, so the endpoint version relocates the problem instead of solving it, and now two code paths write the same rows `[reasoned]`. |
| **R3 — rely on the codec's tolerance: "unknown fields are ignored"** | **WRONG**, and the most common answer given. True premise, false conclusion — measured at 1000 of 1000 records losing the field through an ordinary read-modify-write on name-keyed and positional codecs, with zero errors raised (tag-keyed codecs retain, which is codec luck, not safety) `[executed]`. Tolerance on arrival is not durability. |

## 6 · Decomposition

Eight sub-problems. Interfaces are in→out; the typed edges live in `card.json`.

| # | Sub-problem | In → Out | Owns the risk that |
| --- | --- | --- | --- |
| 1 | Identify what the codec keys on | wire format → name / number / position | every later verdict is undefined without it |
| 2 | Enumerate live readers and writers | deployment topology → the set of coexisting versions, and which are unowned | an unowned reader turns Shape A into Shape B permanently |
| 3 | Classify the change | (change, codec) → verdict per direction | a verdict is asserted rather than measured |
| 4 | Derive the deploy order | two verdicts → either / writers / IMPOSSIBLE | IMPOSSIBLE is treated as "be careful" |
| 5 | Find read-modify-write paths | reader inventory → readers that write records back | node 4's verdict is mistaken for the whole answer |
| 6 | Check value ranges against new types | live data → count of rows outside the narrowed domain | node 3 is completed from schemas alone |
| 7 | Reserve retired names, numbers, offsets | removal history → a permanent do-not-reuse list | the *next* change reuses an identifier |
| 8 | Sequence the deploys | all of the above → an ordered plan | the plan has fewer deploys than the change needs |

The load-bearing edge is **6 → 3**: narrowing's verdict is data-dependent, so node 3 cannot be
completed from the schemas alone. **That is precisely the edge a schema registry does not
have**, which is why it passes a change that corrupts data.

## 7 · Cost & scale model

**This card has no cost model, and that is the honest answer rather than a gap.**
`cost_model.non_quantitative_because` says so explicitly in `card.json`.

All nine changes are one schema edit plus one rolling deploy. They take the same time, need
the same people and cost the same money. What separates them is whether the data survives —
a correctness property, which has no curve. Inventing a price for corruption to satisfy the
shape of a cost model would produce a decorative number, and a decorative number is worse
than an honest absence.

What does exist is a matrix of **outcome counts**, and those live on the shapes and
anti-patterns where they describe consequences rather than prices.

**C1 compatibility is a property of a change against a CODEC, not of the change** — the same
edit is safe on one wire format and silent corruption on another, and the codec does not appear
in the diff `[executed]`.

**C2 rename and renumber are exact mirror images** — each is completely safe on one codec and
has no safe single-step deploy on the other. "Renaming is safe" is therefore wrong about half
the time, and the diff does not say which half `[executed]`.

**C3 broken cells overwhelmingly fail SILENTLY, not loudly** — a loud failure is found in
staging; a silent one is found in a reconciliation, if ever `[executed]`.

**C4 a lagging reader drops unknown fields on write-back — on codecs without built-in
retention** — so an ordinary read-modify-write destroys data that arrived intact, and the
read itself never fails `[executed]`. (Originally claimed for all three codecs; retracted to
name-keyed and positional — tag-keyed retains automatically, verified against real protobuf.)

**C5 narrowing is the only change whose safety depends on the VALUES** — which is why a
schema-registry check cannot detect it: the information required is absent from its input, not
from its logic `[executed]`.

**C6 some changes have no safe deploy order at all** — a different statement from "order them
carefully", and the reason Shape A exists `[executed]`.

**C7 the direction asymmetry is structural** — a reader that does not understand a field can
ignore it, whereas a writer that omits a field a reader *requires* cannot be tolerated. So
writers-first is sometimes safe and readers-first never is, for these nine changes `[executed]`.
**C8 a codec is a property of the READER, not of the file** — a CSV with a header row is
name-keyed under `csv.DictReader` or `pandas.read_csv`, and **positional** under `csv.reader`,
`split(',')`, `awk`, or a warehouse `COPY`, which is positional by default. On byte-identical wire,
`reorder_fields` is *either* for a header reader and **IMPOSSIBLE** for a positional one, while
`rename_field` is exactly inverted — the two readers are precise mirrors **within one file format**
`[executed]`. So C2's mirror is not a JSON-versus-protobuf fact; it is a fact about what the reader
keys on, and the wire format only constrains which readers are possible. One verdict cannot describe
a CSV. **Enumerate readers, not formats**, and take the worst verdict across them.


**Breakpoints are structural rather than numeric** — at 1 reader you do not control, at 2 live
schema versions, at 1 read-modify-write path, at 1 reachable retired identifier. Each carries
its unit in `card.json`.

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

## 8 · Code

Runnable as written from the card directory.

```python
from impl.changes import rename_field, narrow_type
from impl.measure import compatibility_matrix, required_deploy_order, read_modify_write
from impl.wire import BASE, NamedCodec, TaggedCodec, roundtrip, sample_record

# The mirror: one edit, two codecs, opposite outcomes.
rec = sample_record(7)
new = rename_field(BASE)
print(roundtrip(BASE, new, TaggedCodec, rec)[0])   # SAFE
print(roundtrip(BASE, new, NamedCodec, rec)[0])    # SILENT_WRONG

# What order does this change need?
order = required_deploy_order()
print(order[("rename_field", "tagged")])           # either
print(order[("rename_field", "named")])            # IMPOSSIBLE

# The read-modify-write hole, with and without retention.
print(read_modify_write(NamedCodec, n=1000, preserve_unknown=False)["lost"])  # 1000
print(read_modify_write(NamedCodec, n=1000, preserve_unknown=True)["lost"])   # 0
```

## 9 · Verification

| Claim | Test that proves it |
| --- | --- |
| rename/renumber are exact mirrors | `test_the_two_are_exact_mirrors` |
| 12 of 15 broken cells fail silently | `test_four_in_five_broken_cells_fail_SILENTLY` |
| 5 changes have no safe single-step deploy | `test_five_changes_have_no_safe_single_step_deploy_on_some_codec` |
| readers-first is never required | `test_no_change_ever_requires_readers_last` |
| RMW loss is codec-dependent; retention fixes name-keyed | `test_loss_without_retention_is_CODEC_DEPENDENT_not_universal`, `test_unknown_field_retention_eliminates_the_loss_on_keyed_codecs`, `test_tagged_retention_matches_real_protobuf` |
| positional retention is impossible in principle | `test_a_positional_codec_cannot_retain_unknowns_even_in_principle` |
| narrowing is silent and data-dependent | `test_a_minority_of_rows_is_corrupted_and_nothing_raises`, `test_narrowing_is_the_only_change_whose_verdict_depends_on_the_DATA` |
| the fixture can actually fail | `test_fixture_values_must_differ_from_their_defaults` |

**How a reader verifies against their own contract**, without adopting any of this code: take
one real record, encode it with the current schema, decode it with the proposed one, and
**compare values field by field** — then do it in the other direction. If either comparison
differs while no exception was raised, you have found a silent case. The single most important
detail is that asserting "no error was raised" cannot see 80% of the failures in this table.

## 10 · Anti-patterns

**A1 reusing a retired field number or column offset** — *Diagnostic:* the new field is
populated for rows written before it existed. SILENT_WRONG in both directions on tagged and
positional; **SAFE on name-keyed**, which is why the habit survives in teams that have only
used JSON `[executed]`. *Fix:* reserve retired identifiers permanently — two individually
defensible commits compose into corruption, so the guard must live in the schema, not in
review memory.

**A2 reordering or inserting fields in a positional format** — *Diagnostic:* every field after
the edit point reads as a plausible value of the wrong column. Both changes SILENT_WRONG in
both directions on positional, both SAFE on named and tagged `[executed]`. *Fix:* append only,
or move off positional. A commit that alphabetises columns is data-corrupting and looks like
whitespace.

**A3 renaming on a name-keyed codec, or renumbering on a tag-keyed one** — *Diagnostic:* the
field reads as its default everywhere, and rows whose real value happened to equal the default
look correct. Neither is recoverable by deploy ordering; both are IMPOSSIBLE `[executed]`.
*Fix:* treat it as expand/migrate/contract. Never as a rename.

**A4 read-modify-write through a reader that lags the writer** — *Diagnostic:* a field is
populated on write and empty later, with no error and no log line anywhere. 1000 of 1000 lost,
0 raised, on name-keyed and positional codecs; retention takes name-keyed to 0 `[executed]`.
*Fix:* enable retention on every reader that
writes records back, or forbid whole-record writes from a lagging reader.

**A5 narrowing a type because current values fit** — *Diagnostic:* a minority of rows —
reliably the largest ones — hold wrapped values while every decode succeeds. 100 of 1000 wrong
with 0 raised at 10% over the boundary `[executed]`. *Fix:* never narrow a live field; add a
new one. And do not accept a schema-only verdict for a type change.

**A6 adding a required field with no default** — *Diagnostic:* a hard decode error on every
record from an older writer, immediately, in staging. HARD_FAIL forward on all three codecs
`[executed]`. **Listed as the counter-example:** it is the only change of the nine that fails
loudly, therefore the only one that is genuinely cheap to get wrong — and it is the one people
fear most. *Fix:* give it a default, or add it optional and enforce presence in application code.

**A7 treating "it parses" or "the checker approved it" as compatibility** — *Diagnostic:* a
green compatibility check, a clean deploy, flat error rates, and a reconciliation that does not
balance. 12 of 15 broken cells decode successfully into a wrong value; all 3 that raise are the
same change `[executed]`. *Fix:* test both directions with real records and **assert values**,
not the absence of exceptions.
**A8 trusting a header row to make a text format name-keyed** — *Diagnostic:* a column reorder is
reviewed as a tidy-up and approved because "the file has a header", and exactly one downstream
consumer's numbers shift while every other consumer is fine. On identical bytes, a reorder is
`SAFE`/`SAFE` for a header-parsing reader and `SILENT_WRONG`/`SILENT_WRONG` — IMPOSSIBLE — for a
position-parsing one; a rename is exactly inverted `[executed]`. The header is present in the bytes
in every one of those cases; it protects only the readers that actually read it. *Fix:* enumerate the
readers and classify each, then take the worst verdict. Warehouse bulk loaders and shell pipelines
are the ones that surprise people. If you cannot enumerate them, that is an escalation exit, not a
reason to assume the header saves you.


**When NOT to use this card:** a single writer and single reader deployed atomically together
(no version window exists, so nothing here has anything to act on); a discardable cache entry;
a fully self-describing format read by reflection with no compiled schema; API surface design
rather than a live contract; or the case where you own every reader and can stop the world — R1
is then correct and this card is overhead.

## 11 · Escalation

| Symptom | Next move |
| --- | --- |
| You cannot determine what the codec keys on | **Stop. Do not classify the change.** Encode with the old schema, decode with the candidate, compare values — 20 lines, and it settles C1 empirically. |
| IMPOSSIBLE and you cannot run three deploys | Adopt Shape C and accept the permanent branch, or do not make the change. Do not try to order two deploys cleverly: no ordering exists. |
| Safe change, but a reader does RMW and retention is unavailable | The reader must stop writing whole records. Route the edit through a current-schema writer, or make the update field-scoped. |
| You need the count of rows exceeding a narrowed type and cannot query it | **Do not narrow the column.** C5 makes this undecidable from schemas, and A5 shows the failure is a silent minority — the shape a sample misses. |
| The contract is positional and you need any structural change | **Leave this card.** The question is now whether to migrate off a positional format, which is a data-migration problem. |
| The record has an identity and retries may deliver it twice | **Leave this card for PC-0003.** Field identity and request identity are different problems. |
| Two writers disagree about the current schema version | **Leave this card.** That is a coordination problem; compatibility rules cannot resolve a disputed source of truth. |

## 12 · Evidence ledger

| Class | Count |
| --- | --- |
| `[executed]` | 29 |
| `[cited]` | 1 |
| `[reasoned]` | 3 |

**Every `[reasoned]` claim, by name** — these are hypotheses, not results:

1. **Shape A degrades to Shape C on a positional codec.** Argued from the measured positional
   results; no test constructs a widened positional row.
2. **Shape C (versioned envelope) as a whole.** Not implemented in `impl/`. Its selection
   condition is measured; its behaviour is not.
3. **R2 (endpoint versioning) is wrong for storage contracts.** Argued from the observation
   that written records do not move; not simulated.

**Authoring honesty — three measurements were discarded as fixture artifacts before anything
was written.** (1) `rename_field` measured SAFE on a name-keyed codec because the fixture set
`currency="USD"`, the field's own default, so a completely lost field returned a value equal to
the real one. (2) `renumber_field` measured SAFE on tagged for the same reason. (3)
`narrow_type` measured SAFE on all three codecs with 0/1000 rows wrong because the oracle
computed its expected value by coercing through the **reader's** type, comparing the truncation
against itself. All three are now regression-tested. The third is the sharpest, and it
generalises: **an oracle that applies the transformation under test to its own expectation
cannot fail, and reports that inability as a pass.**

**This card also changed the gate that validates it.** PC-0004 is the first card entitled to
`cost_model.non_quantitative_because`, and check 6 counted the digits *inside that field* —
12 of them, unavoidably, because explaining why a correctness problem has no cost curve
requires naming the outcome counts that exist instead of one. The cost model scores 7 on its
own and 19 with the justification, so the gate warned that the escape hatch was unused. **The
field whose entire purpose is to say "this cannot be quantified" was read as quantification and
voided itself** — the same class as check 6's original defect, one level up.

---
