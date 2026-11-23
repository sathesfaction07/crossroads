"""Sub-problem 5 — THE CODEC IS A PROPERTY OF THE READER, NOT OF THE FILE.

C1 says compatibility is a property of a change against a codec. It does not say where the codec
comes from, and this card's three codecs are named as though they were properties of wire FORMATS:
"named" (JSON), "tagged" (protobuf), "positional" (CSV). For a self-describing text format that is
FALSE, and the falsehood is load-bearing rather than pedantic.

A CSV with a header row is name-keyed or positional according to how it is PARSED:

    csv.DictReader / pandas.read_csv / a header-aware Spark reader   -> name-keyed
    csv.reader / line.split(",") / awk '{print $3}'                  -> positional
    a warehouse COPY / LOAD DATA / external-table definition          -> positional by DEFAULT

So one exported file can be simultaneously safe for one consumer and silently corrupting for
another, from a single change, with no way to tell from the file. The two codecs below produce
BYTE-IDENTICAL wire and differ only in `decode`, which is the whole demonstration: hold the bytes and
the change fixed, vary only the reader, and the verdict flips.

This module exists because a naive consumer said it, unprompted, while being asked to plan an
"alphabetise the CSV columns" change:

    "The codec question has a surprising answer: it depends on the reader, not the file ... Warehouse
     bulk loaders are positional by default, and a reconciliation job is exactly the kind of thing
     that loads via COPY. Go read the reader. Do not assume the header saves you."

The card had no way to express that. Its verdict for a CSV was a single cell.

Stdlib only, and the verdict logic is the already-tested `roundtrip` -- these are codecs plugged into
it, not a second oracle.
"""
from __future__ import annotations

from typing import Any

from .wire import Field, Schema, _read_one


def _parse(raw: Any, field: Field) -> Any:
    """Cast a CSV cell using the READER's declared type, as any real CSV reader does.

    Everything in a CSV is text, so without this step every integer field would compare unequal to
    its own value and the whole matrix would read SILENT_WRONG for trivial reasons. A cell that
    cannot be parsed as the declared type is passed through unchanged rather than raising, which is
    what makes a positional mismatch SILENT instead of loud: reading "EUR" into an int64 column
    yields "EUR", not an exception.
    """
    if raw is None or raw == "":
        return None
    if field.type in ("int32", "int64"):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return raw
    return raw


def _emit(schema: Schema, record: dict) -> str:
    """The shared writer. Both codecs below emit exactly this, header included."""
    head = ",".join(f.name for f in schema.fields)
    row = ",".join("" if record.get(f.fid) is None else str(record.get(f.fid))
                   for f in schema.fields)
    return f"{head}\n{row}\n"


def _split(wire: str) -> tuple[list[str], list[str]]:
    lines = [ln for ln in wire.strip().split("\n") if ln != ""]
    return lines[0].split(","), (lines[1].split(",") if len(lines) > 1 else [])


class CsvHeaderCodec:
    """A CSV read by HEADER NAME -- csv.DictReader, pandas.read_csv, header-aware Spark.

    Name-keyed. Reordering columns is free. Renaming one loses the field silently, because the
    reader looks for a name that is no longer in the header and falls back to its default.
    """

    name = "csv-by-header"
    keys_on = "the header row, i.e. field NAME"

    @staticmethod
    def encode(schema: Schema, record: dict) -> str:
        return _emit(schema, record)

    @staticmethod
    def decode(schema: Schema, wire: str) -> dict:
        head, vals = _split(wire)
        by_name = dict(zip(head, vals))
        return {f.fid: _read_one(f, f.name in by_name, _parse(by_name.get(f.name), f))
                for f in schema.fields}


class CsvPositionalCodec:
    """The SAME BYTES read by COLUMN OFFSET -- csv.reader, split(','), awk, a warehouse COPY.

    Positional. The header is decoration: it is consumed and discarded. Reordering columns is
    silently wrong in both directions; renaming one is completely free, because the name was never
    used. Exactly inverted from the codec above, on identical input.
    """

    name = "csv-by-position"
    keys_on = "column offset; the header row is decoration"

    @staticmethod
    def encode(schema: Schema, record: dict) -> str:
        return _emit(schema, record)

    @staticmethod
    def decode(schema: Schema, wire: str) -> dict:
        _, vals = _split(wire)
        return {f.fid: _read_one(f, i < len(vals),
                                 _parse(vals[i] if i < len(vals) else None, f))
                for i, f in enumerate(schema.fields)}


CSV_READERS = (CsvHeaderCodec, CsvPositionalCodec)

# Which real tools land you in which column. Not measured -- this is a mapping from the two decode
# behaviours above onto the APIs people actually call, and it is the part a reader needs in order to
# answer "which one am I?" without reading this module.
READER_TAXONOMY = {
    "csv-by-header": ("csv.DictReader", "pandas.read_csv", "Spark with header=true",
                      "any reader given an explicit column->name mapping"),
    "csv-by-position": ("csv.reader", "line.split(',')", "awk $N", "cut -fN",
                        "warehouse COPY / LOAD DATA (positional by default)",
                        "an external-table DDL that declares columns in order"),
}

__all__ = ["CsvHeaderCodec", "CsvPositionalCodec", "CSV_READERS", "READER_TAXONOMY"]
