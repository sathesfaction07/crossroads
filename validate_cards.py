#!/usr/bin/env python3
"""validate_cards.py — the depth gate for problem cards.

WHY THIS EXISTS
---------------
Measured, in this same workspace: 18 of 31 knowledge bases decayed to ~30-character
evidence strings that name no file and can be checked against nothing. That was not bad
authoring. Those KBs are indistinguishable in intent from the 13 that stayed deep --
the difference is that NOTHING FORCED THEM to stay deep.

So depth here is not a convention, it is a gate. Every check below fails the build, and
every one of them corresponds to a failure actually observed:

  1. required sections present AND non-empty       <- the 30-char decay
  2. every python fence parses                     <- "a description of code is not code"
  3. tests exist, RUN, and the count matches       <- lets `executed` mean something
  4. >=1 anti-pattern and >=1 rejected alternative <- 3 KBs had ZERO counter-examples;
                                                      one accepted 143 of 143 repos
  5. >=2 solution shapes                           <- "optimally" is void with one option
  6. cost model QUANTIFIES (ids excluded)          <- the first version counted digits
                                                      anywhere, so C1..C10 with claims of
                                                      "it depends" scored 11 and PASSED
  7. evidence ledger matches the actual tag counts <- hand-maintained counts always drift
  8. decomposition edges resolve                   <- a KB once deferred to a sibling that
                                                      rejected the package: a pointer to nowhere
  9. cited paths exist ON DISK                     <- "an index is not the disk"
 10. reasoned-fraction is reported, not hidden     <- 33% of `verified` rows were wrong;
                                                      unverifiable claims must be visible
 11. CARD.md and card.json must not drift         <- they did, within a day: header said
                                                      30 tests, card.json said 32, 32 ran
 12. card.json per-item evidence is validated     <- it was never counted at all, though
                                                      a JSON-only consumer weights by it
 13. consumer scenarios: rubrics resolve to real  <- the only check that tests PURPOSE
     card elements; >=1 refusal; each recorded       rather than shape, and the only one
     run carries its comparability conditions       padding cannot satisfy
 14. breakpoints state a unit; measured values     <- a consumer compared 1,619,100
     state the corpus they were measured on           COMPARISONS to a 5,000-ITEM
                                                      threshold, and quoted an 80-doc
                                                      fixture's recall onto 1,800 contracts
 17. `executed` claims declare a GROUNDING, and    <- PC-0004's 54-cell wire-format
     a simulator-grounded card must be                SIMULATOR printed the same
     corroborated from outside this repo or            `[executed]` tag as PC-0002's
     declare claim_strength="direction"                `dot == cosine` ALGEBRAIC identity.
                                                      Its one citation pointed back into
                                                      problem-cards/ -- self-citation.

Usage:  python3 validate_cards.py [--strict]
"""
from __future__ import annotations

import ast
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CARDS = os.path.join(HERE, "cards")
# cards/<card>/ -> problem-cards/ -> the portfolio root that cited paths are relative to
PORTFOLIO_ROOT = os.path.dirname(HERE)

REQUIRED_SECTIONS = [
    "Problem statement",
    "Recognition signals",
    "Why the naive approach fails",
    "Solution shapes",
    "Alternatives rejected",
    "Decomposition",
    "Cost & scale model",
    "Code",
    "Verification",
    "Anti-patterns",
    "Escalation",
    "Evidence ledger",
]
EVIDENCE_CLASSES = ("executed", "cited", "reasoned")
MIN_SECTION_CHARS = 200

# Conditions every recorded consumer run must carry, or the result is not comparable to
# the next one. `consumer_prior_exposure` is here because model_class + input_scope do NOT
# capture whether the consumer already knew the card or its review -- and the card's own
# author structurally cannot produce a run free of it.
REQUIRED_CONDITIONS = ("model_class", "input_scope", "consumer_prior_exposure")


def sections(md: str) -> dict[str, str]:
    """Split on '## ' headings, tolerating a leading section number like '## 3 · '."""
    out, name, buf = {}, None, []
    for line in md.splitlines():
        if line.startswith("## "):
            if name:
                out[name] = "\n".join(buf)
            name = re.sub(r"^\d+\s*[·.\-]\s*", "", line[3:]).strip()
            buf = []
        elif name:
            buf.append(line)
    if name:
        out[name] = "\n".join(buf)
    return out


def python_fences(md: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", md, flags=re.S)


def claim_body(md: str) -> str:
    """The part of a card where an evidence tag means "this claim is so evidenced".

    Excludes (a) blockquote lines -- the legend at the top defines the tags, it does not
    use them, and (b) everything from the Evidence ledger heading down -- that section
    tabulates and discusses the tags.

    Without this, counting was inflated by the legend, the ledger's own table rows, and
    any prose mentioning a class name: 8 "reasoned claims" were really 4. The
    ledger-vs-actual check then enforced agreement with a wrong number, which is the
    worst kind of green check.
    """
    lines = []
    for line in md.splitlines():
        if re.match(r"^##\s*\d*\s*[·.\-]?\s*Evidence ledger", line):
            break
        if line.lstrip().startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines)


def count_evidence(md: str) -> dict[str, int]:
    """Count evidence tags used AS CLAIM ANNOTATIONS, not merely mentioned."""
    body = claim_body(md)
    return {c: len(re.findall(rf"`\[{c}\]`", body)) for c in EVIDENCE_CLASSES}


def ledger_counts(md: str) -> dict[str, int]:
    """Parse the declared counts out of the Evidence ledger table."""
    out = {}
    for c in EVIDENCE_CLASSES:
        m = re.search(rf"\|\s*`\[{c}\]`\s*\|\s*(\d+)\s*\|", md)
        if m:
            out[c] = int(m.group(1))
    return out


# The cross-card relation vocabulary. One spelling per relation, because the index publishes
# these edges and a consumer filtering on the value must not have to guess which variant a
# given card chose. Found on inspection: PC-0001 and PC-0002 said "composes-with" while
# PC-0003 said "composes_with" -- two names for one thing, across three cards.
RELATION_VOCAB = ("composes_with", "conflicts_with", "supersedes", "prerequisite_of")
MIN_WHY_CHARS = 40

# `executed` was doing two incompatible jobs, and merging them is the claimed-vs-evidenced
# failure this whole schema was built against -- one layer down.
#
#   ANALYTIC          the code IS the subject. `overlap >= k-1` is index arithmetic, zero-pad
#                     pooling is algebra, C6 is a property of hashing. Running it self-certifies.
#   SYNTHETIC-FIXTURE a constructed population. Real numbers, but about a fixture I chose.
#   SIMULATOR         the code is a MODEL of an external phenomenon. Executing it proves the
#                     card's numbers faithfully preserve the simulator -- PIN-fidelity -- and
#                     says nothing whatever about WORLD-fidelity.
#   PRODUCTION-DATA   measured on real traffic or a real corpus.
#
# PC-0004's compatibility matrix is a simulator: 54 cells of my own wire-format model. Its
# `[executed]` tag looked identical to PC-0002's `dot == cosine after normalising`, which is an
# algebraic identity. Those are not the same kind of knowledge and must not print the same.
GROUNDING_VOCAB = ("analytic", "synthetic-fixture", "simulator", "production-data")

# A simulator-grounded card must be corroborated from OUTSIDE this repository before it claims
# more than direction. A citation pointing back into problem-cards/ is a self-citation: PC-0004
# cites `problem-cards/run_scenarios.py`, which I wrote in the same session as the card, so it
# corroborates nothing. The precedent for what does count is PC-0002's C5, which cites a real
# internal pipeline carrying the comment "L2-normalise once so that dot = cosine" -- code
# written by someone else, without reference to this card.
SELF_CITE_PREFIX = "problem-cards/"

# How far a card is entitled to be trusted. `direction` is the honest floor for a card whose
# numbers come from a model of the world rather than the world: it says "the shape of this is
# right, the magnitudes are mine". Declaring it is permitted and costs nothing; presenting
# modelled numbers as measurements is what is forbidden.
CLAIM_STRENGTHS = ("direction", "magnitude", "exact")

# WHAT an external citation actually underwrites. Introduced because the understatement warning
# below fired on PC-0005 purely because citations EXISTED, while both of those citations state in
# their own `honest_limit` that they corroborate the operating REGIME and an existing PRACTICE and
# say nothing about magnitudes. A presence check cannot tell "real services sit in this band" from
# "these numbers are right", so it pushed toward inflating claim_strength on evidence that does not
# support it -- the precise failure the grounding vocabulary exists to prevent, inverted.
#
#   regime     the operating range the card measures is where real systems actually sit
#   practice   the technique the card recommends exists in production, with real tooling
#   mechanism  the causal structure is confirmed by real code (including code that CHANGED
#              the card's recommendation, which is the strongest form of this)
#   magnitude  the measured VALUES are corroborated -- the only one that licenses more than
#              `direction`, and none of this portfolio's six citations claims it
CORROBORATES = ("regime", "practice", "mechanism", "magnitude")


def canonical_relation(rel) -> str | None:
    """Return the canonical spelling of a declared relation, or None if it is not one.

    Normalising hyphens and spaces is deliberately NOT the same as accepting anything: a
    relation that normalises INTO the vocabulary is drift (warn, fixable), while one that does
    not is invented (error). Accepting both spellings as equally valid would be the same
    mistake as adding a placeholder to a service-account allowlist to make a test pass.
    """
    if not isinstance(rel, str):
        return None
    norm = rel.strip().lower().replace("-", "_").replace(" ", "_")
    return norm if norm in RELATION_VOCAB else None


def all_card_ids() -> set[str]:
    """Every card id present on disk, so a cross-card edge is resolved rather than assumed.

    Reads the disk for the same reason check 9 does: an index is not the disk.
    """
    out: set[str] = set()
    if not os.path.isdir(CARDS):
        return out
    for d in sorted(os.listdir(CARDS)):
        p = os.path.join(CARDS, d, "card.json")
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                cid = json.load(fh).get("id")
        except (json.JSONDecodeError, OSError):
            continue
        if cid:
            out.add(cid)
    return out



# Keys that describe the cost model rather than measuring anything. Digits inside them are
# never quantification, so they are removed before counting.
NON_MEASUREMENT_KEYS = frozenset({"id", "non_quantitative_because"})


def quantified_digits(cost_model: dict) -> int:
    """Count digits in the QUANTITY-BEARING parts of a cost model.

    Check 6 used to count digits anywhere in `json.dumps(cost_model)`. Measured against a
    deliberate decoy while authoring PC-0003, that was wrong in BOTH directions:

      * a model whose constraints were named C1..C10 and whose every claim was "it depends on
        your workload" scored 11 digits and PASSED -- all eleven came from the id numerals;
      * a model stating a real constraint in words ("a losing CAS is ambiguous") scored 0
        and FAILED.

    So it measured digit density, not quantification. An id is a label, never a measurement.

    `non_quantitative_because` was then added as an escape hatch, and was itself counted --
    found by authoring PC-0004, the first card genuinely entitled to use it. That cost model
    scores 7 digits, correctly below the threshold, while the hatch TEXT carries 12: 12, 54,
    1000, 1000. Those digits are unavoidable, because the only way to explain why a
    correctness problem has no cost curve is to name the outcome counts that exist in place of
    one. Total 19, so the gate warned that the declaration was an unused escape hatch: the
    field whose entire purpose is to say "this cannot be quantified" was read as
    quantification and voided itself.

    Identical class to the original defect, one level up -- digit density mistaken for
    measurement. A key that talks ABOUT the model is not a measurement IN it.
    """
    def strip_non_measurements(o):
        if isinstance(o, dict):
            return {k: strip_non_measurements(v) for k, v in o.items()
                    if k not in NON_MEASUREMENT_KEYS}
        if isinstance(o, list):
            return [strip_non_measurements(v) for v in o]
        return o

    return len(re.findall(r"\d", json.dumps(strip_non_measurements(cost_model))))



def validate(card_dir: str) -> tuple[list[str], list[str], dict]:
    errs: list[str] = []
    warns: list[str] = []
    stats: dict = {}
    name = os.path.basename(card_dir)

    card_md = os.path.join(card_dir, "CARD.md")
    card_js = os.path.join(card_dir, "card.json")
    for p in (card_md, card_js):
        if not os.path.exists(p):
            return [f"{name}: missing {os.path.basename(p)}"], [], {}

    with open(card_md, encoding="utf-8") as fh:
        md = fh.read()
    with open(card_js, "rb") as fh:
        card_sha = hashlib.sha256(fh.read()).hexdigest()
    with open(card_js, encoding="utf-8") as fh:
        try:
            meta = json.load(fh)
        except json.JSONDecodeError as e:
            return [f"{name}: card.json is not valid JSON ({e})"], [], {}

    secs = sections(md)

    # 1 -- required sections, present and substantive
    for req in REQUIRED_SECTIONS:
        hit = next((k for k in secs if req.lower() in k.lower()), None)
        if hit is None:
            errs.append(f"{name}: missing required section '{req}'")
        elif len(secs[hit].strip()) < MIN_SECTION_CHARS:
            errs.append(f"{name}: section '{hit}' is {len(secs[hit].strip())} chars, "
                        f"below the {MIN_SECTION_CHARS} minimum (a heading is not depth)")

    # 2 -- every python fence must parse
    for i, src in enumerate(python_fences(md), 1):
        try:
            ast.parse(src)
        except SyntaxError as e:
            errs.append(f"{name}: python fence #{i} does not parse ({e.msg} line {e.lineno})")

    # 3 -- tests must exist, run, and match the declared count
    tests_dir = os.path.join(card_dir, "tests")
    declared = (meta.get("tests") or {}).get("count")
    if not os.path.isdir(tests_dir):
        errs.append(f"{name}: no tests/ directory -- 'executed' claims are unsupportable")
    else:
        proc = subprocess.run([sys.executable, "-m", "unittest", "discover",
                               "-s", "tests", "-t", "."],
                              cwd=card_dir, capture_output=True, text=True)
        m = re.search(r"^Ran (\d+) test", proc.stderr, flags=re.M)
        ran = int(m.group(1)) if m else 0
        ok = proc.returncode == 0
        if not ok:
            errs.append(f"{name}: test suite FAILS -- every 'executed' claim is void")
        if declared is not None and ran != declared:
            errs.append(f"{name}: card.json declares {declared} tests, {ran} ran")
        if ran == 0:
            errs.append(f"{name}: zero tests collected")

    # 4 -- negative knowledge is mandatory
    if len(meta.get("anti_patterns", [])) < 1:
        errs.append(f"{name}: no anti_patterns. A card that never says what fails is a brochure")
    if len(meta.get("rejected", [])) < 1:
        errs.append(f"{name}: no rejected alternatives -- 'optimal' is unjustified")

    # 5 -- at least two shapes, or there is no choice to make
    shapes = meta.get("solution_shapes", [])
    if len(shapes) < 2:
        errs.append(f"{name}: {len(shapes)} solution shape(s); >=2 required")
    if shapes and not any(s.get("implemented") for s in shapes):
        warns.append(f"{name}: no solution shape marked implemented")

    # 6 -- the cost model must QUANTIFY. Ids are labels and do not count; a card whose
    # decision genuinely is not about cost may say so explicitly instead of padding.
    cm = meta.get("cost_model", {})
    qdigits = quantified_digits(cm)
    why_not = cm.get("non_quantitative_because")
    if qdigits < 10 and not why_not:
        errs.append(f"{name}: cost_model quantifies almost nothing -- only {qdigits} digits "
                    f"outside ids. Either measure the tradeoff, or set "
                    f"cost_model.non_quantitative_because to state why it cannot be")
    if why_not and qdigits >= 10:
        warns.append(f"{name}: cost_model declares non_quantitative_because yet carries "
                     f"{qdigits} digits of measurement -- drop the declaration, it is now "
                     f"an unused escape hatch")
    if not meta.get("cost_model", {}).get("breakpoints"):
        errs.append(f"{name}: cost_model has no breakpoints (where does this stop working?)")
    # A bare number carries no unit, and a JSON-only consumer must then guess it. Observed:
    # a consumer read `{"below": 5000}` and compared 1,619,100 COMPARISONS against it, when
    # the threshold is 5,000 ITEMS. It reached the right answer by luck of magnitude.
    # CARD.md said "below N~5,000" and was never ambiguous -- the defect existed only in
    # the record the consumer was restricted to, which is precisely why that test matters.
    for i, b in enumerate(meta.get("cost_model", {}).get("breakpoints", [])):
        if not b.get("unit"):
            errs.append(f"{name}: cost_model.breakpoints[{i}] states a bare number with "
                        f"no 'unit' -- a JSON-only consumer must guess what it counts")
    # A measured value without its corpus invites transfer to any corpus. Observed: C1's
    # 0.6133 (an 80-doc fixture) was quoted as "recall is only ~61%" for 1,800 legal
    # contracts. Warn, not error: the fix is a field, but which values need it is a
    # judgement call and I have exactly one card to generalise from.
    # ANY measured content needs its corpus, not just a scalar. The first version tested
    # `isinstance(measured, (int, float))`, so a constraint publishing a TABLE of measurements
    # bypassed the check entirely -- and 2 of 3 constraints in the first card did exactly that
    # while the gate stayed green. Same shape as the dead `dnu_text`: a check that looks like it
    # covers a case and does not.
    for c in meta.get("cost_model", {}).get("constraints", []):
        if c.get("measured") is not None and not c.get("measured_on"):
            warns.append(f"{name}: {c.get('id')} publishes measured values with no "
                         f"'measured_on' -- a consumer will read them as properties of the "
                         f"algorithm rather than of the corpus they were measured on")

    # 6b -- a number with no INFERENCE is unusable. MEASURED, not theorised.
    # Check 6 above asks whether a value states the corpus it came from. This asks the other half:
    # whether the card states what the value LICENSES. They are different failures and a number can
    # have one without the other.
    #
    # The incident: on the sonnet SC-04 control experiment the card arm lost TWO pre-registered
    # rubric items to exactly this, on a card whose numbers were all present and correct.
    #   D1 needed "suppression's saving is SMALL, so deletion is the volume lever". The card said
    #      "saves 0.37 pages/week" and NOWHERE said 0.37 was small, or what followed from it. Zero
    #      hits for 'volume lever', 'negligible', 'deletion dominates'.
    #   D4 needed "the cost is small BY NATURE, which is why it always looks anecdotal". 0.0588
    #      appears three times as a bare value and is never once interpreted.
    # Meanwhile D2 was WON because C4's finding is paired with its inference in R2.why ("any
    # specific N would be fabricated") and A7.fix ("budget the page rate against capacity, not the
    # alarm count"). Same card, same consumer, same run: interpreted numbers transferred, bare ones
    # did not.
    #
    # I first diagnosed those misses as a TRANSMISSION failure and predicted the cause was
    # structural burial. Measurement refuted that -- the missed items sat EARLIER in their fields
    # than the transmitted ones, and two of them were the entire content of their field. The
    # mechanism is not position, it is the absence of a conclusion.
    #
    # WARN, not error, and deliberately so: the marker set is generous, so it over-credits prose
    # that merely contains "so", and it cannot judge whether an inference is CORRECT. That makes a
    # LOW ratio strong evidence and a high one weak evidence -- an asymmetry a reader must know
    # about. Portfolio at introduction: 39/69 = 57%, worst PC-0005 at 41%, best PC-0004 at 83%.
    #
    # INSTRUMENT BUG #17, found by running this check against the two elements that motivated it.
    # The first version asked "does this ELEMENT contain any decision language?" and BOTH S3 and A4
    # PASSED -- on markers with nothing to do with their numbers ("Do not use as a substitute for
    # deleting alarms", "never quote a zero that is structural"). So the check would NOT have caught
    # the defect it was built for: the same "looks enforced and is not" shape as the dead
    # `must_cite_do_not_use_when`. Element-level presence is the wrong granularity.
    #
    # Now per-NUMBER: every numeric token must have decision language within PROXIMITY characters.
    # That is the property actually wanted -- "this value is interpreted" -- rather than "this
    # element mentions a decision somewhere". Verified by reverting S3 and A4 to their pre-fix text
    # and confirming both are now flagged, then restoring byte-identically.
    PROXIMITY = 220
    inference_re = re.compile(
        r"\b(so |therefore|which means|that means|do not |never |prefer |instead of|is small|"
        r"is negligible|negligible|dominates|not the fix|not a .{0,20}lever|is why|which is why|"
        r"implies|forbids|rules out|must not|cannot be|budget )", re.I)
    numeric_re = re.compile(r"\d+\.\d+|\d+%")
    for kind, el in ([("constraint", c) for c in meta.get("cost_model", {}).get("constraints", [])]
                     + [("shape", s) for s in meta.get("solution_shapes", [])]
                     + [("anti-pattern", a) for a in meta.get("anti_patterns", [])]):
        if not numeric_re.search(json.dumps(el, ensure_ascii=False)):
            continue
        naked = []
        for fval in [v for k, v in el.items() if isinstance(v, str) and k != "id"]:
            # Per NUMBER, as described above: decision language must sit within PROXIMITY
            # characters of each number. (This loop used to test the whole field, so one
            # "therefore" anywhere in a long field licensed every number in it -- the
            # field-level version of the element-level defect this check was built to fix.)
            for num in numeric_re.finditer(fval):
                window = fval[max(0, num.start() - PROXIMITY) : num.end() + PROXIMITY]
                if not inference_re.search(window):
                    naked.append(num.group())
        if naked:
            warns.append(
                f"{name}: {kind} {el.get('id')} has {len(naked)} number(s) in a field with no "
                f"decision language ({', '.join(naked[:5])}"
                f"{' ...' if len(naked) > 5 else ''}) -- a consumer cannot tell what they license. "
                f"One rubric item was measurably lost to exactly this shape.")

    # Sample size, made partially gateable. A gate cannot ask whether a sample DESERVES a
    # claim -- but it can ask whether one claim in a card rests on a far smaller sample than
    # its neighbours, which is internal inconsistency and IS checkable. This is the defect a
    # consumer found: chunks/doc measured on 30 documents while every other number in the card
    # used 2000. Grouped by `population`, because 48 synthetic vectors and 2000 documents are
    # not comparable sample sizes.
    pops: dict[str, list[tuple[str, int]]] = {}
    for c in meta.get("cost_model", {}).get("constraints", []):
        mo = c.get("measured_on")
        if isinstance(mo, dict) and isinstance(mo.get("n"), int) and mo.get("population"):
            pops.setdefault(mo["population"], []).append((c.get("id", "?"), mo["n"]))
    for population, entries in pops.items():
        if len(entries) < 2:
            continue
        biggest = max(n for _, n in entries)
        for cid, n in entries:
            if n * 10 < biggest:
                warns.append(f"{name}: {cid} is measured on n={n} while this card measures "
                             f"n={biggest} of the same population ({population}) -- an order "
                             f"of magnitude smaller. Does the sample deserve the claim?")

    # 7 -- the ledger must match reality (hand-kept counts drift; that is why this exists)
    actual, declared_led = count_evidence(md), ledger_counts(md)
    for c in EVIDENCE_CLASSES:
        if c in declared_led and declared_led[c] != actual[c]:
            errs.append(f"{name}: evidence ledger says {declared_led[c]} `[{c}]` "
                        f"but the card contains {actual[c]}")
    if sum(actual.values()) == 0:
        errs.append(f"{name}: no evidence classes tagged at all")

    # 8 -- decomposition edges must resolve
    dec = meta.get("decomposition", {})
    node_ids = {n["n"] for n in dec.get("nodes", [])}
    for e in dec.get("edges", []):
        if e.get("from") not in node_ids:
            errs.append(f"{name}: edge from {e.get('from')!r} is not a declared node")
        to = e.get("to")
        if isinstance(to, int) and to not in node_ids:
            errs.append(f"{name}: edge to {to!r} is not a declared node")
        if not e.get("why"):
            errs.append(f"{name}: edge {e.get('from')}->{to} has no 'why'")
    if not node_ids:
        errs.append(f"{name}: decomposition has no nodes -- nothing to break the problem into")

    # 9 -- cited paths must exist on disk, not merely be plausible. Two declared
    # exceptions for the public edition, both of which must say so on their face:
    #   - "private:" prefix: an external source read for the citation whose code
    #     cannot ship (still counts as external corroboration; never disk-checked)
    #   - "unshipped": true on the entry: tooling or grounding artifacts of the
    #     original workspace, deliberately excluded from this edition
    # Anything else missing from disk is still an error -- the gate is unchanged
    # for every path that claims to be present.
    for cit in meta.get("cited_evidence", []):
        path = cit.get("path", "")
        if path.startswith("private:") or cit.get("unshipped") is True:
            continue
        p = os.path.join(PORTFOLIO_ROOT, path)
        if not os.path.exists(p):
            errs.append(f"{name}: cited path does not exist on disk: {cit.get('path')}")

    # 11 -- TWIN CONSISTENCY. CARD.md and card.json are two records of one card, and
    # until now the ONLY thing forcing them to agree was the test count. The flagship
    # card drifted anyway: its header said 30 tests while card.json said 32 and 32 ran.
    # Anything stated in both must be cross-checked or it will diverge.
    def scoped(section_name: str) -> str:
        hit = next((k for k in secs if section_name.lower() in k.lower()), None)
        return secs.get(hit, "") if hit else ""

    twins = [
        ("solution shapes",
         len(re.findall(r"^### Shape ", md, re.M)), len(meta.get("solution_shapes", []))),
        ("anti-patterns",
         len(re.findall(r"^\*\*A\d+ ", scoped("Anti-patterns"), re.M)),
         len(meta.get("anti_patterns", []))),
        ("rejected alternatives",
         len(re.findall(r"^\| \*\*", scoped("Alternatives rejected"), re.M)),
         len(meta.get("rejected", []))),
        ("cost constraints",
         len(re.findall(r"\*\*C\d+ ", scoped("Cost & scale model"))),
         len(meta.get("cost_model", {}).get("constraints", []))),
    ]
    for label, in_md, in_js in twins:
        if in_md != in_js:
            errs.append(f"{name}: TWIN DRIFT -- {label}: CARD.md has {in_md}, "
                        f"card.json has {in_js}")

    # the header's test count is stated in prose and was the one that actually drifted
    m = re.search(r"\*\*Tests\*\*\s*\|\s*(\d+)", md)
    if m and declared is not None and int(m.group(1)) != declared:
        errs.append(f"{name}: TWIN DRIFT -- CARD.md header says {m.group(1)} tests, "
                    f"card.json says {declared}")
    elif m is None:
        warns.append(f"{name}: header has no '**Tests** | N' cell to cross-check")

    # 12 -- card.json's per-item evidence fields were never validated at all.
    # They tag STRUCTURED items; the markdown tags tag PROSE claims. Two different
    # populations, so equal totals are not required -- but an invalid class, or a
    # disagreement on an item carrying the SAME id in both, is a defect.
    json_ev: dict[str, int] = {}

    def walk(o):
        if isinstance(o, dict):
            e = o.get("evidence")
            if isinstance(e, str):
                json_ev[e] = json_ev.get(e, 0) + 1
                if e not in EVIDENCE_CLASSES:
                    errs.append(f"{name}: card.json evidence class {e!r} is not one of "
                                f"{list(EVIDENCE_CLASSES)}")
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(meta)
    if not json_ev:
        errs.append(f"{name}: no per-item 'evidence' fields in card.json -- a consumer "
                    f"reading only the JSON cannot weight any claim")

    # cross-check the ids that appear in BOTH records
    for coll, pat in (("anti_patterns", r"^\*\*(A\d+) .*?(?=^\*\*A\d+ |\Z)"),):
        section = scoped("Anti-patterns")
        md_class = {}
        for blk in re.finditer(pat, section, re.M | re.S):
            aid, body = blk.group(1), blk.group(0)
            found = [c for c in EVIDENCE_CLASSES if f"`[{c}]`" in body]
            if found:
                md_class[aid] = "executed" if "executed" in found else found[0]
        for item in meta.get(coll, []):
            aid, js = item.get("id"), item.get("evidence")
            if aid in md_class and js and md_class[aid] != js:
                errs.append(f"{name}: {aid} is '{md_class[aid]}' in CARD.md but "
                            f"'{js}' in card.json")

    # 13 -- CONSUMER SCENARIOS. The only check that tests the card's PURPOSE (can a
    # consumer reach the right decision?) rather than its shape. A model cannot be run
    # inside a gate, so what IS enforced statically: every expected decision must resolve
    # to a real element of card.json. That makes it impossible for a rubric to demand
    # something the card does not contain -- and unlike the section-length minimum, it
    # cannot be satisfied by padding.
    sc_path = os.path.join(card_dir, "scenarios.json")
    if not os.path.exists(sc_path):
        errs.append(f"{name}: no scenarios.json -- nothing tests whether the card can "
                    f"actually be planned over")
    else:
        with open(sc_path, encoding="utf-8") as fh:
            try:
                sc = json.load(fh)
            except json.JSONDecodeError as e:
                sc = None
                errs.append(f"{name}: scenarios.json is not valid JSON ({e})")
        if sc is not None:
            scenarios = sc.get("scenarios", [])
            shape_ids = {s.get("id") for s in meta.get("solution_shapes", [])}
            ap_ids = {a.get("id") for a in meta.get("anti_patterns", [])}
            c_ids = {c.get("id") for c in meta.get("cost_model", {}).get("constraints", [])}
            edges = {(e.get("from"), e.get("to")) for e in dec.get("edges", [])}
            esc_text = " ".join(f"{e.get('symptom','')} {e.get('action','')}"
                                for e in meta.get("escalation", [])).lower()
            dnu_text = " ".join(meta.get("do_not_use_when", [])).lower()

            runs_recorded = runs_current = 0
            if not scenarios:
                errs.append(f"{name}: scenarios.json declares no scenarios")
            if not any(s.get("kind") == "refusal" for s in scenarios):
                errs.append(f"{name}: no 'refusal' scenario. A card with no case where the "
                            f"right answer is 'do not use this' cannot be trusted to "
                            f"decline -- which is the failure mode of a KB that rejected "
                            f"nothing")

            stats["scenarios"] = len(scenarios)
            stats["refusals"] = sum(1 for s in scenarios if s.get("kind") == "refusal")
            for s in scenarios:
                sid = s.get("id", "<unnamed>")
                if not s.get("prompt"):
                    errs.append(f"{name}/{sid}: scenario has no prompt")
                r = s.get("rubric") or {}
                if not r:
                    errs.append(f"{name}/{sid}: scenario has no rubric -- unscoreable")

                for key, universe, label in (
                        ("must_flag_anti_patterns", ap_ids, "anti-pattern"),
                        ("must_cite_constraints", c_ids, "cost constraint")):
                    for want in r.get(key, []):
                        if want not in universe:
                            errs.append(f"{name}/{sid}: rubric {key} expects {want!r} "
                                        f"but no such {label} exists in card.json")
                for key in ("must_select_shape", "must_not_select_shape",
                            "must_flag_unanswered_prerequisite_shape"):
                    want = r.get(key)
                    if want is not None and want not in shape_ids:
                        errs.append(f"{name}/{sid}: rubric {key}={want!r} is not a "
                                    f"declared solution shape")
                want = r.get("must_build_monitoring_from")
                if want is not None and want not in ap_ids:
                    errs.append(f"{name}/{sid}: rubric must_build_monitoring_from="
                                f"{want!r} is not a declared anti-pattern")
                e = r.get("must_flag_naive_scan_via_edge")
                if e and (e.get("from"), e.get("to")) not in edges:
                    errs.append(f"{name}/{sid}: rubric expects edge "
                                f"{e.get('from')}->{e.get('to')} which is not declared")
                # `must_cite_do_not_use_when` was DEAD: `dnu_text` was computed and never
                # read, so this key looked enforced and was not. Found while authoring a
                # second card's rubrics -- exactly the "complete, plausible, wrong" shape.
                # Stem-matched at 6 chars because a rubric naturally says "auditability"
                # where the card says "auditable".
                for want in r.get("must_cite_do_not_use_when", []):
                    # Numeric tokens are matched at ANY length, and they are the reliable
                    # anchor. First version required a 5+ character word, and fired a FALSE
                    # POSITIVE on its first real run: a rubric saying "N below 5000" against
                    # a card saying "N < ~5000" shares no long word. The card was right and
                    # the check was wrong -- trusting it would have corrupted a correct
                    # rubric to satisfy a broken gate. A gate failure is a claim too.
                    words = str(want).lower().split()
                    stems = [w[:6] for w in words if len(w) >= 5]
                    stems += [w for w in words if any(c.isdigit() for c in w)]
                    if stems and not any(s in dnu_text for s in stems):
                        errs.append(f"{name}/{sid}: rubric must_cite_do_not_use_when "
                                    f"expects {want!r} but no do_not_use_when entry "
                                    f"mentions it")
                exit_ = r.get("must_take_escalation_exit")
                if exit_ and not any(w in esc_text for w in exit_.lower().split()[:4]):
                    errs.append(f"{name}/{sid}: rubric escalation exit {exit_!r} matches "
                                f"no escalation entry")
                path = r.get("must_quantify_naive_cost_from")
                if path:
                    node = meta
                    for part in path.split("."):
                        node = node.get(part) if isinstance(node, dict) else None
                    if node is None:
                        errs.append(f"{name}/{sid}: rubric path {path!r} does not resolve "
                                    f"in card.json")
            def check_run_conditions(sid: str, obs: dict) -> bool:
                """Validate one recorded run; return True only if it is a NAIVE BASELINE.

                Written as an early-return guard on purpose. The previous version let the
                missing-`conditions` case fall into a branch that dereferenced it, so the
                gate FAILED BY CRASHING -- which still fails the build, but hands the
                author a stack trace instead of a verdict, and the protection evaporates
                the moment someone adds a defensive `.get(..., {})` downstream for an
                unrelated reason. Errors here are diagnoses, matching the rest of the gate.
                """
                cond = obs.get("conditions")
                if not isinstance(cond, dict):
                    errs.append(f"{name}/{sid}: has a recorded result but no "
                                f"`conditions` -- an uncomparable result")
                    return False
                missing = [k for k in REQUIRED_CONDITIONS if not cond.get(k)]
                for k in missing:
                    errs.append(f"{name}/{sid}: conditions missing {k!r} -- results are "
                                f"not comparable across runs without it")

                # Staleness is keyed on a HASH of card.json, not the test count. The
                # count is a weak proxy: two card.json defects (a missing unit, a missing
                # corpus) were fixed without the count changing at all, so a run recorded
                # at that count would have looked current against a materially different
                # input. Consumers read card.json, so its bytes are the right key.
                state = cond.get("card_state_at_run") or {}
                at_run = state.get("card_json_sha256")
                if not at_run:
                    # A record that CANNOT be completed must not read like one that
                    # merely has not been. Three PC-0001 runs predate hashing and their
                    # card.json bytes were overwritten in place, so the gap is permanent
                    # by construction -- flagging them identically to a fixable omission
                    # invites a future session to waste effort trying to fill them.
                    if state.get("staleness") == "PERMANENTLY_UNVERIFIABLE":
                        warns.append(f"{name}/{sid}: card.json bytes for this run no longer "
                                     f"exist and cannot be recovered -- marked "
                                     f"PERMANENTLY_UNVERIFIABLE, not a pending gap. Staleness "
                                     f"is undetectable by construction and always will be")
                    else:
                        warns.append(f"{name}/{sid}: conditions record no "
                                     f"card_state_at_run.card_json_sha256, so staleness "
                                     f"against the current card is undetectable")
                    return False
                if not card_sha.startswith(str(at_run)):
                    warns.append(f"{name}/{sid}: run was made against card.json "
                                 f"{at_run}, now {card_sha[:12]}. This result is a "
                                 f"historical record, not a baseline")
                    return False

                # Currency is not enough. A consumer that had already seen the card, or
                # the review that produced it, is not testing whether the card can be
                # planned over -- it is reciting. Recorded, but never a baseline.
                exposure = str(cond.get("consumer_prior_exposure") or "").strip().lower()
                if not exposure:
                    return False          # already reported by the missing-keys loop
                if not exposure.startswith("none"):
                    warns.append(f"{name}/{sid}: consumer had prior exposure "
                                 f"({cond.get('consumer_prior_exposure')}) -- recorded, "
                                 f"but not counted as a naive baseline")
                    return False
                return True

            for s in scenarios:
                sid = s.get("id", "<unnamed>")
                # A scenario accumulates runs over time -- that IS comparability -- so
                # both shapes are first-class: `observed` (one run) and `observed_history`
                # (a list). Supporting only the first cost two recorded runs the moment a
                # second was added: the gate reported "no recorded run" for a scenario
                # holding two, and runs-recorded silently fell from 2 to 1. No exception,
                # complete output, wrong.
                runs = []
                if isinstance(s.get("observed"), dict):
                    runs.append((sid, s["observed"]))
                for i, r in enumerate(s.get("observed_history") or [], 1):
                    if isinstance(r, dict):
                        runs.append((f"{sid}#run{i}", r))
                if not runs:
                    warns.append(f"{name}/{sid}: no recorded run -- the static rubric is "
                                 f"checked but the card has never been planned over")
                for rid, obs in runs:
                    runs_recorded += 1
                    if check_run_conditions(rid, obs):
                        runs_current += 1

            stats["runs_recorded"] = runs_recorded
            stats["runs_current"] = runs_current

    # 15 -- the generated cost table must not be stale. Hand-written line counts were wrong
    # twice in the same section, so they are generated; a generated value that has drifted is
    # exactly what the ledger check already exists to catch.
    if COST_BEGIN in md and COST_END in md:
        got = md[md.index(COST_BEGIN) + len(COST_BEGIN):md.index(COST_END)]
        if got != "\n" + cost_table() + "\n":
            errs.append(f"{name}: the generated cost table is STALE -- run --sync-ledger")

    # 16 -- related_cards was not validated AT ALL, and the cross-card graph had already
    # rotted unnoticed: two spellings of one relation across three cards, and two edges
    # asserting a relationship with an EMPTY `why`. The retrieval layer publishes these
    # edges, so a dangling id hands every consumer a pointer to nothing -- the same failure
    # as the KB that deferred to a sibling which had rejected the package.
    known_ids = all_card_ids()
    for i, r in enumerate(meta.get("related_cards", [])):
        if not isinstance(r, dict):
            errs.append(f"{name}: related_cards[{i}] is {type(r).__name__}, not an object "
                        f"-- a bare id cannot carry a relation or a reason")
            continue
        rid = r.get("id")
        if rid == meta.get("id"):
            errs.append(f"{name}: related_cards[{i}] points at itself")
        elif rid not in known_ids:
            errs.append(f"{name}: related_cards[{i}] points at {rid!r}, which is not a card "
                        f"on disk -- a dangling edge in the cross-card graph")
        rel = r.get("relation")
        canon = canonical_relation(rel)
        if canon is None:
            errs.append(f"{name}: related_cards[{i}] relation {rel!r} is not one of "
                        f"{list(RELATION_VOCAB)}")
        elif canon != rel:
            # Warn, not error: this is spelling drift in already-shipped cards, and fixing it
            # edits card.json, which invalidates every prepared consumer run against it. The
            # abs-path gate set this precedent -- turning CI red on day one for a pre-existing
            # condition just teaches people to ignore the gate.
            warns.append(f"{name}: related_cards[{i}] relation {rel!r} is a non-canonical "
                         f"spelling of {canon!r} -- a consumer filtering on the relation "
                         f"would silently miss this edge")
        if len(str(r.get("why") or "").strip()) < MIN_WHY_CHARS:
            warns.append(f"{name}: related_cards[{i}] -> {rid} asserts a relationship with "
                         f"no substantive 'why' -- an unexplained edge is the 30-character "
                         f"decay this gate exists to stop, one level up")

    # 17 -- grounding. See GROUNDING_VOCAB: `executed` conflated "the algebra says" with "my
    # simulator says". Both were printing as the schema's strongest evidence class.
    exec_nodes: list[tuple[str, dict]] = []

    def collect_executed(node, path):
        if isinstance(node, dict):
            if node.get("evidence") == "executed":
                exec_nodes.append((str(node.get("id") or path), node))
            for k, v in node.items():
                collect_executed(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                collect_executed(v, f"{path}[{i}]")

    collect_executed(meta, "")

    # A live prepared consumer run is irreplaceable: any byte written to card.json invalidates
    # it, and I cannot be the fresh consumer myself. So for those cards this is a warning, on
    # the precedent set by check 16 -- backfill after the run is recorded, not before.
    pending = os.path.exists(os.path.join(card_dir, ".scenario_pending.json"))

    missing = [cid for cid, n in exec_nodes if "grounding" not in n]
    for cid, n in exec_nodes:
        g = n.get("grounding")
        if g is not None and g not in GROUNDING_VOCAB:
            # Always an error: a misspelt grounding is worse than an absent one, because it
            # looks enforced. This is how `must_cite_do_not_use_when` came to be dead.
            errs.append(f"{name}: {cid} grounding {g!r} is not one of "
                        f"{list(GROUNDING_VOCAB)}")
    if missing:
        msg = (f"{name}: {len(missing)} executed claim(s) carry no 'grounding' "
               f"({', '.join(missing[:6])}{' ...' if len(missing) > 6 else ''}) -- "
               f"'the algebra says' and 'my simulator says' are printing as the same class")
        (warns if pending else errs).append(
            msg + (" [warned, not failed: a prepared consumer run is pending against this "
                   "card.json and editing it would destroy the run]" if pending else ""))

    # The corroboration requirement is CONDITIONAL ON CLAIM STRENGTH. A simulator-grounded
    # card that openly declares itself direction-only is being honest and is allowed; the
    # failure being prevented is a card that presents modelled numbers as though they were
    # measurements of the world. So the card gets a choice: corroborate, or self-limit.
    sims = [cid for cid, n in exec_nodes if n.get("grounding") == "simulator"]
    if sims:
        external = [c for c in (meta.get("cited_evidence") or [])
                    if isinstance(c, dict) and str(c.get("path", ""))
                    and not str(c.get("path", "")).startswith(SELF_CITE_PREFIX)]
        reviewer = str(meta.get("domain_reviewer") or "").strip()
        strength = str(meta.get("claim_strength") or "").strip().lower()
        if strength and strength not in CLAIM_STRENGTHS:
            errs.append(f"{name}: claim_strength {meta.get('claim_strength')!r} is not one of "
                        f"{list(CLAIM_STRENGTHS)}")
        if not external and not reviewer and strength != "direction":
            errs.append(
                f"{name}: {len(sims)} simulator-grounded claim(s) ({', '.join(sims[:5])}) with "
                f"no corroboration from outside this repository -- every cited_evidence path "
                f"starts with {SELF_CITE_PREFIX!r}, which is self-citation. Executing a "
                f"simulator proves PIN-fidelity, not WORLD-fidelity. Either add an external "
                f"[cited] anchor or a 'domain_reviewer', or set claim_strength=\"direction\" "
                f"to say so on the card's face")
        # WHAT a citation supports, not merely THAT one exists. The previous version warned on
        # `external or reviewer`, and it fired on PC-0005 -- whose two external paths both state
        # in their own honest_limit that they corroborate the REGIME and the PRACTICE and say
        # nothing about magnitudes. So the warning pressured the author to upgrade
        # claim_strength on the strength of citations that do not support the upgrade, which is
        # the exact inflation the grounding vocabulary exists to prevent. A presence check cannot
        # distinguish "real services sit in this band" from "these numbers are right".
        graded = [c for c in external if c.get("corroborates")]
        untagged_ext = [c for c in external if not c.get("corroborates")]
        bad_vocab = [c for c in graded if c["corroborates"] not in CORROBORATES]
        for c in bad_vocab:
            errs.append(f"{name}: cited_evidence corroborates={c['corroborates']!r} is not one of "
                        f"{list(CORROBORATES)}")
        for c in untagged_ext:
            warns.append(f"{name}: external cited_evidence {str(c.get('path'))[:48]!r} does not "
                         f"say WHAT it corroborates -- add 'corroborates' from "
                         f"{list(CORROBORATES)}, because a citation that supports the regime is "
                         f"not evidence that the magnitudes are right")
        magnitude = [c for c in graded if c["corroborates"] == "magnitude"]
        if strength == "direction" and (magnitude or reviewer):
            warns.append(f"{name}: claim_strength='direction' while corroboration of MAGNITUDE "
                         f"exists -- the self-limitation may now be understating the card")
    stats["grounding"] = {g: sum(1 for _, n in exec_nodes if n.get("grounding") == g)
                          for g in GROUNDING_VOCAB}
    stats["executed_claims"] = len(exec_nodes)


    frac = actual["reasoned"] / max(sum(actual.values()), 1)
    if frac > 0.5:
        warns.append(f"{name}: {frac:.0%} of tagged claims are 'reasoned' "
                     f"-- mostly unverified; treat as hypotheses")

    return errs, warns, {**stats, "tags": actual, "json_evidence": json_ev,
                         "reasoned_fraction": frac,
                         "shapes": len(shapes),
                         "anti_patterns": len(meta.get("anti_patterns", [])),
                         "nodes": len(node_ids)}


def sync_counts(card_dir: str) -> bool:
    """Derive the test count from ACTUALLY RUNNING the suite, into both twins.

    The count is stated in three places -- the CARD.md header, card.json, and reality.
    Reality is authoritative, so both statements are generated from it. `passing` is
    removed if present: the gate re-runs the suite, so a hand-kept boolean is a claim
    that can only ever be wrong.
    """
    md_path = os.path.join(card_dir, "CARD.md")
    js_path = os.path.join(card_dir, "card.json")
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover",
                           "-s", "tests", "-t", "."],
                          cwd=card_dir, capture_output=True, text=True)
    m = re.search(r"^Ran (\d+) test", proc.stderr, flags=re.M)
    if not m:
        return False
    n = int(m.group(1))
    changed = False

    with open(md_path, encoding="utf-8") as fh:
        md = fh.read()
    new_md = re.sub(r"(\*\*Tests\*\*\s*\|\s*)\d+", rf"\g<1>{n}", md, count=1)
    if new_md != md:
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(new_md)
        changed = True

    with open(js_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    tests = meta.setdefault("tests", {})
    if tests.get("count") != n or "passing" in tests:
        tests["count"] = n
        tests.pop("passing", None)
        with open(js_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
            fh.write("\n")
        changed = True
    return changed


COST_BEGIN = "<!-- COST-TABLE:BEGIN (generated by validate_cards.py --sync-ledger) -->"
COST_END = "<!-- COST-TABLE:END -->"


def _loc(pattern: str) -> int:
    files = [f for f in glob.glob(pattern) if "__pycache__" not in f]
    total = 0
    for f in files:
        with open(f, encoding="utf-8") as fh:
            total += sum(1 for _ in fh)
    return total


def cost_table() -> str:
    """The authoring-cost table, GENERATED from the filesystem.

    This exists because I hand-wrote these numbers into a card TWICE and was wrong both
    times -- in the very section that argues unexecuted numbers are untrustworthy. The
    established rule in this repo is that a derivable value must be derived, which is why
    the evidence ledger and the test count are generated. Line counts are no different.
    """
    dirs = sorted(d for d in os.listdir(CARDS)
                  if os.path.isdir(os.path.join(CARDS, d)) and not d.startswith("."))
    cols = []
    for d in dirs:
        base = os.path.join(CARDS, d)
        impl = _loc(os.path.join(base, "impl", "*.py"))
        tests = _loc(os.path.join(base, "tests", "*.py"))
        md = _loc(os.path.join(base, "CARD.md"))
        js = _loc(os.path.join(base, "card.json"))
        scen = _loc(os.path.join(base, "scenarios.json"))
        cols.append({
            "id": d.split("-")[0] + "-" + d.split("-")[1],
            "impl": impl, "tests": tests, "md": md, "json": js, "scen": scen,
            "total": impl + tests + md + js + scen,
            "t2i": tests / impl if impl else 0.0,
            "d2c": (md + js) / (impl + tests) if (impl + tests) else 0.0,
        })
    head = "| | " + " | ".join(c["id"] for c in cols) + " |"
    rule = "| --- | " + " | ".join("---" for _ in cols) + " |"
    rows = [
        ("`impl/`", lambda c: str(c["impl"])),
        ("`tests/`", lambda c: str(c["tests"])),
        ("`CARD.md`", lambda c: str(c["md"])),
        ("`card.json`", lambda c: str(c["json"])),
        ("`scenarios.json`", lambda c: str(c["scen"])),
        ("**total**", lambda c: f"**{c['total']}**"),
        ("tests-to-impl", lambda c: f"{c['t2i']:.2f}"),
        ("doc-to-code", lambda c: f"{c['d2c']:.2f}"),
    ]
    body = [f"| {label} | " + " | ".join(fn(c) for c in cols) + " |" for label, fn in rows]
    return "\n".join([head, rule] + body)


def sync_cost_table(card_dir: str) -> bool:
    """Rewrite the marked cost table in CARD.md from the filesystem, to a FIXED POINT.

    The table reports CARD.md's own line count, so it is self-referential: writing it changes
    the number it is supposed to report. A single pass therefore leaves the value one edit
    behind, and the gate -- correctly -- calls it stale. That is a trap, because CI runs
    --strict and never syncs: an author who ran sync once and pushed would get a red build
    caused by the sync tool itself.

    So this iterates until the written table agrees with the file it lives in. It converges
    in two passes in practice (the first changes the line count, the second only changes
    digits) and the bound is defensive, not expected.
    """
    md_path = os.path.join(card_dir, "CARD.md")
    changed = False
    for _ in range(5):
        with open(md_path, encoding="utf-8") as fh:
            md = fh.read()
        if COST_BEGIN not in md or COST_END not in md:
            return changed
        start = md.index(COST_BEGIN) + len(COST_BEGIN)
        end = md.index(COST_END)
        wanted = "\n" + cost_table() + "\n"
        if md[start:end] == wanted:
            return changed
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(md[:start] + wanted + md[end:])
        changed = True
    raise RuntimeError(f"{os.path.basename(card_dir)}: cost table did not converge in 5 "
                       f"passes -- it is oscillating, not merely stale")


def sync_ledger(card_dir: str) -> bool:
    """Rewrite the Evidence ledger counts from the actual tags.

    The counts drifted within an hour of the card being written -- three of three wrong.
    That is the same failure that put a stale hardcoded value into 31 llms.txt files
    elsewhere in this workspace: anything hand-maintained and derivable must be derived.
    """
    md_path = os.path.join(card_dir, "CARD.md")
    with open(md_path, encoding="utf-8") as fh:
        md = fh.read()
    actual = count_evidence(md)
    changed = False
    for c in EVIDENCE_CLASSES:
        pat = rf"(\|\s*`\[{c}\]`\s*\|\s*)(\d+)(\s*\|)"
        m = re.search(pat, md)
        if m and int(m.group(2)) != actual[c]:
            md = re.sub(pat, rf"\g<1>{actual[c]}\g<3>", md, count=1)
            changed = True
    if changed:
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(md)
    return changed


def sync_portfolio(max_sweeps: int = 5) -> int:
    """Sync every card repeatedly until a whole pass changes nothing. Returns sweeps used.

    Extracted from `main()` deliberately. A mutation sweep of this portfolio's seven scripts
    found 27 unguarded checks, and every one of them lived in a `main()` or a `check()` -- the
    verdict producers -- while the guarded ones lived in helpers that take arguments and return
    values. Leaving a new convergence loop inline in `main()` would reproduce that result on
    purpose.
    """
    for sweeps in range(1, max_sweeps + 1):
        changed = False
        for d in sorted(os.listdir(CARDS)):
            cd = os.path.join(CARDS, d)
            if not os.path.isdir(cd):
                continue
            if sync_counts(cd):
                print(f"  synced test counts from the actual run: {d}")
                changed = True
            if sync_ledger(cd):
                print(f"  synced evidence ledger: {d}")
                changed = True
            if sync_cost_table(cd):
                print(f"  synced generated cost table: {d}")
                changed = True
        if not changed:
            return sweeps
    raise RuntimeError(f"portfolio cost tables did not converge in {max_sweeps} sweeps -- "
                       f"they are oscillating, not merely stale")



def main() -> None:
    strict = "--strict" in sys.argv
    if "--sync-ledger" in sys.argv:
        # The cost table reports EVERY card's line counts, so its fixed point is
        # PORTFOLIO-WIDE, not per-file. `sync_cost_table` converges one CARD.md against the
        # filesystem as it stands when that card is processed -- and syncing a LATER card
        # changes that card's own line count, which invalidates the table already written into
        # every earlier one.
        #
        # Measured when PC-0004 was added: one full sync pass left PC-0002's table stale, so
        # `--strict` failed immediately afterwards. An author following the documented
        # workflow -- sync once, then gate -- would get a RED build caused by the sync tool.
        # That is precisely the trap sync_cost_table's own docstring was written to avoid, one
        # scope up: it iterated a file to convergence and nothing iterated the portfolio.
        sweeps = sync_portfolio()
        if sweeps > 1:
            print(f"  (converged after {sweeps} sweeps: the cost table is a portfolio-wide "
                  f"fixed point, so one pass per card is not enough)")
    if not os.path.isdir(CARDS):
        print(f"no cards/ directory at {CARDS}")
        sys.exit(1)
    dirs = sorted(d for d in os.listdir(CARDS)
                  if os.path.isdir(os.path.join(CARDS, d)) and not d.startswith("."))

    print("=" * 78)
    print("PROBLEM CARD DEPTH GATE")
    print("=" * 78)
    all_errs, all_warns = [], []
    for d in dirs:
        errs, warns, stats = validate(os.path.join(CARDS, d))
        status = "FAIL" if errs else ("warn" if warns else "ok")
        print(f"\n  {d}   [{status}]")
        if stats:
            t = stats["tags"]
            print(f"      evidence: executed={t['executed']} cited={t['cited']} "
                  f"reasoned={t['reasoned']} (reasoned {stats['reasoned_fraction']:.0%})")
            print(f"      shapes={stats['shapes']} anti-patterns={stats['anti_patterns']} "
                  f"decomposition-nodes={stats['nodes']}")
            if stats.get("json_evidence"):
                je = stats["json_evidence"]
                print(f"      card.json per-item evidence: "
                      f"{' '.join(f'{k}={v}' for k, v in sorted(je.items()))} "
                      f"(structured items -- a different population from the prose tags)")
            if stats.get("scenarios") is not None:
                print(f"      scenarios={stats['scenarios']} "
                      f"(refusal={stats.get('refusals', 0)}) "
                      f"runs-recorded={stats.get('runs_recorded', 0)} "
                      f"runs-against-current-card={stats.get('runs_current', 0)}")
        for e in errs:
            print(f"      ERROR: {e}")
        for w in warns:
            print(f"      warn:  {w}")
        all_errs += errs
        all_warns += warns

    print("\n" + "=" * 78)
    print(f"  cards={len(dirs)} | errors={len(all_errs)} | warnings={len(all_warns)}")
    print("RESULT:", "ALL CLEAN" if not all_errs else "DEPTH GATE FAILED")
    sys.exit(1 if (strict and all_errs) else 0)


if __name__ == "__main__":
    main()
