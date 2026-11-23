#!/usr/bin/env python3
"""Tests for validate_cards.py — the depth gate.

Every test below guards a defect that ALREADY SHIPPED in this gate or a failure measured
in the 31-KB portfolio it was built to prevent. A gate that is itself unverified is just
a second place for a wrong claim to hide.

Run:  python3 -m unittest test_validate_cards -v
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("vc", HERE / "validate_cards.py")
VC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(VC)


class TestClaimBody(unittest.TestCase):
    """REGRESSION: count_evidence counted every occurrence of a tag, so the legend, the
    ledger's own table rows, and prose merely MENTIONING a class were all counted as
    claims. 8 "reasoned claims" were really 4 -- and the ledger-vs-actual check then
    enforced agreement with the wrong number, producing a green check on a false count."""

    def test_blockquote_legend_is_not_counted(self):
        md = ("# C\n"
              "> `[executed]` means a test proves it\n"
              "## 1 · Problem statement\n"
              "A real claim `[executed]`\n")
        self.assertEqual(VC.count_evidence(md)["executed"], 1)

    def test_counting_stops_at_the_evidence_ledger(self):
        md = ("## 1 · Problem statement\n"
              "claim `[cited]`\n"
              "## 12 · Evidence ledger\n"
              "| `[cited]` | 99 | tabulated, not claimed |\n")
        self.assertEqual(VC.count_evidence(md)["cited"], 1)

    def test_ledger_heading_variants_are_recognised(self):
        for heading in ("## Evidence ledger", "## 12 · Evidence ledger",
                        "## 12. Evidence ledger"):
            md = f"## 1 · P\nx `[reasoned]`\n{heading}\n| `[reasoned]` | 7 | y |\n"
            self.assertEqual(VC.count_evidence(md)["reasoned"], 1, heading)

    def test_a_tag_in_a_table_cell_still_counts(self):
        md = "## 1 · P\n| signal | why `[executed]` |\n"
        self.assertEqual(VC.count_evidence(md)["executed"], 1)


class TestSections(unittest.TestCase):
    def test_numbered_headings_are_normalised(self):
        secs = VC.sections("## 3 · Why the naive approach fails\nbody\n")
        self.assertIn("Why the naive approach fails", secs)

    def test_body_is_captured_per_section(self):
        secs = VC.sections("## 1 · A\nalpha\n## 2 · B\nbeta\n")
        self.assertEqual(secs["A"].strip(), "alpha")
        self.assertEqual(secs["B"].strip(), "beta")

    def test_python_fences_are_extracted(self):
        md = "```python\nx = 1\n```\n```bash\nls\n```\n"
        self.assertEqual(VC.python_fences(md), ["x = 1\n"])


def _card(tmp: str, *, md_extra: str = "", meta_over: dict | None = None,
          scen_over: dict | None = None, tests_pass: bool = True,
          n_tests: int = 1) -> str:
    """Build a minimal card that PASSES, so each test can break exactly one thing."""
    d = os.path.join(tmp, "cards", "PC-9999-fixture")
    os.makedirs(os.path.join(d, "tests"), exist_ok=True)
    filler = "x" * 260
    parts = []
    for i, s in enumerate(VC.REQUIRED_SECTIONS, 1):
        parts.append(f"## {i} · {s}\n{filler} `[executed]`\n")
        if s == "Solution shapes":
            parts.append("### Shape A — a\n### Shape B — b\n")
        elif s == "Alternatives rejected":
            parts.append("| **only** | why |\n")
        elif s == "Anti-patterns":
            # the A1 block must carry its own tag, or there is nothing for the
            # md-vs-json class cross-check to compare against
            parts.append("**A1 — a.** body `[executed]`\n")
        elif s == "Cost & scale model":
            parts.append("**C1 — c.** body\n")
    body = "| **Tests** | " + str(n_tests) + " |\n" + "".join(parts)
    Path(d, "CARD.md").write_text(body + md_extra, encoding="utf-8")

    meta = {
        "id": "PC-9999",
        "solution_shapes": [{"id": "A", "implemented": True}, {"id": "B"}],
        "rejected": [{"option": "o", "why": "w"}],
        "anti_patterns": [{"id": "A1", "name": "n", "why": "w", "evidence": "executed"}],
        "cost_model": {"constraints": [{"id": "C1", "n": 1234567890, "evidence": "executed"}],
                       "breakpoints": [{"below": 5000, "action": "naive",
                                        "unit": "items (N)"}]},
        "decomposition": {"nodes": [{"n": 1, "name": "a"}, {"n": 2, "name": "b"}],
                          "edges": [{"from": 2, "type": "requires", "to": 1, "why": "w"}]},
        "cited_evidence": [],
        "tests": {"count": n_tests},
    }
    meta.update(meta_over or {})

    # Check 17 requires every `executed` claim to declare a GROUNDING. Normalise here, AFTER
    # the override merge, rather than editing the ~20 tests that supply their own constraints:
    # not one of them is ABOUT grounding, so hardcoding the field into each would couple every
    # unrelated test to this schema addition. A test that supplies its own `grounding` (or an
    # explicitly invalid one) still wins, because this only fills what is absent.
    def _default_grounding(node):
        if isinstance(node, dict):
            if node.get("evidence") == "executed" and "grounding" not in node:
                node["grounding"] = "analytic"
            for v in node.values():
                _default_grounding(v)
        elif isinstance(node, list):
            for v in node:
                _default_grounding(v)

    if not meta.pop("_no_grounding", False):
        _default_grounding(meta)
    Path(d, "card.json").write_text(json.dumps(meta), encoding="utf-8")

    # the hash must be taken AFTER card.json is final, or the fixture is born stale --
    # the same mistake that lost the real SC-02 run-2 input hash
    sha = hashlib.sha256(Path(d, "card.json").read_bytes()).hexdigest()
    cond = {"model_class": "test-class", "input_scope": "card.json only",
            "consumer_prior_exposure": "none -- fixture",
            "card_state_at_run": {"card_json_sha256": sha[:12]}}
    scen = {"scenarios": [
        {"id": "SC-01", "kind": "planning", "prompt": "p",
         "rubric": {"must_select_shape": "A", "must_flag_anti_patterns": ["A1"]},
         "observed": {"result": "pass", "conditions": dict(cond)}},
        {"id": "SC-02", "kind": "refusal", "prompt": "p",
         "rubric": {"must_answer_no_first": True},
         "observed": {"result": "pass", "conditions": dict(cond)}},
    ]}
    scen.update(scen_over or {})
    Path(d, "scenarios.json").write_text(json.dumps(scen), encoding="utf-8")

    Path(d, "tests", "__init__.py").write_text("", encoding="utf-8")
    assertion = "self.assertTrue(True)" if tests_pass else "self.assertTrue(False)"
    cases = "\n".join(f"    def test_{i}(self):\n        {assertion}\n"
                      for i in range(n_tests))
    Path(d, "tests", "test_f.py").write_text(
        "import unittest\nclass T(unittest.TestCase):\n" + (cases or "    pass\n"),
        encoding="utf-8")
    return d


class TestGateFires(unittest.TestCase):
    """Each check must actually fail on a violation. A gate that cannot fail is decoration
    -- which is precisely what CI gate 3 was in the portfolio: it passed while its
    hardcoded KB list had drifted from 31 to 17."""

    def _errs(self, **kw) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, **kw)
            errs, _, _ = VC.validate(d)
            return " | ".join(errs)

    def test_the_baseline_fixture_passes(self):
        """If the happy path failed, every other test here would be meaningless."""
        self.assertEqual(self._errs(), "")

    def test_missing_section_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp)
            md = Path(d, "CARD.md").read_text(encoding="utf-8")
            md = md.replace("## 10 · Anti-patterns", "## 10 · Something else")
            Path(d, "CARD.md").write_text(md, encoding="utf-8")
            errs, _, _ = VC.validate(d)
            self.assertTrue(any("Anti-patterns" in e for e in errs), errs)

    def test_a_thin_section_is_an_error(self):
        """The 30-char decay: a heading with nothing under it must not pass."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp)
            md = Path(d, "CARD.md").read_text(encoding="utf-8")
            md = md.replace("x" * 260, "thin", 1)
            Path(d, "CARD.md").write_text(md, encoding="utf-8")
            errs, _, _ = VC.validate(d)
            self.assertTrue(any("below the" in e for e in errs), errs)

    def test_unparseable_python_fence_is_an_error(self):
        self.assertIn("does not parse",
                      self._errs(md_extra="\n```python\ndef (:\n```\n"))

    def test_failing_tests_void_the_card(self):
        self.assertIn("test suite FAILS", self._errs(tests_pass=False))

    def test_declared_test_count_must_match_reality(self):
        self.assertIn("declares", self._errs(meta_over={"tests": {"count": 99}}))

    def test_no_anti_patterns_is_an_error(self):
        self.assertIn("no anti_patterns", self._errs(meta_over={"anti_patterns": []}))

    def test_no_rejected_alternatives_is_an_error(self):
        self.assertIn("no rejected", self._errs(meta_over={"rejected": []}))

    def test_single_solution_shape_is_an_error(self):
        """REWRITTEN: the previous version passed FOR THE WRONG REASON.

        It asserted the substring "solution shape" while leaving CARD.md with two `### Shape`
        headings, so TWIN DRIFT fired with "TWIN DRIFT -- solution shapes: CARD.md has 2,
        card.json has 1" -- which also contains that substring. A mutation sweep disabling
        check 5 outright left the whole suite green: the check had no test at all, and the
        test that appeared to cover it was reading another check's output.

        Now both records agree on ONE shape, so TWIN DRIFT cannot fire, and the assertion is
        on check 5's own wording.
        """
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, meta_over={"solution_shapes": [{"id": "A", "implemented": True}]})
            md = Path(d, "CARD.md").read_text(encoding="utf-8")
            md = md.replace("### Shape B \u2014 b\n", "")
            Path(d, "CARD.md").write_text(md, encoding="utf-8")
            errs, _, _ = VC.validate(d)
            joined = " | ".join(errs)
            self.assertIn("1 solution shape(s); >=2 required", joined)
            self.assertNotIn("TWIN DRIFT", joined,
                             "the fixture must isolate check 5 from the twin check")

    def test_a_dangling_edge_FROM_is_an_error(self):
        """The `from` branch of check 8 was undefended.

        `test_dangling_decomposition_edge_is_an_error` uses `to: 7`, so it exercises the `to`
        branch and passes even with the `from` branch disabled. A check with two branches
        needs two tests, or half of it is decoration.
        """
        errs = self._errs(meta_over={"decomposition": {
            "nodes": [{"n": 1, "name": "a"}, {"n": 2, "name": "b"}],
            "edges": [{"from": 7, "type": "requires", "to": 1, "why": "w"}]}})
        self.assertIn("edge from 7 is not a declared node", errs)

    def test_an_escalation_exit_matching_nothing_is_an_error(self):
        """Check 13d had NO test. It validates that a scenario's expected escalation exit
        actually resolves to an escalation entry -- the same class as the dead
        `must_cite_do_not_use_when`, which was computed and never read for two whole cards.
        """
        errs = self._errs(
            meta_over={"escalation": [{"symptom": "totals drifted upward",
                                       "action": "check the ordering"}]},
            scen_over={"scenarios": [
                {"id": "S1", "kind": "planning", "prompt": "p",
                 "rubric": {"must_take_escalation_exit": "quantum flux capacitor overload"}},
                {"id": "S2", "kind": "refusal", "prompt": "p", "rubric": {"a": 1}}]})
        self.assertIn("matches no escalation entry", errs)

    def test_an_escalation_exit_that_does_resolve_is_clean(self):
        """A check that rejected valid exits would be worse than none -- it would push authors
        to delete the rubric key rather than fix the card."""
        errs = self._errs(
            meta_over={"escalation": [{"symptom": "totals drifted upward after an incident",
                                       "action": "check the ordering"}]},
            scen_over={"scenarios": [
                {"id": "S1", "kind": "planning", "prompt": "p",
                 "rubric": {"must_take_escalation_exit": "totals drifted upward"}},
                {"id": "S2", "kind": "refusal", "prompt": "p", "rubric": {"a": 1}}]})
        self.assertNotIn("escalation", errs)

    def test_cost_model_without_numbers_is_an_error(self):
        self.assertIn("quantifies almost nothing", self._errs(
            meta_over={"cost_model": {"constraints": [{"claim": "fast"}],
                                      "breakpoints": [{"action": "x"}]}}))

    def test_cost_model_without_breakpoints_is_an_error(self):
        self.assertIn("no breakpoints", self._errs(
            meta_over={"cost_model": {"constraints": [{"n": 1234567890}]}}))

    def test_dangling_decomposition_edge_is_an_error(self):
        """A KB in this workspace deferred to a sibling that rejected the package: an
        edge pointing at nothing. Same failure, caught structurally."""
        self.assertIn("not a declared node", self._errs(
            meta_over={"decomposition": {
                "nodes": [{"n": 1, "name": "a"}],
                "edges": [{"from": 1, "type": "requires", "to": 7, "why": "w"}]}}))

    def test_edge_without_a_why_is_an_error(self):
        self.assertIn("no 'why'", self._errs(
            meta_over={"decomposition": {
                "nodes": [{"n": 1, "name": "a"}, {"n": 2, "name": "b"}],
                "edges": [{"from": 2, "type": "requires", "to": 1}]}}))

    def test_empty_decomposition_is_an_error(self):
        self.assertIn("no nodes", self._errs(
            meta_over={"decomposition": {"nodes": [], "edges": []}}))

    def test_cited_path_must_exist_on_disk(self):
        """'An index is not the disk' -- the error I made in the overlap review."""
        self.assertIn("does not exist on disk", self._errs(
            meta_over={"cited_evidence": [{"path": "no/such/file.py"}]}))

    def test_ledger_mismatch_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, md_extra="\n| `[executed]` | 999 | x |\n")
            errs, _, _ = VC.validate(d)
            self.assertTrue(any("evidence ledger says" in e for e in errs), errs)

    def test_malformed_card_json_is_reported_not_crashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp)
            Path(d, "card.json").write_text("{not json", encoding="utf-8")
            errs, _, _ = VC.validate(d)
            self.assertTrue(any("not valid JSON" in e for e in errs), errs)


class TestTwinConsistency(unittest.TestCase):
    """The flagship card drifted between CARD.md and card.json within a day: the header
    said 30 tests, card.json said 32, and 32 ran. The test count was the ONLY thing
    cross-checked between the two records; everything else agreed by luck."""

    def _errs(self, **kw) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            errs, _, _ = VC.validate(_card(tmp, **kw))
            return " | ".join(errs)

    def test_shape_count_drift_is_caught(self):
        self.assertIn("TWIN DRIFT", self._errs(meta_over={"solution_shapes": [
            {"id": "A", "implemented": True}, {"id": "B"}, {"id": "C"}]}))

    def test_anti_pattern_count_drift_is_caught(self):
        self.assertIn("anti-patterns", self._errs(meta_over={"anti_patterns": [
            {"id": "A1", "name": "n", "why": "w", "evidence": "executed"},
            {"id": "A2", "name": "n", "why": "w", "evidence": "reasoned"}]}))

    def test_rejected_count_drift_is_caught(self):
        self.assertIn("rejected alternatives", self._errs(meta_over={"rejected": [
            {"option": "a", "why": "w"}, {"option": "b", "why": "w"}]}))

    def test_header_test_count_drift_is_caught(self):
        """The exact defect that shipped."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, n_tests=1)
            md = Path(d, "CARD.md").read_text(encoding="utf-8").replace("| **Tests** | 1 |",
                                                        "| **Tests** | 30 |")
            Path(d, "CARD.md").write_text(md, encoding="utf-8")
            errs, _, _ = VC.validate(d)
            self.assertTrue(any("header says 30" in e for e in errs), errs)

    def test_missing_header_cell_warns_rather_than_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp)
            md = Path(d, "CARD.md").read_text(encoding="utf-8").replace("| **Tests** | 1 |", "")
            Path(d, "CARD.md").write_text(md, encoding="utf-8")
            errs, warns, _ = VC.validate(d)
            self.assertEqual(errs, [])
            self.assertTrue(any("no '**Tests**" in w for w in warns), warns)


class TestJsonEvidence(unittest.TestCase):
    """card.json's per-item `evidence` fields were never validated at all -- a consumer
    reading only the JSON weights its claims by them."""

    def _errs(self, **kw) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            errs, _, _ = VC.validate(_card(tmp, **kw))
            return " | ".join(errs)

    def test_invalid_evidence_class_is_caught(self):
        self.assertIn("not one of", self._errs(meta_over={"anti_patterns": [
            {"id": "A1", "name": "n", "why": "w", "evidence": "vibes"}]}))

    def test_no_per_item_evidence_at_all_is_an_error(self):
        self.assertIn("cannot weight any claim", self._errs(meta_over={
            "anti_patterns": [{"id": "A1", "name": "n", "why": "w"}],
            "cost_model": {"constraints": [{"id": "C1", "n": 1234567890}],
                           "breakpoints": [{"below": 5000, "action": "naive"}]},
            "recognition_signals": [], "selection_rule": {"text": "t"}}))

    def test_class_disagreement_on_a_shared_id_is_caught(self):
        """A1 is `[executed]` in the markdown but 'reasoned' in the JSON: the same claim
        cannot be two strengths at once."""
        self.assertIn("in CARD.md but", self._errs(meta_over={"anti_patterns": [
            {"id": "A1", "name": "n", "why": "w", "evidence": "reasoned"}]}))


class TestScenarios(unittest.TestCase):
    """The only check that tests the card's purpose rather than its shape."""

    def _errs(self, **kw) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            errs, _, _ = VC.validate(_card(tmp, **kw))
            return " | ".join(errs)

    def test_missing_scenarios_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp)
            os.remove(os.path.join(d, "scenarios.json"))
            errs, _, _ = VC.validate(d)
            self.assertTrue(any("no scenarios.json" in e for e in errs), errs)

    def test_no_refusal_scenario_is_an_error(self):
        """A card that can never be declined is the single-KB version of a corpus that
        rejected nothing -- the exact blind spot measured in 3 sibling KBs."""
        self.assertIn("no 'refusal' scenario", self._errs(scen_over={"scenarios": [
            {"id": "S", "kind": "planning", "prompt": "p", "rubric": {"x": 1}}]}))

    def test_rubric_referencing_an_absent_anti_pattern_is_an_error(self):
        self.assertIn("no such anti-pattern", self._errs(scen_over={"scenarios": [
            {"id": "S1", "kind": "planning", "prompt": "p",
             "rubric": {"must_flag_anti_patterns": ["A9"]}},
            {"id": "S2", "kind": "refusal", "prompt": "p", "rubric": {"a": 1}}]}))

    def test_rubric_referencing_an_absent_shape_is_an_error(self):
        self.assertIn("not a declared solution shape", self._errs(scen_over={"scenarios": [
            {"id": "S1", "kind": "planning", "prompt": "p",
             "rubric": {"must_select_shape": "Z"}},
            {"id": "S2", "kind": "refusal", "prompt": "p", "rubric": {"a": 1}}]}))

    def test_rubric_referencing_an_absent_edge_is_an_error(self):
        self.assertIn("not declared", self._errs(scen_over={"scenarios": [
            {"id": "S1", "kind": "planning", "prompt": "p",
             "rubric": {"must_flag_naive_scan_via_edge": {"from": 9, "to": 8}}},
            {"id": "S2", "kind": "refusal", "prompt": "p", "rubric": {"a": 1}}]}))

    def test_rubric_with_an_unresolvable_json_path_is_an_error(self):
        self.assertIn("does not resolve", self._errs(scen_over={"scenarios": [
            {"id": "S1", "kind": "planning", "prompt": "p",
             "rubric": {"must_quantify_naive_cost_from": "cost_model.nope"}},
            {"id": "S2", "kind": "refusal", "prompt": "p", "rubric": {"a": 1}}]}))

    def test_scenario_without_a_rubric_is_unscoreable(self):
        self.assertIn("no rubric", self._errs(scen_over={"scenarios": [
            {"id": "S1", "kind": "planning", "prompt": "p"},
            {"id": "S2", "kind": "refusal", "prompt": "p", "rubric": {"a": 1}}]}))

    def test_recorded_run_without_conditions_is_an_error(self):
        """A result without its conditions cannot be compared to the next result, and
        comparability over time is the entire value of a fixture. If a run was worth
        recording, its conditions are not optional."""
        self.assertIn("no `conditions`", self._errs(scen_over={"scenarios": [
            {"id": "S1", "kind": "planning", "prompt": "p", "rubric": {"a": 1},
             "observed": {"result": "pass"}},
            {"id": "S2", "kind": "refusal", "prompt": "p", "rubric": {"a": 1}}]}))

    def test_conditions_missing_model_class_is_an_error(self):
        self.assertIn("missing 'model_class'", self._errs(scen_over={"scenarios": [
            {"id": "S1", "kind": "planning", "prompt": "p", "rubric": {"a": 1},
             "observed": {"result": "pass",
                          "conditions": {"input_scope": "card.json only"}}},
            {"id": "S2", "kind": "refusal", "prompt": "p", "rubric": {"a": 1}}]}))

    def test_conditions_missing_input_scope_is_an_error(self):
        """Whether the consumer saw CARD.md, impl/, or the repo changes what the result
        means. Both stored PC-0001 runs were card.json-only; a run with repo access is a
        different experiment wearing the same name."""
        self.assertIn("missing 'input_scope'", self._errs(scen_over={"scenarios": [
            {"id": "S1", "kind": "planning", "prompt": "p", "rubric": {"a": 1},
             "observed": {"result": "pass", "conditions": {"model_class": "x"}}},
            {"id": "S2", "kind": "refusal", "prompt": "p", "rubric": {"a": 1}}]}))

    def test_a_run_against_an_older_card_json_warns_and_is_not_a_baseline(self):
        """Staleness is keyed on sha256(card.json), not the test count. Two real card.json
        defects were fixed WITHOUT the test count changing, so a count-keyed run would have
        looked current against a materially different consumer input."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp)
            sc = json.loads(Path(d, "scenarios.json").read_text(encoding="utf-8"))
            sc["scenarios"][0]["observed"]["conditions"]["card_state_at_run"] = {
                "card_json_sha256": "deadbeefcafe"}
            Path(d, "scenarios.json").write_text(json.dumps(sc), encoding="utf-8")
            errs, warns, stats = VC.validate(d)
            self.assertEqual(errs, [])
            self.assertTrue(any("deadbeefcafe" in w and "historical record" in w
                                for w in warns), warns)
            self.assertEqual(stats["runs_recorded"], 2)
            self.assertEqual(stats["runs_current"], 1, "the stale run must not count")

    def test_a_card_json_edit_invalidates_every_recorded_run(self):
        """The steady state the reviewer identified: a successful consumer run that causes
        a card fix destroys its own comparability. This must be VISIBLE, not silent."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp)
            _, _, before = VC.validate(d)
            self.assertEqual(before["runs_current"], 2)
            meta = json.loads(Path(d, "card.json").read_text(encoding="utf-8"))
            meta["cost_model"]["breakpoints"][0]["unit"] = "items (N) -- clarified"
            Path(d, "card.json").write_text(json.dumps(meta), encoding="utf-8")
            _, warns, after = VC.validate(d)
            self.assertEqual(after["runs_current"], 0,
                             "editing card.json must invalidate every prior run")
            self.assertEqual(len([w for w in warns if "historical record" in w]), 2)

    def test_observed_history_counts_every_run(self):
        """Regression. Adding a SECOND run to a scenario -- by moving `observed` into
        `observed_history` -- made the gate report 'no recorded run' for a scenario holding
        two, and runs-recorded silently fell from 2 to 1. A fixture whose whole purpose is
        accumulating comparable runs must count all of them."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp)
            sc = json.loads(Path(d, "scenarios.json").read_text(encoding="utf-8"))
            first = sc["scenarios"][0].pop("observed")
            sc["scenarios"][0]["observed_history"] = [first, json.loads(json.dumps(first))]
            Path(d, "scenarios.json").write_text(json.dumps(sc), encoding="utf-8")
            errs, warns, stats = VC.validate(d)
            self.assertEqual(errs, [])
            self.assertFalse(any("no recorded run" in w for w in warns), warns)
            self.assertEqual(stats["runs_recorded"], 3, "2 in history + 1 on SC-02")
            self.assertEqual(stats["runs_current"], 3)

    def test_missing_conditions_is_diagnosed_not_crashed(self):
        """The gate must FAIL BY DIAGNOSIS, not by raising. Previously, disabling the
        conditions check sent flow into a branch that dereferenced None, so the protection
        came from a crash -- which still fails a build, but hands the author a stack trace
        instead of a verdict, and evaporates the moment someone adds a defensive
        `.get(..., {})` downstream. The assertion below is on the MESSAGE, so it is
        independent of whether anything later would have crashed."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp)
            sc = json.loads(Path(d, "scenarios.json").read_text(encoding="utf-8"))
            sc["scenarios"][0]["observed"] = {"result": "pass"}
            Path(d, "scenarios.json").write_text(json.dumps(sc), encoding="utf-8")
            errs, _, stats = VC.validate(d)          # must not raise
            self.assertTrue(any("has a recorded result but no `conditions`" in e
                                for e in errs), errs)
            self.assertEqual(stats["runs_current"], 1, "the unconditioned run cannot count")

    def test_missing_consumer_prior_exposure_is_an_error(self):
        self.assertIn("missing 'consumer_prior_exposure'", self._errs(scen_over={
            "scenarios": [
                {"id": "S1", "kind": "planning", "prompt": "p", "rubric": {"a": 1},
                 "observed": {"result": "pass", "conditions": {
                     "model_class": "x", "input_scope": "y"}}},
                {"id": "S2", "kind": "refusal", "prompt": "p", "rubric": {"a": 1}}]}))

    def test_a_consumer_with_prior_exposure_is_recorded_but_never_a_baseline(self):
        """Currency is not independence. The card's own author cannot produce a naive run:
        any agent they delegate to inherits the authoring conversation, which contains the
        expected answer. Such a run is real data and must be kept -- but it is not a
        baseline, however current the card.json hash is."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp)
            sc = json.loads(Path(d, "scenarios.json").read_text(encoding="utf-8"))
            sc["scenarios"][0]["observed"]["conditions"]["consumer_prior_exposure"] = (
                "UNVERIFIED -- spawned inside the authoring conversation")
            Path(d, "scenarios.json").write_text(json.dumps(sc), encoding="utf-8")
            errs, warns, stats = VC.validate(d)
            self.assertEqual(errs, [])
            self.assertTrue(any("prior exposure" in w and "not counted as a naive baseline"
                                in w for w in warns), warns)
            self.assertEqual(stats["runs_recorded"], 2)
            self.assertEqual(stats["runs_current"], 1)

    def test_unrecorded_card_state_makes_staleness_undetectable_and_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, scen_over={"scenarios": [
                {"id": "S1", "kind": "planning", "prompt": "p", "rubric": {"a": 1},
                 "observed": {"result": "pass", "conditions": {
                     "model_class": "x", "input_scope": "y",
                     "consumer_prior_exposure": "none"}}},
                {"id": "S2", "kind": "refusal", "prompt": "p", "rubric": {"a": 1}}]})
            errs, warns, _ = VC.validate(d)
            self.assertEqual(errs, [], "only the missing hash should be in play here")
            self.assertTrue(any("card_json_sha256" in w and "undetectable" in w
                                for w in warns), warns)

    def test_stats_expose_the_comparable_run_count(self):
        """`runs-against-current-card` is printed by the gate so a zero cannot hide."""
        with tempfile.TemporaryDirectory() as tmp:
            _, _, stats = VC.validate(_card(tmp))
            self.assertEqual(stats["scenarios"], 2)
            self.assertEqual(stats["refusals"], 1)
            self.assertEqual(stats["runs_current"], 2)

    def test_a_rubric_citing_an_absent_do_not_use_when_entry_is_an_error(self):
        """This key was DEAD for two cards: `dnu_text` was computed and never read, so the
        rubric looked enforced and was not."""
        self.assertIn("no do_not_use_when entry", self._errs(
            meta_over={"do_not_use_when": ["N < ~5000 (naive is simpler)"]},
            scen_over={"scenarios": [
                {"id": "S1", "kind": "planning", "prompt": "p", "rubric": {"a": 1}},
                {"id": "S2", "kind": "refusal", "prompt": "p",
                 "rubric": {"must_cite_do_not_use_when": ["GDPR compliance"]}}]}))

    def test_a_numeric_expectation_matches_a_differently_worded_entry(self):
        """REGRESSION for a false positive this check produced on its first real run: a
        rubric saying 'N below 5000' against a card saying 'N < ~5000' shares no 5+ character
        word. The card was right; the checker was wrong. Numbers anchor at any length."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp,
                      meta_over={"do_not_use_when": ["N < ~5000 (naive is simpler)"]},
                      scen_over={"scenarios": [
                          {"id": "S1", "kind": "planning", "prompt": "p", "rubric": {"a": 1}},
                          {"id": "S2", "kind": "refusal", "prompt": "p",
                           "rubric": {"must_cite_do_not_use_when": ["N below 5000"]}}]})
            errs, _, _ = VC.validate(d)
            self.assertEqual([e for e in errs if "do_not_use_when" in e], [])

    def test_stem_matching_tolerates_auditability_against_auditable(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp,
                      meta_over={"do_not_use_when": ["per-pair decisions must be auditable"]},
                      scen_over={"scenarios": [
                          {"id": "S1", "kind": "planning", "prompt": "p", "rubric": {"a": 1}},
                          {"id": "S2", "kind": "refusal", "prompt": "p",
                           "rubric": {"must_cite_do_not_use_when": ["auditability"]}}]})
            errs, _, _ = VC.validate(d)
            self.assertEqual([e for e in errs if "do_not_use_when" in e], [])

    def test_scenario_with_no_recorded_run_only_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, scen_over={"scenarios": [
                {"id": "S1", "kind": "planning", "prompt": "p", "rubric": {"a": 1}},
                {"id": "S2", "kind": "refusal", "prompt": "p", "rubric": {"a": 1}}]})
            errs, warns, _ = VC.validate(d)
            self.assertEqual(errs, [])
            self.assertTrue(any("never been planned over" in w for w in warns), warns)


class TestSyncCounts(unittest.TestCase):
    def test_test_count_is_derived_from_the_actual_run(self):
        """The count is stated in the header, in card.json, and in reality. Reality wins."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, n_tests=3)
            md = Path(d, "CARD.md").read_text(encoding="utf-8").replace("| **Tests** | 3 |",
                                                        "| **Tests** | 99 |")
            Path(d, "CARD.md").write_text(md, encoding="utf-8")
            meta = json.loads(Path(d, "card.json").read_text(encoding="utf-8"))
            meta["tests"] = {"count": 77, "passing": True}
            Path(d, "card.json").write_text(json.dumps(meta), encoding="utf-8")

            self.assertTrue(VC.sync_counts(d))
            self.assertIn("| **Tests** | 3 |", Path(d, "CARD.md").read_text(encoding="utf-8"))
            after = json.loads(Path(d, "card.json").read_text(encoding="utf-8"))
            self.assertEqual(after["tests"]["count"], 3)
            self.assertNotIn("passing", after["tests"],
                             "a hand-kept 'passing' boolean can only ever be wrong")
            self.assertFalse(VC.sync_counts(d), "second run must be a no-op")


class TestSyncLedger(unittest.TestCase):
    def test_sync_rewrites_drifted_counts(self):
        """The counts drifted on all three classes within an hour of authoring. Anything
        derivable and hand-maintained must be derived -- the same lesson that put a stale
        hardcoded month into a freshness script and a stale total into 31 llms.txt files."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, md_extra="\n## 12 · Evidence ledger\n| `[executed]` | 999 | x |\n")
            self.assertTrue(VC.sync_ledger(d))
            md = Path(d, "CARD.md").read_text(encoding="utf-8")
            actual = VC.count_evidence(md)["executed"]
            self.assertIn(f"| `[executed]` | {actual} |", md)
            self.assertFalse(VC.sync_ledger(d), "second run must be a no-op")


class TestGeneratedCostTable(unittest.TestCase):
    """The authoring-cost line counts were hand-written and wrong TWICE -- once from
    pre-final estimates, once as a typo (385 for 386) -- in the very section arguing that
    unexecuted numbers are untrustworthy. They are generated now, and the table is
    self-referential: it reports the line count of the file it lives in.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = _card(self._tmp.name)
        self._saved = VC.CARDS
        VC.CARDS = os.path.join(self._tmp.name, "cards")

    def tearDown(self):
        VC.CARDS = self._saved
        self._tmp.cleanup()

    def _add_markers(self, body: str = "\n| bogus | 1 |\n"):
        md = Path(self.d, "CARD.md").read_text(encoding="utf-8")
        Path(self.d, "CARD.md").write_text(
            md + "\n" + VC.COST_BEGIN + body + VC.COST_END + "\n", encoding="utf-8")

    def test_the_table_is_computed_from_the_filesystem(self):
        table = VC.cost_table()
        self.assertIn("| `CARD.md` |", table)
        self.assertIn("| doc-to-code |", table)
        md_lines = sum(1 for _ in open(os.path.join(self.d, "CARD.md"), encoding="utf-8"))
        self.assertIn(str(md_lines), table, "CARD.md's real line count must appear")

    def test_a_stale_table_is_a_gate_error(self):
        self._add_markers()
        errs, _, _ = VC.validate(self.d)
        self.assertTrue(any("cost table is STALE" in e for e in errs), errs)

    def test_one_sync_invocation_leaves_the_gate_clean(self):
        """The trap this guards: the table reports its own file's line count, so a SINGLE
        pass writes a value that its own write invalidates. CI runs --strict and never syncs,
        so a one-pass sync would have produced a red build caused by the sync tool itself."""
        self._add_markers()
        self.assertTrue(VC.sync_cost_table(self.d))
        errs, _, _ = VC.validate(self.d)
        self.assertEqual([e for e in errs if "cost table" in e], [],
                         "one invocation must reach the fixed point")

    def test_a_second_sync_is_a_no_op(self):
        self._add_markers()
        VC.sync_cost_table(self.d)
        self.assertFalse(VC.sync_cost_table(self.d))

    def test_a_card_with_no_markers_is_not_required_to_have_a_table(self):
        errs, _, _ = VC.validate(self.d)
        self.assertEqual([e for e in errs if "cost table" in e], [])
        self.assertFalse(VC.sync_cost_table(self.d))


class TestRelatedCards(unittest.TestCase):
    """`related_cards` was not validated AT ALL, and the cross-card graph had already rotted:
    PC-0001 and PC-0002 said "composes-with" while PC-0003 said "composes_with" -- two names
    for one relation across three cards -- and two of the three edges asserted a relationship
    with a completely EMPTY `why`. The index publishes these edges, so nothing between the
    author and every downstream consumer was checking them.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = _card(self._tmp.name)
        self._saved = VC.CARDS
        VC.CARDS = os.path.join(self._tmp.name, "cards")
        # a second card, so a VALID outbound edge has somewhere real to point
        other = os.path.join(VC.CARDS, "PC-8888-other")
        os.makedirs(other, exist_ok=True)
        Path(other, "card.json").write_text(json.dumps({"id": "PC-8888"}), encoding="utf-8")

    def tearDown(self):
        VC.CARDS = self._saved
        self._tmp.cleanup()

    def _run(self, related):
        meta = json.loads(Path(self.d, "card.json").read_text(encoding="utf-8"))
        meta["related_cards"] = related
        Path(self.d, "card.json").write_text(json.dumps(meta), encoding="utf-8")
        errs, warns, _ = VC.validate(self.d)
        return " | ".join(errs), " | ".join(warns)

    GOOD = [{"id": "PC-8888", "relation": "composes_with",
             "why": "one asks whether two items match, the other whether two requests do"}]

    def test_a_well_formed_edge_is_clean(self):
        """If the happy path were not clean, every assertion below would be meaningless."""
        errs, warns = self._run(self.GOOD)
        self.assertEqual([e for e in errs.split(" | ") if "related_cards" in e], [])
        self.assertNotIn("related_cards", warns)

    def test_a_dangling_card_id_is_an_error(self):
        """The exact shape of a defect already measured elsewhere in this workspace: a KB
        deferred to a sibling that had REJECTED the package -- a pointer to nothing."""
        errs, _ = self._run([{"id": "PC-7777", "relation": "composes_with",
                              "why": "a reason long enough to satisfy the minimum length"}])
        self.assertIn("not a card on disk", errs)

    def test_a_self_reference_is_an_error(self):
        errs, _ = self._run([{"id": "PC-9999", "relation": "composes_with",
                              "why": "a reason long enough to satisfy the minimum length"}])
        self.assertIn("points at itself", errs)

    def test_an_invented_relation_is_an_error(self):
        errs, _ = self._run([{"id": "PC-8888", "relation": "vaguely_related_to",
                              "why": "a reason long enough to satisfy the minimum length"}])
        self.assertIn("is not one of", errs)

    def test_a_bare_string_instead_of_an_object_is_an_error(self):
        """A bare id cannot carry a relation or a reason, so it cannot be checked at all."""
        errs, _ = self._run(["PC-8888"])
        self.assertIn("not an object", errs)

    def test_the_shipped_spelling_drift_warns_rather_than_failing_the_build(self):
        """'composes-with' normalises INTO the vocabulary, so it is drift, not invention.

        Warn on purpose: fixing it edits card.json, which invalidates every prepared consumer
        run against that card. The abs-path gate set this precedent -- turning CI red on day
        one for a pre-existing condition teaches people to ignore the gate.
        """
        errs, warns = self._run([{"id": "PC-8888", "relation": "composes-with",
                                 "why": "a reason long enough to satisfy the minimum"}])
        self.assertEqual([e for e in errs.split(" | ") if "related_cards" in e], [])
        self.assertIn("non-canonical spelling", warns)

    def test_an_edge_with_no_why_warns(self):
        errs, warns = self._run([{"id": "PC-8888", "relation": "composes_with"}])
        self.assertEqual([e for e in errs.split(" | ") if "related_cards" in e], [])
        self.assertIn("no substantive 'why'", warns)

    def test_a_one_word_why_is_not_substantive(self):
        """The 30-character decay, one level up: "related" asserts nothing."""
        _, warns = self._run([{"id": "PC-8888", "relation": "composes_with",
                               "why": "related"}])
        self.assertIn("no substantive 'why'", warns)

    def test_canonical_relation_normalises_only_into_the_vocabulary(self):
        self.assertEqual(VC.canonical_relation("composes-with"), "composes_with")
        self.assertEqual(VC.canonical_relation("Composes With"), "composes_with")
        self.assertEqual(VC.canonical_relation("composes_with"), "composes_with")
        self.assertIsNone(VC.canonical_relation("kind-of-related"))
        self.assertIsNone(VC.canonical_relation(None))
        self.assertIsNone(VC.canonical_relation(7))

    def test_all_card_ids_reads_the_disk(self):
        self.assertEqual(VC.all_card_ids(), {"PC-9999", "PC-8888"})

    def test_all_card_ids_survives_an_unreadable_card(self):
        """One corrupt card must not make every OTHER card's edges look dangling -- that
        would turn one defect into an error on every card in the portfolio."""
        Path(VC.CARDS, "PC-8888-other", "card.json").write_text("{ not json", encoding="utf-8")
        self.assertEqual(VC.all_card_ids(), {"PC-9999"})



class TestCheck6Quantification(unittest.TestCase):
    """Check 6 claimed to enforce "unquantified tradeoffs are 'it depends'". Tested against a
    deliberate decoy while authoring a correctness-oriented third card, it was wrong in BOTH
    directions -- it counted digit CHARACTERS anywhere in json.dumps(cost_model), so id
    numerals satisfied it and honest prose failed it.
    """

    def _errs(self, cost_model) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            errs, _, _ = VC.validate(_card(tmp, meta_over={"cost_model": cost_model}))
            return " | ".join(errs)

    def _warns(self, cost_model) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            _, warns, _ = VC.validate(_card(tmp, meta_over={"cost_model": cost_model}))
            return " | ".join(warns)

    DECOY = {
        "constraints": [{"id": f"C{i}", "claim": "it depends on your workload",
                         "evidence": "reasoned"} for i in range(1, 11)],
        "breakpoints": [{"at": "when it gets slow", "unit": "vibes"}],
    }

    def test_ids_alone_no_longer_satisfy_the_check(self):
        """The exact decoy that passed the old check with 11 digits, every one of them from
        the numerals in C1..C10."""
        self.assertEqual(VC.quantified_digits(self.DECOY), 0)
        self.assertIn("quantifies almost nothing", self._errs(self.DECOY))

    def test_the_old_implementation_would_have_passed_that_decoy(self):
        """Pins the defect itself, so nobody can 'simplify' the counter back to it."""
        naive_count = len(re.findall(r"\d", json.dumps(self.DECOY)))
        self.assertGreaterEqual(naive_count, 10,
                                "the decoy must still look fine to the old rule")
        self.assertLess(VC.quantified_digits(self.DECOY), 10)

    def test_a_real_measurement_passes(self):
        cm = {"constraints": [{"id": "C1", "claim": "duplicates", "measured": 0.1668,
                               "measured_on": {"what": "x", "population": "p", "n": 4000},
                               "evidence": "executed"}],
              "breakpoints": [{"at": 61, "unit": "ticks"}]}
        self.assertNotIn("quantifies almost nothing", self._errs(cm))

    def test_a_genuinely_non_quantitative_card_may_declare_it(self):
        """The point of authoring a correctness-not-cost card: the schema must admit one.
        Padding with fake numbers would be the exact sin the rest of the gate forbids, so the
        escape hatch requires SAYING SO, which is reviewable."""
        cm = dict(self.DECOY)
        cm["non_quantitative_because"] = ("the decision is correctness, not cost: every "
                                          "alternative has the same throughput")
        self.assertNotIn("quantifies almost nothing", self._errs(cm))

    def test_the_escape_hatch_warns_if_it_is_left_in_place_once_measurements_exist(self):
        """Otherwise the hatch becomes permanent decoration -- the same decay as a stale
        ledger or a back-filled hash."""
        cm = {"constraints": [{"id": "C1", "measured": {"a": 1234567890, "b": 4000},
                               "measured_on": {"what": "x", "population": "p", "n": 4000},
                               "evidence": "executed"}],
              "breakpoints": [{"at": 61, "unit": "ticks"}],
              "non_quantitative_because": "not really"}
        self.assertIn("drop the declaration", self._warns(cm))

    def test_the_hatch_text_does_not_count_as_the_quantification_it_denies(self):
        """Found by authoring PC-0004, the first card genuinely entitled to the hatch.

        Its cost model scores 7 digits -- correctly below the threshold -- while the hatch
        TEXT carries 12 (12, 54, 1000, 1000), because the only way to explain why a
        correctness problem has no cost curve is to name the outcome counts that exist in
        place of one. Total 19, so the gate warned that the declaration was an unused escape
        hatch. The field whose entire purpose is to say "this cannot be quantified" was read
        as quantification and voided itself.

        Same class as the original check-6 defect one level up: digit density mistaken for
        measurement. A key that talks ABOUT the model is not a measurement IN it.
        """
        cm = {
            "constraints": [{"id": "C1", "claim": "stated in words", "evidence": "executed"}],
            "breakpoints": [{"at": 1, "unit": "readers you do not control", "what": "x"}],
            "non_quantitative_because": ("no cost curve exists: 12 of 54 cells are silently "
                                         "wrong and 1000 of 1000 records are lost, and those "
                                         "are outcome counts rather than prices"),
        }
        self.assertLess(VC.quantified_digits(cm), 10,
                        "the justification's own digits must not be counted as measurement")
        self.assertNotIn("drop the declaration", self._warns(cm))
        self.assertNotIn("quantifies almost nothing", self._errs(cm))

    def test_the_hatch_still_warns_when_the_MEASUREMENTS_are_real(self):
        """The fix must not disable the check it repairs. Digits in constraints and
        breakpoints still count, so a card with a genuine cost model plus a leftover hatch is
        still told to drop it -- exactly as before."""
        cm = {"constraints": [{"id": "C1", "measured": {"p50": 1234, "p99": 56789},
                               "measured_on": {"what": "x", "population": "p", "n": 100}}],
              "breakpoints": [{"at": 5000, "unit": "items"}],
              "non_quantitative_because": "leftover"}
        self.assertGreaterEqual(VC.quantified_digits(cm), 10)
        self.assertIn("drop the declaration", self._warns(cm))

    def test_ids_are_still_excluded_after_the_hatch_fix(self):
        """Guards against the fix being written as a replacement rather than an addition:
        both keys must be stripped, and PC-0003's decoy is what proves `id` still is."""
        self.assertEqual(VC.quantified_digits(self.DECOY), 0)
        self.assertIn("id", VC.NON_MEASUREMENT_KEYS)
        self.assertIn("non_quantitative_because", VC.NON_MEASUREMENT_KEYS)


    def test_digits_are_counted_inside_nested_measured_tables(self):
        """A constraint publishing a TABLE is the shape that already defeated one check in
        this file; the counter must recurse rather than look only at scalars."""
        cm = {"constraints": [{"id": "C1", "measured": {"lost": 573, "dup": 573,
                                                       "rows_wrong": 501}}],
              "breakpoints": [{"at": 61, "unit": "ticks"}]}
        self.assertGreaterEqual(VC.quantified_digits(cm), 10)

    def test_every_real_card_passes_check_6_and_for_the_right_reason(self):
        """Two ways to pass, and neither may be vacuous.

        This test previously asserted `digits >= 10` for every card on disk, which encoded the
        assumption that every card quantifies. That held for three cards and PC-0004 broke it
        legitimately -- it is the first card genuinely entitled to the hatch, and it scores 7.
        A test that had to be relaxed to admit a correct card was asserting the wrong thing.

        So the assertion is now the real contract: a card passes on measurement OR on a
        declared justification, never on id numerals. Both populations are required to be
        non-empty, because if every card were on one side the other branch would be untested
        while looking covered.

        Measured: ids contribute 3, 6 and 7 digits to the three quantifying cards, so none of
        them passes on labels.
        """
        quantified, declared = [], []
        for d in sorted(os.listdir(VC.CARDS)):
            p = os.path.join(VC.CARDS, d, "card.json")
            if not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as fh:
                cm = json.load(fh).get("cost_model", {})
            digits = VC.quantified_digits(cm)
            hatch = bool(cm.get("non_quantitative_because"))
            self.assertTrue(digits >= 10 or hatch,
                            f"{d} fails check 6: {digits} digits and no "
                            f"non_quantitative_because")
            if hatch:
                declared.append((d, digits))
                self.assertLess(digits, 10,
                                f"{d} declares the hatch AND quantifies -- the gate warns "
                                f"about this, so no shipped card may be in that state")
            else:
                quantified.append((d, digits))
        self.assertGreaterEqual(len(quantified) + len(declared), 4,
                                "every card on disk must be inspected")
        self.assertTrue(quantified, "no card quantifies -- the digits branch is untested")
        self.assertTrue(declared, "no card declares the hatch -- that branch is untested")



class TestCostModelUnits(unittest.TestCase):
    """Both defects here were found by a CONSUMER planning over card.json -- not by the
    author, and not by the gate. They are the flattening failure one level down: a bare
    number flattens away its unit, and a measured value flattens away its corpus."""

    def _errs(self, **kw) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            errs, _, _ = VC.validate(_card(tmp, **kw))
            return " | ".join(errs)

    def test_breakpoint_without_a_unit_is_an_error(self):
        """Observed: a consumer read `{"below": 5000}` and compared 1,619,100 COMPARISONS
        against it, when the threshold is 5,000 ITEMS -- right answer, by luck of magnitude.
        CARD.md said 'below N~5,000' and was never ambiguous, so the defect existed ONLY in
        the record that consumer was restricted to."""
        self.assertIn("no 'unit'", self._errs(meta_over={"cost_model": {
            "constraints": [{"id": "C1", "n": 1234567890, "evidence": "executed"}],
            "breakpoints": [{"below": 5000, "action": "naive"}]}}))

    def test_a_measured_value_without_its_corpus_warns(self):
        """Observed: C1's 0.6133 (an 80-doc synthetic fixture) was quoted as 'recall is only
        ~61%' for 1,800 legal contracts -- read as a property of the algorithm rather than
        of the corpus. Warn, not error: which values need it is a judgement call."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, meta_over={"cost_model": {
                "constraints": [{"id": "C1", "n": 1234567890, "measured": 0.6133,
                                 "evidence": "executed"}],
                "breakpoints": [{"below": 5000, "action": "naive", "unit": "items (N)"}]}})
            errs, warns, _ = VC.validate(d)
            self.assertEqual(errs, [])
            self.assertTrue(any("measured_on" in w for w in warns), warns)

    def test_a_TABLE_of_measurements_with_no_corpus_also_warns(self):
        """THE HOLE. The first version tested `isinstance(measured, (int, float))`, so a
        constraint publishing a dict of measurements bypassed the check completely -- and 2 of
        3 constraints in PC-0001 did exactly that while the gate stayed green. Same shape as
        the dead `dnu_text`: a check that looks like it covers a case and does not."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, meta_over={"cost_model": {
                "constraints": [{"id": "C1", "n": 1234567890, "evidence": "executed",
                                 "measured": {"reduction": 32.6, "candidates": 97}}],
                "breakpoints": [{"below": 5000, "action": "naive", "unit": "items (N)"}]}})
            errs, warns, _ = VC.validate(d)
            self.assertEqual(errs, [])
            self.assertTrue(any("measured_on" in w for w in warns), warns)


class TestGroundingOfExecutedClaims(unittest.TestCase):
    """Check 17. `executed` was doing two incompatible jobs and printing one label.

    PC-0002's `dot == cosine after L2-normalising` is an ALGEBRAIC identity -- the code is the
    subject, so running it self-certifies. PC-0004's 54-cell compatibility matrix is a
    SIMULATOR of three wire formats -- running it proves the card's numbers faithfully preserve
    my model (pin-fidelity) and says nothing about the world (world-fidelity). Both tagged
    `[executed]`. Merging them is the claimed-vs-evidenced merge this schema was built against,
    one layer down.
    """

    @staticmethod
    def _run(**kw):
        with tempfile.TemporaryDirectory() as tmp:
            return VC.validate(_card(tmp, **kw))

    def test_executed_claim_without_grounding_is_an_error(self):
        errs, _, _ = self._run(meta_over={"_no_grounding": True})
        self.assertTrue(any("no 'grounding'" in e for e in errs), errs)

    def test_grounding_outside_the_vocabulary_is_always_an_error(self):
        """A misspelt grounding is worse than an absent one: it LOOKS enforced. That is
        precisely how `must_cite_do_not_use_when` came to be dead code."""
        errs, _, _ = self._run(meta_over={"cost_model": {
            "constraints": [{"id": "C1", "n": 1234567890, "evidence": "executed",
                             "grounding": "vibes"}],
            "breakpoints": [{"below": 5000, "action": "naive", "unit": "items (N)"}]}})
        self.assertTrue(any("not one of" in e and "vibes" in e for e in errs), errs)

    def test_simulator_grounded_with_only_a_self_citation_is_an_error(self):
        """PC-0004's single citation was `problem-cards/run_scenarios.py` -- a file I wrote in
        the same session as the card. A card citing itself corroborates nothing."""
        errs, _, _ = self._run(meta_over={
            "cited_evidence": [{"path": "problem-cards/run_scenarios.py", "what": "w"}],
            "cost_model": {
                "constraints": [{"id": "C1", "n": 1234567890, "evidence": "executed",
                                 "grounding": "simulator"}],
                "breakpoints": [{"below": 5000, "action": "naive", "unit": "items (N)"}]}})
        self.assertTrue(any("self-citation" in e for e in errs), errs)

    def test_a_simulator_card_may_instead_declare_itself_direction_only(self):
        """The requirement is conditional on CLAIM STRENGTH. A card that says on its face
        'the shape is right, the magnitudes are mine' is being honest and is allowed. What is
        forbidden is presenting modelled numbers as measurements of the world."""
        errs, _, _ = self._run(meta_over={
            "claim_strength": "direction",
            "cited_evidence": [{"path": "problem-cards/run_scenarios.py", "what": "w"}],
            "cost_model": {
                "constraints": [{"id": "C1", "n": 1234567890, "evidence": "executed",
                                 "grounding": "simulator"}],
                "breakpoints": [{"below": 5000, "action": "naive", "unit": "items (N)"}]}})
        self.assertFalse([e for e in errs if "self-citation" in e], errs)

    def test_a_named_domain_reviewer_also_satisfies_corroboration(self):
        errs, _, _ = self._run(meta_over={
            "domain_reviewer": "reviewed by the team that owns the wire format",
            "cost_model": {
                "constraints": [{"id": "C1", "n": 1234567890, "evidence": "executed",
                                 "grounding": "simulator"}],
                "breakpoints": [{"below": 5000, "action": "naive", "unit": "items (N)"}]}})
        self.assertFalse([e for e in errs if "self-citation" in e], errs)

    def test_an_invalid_claim_strength_is_an_error(self):
        errs, _, _ = self._run(meta_over={
            "claim_strength": "definitely-true",
            "cost_model": {
                "constraints": [{"id": "C1", "n": 1234567890, "evidence": "executed",
                                 "grounding": "simulator"}],
                "breakpoints": [{"below": 5000, "action": "naive", "unit": "items (N)"}]}})
        self.assertTrue(any("claim_strength" in e and "not one of" in e for e in errs), errs)

    def test_a_pending_consumer_run_downgrades_the_error_to_a_warning(self):
        """A prepared consumer run is IRREPLACEABLE: any byte written to card.json invalidates
        it, and the card's own author structurally cannot produce a naive replacement. So for
        those two cards this must warn, on the precedent set by check 16 -- backfill after the
        run is recorded, never before. Without this, landing check 17 would have destroyed the
        only two live prepares in the portfolio."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, meta_over={"_no_grounding": True})
            Path(d, ".scenario_pending.json").write_text(
                json.dumps({"scenario": "SC-01", "card_json_sha256": "deadbeef"}),
                encoding="utf-8")
            errs, warns, _ = VC.validate(d)
            self.assertFalse([e for e in errs if "grounding" in e], errs)
            self.assertTrue(any("grounding" in w and "destroy the run" in w for w in warns),
                            warns)

    def test_direction_while_corroborated_warns_about_understating(self):
        """The gate should push back in BOTH directions. A card that self-limits to `direction`
        after gaining real corroboration is now underselling evidence it actually has, and
        under-claiming is a defect too -- it is how a card stops being worth reading."""
        _, warns, _ = self._run(meta_over={
            "claim_strength": "direction",
            "domain_reviewer": "reviewed by the wire-format owners",
            "cost_model": {
                "constraints": [{"id": "C1", "n": 1234567890, "evidence": "executed",
                                 "grounding": "simulator"}],
                "breakpoints": [{"below": 5000, "action": "naive", "unit": "items (N)"}]}})
        self.assertTrue(any("understating" in w for w in warns), warns)

    def test_the_real_cards_declare_a_grounding_or_are_pending_a_run(self):
        """The population check. Every shipped card must either declare grounding on its
        executed claims, or be one of the two with a live prepared run. A card that is neither
        has slipped through, which is how 18 of 31 KBs decayed."""
        for d in sorted(os.listdir(VC.CARDS)):
            cd = os.path.join(VC.CARDS, d)
            if not os.path.isdir(cd) or not os.path.exists(os.path.join(cd, "card.json")):
                continue
            errs, warns, _ = VC.validate(cd)
            pending = os.path.exists(os.path.join(cd, ".scenario_pending.json"))
            offending = [m for m in errs if "no 'grounding'" in m]
            if pending:
                self.assertEqual(offending, [], f"{d}: pending cards must only warn")
            else:
                self.assertEqual(offending, [], f"{d}: shipped card is missing grounding")


class TestSampleSizeConsistency(unittest.TestCase):
    """Whether one claim in a card rests on a far smaller sample than its neighbours.

    Split out of TestCostModelUnits when check 17's tests landed between them. These five were
    briefly methods of the grounding class and still passed -- they use the module-level
    `_card` helper rather than that class's `_errs`, so nothing broke. Passing for an
    unintended reason is exactly the state this portfolio's mutation sweeps exist to find, so
    the boundary is made explicit rather than left to luck.
    """

    def test_a_sample_an_order_of_magnitude_below_its_siblings_warns(self):
        """The consumer-found defect, now gateable. chunks/doc was measured on 30 documents
        while every other number in the card used 2000. A gate cannot ask whether a sample
        DESERVES a claim -- but internal inconsistency within one card IS checkable."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, meta_over={"cost_model": {
                "constraints": [
                    {"id": "C1", "n": 1234567890, "evidence": "executed", "measured": 1.0,
                     "measured_on": {"what": "full", "population": "corpus", "n": 2000}},
                    {"id": "C2", "evidence": "executed", "measured": 1.07,
                     "measured_on": {"what": "small fixture", "population": "corpus", "n": 30}}],
                "breakpoints": [{"below": 5000, "action": "naive", "unit": "items (N)"}]}},
                md_extra="\n## 7 · Cost & scale model\n**C1 — a.** x\n**C2 — b.** y\n")
            _, warns, _ = VC.validate(d)
            hits = [w for w in warns if "deserve the claim" in w]
            self.assertEqual(len(hits), 1, warns)
            self.assertIn("n=30", hits[0])
            self.assertIn("n=2000", hits[0])

    def test_a_deliberate_slice_at_exactly_one_tenth_does_not_warn(self):
        """200-vs-2000 is a deliberate slice and must stay quiet; the threshold is STRICTLY
        below one tenth. A check that fires on defensible sampling would train people to
        ignore it."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, meta_over={"cost_model": {
                "constraints": [
                    {"id": "C1", "n": 1234567890, "evidence": "executed", "measured": 1.0,
                     "measured_on": {"what": "full", "population": "corpus", "n": 2000}},
                    {"id": "C2", "evidence": "executed", "measured": 0.99,
                     "measured_on": {"what": "slice", "population": "corpus", "n": 200}}],
                "breakpoints": [{"below": 5000, "action": "naive", "unit": "items (N)"}]}},
                md_extra="\n## 7 · Cost & scale model\n**C1 — a.** x\n**C2 — b.** y\n")
            _, warns, _ = VC.validate(d)
            self.assertEqual([w for w in warns if "deserve the claim" in w], [])

    def test_different_populations_are_never_compared(self):
        """48 synthetic vectors and 2000 documents are not comparable sample sizes. Comparing
        them would make the check noisy, and a noisy check gets ignored."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, meta_over={"cost_model": {
                "constraints": [
                    {"id": "C1", "n": 1234567890, "evidence": "executed", "measured": 1.0,
                     "measured_on": {"what": "corpus", "population": "docs", "n": 2000}},
                    {"id": "C2", "evidence": "executed", "measured": 0.9,
                     "measured_on": {"what": "vectors", "population": "vectors", "n": 48}}],
                "breakpoints": [{"below": 5000, "action": "naive", "unit": "items (N)"}]}},
                md_extra="\n## 7 · Cost & scale model\n**C1 — a.** x\n**C2 — b.** y\n")
            _, warns, _ = VC.validate(d)
            self.assertEqual([w for w in warns if "deserve the claim" in w], [])

    def test_a_corpus_independent_claim_needs_no_sample_size(self):
        """PC-0001's C3 is exact arithmetic over the divisors of num_perm -- no corpus exists
        to sample. Declaring a population with no `n` must be accepted, not nagged."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, meta_over={"cost_model": {
                "constraints": [{"id": "C1", "n": 1234567890, "evidence": "executed",
                                 "measured": {"knees": [0.125, 0.42]},
                                 "measured_on": {"what": "no corpus; exact arithmetic",
                                                 "population": "exact-arithmetic"}}],
                "breakpoints": [{"below": 5000, "action": "naive", "unit": "items (N)"}]}})
            errs, warns, _ = VC.validate(d)
            self.assertEqual(errs, [])
            self.assertEqual([w for w in warns if "measured_on" in w or "deserve" in w], [])

    def test_a_measured_value_with_its_corpus_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, meta_over={"cost_model": {
                "constraints": [{"id": "C1", "n": 1234567890, "measured": 0.6133,
                                 "measured_on": "80-doc fixture", "evidence": "executed"}],
                "breakpoints": [{"below": 5000, "action": "naive", "unit": "items (N)"}]}})
            errs, warns, _ = VC.validate(d)
            self.assertEqual(errs, [])
            self.assertFalse(any("measured_on" in w for w in warns), warns)


class TestPortfolioWideFixedPoint(unittest.TestCase):
    """The cost table's fixed point is PORTFOLIO-WIDE, and nothing iterated the portfolio.

    `sync_cost_table` already iterated one CARD.md to convergence, and its docstring explains
    exactly why: the table reports that file's own line count, so one pass leaves it stale and
    an author who synced once and pushed would get a red build caused by the sync tool.

    The same argument applies one scope up and was missed. The table reports EVERY card's line
    counts, so syncing a later card invalidates the table already written into every earlier
    one. Measured when PC-0004 was added: a full sync pass left PC-0002 stale and `--strict`
    failed immediately afterwards -- the identical trap the per-file loop was written to avoid.

    Two minimal cards are enough to reproduce it, because the coupling is between files rather
    than inside one.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = VC.CARDS
        VC.CARDS = os.path.join(self._tmp.name, "cards")
        for n in ("PC-9001-alpha", "PC-9002-beta"):
            d = Path(VC.CARDS, n)
            d.mkdir(parents=True)
            # Padding lines make the two cards differ in length, so a wrong table is a wrong
            # NUMBER rather than a coincidentally equal one.
            pad = "\n".join(f"filler {i}" for i in range(len(n)))
            (d / "CARD.md").write_text(
                f"# {n}\n{pad}\n\n{VC.COST_BEGIN}\n{VC.COST_END}\n", encoding="utf-8")

    def tearDown(self):
        VC.CARDS = self._saved
        self._tmp.cleanup()

    def _stale(self) -> list[str]:
        out = []
        wanted = "\n" + VC.cost_table() + "\n"
        for n in sorted(os.listdir(VC.CARDS)):
            md = (Path(VC.CARDS, n) / "CARD.md").read_text(encoding="utf-8")
            got = md[md.index(VC.COST_BEGIN) + len(VC.COST_BEGIN):md.index(VC.COST_END)]
            if got != wanted:
                out.append(n)
        return out

    def _quiet(self, fn, *a, **kw):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(*a, **kw)

    def test_one_pass_per_card_leaves_an_earlier_card_stale(self):
        """Reproduces the defect. This is the OLD behaviour, written out explicitly: one
        `sync_cost_table` per card, in order, exactly as `main()` used to do it."""
        for n in sorted(os.listdir(VC.CARDS)):
            self._quiet(VC.sync_cost_table, os.path.join(VC.CARDS, n))
        self.assertTrue(self._stale(),
                        "one pass per card should leave at least one table stale -- if this "
                        "passes, the fixture no longer reproduces the cross-card coupling")

    def test_sync_portfolio_reaches_a_global_fixed_point(self):
        sweeps = self._quiet(VC.sync_portfolio)
        self.assertGreater(sweeps, 1,
                           "a single sweep cannot converge a portfolio-wide fixed point")
        self.assertEqual(self._stale(), [], "every table must agree after convergence")

    def test_a_second_portfolio_sync_is_a_no_op(self):
        """Idempotence is the property CI depends on: --strict must be clean straight after
        an author's sync, with no second invocation required."""
        self._quiet(VC.sync_portfolio)
        self.assertEqual(self._quiet(VC.sync_portfolio), 1)

    def test_oscillation_raises_rather_than_being_silently_accepted(self):
        """A bound that returns quietly on exhaustion would report convergence it never
        reached -- the same shape as a mutation that fails to apply and prints a verdict."""
        with self.assertRaises(RuntimeError) as cm:
            self._quiet(VC.sync_portfolio, max_sweeps=1)
        self.assertIn("oscillating", str(cm.exception))



if __name__ == "__main__":
    unittest.main()


class TestDecisionLanguageProximity(unittest.TestCase):
    """The check promises PER-NUMBER proximity: decision language within PROXIMITY (220)
    characters of each number. It used to test whole fields, so one "therefore" anywhere in a
    long field licensed every number in it -- and `PROXIMITY` was assigned and never read.
    The third test is the one that failed before the fix."""

    def _naked(self, why: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            d = _card(tmp, meta_over={"anti_patterns": [
                {"id": "A1", "name": "n", "why": why, "evidence": "executed"}]})
            _, warns, _ = VC.validate(d)
            return [w for w in warns if "no decision language" in w and "A1" in w]

    def test_a_number_beside_decision_language_is_licensed(self):
        self.assertEqual(self._naked("p99 is 12.5 ms, so do not page on it"), [])

    def test_a_number_with_no_decision_language_is_flagged(self):
        self.assertTrue(self._naked("p99 measured at 12.5 ms on the corpus"))

    def test_a_distant_decision_word_does_not_license_a_number(self):
        why = "therefore page on errors. " + "x" * 300 + " p99 measured at 12.5 ms"
        flagged = self._naked(why)
        self.assertTrue(flagged, "a decision word 300 characters away licensed the number")
        self.assertIn("12.5", flagged[0])
