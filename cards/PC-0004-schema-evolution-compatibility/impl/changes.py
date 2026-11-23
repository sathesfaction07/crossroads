"""The nine schema changes, each as a pure function `Schema -> Schema`.

These are deliberately the changes that look routine in a review. Every one of them is a
one-line edit to a schema file, and a reviewer approving the diff sees the same shape of
change in all nine cases. Which of them corrupt data is not visible in the diff -- it is a
property of the codec, and the codec is not in the diff either.
"""
from __future__ import annotations

from .wire import BASE, Field, Schema, replace


def _max_tag(s: Schema) -> int:
    return max(f.tag for f in s.fields)


def add_optional(s: Schema = BASE) -> Schema:
    """Append a new optional field with a default. The textbook-safe change."""
    return s.with_fields(s.fields + (
        Field("f.channel", "channel", _max_tag(s) + 1, "str", default="WEB"),), "v2-add-opt")


def add_required_no_default(s: Schema = BASE) -> Schema:
    """Append a REQUIRED field with no default -- the classic "just make it mandatory"."""
    return s.with_fields(s.fields + (
        Field("f.tenant", "tenant", _max_tag(s) + 1, "str", required=True),), "v2-add-req")


def remove_field(s: Schema = BASE) -> Schema:
    """Drop `status`. Safe going one way, and the setup for the retired-tag disaster."""
    return s.with_fields(tuple(f for f in s.fields if f.fid != "f.status"), "v2-remove")


def rename_field(s: Schema = BASE) -> Schema:
    """`currency` -> `currency_code`. Same logical field, new wire NAME."""
    return s.with_fields(
        tuple(replace(f, name="currency_code") if f.fid == "f.currency" else f
              for f in s.fields), "v2-rename")


def renumber_field(s: Schema = BASE) -> Schema:
    """`currency` keeps its name, gets tag 9. Same logical field, new wire NUMBER."""
    return s.with_fields(
        tuple(replace(f, tag=9) if f.fid == "f.currency" else f for f in s.fields),
        "v2-renumber")


def reorder_fields(s: Schema = BASE) -> Schema:
    """Alphabetise the field list. A tidy-up commit; changes no name, no tag, no type."""
    return s.with_fields(tuple(sorted(s.fields, key=lambda f: f.name)), "v2-reorder")


def narrow_type(s: Schema = BASE) -> Schema:
    """`amount_cents` int64 -> int32. "Nobody has orders that big.\""""
    return s.with_fields(
        tuple(replace(f, type="int32") if f.fid == "f.amount_cents" else f
              for f in s.fields), "v2-narrow")


def reuse_retired_tag(s: Schema = BASE) -> Schema:
    """Remove `status` (tag 4), then give tag 4 to a brand-new field of another type.

    Two commits that are each defensible and are catastrophic in composition -- which is why
    protobuf has a `reserved` keyword and why leaving it out is not a style preference.
    """
    kept = tuple(f for f in s.fields if f.fid != "f.status")
    return s.with_fields(
        kept + (Field("f.shipment_id", "shipment_id", 4, "int64", default=0),),
        "v2-reuse-tag")


def insert_in_middle(s: Schema = BASE) -> Schema:
    """Put the new field where it reads best, second, rather than at the end."""
    new = Field("f.channel", "channel", _max_tag(s) + 1, "str", default="WEB")
    return s.with_fields(s.fields[:1] + (new,) + s.fields[1:], "v2-insert-mid")


CHANGES = (
    ("add_optional", add_optional),
    ("add_required_no_default", add_required_no_default),
    ("remove_field", remove_field),
    ("rename_field", rename_field),
    ("renumber_field", renumber_field),
    ("reorder_fields", reorder_fields),
    ("narrow_type", narrow_type),
    ("reuse_retired_tag", reuse_retired_tag),
    ("insert_in_middle", insert_in_middle),
)

__all__ = ["CHANGES"] + [n for n, _ in CHANGES]
