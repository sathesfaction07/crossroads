"""Tests for PC-0004. Every number the card quotes is pinned here.

Two of these exist because the first version of the simulator produced results that described
the FIXTURE rather than the phenomenon, and both would have been published:

  * `test_fixture_values_must_differ_from_their_defaults` -- the record used currency="USD"
    and status="NEW", the declared defaults, so a rename that loses the field entirely
    returned the default, which equalled the real value, and measured SAFE.
  * `test_narrowing_a_large_value_is_silently_wrong` -- the oracle computed the expected value
    by coercing through the READER's type, so an int32 truncation was compared against itself
    and `narrow_type` measured SAFE on all three codecs with 0/1000 rows wrong.

An oracle that applies the transformation under test to its own expectation cannot fail, and
reports that inability as a pass.
"""
from __future__ import annotations

import unittest

from impl.changes import (CHANGES, add_optional, add_required_no_default,
                          insert_in_middle, narrow_type, remove_field, rename_field,
                          renumber_field, reorder_fields, reuse_retired_tag)
from impl.measure import (compatibility_matrix, data_dependent_changes, narrowing_loss,
                          read_modify_write, required_deploy_order, verdict_mix)
from impl.readers import (CSV_READERS, CsvHeaderCodec,  # noqa: E402
                          CsvPositionalCodec)
from impl.wire import (BASE, CODECS, INT32_MAX, NamedCodec, PositionalCodec, TaggedCodec,
                       coerce, roundtrip, sample_record)


class TestFixtureIsCapableOfFailing(unittest.TestCase):
    def test_fixture_values_must_differ_from_their_defaults(self):
        """The fixture bug that produced a false SAFE.

        If a record's value equals its field's default, then "read the field correctly" and
        "missed the field entirely and fell back" are indistinguishable. Every value must
        differ from its default or the whole matrix is untrustworthy.
        """
        rec = sample_record(7)
        for f in BASE.fields:
            if f.fid in rec:
                self.assertNotEqual(rec[f.fid], f.default,
                                    f"{f.name}: fixture value equals its default, so a lost "
                                    f"field would read as a correct one")

    def test_that_default_is_INDISTINGUISHABLE_from_a_legitimate_value(self):
        """REGRESSION for the third card defect a consumer found, and the gate could not.

        The test below asserts a writer-unknown field comes back as the reader's default, and calls
        that SAFE. It is the correct CODEC verdict. But it is also the exact state that harms an
        application: a record written before the field existed and a record whose true value simply
        equals the default decode IDENTICALLY, so no reader can separate them without explicit
        presence. add_optional is SAFE in all 6 cells AND delivers that state in 100% of
        pre-existing records.

        The card knew this about its own FIXTURE -- see sample_record's docstring -- and did not pass
        it to the reader until a consumer run surfaced it.
        """
        new = add_optional(BASE)
        fid = "f.channel"
        field = new.by_fid(fid)

        _, from_old_writer = roundtrip(BASE, new, NamedCodec, sample_record(1))
        self.assertEqual(from_old_writer[fid], field.default)

        legit = dict(sample_record(1), **{fid: field.default})
        _, from_new_writer = roundtrip(new, new, NamedCodec, legit)

        self.assertEqual(from_old_writer[fid], from_new_writer[fid],
                         "if these ever differ, the codec gained explicit presence and the "
                         "card's presence caveat can be relaxed")
        for i in range(50):
            _, got = roundtrip(BASE, new, NamedCodec, sample_record(i))
            self.assertEqual(got[fid], field.default, f"record {i}")

    def test_a_reader_only_field_must_come_back_as_its_default(self):
        """The invariant that catches the worst changes. Without it, retired-tag reuse and
        positional insertion both score SAFE, because the corrupted field is by construction
        absent from the writer's schema and so is never compared."""
        v, got = roundtrip(BASE, add_optional(BASE), NamedCodec, sample_record(1))
        self.assertEqual(v, "SAFE")
        self.assertEqual(got["f.channel"], "WEB")


class TestCodecIdentity(unittest.TestCase):
    """Each codec keys on something different. That is the card's whole thesis, so it is
    pinned directly rather than inferred from the matrix."""

    def test_named_keys_on_the_field_name(self):
        self.assertEqual(set(NamedCodec.encode(BASE, sample_record(1))),
                         {"order_id", "amount_cents", "currency", "status"})

    def test_tagged_keys_on_the_field_number(self):
        self.assertEqual(set(TaggedCodec.encode(BASE, sample_record(1))), {1, 2, 3, 4})

    def test_positional_keys_on_offset_and_carries_no_identity(self):
        wire = PositionalCodec.encode(BASE, sample_record(1))
        self.assertIsInstance(wire, tuple)
        self.assertEqual(len(wire), 4)


class TestTheMirrorPair(unittest.TestCase):
    """The sharpest result in the card: rename and renumber are exact mirror images.

    Each is completely safe on one codec and has no safe single-step deploy on the other. A
    planner told "renaming a field is safe" has been given advice with a 50% chance of being
    catastrophically wrong, and nothing in the schema diff says which half it is in.
    """

    def _both(self, change, codec):
        rec = sample_record(7)
        new = change(BASE)
        return (roundtrip(BASE, new, codec, rec)[0], roundtrip(new, BASE, codec, rec)[0])

    def test_rename_is_safe_on_tagged(self):
        self.assertEqual(self._both(rename_field, TaggedCodec), ("SAFE", "SAFE"))

    def test_rename_is_silently_wrong_on_named_in_both_directions(self):
        self.assertEqual(self._both(rename_field, NamedCodec),
                         ("SILENT_WRONG", "SILENT_WRONG"))

    def test_renumber_is_safe_on_named(self):
        self.assertEqual(self._both(renumber_field, NamedCodec), ("SAFE", "SAFE"))

    def test_renumber_is_silently_wrong_on_tagged_in_both_directions(self):
        self.assertEqual(self._both(renumber_field, TaggedCodec),
                         ("SILENT_WRONG", "SILENT_WRONG"))

    def test_the_two_are_exact_mirrors(self):
        """Stated as one assertion so the symmetry cannot drift apart silently."""
        order = required_deploy_order()
        self.assertEqual(order[("rename_field", "named")], "IMPOSSIBLE")
        self.assertEqual(order[("rename_field", "tagged")], "either")
        self.assertEqual(order[("renumber_field", "named")], "either")
        self.assertEqual(order[("renumber_field", "tagged")], "IMPOSSIBLE")


class TestPerChangeVerdicts(unittest.TestCase):
    def setUp(self):
        self.m = compatibility_matrix()

    def test_add_optional_is_the_only_universally_safe_structural_change(self):
        for codec in ("named", "tagged", "positional"):
            for d in ("forward", "backward"):
                self.assertEqual(self.m[("add_optional", codec, d)], "SAFE")

    def test_add_required_without_a_default_fails_loudly_forward_only(self):
        """The one change that behaves well: it raises. Old writers omit the field, the new
        reader demands it, and the decode stops. Loud, immediate, cannot reach a database."""
        for codec in ("named", "tagged", "positional"):
            self.assertEqual(self.m[("add_required_no_default", codec, "forward")],
                             "HARD_FAIL")
            self.assertEqual(self.m[("add_required_no_default", codec, "backward")], "SAFE")

    def test_reorder_breaks_positional_only(self):
        self.assertEqual(self.m[("reorder_fields", "positional", "forward")], "SILENT_WRONG")
        self.assertEqual(self.m[("reorder_fields", "named", "forward")], "SAFE")
        self.assertEqual(self.m[("reorder_fields", "tagged", "forward")], "SAFE")

    def test_reusing_a_retired_tag_corrupts_tagged_and_positional_but_not_named(self):
        """Two individually defensible commits -- remove a field, add a field -- that are
        catastrophic in composition. This is why protobuf has `reserved`."""
        self.assertEqual(self.m[("reuse_retired_tag", "tagged", "forward")], "SILENT_WRONG")
        self.assertEqual(self.m[("reuse_retired_tag", "positional", "forward")],
                         "SILENT_WRONG")
        self.assertEqual(self.m[("reuse_retired_tag", "named", "forward")], "SAFE")

    def test_inserting_in_the_middle_breaks_positional_only(self):
        self.assertEqual(self.m[("insert_in_middle", "positional", "forward")],
                         "SILENT_WRONG")
        self.assertEqual(self.m[("insert_in_middle", "named", "forward")], "SAFE")

    def test_removing_a_field_is_safe_in_a_single_hop_on_every_codec(self):
        """And this is exactly why removal is dangerous: the single-hop measurement is clean,
        so the damage does not show up here at all -- it shows up in read_modify_write."""
        for codec in ("named", "tagged", "positional"):
            self.assertEqual(self.m[("remove_field", codec, "forward")], "SAFE")

    def test_that_safe_removal_result_is_TERMINAL_ONLY_on_a_positional_codec(self):
        """REGRESSION for a card defect a naive consumer found, and the gate could not.

        The test above is true and its scope is invisible: `changes.remove_field` drops `f.status`,
        which is the LAST field of BASE, so the positional cell is only ever exercised where no
        subsequent column shifts. S2.measured then generalised "remove_field also measures SAFE in a
        single hop" across all three codecs.

        Asked to plan two removals, a consumer refused to reuse that cell -- "removing a middle
        column shifts every field after it, and each one decodes as a plausible value of the wrong
        column with no error" -- and it was right. A non-terminal removal is SILENT_WRONG in BOTH
        directions on positional, which is IMPOSSIBLE in this card's vocabulary: no deploy ordering
        exists. Keyed codecs are unaffected, because nothing about them depends on position.

        The gate could not catch this: every claim resolved to a real measured result. The fixture
        simply never varied the axis the claim generalised over.
        """
        mid = BASE.with_fields(
            tuple(f for f in BASE.fields if f.fid != "f.amount_cents"), "v2-remove-mid")
        rec = sample_record(1)
        self.assertEqual([f.fid for f in BASE.fields].index("f.amount_cents"), 1,
                         "the dropped field must be non-terminal or this test proves nothing")
        self.assertEqual(BASE.fields[-1].fid, "f.status",
                         "the card's own remove_field is terminal -- that is the whole point")

        for codec in CODECS:
            fwd, _ = roundtrip(BASE, mid, codec, rec)
            bwd, _ = roundtrip(mid, BASE, codec, rec)
            if codec.name == "positional":
                self.assertEqual((fwd, bwd), ("SILENT_WRONG", "SILENT_WRONG"),
                                 "both directions wrong == IMPOSSIBLE, no ordering exists")
            else:
                self.assertEqual((fwd, bwd), ("SAFE", "SAFE"), f"{codec.name} is position-blind")


class TestTheCodecIsAPropertyOfTheReader(unittest.TestCase):
    """C8/A8 — added because a consumer refused the card's framing, and was right.

    The card named its three codecs as though they were properties of wire FORMATS. A CSV with a
    header row is name-keyed or positional according to how it is PARSED, so one export has as many
    compatibility verdicts as it has kinds of consumer.
    """

    def test_both_readers_receive_byte_identical_wire(self):
        """The premise. If the bytes differ, the experiment cannot separate reader from format."""
        rec = sample_record(1)
        wires = {c.encode(BASE, rec) for c in CSV_READERS}
        self.assertEqual(len(wires), 1, "the two readers must share one encoder")
        self.assertEqual(wires.pop(),
                         "order_id,amount_cents,currency,status\nord-00001,1001,EUR,PAID\n")

    def test_reorder_and_rename_are_exact_mirrors_across_the_two_readers(self):
        """The result, stated as one assertion so the symmetry cannot drift apart silently.

        Reordering destroys offsets while preserving names; renaming does the reverse. So two readers
        keying on those two things must disagree on exactly those two changes -- 'either' vs
        IMPOSSIBLE, and inverted. This is C2's mirror appearing WITHIN one file format, which is what
        makes it a fact about readers rather than about formats.
        """
        rec = sample_record(1)
        hdr, pos = CsvHeaderCodec, CsvPositionalCodec

        def both(change, codec):
            new = change(BASE)
            return (roundtrip(BASE, new, codec, rec)[0], roundtrip(new, BASE, codec, rec)[0])

        self.assertEqual(both(reorder_fields, hdr), ("SAFE", "SAFE"))
        self.assertEqual(both(reorder_fields, pos), ("SILENT_WRONG", "SILENT_WRONG"))
        self.assertEqual(both(rename_field, pos), ("SAFE", "SAFE"))
        self.assertEqual(both(rename_field, hdr), ("SILENT_WRONG", "SILENT_WRONG"))

    def test_the_header_is_present_in_the_bytes_even_when_it_does_not_protect_you(self):
        """The trap A8 names: reviewers approve a reorder because 'the file has a header'."""
        rec = sample_record(1)
        wire = CsvPositionalCodec.encode(BASE, rec)
        self.assertIn("order_id,amount_cents,currency,status", wire)
        v, _ = roundtrip(BASE, reorder_fields(BASE), CsvPositionalCodec, rec)
        self.assertEqual(v, "SILENT_WRONG", "the header is right there and does not help")


class TestVerdictMix(unittest.TestCase):
    def test_the_matrix_covers_every_cell(self):
        self.assertEqual(len(compatibility_matrix()), len(CHANGES) * 3 * 2)
        self.assertEqual(len(compatibility_matrix()), 54)

    def test_four_in_five_broken_cells_fail_SILENTLY(self):
        """The number the card is built on. Loud failures are a solved problem; these are not.
        12 of 15 broken cells decode successfully into a wrong value."""
        mix = verdict_mix()
        self.assertEqual(mix["total"], 54)
        self.assertEqual(mix["SAFE"], 39)
        self.assertEqual(mix["HARD_FAIL"], 3)
        self.assertEqual(mix["SILENT_WRONG"], 12)
        self.assertEqual(mix["silent_share_of_broken"], 0.8)


class TestDeployOrder(unittest.TestCase):
    def test_order_is_derived_from_the_two_directions(self):
        order = required_deploy_order()
        counts = {}
        for v in order.values():
            counts[v] = counts.get(v, 0) + 1
        self.assertEqual(counts, {"either": 18, "writers": 3, "IMPOSSIBLE": 6})

    def test_five_changes_have_no_safe_single_step_deploy_on_some_codec(self):
        """`IMPOSSIBLE` is not "be careful with ordering" -- it means no ordering exists, and
        the change must be decomposed into several deploys. That is Shape A's whole reason."""
        order = required_deploy_order()
        imp = sorted({c for (c, _), v in order.items() if v == "IMPOSSIBLE"})
        self.assertEqual(imp, ["insert_in_middle", "rename_field", "renumber_field",
                               "reorder_fields", "reuse_retired_tag"])

    def test_no_change_ever_requires_readers_last(self):
        """Measured, not assumed: `writers` appears and `readers` never does, because a reader
        that does not understand a field can ignore it, while a writer that omits a required
        one cannot be tolerated. The asymmetry is a property of who can default."""
        order = required_deploy_order()
        self.assertNotIn("readers", set(order.values()))


class TestReadModifyWrite(unittest.TestCase):
    """The case that defeats the standard mental model, and the reason "unknown fields are
    ignored" is not a compatibility story."""

    def test_loss_without_retention_is_CODEC_DEPENDENT_not_universal(self):
        """CORRECTED. This previously asserted total loss for ALL THREE codecs, including
        tagged -- which is the retracted C4, encoded as a test and passing.

        Real protobuf retains unknown tags automatically, so a tag-keyed codec loses NOTHING
        even with no application-level retention. Verified against google.protobuf by
        test_tagged_retention_matches_real_protobuf below.
        """
        for codec in (NamedCodec, PositionalCodec):
            r = read_modify_write(codec, n=1000, preserve_unknown=False)
            self.assertEqual(r["lost"], 1000, f"{codec.name}: expected total loss")
            self.assertEqual(r["loss_rate"], 1.0)

        r = read_modify_write(TaggedCodec, n=1000, preserve_unknown=False)
        self.assertEqual(r["lost"], 0,
                         "a tag-keyed codec retains unknown tags WITHOUT application help; "
                         "asserting total loss here was the retracted C4")

    def test_tagged_retention_matches_real_protobuf(self):
        """PC-0004's reality check, matching the pattern now used in PC-0001 and PC-0002.

        The model in impl/wire.py is hand-written. Nothing in impl/ or tests/ imported a real
        codec, so a model that had protobuf's most consequential property BACKWARDS passed
        every test. Skipped rather than silently passed when protobuf is unavailable.
        """
        try:
            from google.protobuf import (descriptor_pb2, descriptor_pool,
                                         message_factory)
        except ImportError:
            self.skipTest("google.protobuf not installed; cannot cross-check the model")

        def build(pkg, fields):
            fdp = descriptor_pb2.FileDescriptorProto()
            fdp.name, fdp.package = f"{pkg}.proto", pkg
            msg = fdp.message_type.add()
            msg.name = "M"
            for nm, num in fields:
                f = msg.field.add()
                f.name, f.number = nm, num
                f.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
                f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
            pool = descriptor_pool.DescriptorPool()
            pool.Add(fdp)
            return message_factory.GetMessageClass(
                pool.FindMessageTypeByName(f"{pkg}.M"))

        Wide = build("wide", [("order_id", 1), ("amount", 2), ("channel", 9)])
        Narrow = build("narrow", [("order_id", 1), ("amount", 2)])

        wide = Wide(order_id="o1", amount="500", channel="MOBILE")
        narrow = Narrow()
        narrow.ParseFromString(wide.SerializeToString())   # reader does not know tag 9
        narrow.amount = "600"                              # the ordinary business edit
        round_tripped = Wide()
        round_tripped.ParseFromString(narrow.SerializeToString())

        self.assertEqual(round_tripped.channel, "MOBILE",
                         "real protobuf MUST preserve the unknown field; if this ever fails "
                         "the correction to C4 needs revisiting")
        self.assertEqual(round_tripped.amount, "600", "the edit must survive too")

        # and the model must now agree with reality on the same scenario
        r = read_modify_write(TaggedCodec, n=50, preserve_unknown=False)
        self.assertEqual(r["lost"], 0, "model and real protobuf must agree")

    def test_the_read_itself_never_fails(self):
        """100% data loss with a 0% error rate. Nothing to alarm on, nothing in a log."""
        r = read_modify_write(NamedCodec, n=100, preserve_unknown=False)
        self.assertEqual(r["lost"], 100)

    def test_unknown_field_retention_eliminates_the_loss_on_keyed_codecs(self):
        for codec in (NamedCodec, TaggedCodec):
            r = read_modify_write(codec, n=1000, preserve_unknown=True)
            self.assertEqual(r["lost"], 0, f"{codec.name}: retention must be sufficient")

    def test_a_positional_codec_cannot_retain_unknowns_even_in_principle(self):
        """Not an unimplemented feature. An unknown field in a positional format has no
        identity to carry -- only an offset the old schema does not possess."""
        r = read_modify_write(PositionalCodec, n=100, preserve_unknown=True)
        self.assertEqual(r["retention"], "STRUCTURALLY IMPOSSIBLE")
        self.assertEqual(r["loss_rate"], 1.0)


class TestNarrowing(unittest.TestCase):
    def test_narrowing_a_large_value_is_silently_wrong(self):
        """The oracle bug that produced a false SAFE. If the expected value is computed by
        coercing through the reader's own type, the truncation is compared against itself."""
        rec = dict(sample_record(1), **{"f.amount_cents": 3_000_000_000})
        v, got = roundtrip(BASE, narrow_type(BASE), NamedCodec, rec)
        self.assertEqual(v, "SILENT_WRONG")
        self.assertNotEqual(got["f.amount_cents"], 3_000_000_000)

    def test_a_minority_of_rows_is_corrupted_and_nothing_raises(self):
        nl = narrowing_loss(n=1000, big_from=900)
        self.assertEqual(nl["rows_over_int32"], 100)
        self.assertEqual(nl["silently_wrong"], 100)
        self.assertEqual(nl["raised"], 0)

    def test_int32_coercion_wraps_rather_than_raising(self):
        self.assertEqual(coerce(INT32_MAX, "int32"), INT32_MAX)
        self.assertNotEqual(coerce(INT32_MAX + 1, "int32"), INT32_MAX + 1)
        self.assertEqual(coerce(INT32_MAX + 1, "int32"), -(INT32_MAX + 1))

    def test_narrowing_is_the_only_change_whose_verdict_depends_on_the_DATA(self):
        """The finding that indicts the standard control. A schema-registry compatibility
        check sees two schemas and no values, so this class is invisible to it by
        construction -- not through poor implementation, but through missing input."""
        flipped = data_dependent_changes()
        self.assertEqual(len(flipped), 3)
        self.assertEqual({c for c, _ in flipped}, {"narrow_type"})
        for verdicts in flipped.values():
            self.assertEqual(verdicts, ("SAFE", "SILENT_WRONG"))


class TestChangesAreHonestAboutThemselves(unittest.TestCase):
    def test_every_change_is_a_pure_function_of_the_base_schema(self):
        """A change that mutated BASE would make every later row in the matrix measure a
        different starting point, and the table would still print."""
        before = BASE.fields
        for _, fn in CHANGES:
            fn(BASE)
        self.assertEqual(BASE.fields, before)

    def test_all_nine_changes_are_exercised(self):
        self.assertEqual(len(CHANGES), 9)
        self.assertEqual(len({n for n, _ in CHANGES}), 9)


if __name__ == "__main__":
    unittest.main()
