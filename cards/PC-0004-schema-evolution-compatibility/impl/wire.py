"""Wire formats and their field-identity rules.

The whole card turns on one distinction:

    LOGICAL identity  -- which field this *is* (`fid`), known to the humans and to no codec
    WIRE identity     -- how the codec finds it: by name, by tag number, or by position

Compatibility is not a property of a change. It is a property of a change *against a
codec*, because each codec keys on something different, and a change that leaves the wire
identity intact is safe while the identical change to a different codec is silent
corruption. `fid` never appears on the wire; it exists so the measurement can know what
SHOULD have matched and therefore detect the cases where nothing raised and the value is
simply wrong.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

INT32_MIN, INT32_MAX = -(2 ** 31), 2 ** 31 - 1


class WireError(Exception):
    """A decode that failed loudly. The GOOD failure -- it cannot be mistaken for data."""


@dataclass(frozen=True)
class Field:
    fid: str          # logical identity: ground truth, never serialised
    name: str         # wire identity for NamedCodec
    tag: int          # wire identity for TaggedCodec
    type: str         # "int64" | "int32" | "str" | "bool"
    required: bool = False
    default: Any = None


@dataclass(frozen=True)
class Schema:
    version: str
    fields: tuple[Field, ...]

    def by_fid(self, fid: str) -> Field | None:
        return next((f for f in self.fields if f.fid == fid), None)

    def fids(self) -> set[str]:
        return {f.fid for f in self.fields}

    def with_fields(self, fields, version: str | None = None) -> "Schema":
        return Schema(version or self.version + "'", tuple(fields))


def coerce(value: Any, typ: str) -> Any:
    """Apply the reader's declared type to a value off the wire.

    `int32` wraps rather than raising, which is what a narrowing cast does in C, Java and
    protobuf alike. That is the entire hazard: narrowing is not a decode error, it is a
    decode SUCCESS carrying a different number.
    """
    if value is None:
        return None
    if typ == "int32" and isinstance(value, int) and not isinstance(value, bool):
        if INT32_MIN <= value <= INT32_MAX:
            return value
        return ((value - INT32_MIN) % 2 ** 32) + INT32_MIN
    if typ == "int64" and isinstance(value, bool):
        return int(value)
    if typ == "str" and not isinstance(value, str):
        return str(value)
    return value


def _read_one(field: Field, present: bool, raw: Any) -> Any:
    if not present:
        if field.required and field.default is None:
            raise WireError(
                f"required field {field.name!r} absent from the wire and has no default")
        return field.default
    return coerce(raw, field.type)


class NamedCodec:
    """Field name is the wire identity. JSON, YAML, most REST bodies.

    Unknown keys are dropped on read -- the property usually described as "tolerant". It is
    tolerant of *arrival* and destructive on *departure*: see measure.read_modify_write.
    """

    name = "named"
    keys_on = "field name"

    @staticmethod
    def encode(schema: Schema, record: dict) -> dict:
        return {f.name: record.get(f.fid) for f in schema.fields}

    @staticmethod
    def decode(schema: Schema, wire: dict) -> dict:
        return {f.fid: _read_one(f, f.name in wire, wire.get(f.name))
                for f in schema.fields}


class TaggedCodec:
    """Field NUMBER is the wire identity. Protobuf, Thrift, Avro-with-aliases.

    Renaming is free. Renumbering, and reusing a retired number, are catastrophic -- and
    both look like harmless edits in the schema file.
    """

    name = "tagged"
    keys_on = "field number"

    # CORRECTED. decode() previously iterated schema.fields ONLY, so any wire tag the
    # reader did not know was DROPPED. That is the behaviour the card's C4 asserted and
    # which real protobuf DOES NOT HAVE: verified with google.protobuf, a reader ignorant
    # of a field parsed, re-serialised, and the field SURVIVED. Retaining unknowns is the
    # single most consequential property of a tag-keyed codec, and the model had it
    # backwards. See fleet_grounding.codec_matrix in card.json.
    UNKNOWN = "_unknown_tags"

    @staticmethod
    def encode(schema: Schema, record: dict) -> dict:
        out = {f.tag: record.get(f.fid) for f in schema.fields}
        out.update(record.get(TaggedCodec.UNKNOWN, {}))     # re-emit what we could not read
        return out

    @staticmethod
    def decode(schema: Schema, wire: dict) -> dict:
        known = {f.tag for f in schema.fields}
        rec = {f.fid: _read_one(f, f.tag in wire, wire.get(f.tag)) for f in schema.fields}
        retained = {t: v for t, v in wire.items() if t not in known}
        if retained:
            rec[TaggedCodec.UNKNOWN] = retained
        return rec


class PositionalCodec:
    """Ordinal position is the wire identity. CSV rows, packed structs, tuple encodings.

    Nothing about a field is on the wire except its offset, so every structural edit is a
    reinterpretation of every field after it. There is no tolerance to be had: a positional
    format cannot skip what it does not know, because it does not know anything.
    """

    name = "positional"
    keys_on = "ordinal position"

    @staticmethod
    def encode(schema: Schema, record: dict) -> tuple:
        return tuple(record.get(f.fid) for f in schema.fields)

    @staticmethod
    def decode(schema: Schema, wire: tuple) -> dict:
        return {f.fid: _read_one(f, i < len(wire), wire[i] if i < len(wire) else None)
                for i, f in enumerate(schema.fields)}


CODECS = (NamedCodec, TaggedCodec, PositionalCodec)


# --- the schema every measurement starts from ---------------------------------------
BASE = Schema("v1", (
    Field("f.order_id", "order_id", 1, "str", required=True, default=""),
    Field("f.amount_cents", "amount_cents", 2, "int64", required=True, default=0),
    Field("f.currency", "currency", 3, "str", default="USD"),
    Field("f.status", "status", 4, "str", default="NEW"),
))


def sample_record(i: int) -> dict:
    """A record whose every value DIFFERS from its field's default.

    That is a correctness requirement of the fixture, not a stylistic choice. The first
    version used currency="USD" and status="NEW", which are exactly the declared defaults --
    so when a rename made the reader miss the field and fall back to its default, the fallback
    coincidentally equalled the real value and `rename_field` on a name-keyed codec measured
    as SAFE. It is not safe; it loses the field entirely. A fixture whose values equal its
    defaults cannot distinguish "read correctly" from "read nothing at all".
    """
    return {
        "f.order_id": f"ord-{i:05d}",
        "f.amount_cents": 1_000 + i,
        "f.currency": "EUR",      # default is "USD" -- must differ
        "f.status": "PAID",       # default is "NEW" -- must differ
    }


def roundtrip(writer: Schema, reader: Schema, codec, record: dict) -> tuple[str, dict]:
    """Write with one schema, read with another. Returns (verdict, decoded).

    Verdicts, and the ordering matters more than the names:

      SAFE          every field present in BOTH schemas survived intact
      HARD_FAIL     the decode raised -- loud, immediate, cannot reach a database
      SILENT_WRONG  the decode SUCCEEDED and a shared field now holds a different value

    SILENT_WRONG is the worst outcome and the only one no monitoring will show you, which
    is why it is a separate verdict rather than being folded into "incompatible".
    """
    wire = codec.encode(writer, record)
    try:
        got = codec.decode(reader, wire)
    except WireError as e:
        return "HARD_FAIL", {"error": str(e)}
    shared = writer.fids() & reader.fids()
    for fid in sorted(shared):
        # Compare against the ORIGINAL logical value, never one re-coerced through the
        # reader's own type. The first version computed `coerce(record[fid], reader.type)`,
        # putting the narrowing into the expectation as well as the result -- so an int32
        # truncation compared equal to itself and `narrow_type` measured SAFE on all three
        # codecs with 0/1000 rows wrong. An oracle that applies the transformation under test
        # to its own expected value cannot fail, and reports that inability as a pass.
        if got.get(fid) != record.get(fid):
            return "SILENT_WRONG", got
    # The invariant that is easy to forget, and the one that catches the worst changes: a
    # field the WRITER never knew about must come back as the reader's default. If it comes
    # back holding anything else, the reader has populated it from some other field's bytes.
    # Checking only shared fields would score retired-tag reuse and positional insertion as
    # SAFE -- both scored SAFE until this loop existed, because the corrupted field is by
    # construction not in the writer's schema and so was never compared.
    for fid in sorted(reader.fids() - writer.fids()):
        rf = reader.by_fid(fid)
        if got.get(fid) != rf.default:
            return "SILENT_WRONG", got
    return "SAFE", got


__all__ = ["Field", "Schema", "WireError", "NamedCodec", "TaggedCodec",
           "PositionalCodec", "CODECS", "BASE", "coerce", "roundtrip",
           "sample_record", "replace", "INT32_MAX", "INT32_MIN"]
