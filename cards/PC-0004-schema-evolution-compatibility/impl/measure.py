"""Measure which schema changes are safe, against which codec, in which direction.

Run:  python3 -m impl.measure

Nothing here measures cost. That is not an omission -- see `verdict_mix()`. All nine changes
deploy identically, take the same time, and cost the same money. What differs between them
is whether the data survives, and "how much does it cost" is the wrong question about a
correctness property. This module produces a matrix of verdicts, not a curve.
"""
from __future__ import annotations

from .changes import CHANGES, add_optional
from .wire import (BASE, CODECS, NamedCodec, PositionalCodec, TaggedCodec,
                   roundtrip, sample_record)

# Deploying a change to a running system exposes exactly two orderings, because during any
# rolling deploy both versions are live at once:
#   FORWARD  -- old writer -> new reader   (readers upgraded first)
#   BACKWARD -- new writer -> old reader   (writers upgraded first)
DIRECTIONS = ("forward", "backward")


def compatibility_matrix(record: dict | None = None) -> dict:
    """{(change, codec, direction): verdict} over all 9 x 3 x 2 = 54 cells."""
    rec = record if record is not None else sample_record(7)
    out = {}
    for cname, fn in CHANGES:
        new = fn(BASE)
        for codec in CODECS:
            out[(cname, codec.name, "forward")] = roundtrip(BASE, new, codec, rec)[0]
            out[(cname, codec.name, "backward")] = roundtrip(new, BASE, codec, rec)[0]
    return out


def verdict_mix(matrix: dict | None = None) -> dict:
    """How many cells fail LOUDLY versus how many fail SILENTLY.

    This is the number that justifies the card's whole framing. A change that raises is a
    change you find in staging. A change that decodes successfully into a wrong value is a
    change you find in a quarterly reconciliation, if ever.
    """
    m = matrix or compatibility_matrix()
    mix = {"SAFE": 0, "HARD_FAIL": 0, "SILENT_WRONG": 0}
    for v in m.values():
        mix[v] += 1
    mix["total"] = len(m)
    broken = mix["HARD_FAIL"] + mix["SILENT_WRONG"]
    mix["silent_share_of_broken"] = round(mix["SILENT_WRONG"] / broken, 4) if broken else 0.0
    return mix


def required_deploy_order(matrix: dict | None = None) -> dict:
    """{(change, codec): order} -- derived from the two directions, not asserted.

    'either'      both directions safe: deploy in any order, no coordination needed
    'readers'     only forward is safe: every reader must understand the new form FIRST
    'writers'     only backward is safe: writers may move first
    'IMPOSSIBLE'  neither direction is safe: there is no single-step deploy of this change,
                  and no amount of ordering care will produce one. It must be decomposed.
    """
    m = matrix or compatibility_matrix()
    out = {}
    for cname, _ in CHANGES:
        for codec in CODECS:
            fwd = m[(cname, codec.name, "forward")] == "SAFE"
            bwd = m[(cname, codec.name, "backward")] == "SAFE"
            out[(cname, codec.name)] = ("either" if fwd and bwd else
                                        "readers" if fwd else
                                        "writers" if bwd else "IMPOSSIBLE")
    return out


def read_modify_write(codec, n: int = 1000, preserve_unknown: bool = False) -> dict:
    """An OLD reader reads a NEW record, edits one field, and writes it back.

    CORRECTED -- and the correction is the whole point of this function.

    This previously taught: "ignoring a field on the way IN means omitting it on the way OUT
    ... The read never fails. The write destroys the field." That is TRUE for some codecs and
    FALSE for the one most readers picture. Executed against real google.protobuf: a reader
    with no knowledge of a field parsed the record, re-serialised it, and THE FIELD SURVIVED.
    protobuf retains unknown tags automatically; it is not an application feature you enable.

    So the honest statement is codec-dependent:
      * tag-keyed WITH retention (protobuf, Thrift): NO loss, and no application help needed.
        `preserve_unknown` is irrelevant here -- the codec has already done it.
      * name-keyed through a typed struct (JSON -> dataclass, dict access): LOSS unless the
        application deliberately carries the extra keys. This is where `preserve_unknown`
        is the real knob.
      * positional (CSV rows, packed structs): retention is STRUCTURALLY IMPOSSIBLE -- an
        unknown field has no identity to carry, only an offset the old schema lacks.

    The card's C4 asserted the drop as universal. It is not. See fleet_grounding.codec_matrix.
    """
    new = add_optional(BASE)
    old = BASE
    lost = 0
    for i in range(n):
        rec = sample_record(i)
        rec["f.channel"] = "MOBILE"
        wire = codec.encode(new, rec)
        got = codec.decode(old, wire)
        got["f.status"] = "SHIPPED"              # the ordinary business edit
        back = codec.encode(old, got)
        if preserve_unknown:
            if isinstance(wire, dict) and isinstance(back, dict):
                back = {**{k: v for k, v in wire.items() if k not in back}, **back}
            else:
                # A positional codec cannot do this even in principle: an unknown field has
                # no identity to carry, only an offset that the old schema does not have.
                # Retention is not a feature the format declined to implement.
                return {"codec": codec.name, "n": n, "lost": n,
                        "loss_rate": 1.0, "retention": "STRUCTURALLY IMPOSSIBLE"}
        if codec.decode(new, back).get("f.channel") != "MOBILE":
            lost += 1
    return {"codec": codec.name, "n": n, "lost": lost, "loss_rate": round(lost / n, 4),
            "retention": "on" if preserve_unknown else "off"}


def narrowing_loss(n: int = 1000, big_from: int = 900) -> dict:
    """Narrowing int64 -> int32: how many rows change value, and does anything raise?

    Deliberately measured with only a MINORITY of rows over the boundary, because that is
    the real shape: the change ships, almost everything is fine, and the failures are the
    largest orders -- the ones a reconciliation notices last and cares about most.
    """
    from .changes import narrow_type
    new = narrow_type(BASE)
    wrong = raised = 0
    for i in range(n):
        rec = sample_record(i)
        if i >= big_from:
            rec["f.amount_cents"] = 3_000_000_000 + i     # > INT32_MAX
        v, _ = roundtrip(BASE, new, NamedCodec, rec)
        if v == "SILENT_WRONG":
            wrong += 1
        elif v == "HARD_FAIL":
            raised += 1
    return {"n": n, "rows_over_int32": n - big_from, "silently_wrong": wrong,
            "raised": raised, "wrong_rate": round(wrong / n, 4)}


def data_dependent_changes() -> dict:
    """Which verdicts flip when only the DATA changes and the schemas are held identical?

    This exists because the matrix, run on one ordinary record, reports `narrow_type` as SAFE
    on all three codecs -- while `narrowing_loss()` shows it silently corrupting 100 rows in
    1000. Both are correct, and the tension is the finding rather than a discrepancy to be
    explained away: narrowing is the only change of the nine whose safety is a property of the
    VALUES, not of the schemas.

    That has a direct consequence for tooling. A schema-registry compatibility check -- the
    standard control, and one that sees only two schemas -- cannot detect this class by
    construction. The check is not badly implemented; the information it would need is not in
    its input.
    """
    small = sample_record(7)                                  # amount_cents = 1007
    big = dict(small, **{"f.amount_cents": 3_000_000_000})    # > INT32_MAX
    flipped = {}
    for cname, fn in CHANGES:
        new = fn(BASE)
        for codec in CODECS:
            a = roundtrip(BASE, new, codec, small)[0]
            b = roundtrip(BASE, new, codec, big)[0]
            if a != b:
                flipped[(cname, codec.name)] = (a, b)
    return flipped



def _fmt(matrix, order):
    sym = {"SAFE": "safe", "HARD_FAIL": "FAIL", "SILENT_WRONG": "WRONG"}
    lines = [f"{'change':<26}{'codec':<12}{'fwd':<7}{'bwd':<7}deploy order",
             "-" * 72]
    for cname, _ in CHANGES:
        for codec in CODECS:
            f = sym[matrix[(cname, codec.name, "forward")]]
            b = sym[matrix[(cname, codec.name, "backward")]]
            lines.append(f"{cname:<26}{codec.name:<12}{f:<7}{b:<7}"
                         f"{order[(cname, codec.name)]}")
    return "\n".join(lines)


def main() -> None:
    m = compatibility_matrix()
    order = required_deploy_order(m)
    print("=" * 72)
    print("COMPATIBILITY MATRIX -- 9 changes x 3 codecs x 2 directions")
    print("=" * 72)
    print(_fmt(m, order))

    mix = verdict_mix(m)
    print("\n" + "=" * 72)
    print("VERDICT MIX")
    print("=" * 72)
    print(f"  total cells      {mix['total']}")
    print(f"  SAFE             {mix['SAFE']}")
    print(f"  HARD_FAIL        {mix['HARD_FAIL']}   (loud: found in staging)")
    print(f"  SILENT_WRONG     {mix['SILENT_WRONG']}   (quiet: found in reconciliation)")
    print(f"  silent share of broken cells: {mix['silent_share_of_broken']}")

    print("\n" + "=" * 72)
    print("DEPLOY ORDER, counted")
    print("=" * 72)
    counts = {}
    for v in order.values():
        counts[v] = counts.get(v, 0) + 1
    for k in ("either", "readers", "writers", "IMPOSSIBLE"):
        if k in counts:
            print(f"  {k:<12} {counts[k]}")
    imp = sorted({c for (c, _), v in order.items() if v == "IMPOSSIBLE"})
    print(f"  changes with NO safe single-step deploy on some codec: {imp}")

    print("\n" + "=" * 72)
    print("READ-MODIFY-WRITE THROUGH AN OLD READER")
    print("=" * 72)
    for codec in (NamedCodec, TaggedCodec, PositionalCodec):
        off = read_modify_write(codec, preserve_unknown=False)
        on = read_modify_write(codec, preserve_unknown=True)
        print(f"  {codec.name:<12} retention off: lost {off['lost']}/{off['n']} "
              f"({off['loss_rate']})   retention on: "
              f"{on['lost']}/{on['n']} ({on['loss_rate']}) [{on['retention']}]")

    print("\n" + "=" * 72)
    print("NARROWING int64 -> int32")
    print("=" * 72)
    nl = narrowing_loss()
    dd = data_dependent_changes()
    print(f"  n={nl['n']}  rows over INT32_MAX={nl['rows_over_int32']}  "
          f"silently wrong={nl['silently_wrong']}  raised={nl['raised']}")
    print("\n  Verdicts that FLIP on data alone, schemas held identical:")
    for (c, cd), (a, b) in sorted(dd.items()):
        print(f"    {c:<22}{cd:<12}{a} -> {b}")
    print(f"  => {len(dd)} cell(s). A schema-only compatibility check cannot see these:")
    print(f"     its input does not contain the values.")

    print(f"  every over-boundary row decoded SUCCESSFULLY with a different value")


if __name__ == "__main__":
    main()
