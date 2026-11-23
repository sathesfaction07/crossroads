"""At-least-once delivery, simulated deterministically.

The critical modelling decision: duplicates do NOT come from lost requests. They come from
lost ACKNOWLEDGEMENTS. The server received the request, applied the effect, and then the
response was lost -- so the client, which cannot distinguish "never arrived" from "arrived
and the reply was lost", retries. Every duplicate in this simulator has therefore ALREADY
been applied once by a naive handler.

Modelling it the other way round (drop requests, then retry) produces a simulator in which
retries are harmless, which is precisely the intuition that makes people skip idempotency.

Determinism: `random.Random(seed)`, never `builtins.hash`. Python salts string hashing per
process (PYTHONHASHSEED), so a hash-derived key is not reproducible across runs -- a bug
already found the hard way in PC-0002, where it made "identical" vectors differ per process.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Request:
    """One DELIVERY of one logical operation.

    `logical_id` is the business identity (which order). `idem_key` is what the client sends
    to say "this is the same attempt as before" -- stable across retries of one operation,
    distinct between different operations. Keeping them separate is the whole point: two
    different operations on the same order share a logical_id but not an idem_key, and a
    retry shares both.
    """
    logical_id: str
    idem_key: str
    payload: tuple            # tuple, so it is hashable and comparable
    attempt: int
    delivery_seq: int

    @property
    def amount(self) -> int:
        return dict(self.payload).get("amount", 0)


@dataclass
class Stream:
    deliveries: list[Request]
    n_logical: int
    n_duplicate_deliveries: int
    attempts_histogram: dict[int, int] = field(default_factory=dict)

    @property
    def duplicate_ratio(self) -> float:
        return self.n_duplicate_deliveries / max(1, self.n_logical)


def delivery_stream(n_logical: int, *, seed: int, p_ack_lost: float = 0.15,
                    max_attempts: int = 4, identical_payload_rate: float = 0.0,
                    amount_space: int = 10 ** 9) -> Stream:
    """Build a deterministic at-least-once delivery stream.

    `identical_payload_rate` injects operations that are LEGITIMATELY identical in payload
    but are distinct operations (two separate $10 charges on the same account). They carry
    different idem_keys and must both apply. This is the input that separates a correct
    dedupe key from a content hash, and without it a content-hash handler looks perfect.

    `amount_space` is the payload entropy, and it is a PARAMETER rather than an accident
    because the first version of this simulator drew amounts from 999 values for 4,000
    operations. Content-hash dedupe then merged 75% of all operations by birthday collision,
    and reporting that as its false-merge rate would have described the fixture rather than
    the technique. Entropy is now stated with every measurement that depends on it.
    """
    rng = random.Random(seed)
    deliveries: list[Request] = []
    dupes = 0
    hist: dict[int, int] = {}
    seq = 0

    for i in range(n_logical):
        logical_id = f"order-{i // 3}"          # several operations share an order
        if rng.random() < identical_payload_rate:
            payload = (("amount", 10), ("currency", "USD"))   # deliberately identical
        else:
            payload = (("amount", rng.randrange(1, amount_space)), ("currency", "USD"))
        idem_key = f"key-{i:06d}"               # distinct per OPERATION, stable per retry

        attempts = 1
        while attempts < max_attempts and rng.random() < p_ack_lost:
            attempts += 1
        hist[attempts] = hist.get(attempts, 0) + 1
        dupes += attempts - 1

        for a in range(1, attempts + 1):
            deliveries.append(Request(logical_id=logical_id, idem_key=idem_key,
                                      payload=payload, attempt=a, delivery_seq=seq))
            seq += 1

    return Stream(deliveries=deliveries, n_logical=n_logical,
                  n_duplicate_deliveries=dupes, attempts_histogram=hist)
