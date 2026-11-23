"""Sub-problem 3 — THROUGHPUT. Padding is the bill you did not ask for.

A batched forward pass costs `max_len_in_batch x batch_size` token slots, not the sum of
the real lengths. On a right-skewed corpus, batching in arrival order therefore pays for a
large amount of nothing. This is exact arithmetic -- no model, no timing, no hardware
assumptions -- so the ratios are `[executed]`.

What is NOT claimed here: wall-clock speedup. Slots are a proxy for cost, and a good one
for attention-dominated workloads, but real throughput also depends on kernel efficiency at
different shapes. This card measures slots and says so.
"""
from __future__ import annotations


def batches_arrival(lengths: list[int], batch_size: int) -> list[list[int]]:
    """Batch in the order documents arrived -- the default nobody chose deliberately."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    return [lengths[i:i + batch_size] for i in range(0, len(lengths), batch_size)]


def batches_bucketed(lengths: list[int], batch_size: int) -> list[list[int]]:
    """Sort by length, then batch, so each batch pads to nearly its own longest member."""
    return batches_arrival(sorted(lengths), batch_size)


def bucketed_with_restore(lengths: list[int], batch_size: int) -> tuple[list[list[int]], list[int]]:
    """Length-bucketed batches PLUS the permutation needed to put results back.

    This is the part that turns a cheap win into a correctness bug when omitted. Bucketing
    reorders documents; embeddings come back in bucketed order; if the caller zips them
    against the original document list, **every vector is attached to the wrong document**
    and nothing crashes. The permutation is returned as a required value rather than an
    optional convenience so that losing it is a visible omission.
    """
    order = sorted(range(len(lengths)), key=lambda i: lengths[i])
    batched = batches_arrival([lengths[i] for i in order], batch_size)
    return batched, order


def restore(values: list, order: list[int]) -> list:
    """Invert `bucketed_with_restore`'s permutation."""
    if len(values) != len(order):
        raise ValueError(f"cannot restore {len(values)} values with a {len(order)}-permutation")
    out = [None] * len(values)
    for slot, original in enumerate(order):
        out[original] = values[slot]
    return out


def slots(batches: list[list[int]]) -> int:
    """Token slots actually paid for: sum over batches of max_len x rows."""
    return sum(max(b) * len(b) for b in batches if b)


def padding_waste(lengths: list[int], batch_size: int, strategy: str = "arrival") -> dict:
    """Fraction of paid token slots that carry no data.

    `strategy` is 'arrival' or 'bucketed'. Returns both the waste fraction and the absolute
    slot count, because the fraction alone hides scale and the count alone hides efficiency.
    """
    if strategy == "arrival":
        batches = batches_arrival(lengths, batch_size)
    elif strategy == "bucketed":
        batches = batches_bucketed(lengths, batch_size)
    else:
        raise ValueError(f"unknown strategy {strategy!r}")
    paid = slots(batches)
    useful = sum(lengths)
    return {
        "batch_size": batch_size,
        "strategy": strategy,
        "unit": "token slots (max_len x rows), not seconds",
        "paid_slots": paid,
        "useful_tokens": useful,
        "wasted_fraction": (paid - useful) / paid if paid else 0.0,
    }


def bucketing_gain(lengths: list[int], batch_size: int) -> dict:
    """Slots saved by length-bucketing, at one batch size.

    Reported per batch size on purpose: the gain is NOT a single number, and it is NOT MONOTONE
    either. It RISES with batch size at first, because a bigger batch in arrival order is more
    likely to contain an outlier that everything else pads up to. Then it FALLS, because a bucketed
    batch that large spans a wide length range again. On the canonical corpus it peaks at
    batch_size=128 (4.4595x) and is back to exactly 1.0 by 2048.

    That endpoint is exact rather than measured: once batch_size >= len(lengths) there is a single
    batch whose max is the same under every ordering, so the reduction is 1.0 identically. A card
    that quoted one figure would be flattening a curve into a point -- and a card that quoted the
    TREND would get the sign wrong past the peak.

    This docstring previously claimed the gain "grows with batch size". That contradicted the card's
    own constraint C3 AND this package's own test_bucketing_gain_is_not_monotonic_in_batch_size, so
    the code and its tests were right and the prose beside them was wrong. Found by an understatement
    audit that was looking for something else entirely.
    """
    a = padding_waste(lengths, batch_size, "arrival")
    b = padding_waste(lengths, batch_size, "bucketed")
    return {
        "batch_size": batch_size,
        "arrival_slots": a["paid_slots"],
        "bucketed_slots": b["paid_slots"],
        "arrival_wasted_fraction": a["wasted_fraction"],
        "bucketed_wasted_fraction": b["wasted_fraction"],
        "slot_reduction": a["paid_slots"] / b["paid_slots"] if b["paid_slots"] else 0.0,
    }
