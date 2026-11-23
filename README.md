# decision-cards

Five evidence-graded **engineering decision cards**, plus the authoring schema and the
depth gate that keeps them honest. A card is a *problem*, not a tutorial: it exists so
that an engineer (or an AI planner) can recognise a situation from observable signals,
choose between real alternatives, decompose the work, and know when it has gone wrong.

| Card | Problem |
|---|---|
| **PC-0001** | Near-duplicate detection at scale — without comparing every pair |
| **PC-0002** | Embedding generation for a corpus — identity, caching, and what silently goes stale |
| **PC-0003** | Idempotency under retries — when two requests are "the same operation" |
| **PC-0004** | Evolving a serialized contract without silently corrupting data |
| **PC-0005** | What deserves to wake a human — alarm portfolios and attention as a budget |

## Coverage, honestly

This corpus covers **platform and data engineering**: deduplication, embedding pipelines,
idempotency, schema evolution, and operational alerting. It contains **no modelling
discipline** — nothing here teaches forecasting, recommendation, vision, or causal
inference. Cards were written where measured evidence could be produced; none were
manufactured to fill coverage gaps, because an unmeasured card is just an opinion with
a template.

## Evidence classes — and the reproducibility bar

Every claim in every card carries a class:

| Class | Meaning | Your move as a reader |
|---|---|---|
| `[executed]` | a test in that card's `tests/` fails if the claim is false | re-run it (below) |
| `[cited]` | read in real production code — which is *not* the same as correct | treat as testimony |
| `[reasoned]` | argued from the other two, not independently verified | treat as hypothesis |

The bar for `[executed]` is reproduction, not trust: every such claim is pinned by a test
that ships in this repository, the implementations are **pure standard library** (no
dependencies to pin), and each card's §12 ledger is *generated* by
`validate_cards.py --sync-ledger`, because hand-maintained counts drifted within an hour
of the first card being written.

```bash
cd cards/PC-0001-near-duplicate-detection-at-scale
python3 -m unittest discover -s tests -t .        # every [executed] claim, re-run
```

## What "public edition" means here

These cards were authored inside a large e-commerce engineering organization, and the
reference implementations were **written for the cards** — they are original, stdlib-only
code and ship verbatim. Three things changed for publication, each visible on its face:

1. **Citations to private production code are anonymized.** Paths now read
   `private:...` with a system description; one verbatim snippet is paraphrased with
   variable names changed and logic preserved (PC-0001 §3, marked as such). The `[cited]`
   class already meant "read in real code, not thereby correct" — in this edition those
   sources are additionally not independently checkable, so weigh them accordingly.
2. **The fleet-grounding layer is removed.** The original workspace corroborated several
   claims against internal fleet scans and ticket data that cannot ship. Affected claims
   stand on their simulator and analytic evidence, and their `card.json` says what kind of
   evidence backs them.
3. **The experiment apparatus stayed home.** Consumer-run studies, grounding artifacts,
   and the research ledger are not part of this edition; self-citations to them are
   marked `"unshipped": true` and the validator knows the convention.

Nothing else was rewritten. The corrections the cards keep on display (e.g. PC-0001's
1000×-wrong wall-clock estimate, preserved with its fix) are part of the method:
if a cost claim cannot be executed, distrust it.

## Guards

```bash
python3 validate_cards.py --strict     # the depth gate: 12 sections, generated ledger,
                                       # resolving decomposition edges, evidence vocab
python3 check_public_edition.py        # leak scan, link resolution,
                                       # every [executed] claim maps to a shipping test
python3 -m unittest test_validate_cards.py   # 106 tests on the gate itself
```

The schema and its rationale — why every rule is a gate rather than a guideline, with the
measured decay data that motivated each — is in [SCHEMA.md](SCHEMA.md).
