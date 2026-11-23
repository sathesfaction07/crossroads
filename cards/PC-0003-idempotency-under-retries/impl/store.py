"""The store, plus the two effect algebras that decide which solution shapes are available.

The distinction that turns out to matter more than anything about the transport:

  ASSIGN     state[k] = v          applying it twice leaves the same state
  INCREMENT  state[k] += v         applying it twice does not

A retry is harmless under ASSIGN and corrupting under INCREMENT, with the SAME delivery
stream and the SAME handler. So "how many duplicates arrived" is not the interesting number;
"what the duplicates did" is. A card that reports only duplicate-delivery rate would let a
consumer conclude an ASSIGN workload needs a dedupe store, which it does not.

TTL is measured on a logical clock in ticks, not wall time, so expiry is deterministic.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

ASSIGN = "assign"
INCREMENT = "increment"


class Clock:
    def __init__(self) -> None:
        self.t = 0

    def tick(self, n: int = 1) -> None:
        self.t += n

    def now(self) -> int:
        return self.t


@dataclass
class DedupeRecord:
    expires_at: int
    response: tuple | None      # None models "key stored, response not stored"


@dataclass
class Reservation:
    """A dedupe record that knows whether the effect it guards actually completed.

    Modelled on real internal code (IdempotencyReservationDao), which stamps a `requestHash`
    alongside the key "so a replay can detect a reused token carrying a different request",
    and offers `releaseIfOwnedBy` to undo a reservation whose work never happened. Both are
    absent from the textbook key-then-effect ordering, and both turn out to matter:
    `committed` is what lets a retry tell "already done" from "started and died", which is the
    difference between losing the operation and resuming it.
    """
    resource_id: str
    request_hash: str
    expires_at: int
    committed: bool = False
    response: tuple | None = None


@dataclass
class Response:
    status: str
    body: tuple | None = None


@dataclass
class Store:
    algebra: str = INCREMENT
    clock: Clock = field(default_factory=Clock)

    # observable business state
    total: dict[str, int] = field(default_factory=dict)
    version: dict[str, int] = field(default_factory=dict)

    # instrumentation
    applications: Counter = field(default_factory=Counter)   # idem_key -> times applied
    dedupe: dict[str, DedupeRecord] = field(default_factory=dict)
    reservations: dict[str, Reservation] = field(default_factory=dict)
    dedupe_hits: int = 0
    dedupe_writes: int = 0

    def apply(self, req, force_assign: bool = False) -> None:
        """Perform the side effect. Per-key counting makes duplicates visible.

        `force_assign` models a handler that rewrites the operation as an assignment in order
        to get idempotency for free. Under an ASSIGN workload that is exactly right. Under an
        INCREMENT workload it computes a DIFFERENT FUNCTION and raises nothing -- the totals
        are simply wrong. Keeping it as a flag on one method is deliberate: it is a two-line
        difference in real code too.
        """
        self.applications[req.idem_key] += 1
        if self.algebra == INCREMENT and not force_assign:
            self.total[req.logical_id] = self.total.get(req.logical_id, 0) + req.amount
        else:
            self.total[req.logical_id] = req.amount
        self.version[req.logical_id] = self.version.get(req.logical_id, 0) + 1

    # ---- plain dedupe records -----------------------------------------------
    def put_dedupe(self, key: str, response: tuple | None, ttl: int) -> None:
        self.dedupe[key] = DedupeRecord(expires_at=self.clock.now() + ttl, response=response)
        self.dedupe_writes += 1

    def get_dedupe(self, key: str) -> DedupeRecord | None:
        rec = self.dedupe.get(key)
        if rec is None:
            return None
        if rec.expires_at <= self.clock.now():
            del self.dedupe[key]          # expired: indistinguishable from never-seen
            return None
        self.dedupe_hits += 1
        return rec

    # ---- reservations: key-first, but resumable ------------------------------
    def get_reservation(self, key: str) -> Reservation | None:
        res = self.reservations.get(key)
        if res is None:
            return None
        if res.expires_at <= self.clock.now():
            del self.reservations[key]
            return None
        return res

    def put_reservation(self, key: str, resource_id: str, request_hash: str,
                        ttl: int) -> None:
        self.reservations[key] = Reservation(resource_id=resource_id,
                                            request_hash=request_hash,
                                            expires_at=self.clock.now() + ttl)
        self.dedupe_writes += 1

    def commit_reservation(self, key: str, response: tuple) -> None:
        res = self.reservations.get(key)
        if res is not None:
            res.committed = True
            res.response = response
            self.dedupe_writes += 1

    # ---- outcome accounting -------------------------------------------------
    def duplicate_applications(self) -> int:
        return sum(c - 1 for c in self.applications.values() if c > 1)

    def lost_operations(self, expected_keys) -> int:
        return sum(1 for k in expected_keys if self.applications.get(k, 0) == 0)


def expected_totals(stream, algebra: str) -> dict[str, int]:
    """The correct final state: each logical operation applied exactly once.

    Computed from the stream by collapsing idem_keys, which is the definition of
    exactly-once as an OUTCOME rather than as a delivery guarantee.
    """
    seen: set[str] = set()
    out: dict[str, int] = {}
    for r in stream.deliveries:
        if r.idem_key in seen:
            continue
        seen.add(r.idem_key)
        if algebra == INCREMENT:
            out[r.logical_id] = out.get(r.logical_id, 0) + r.amount
        else:
            out[r.logical_id] = r.amount
    return out


def distinct_keys(stream) -> list[str]:
    seen, out = set(), []
    for r in stream.deliveries:
        if r.idem_key not in seen:
            seen.add(r.idem_key)
            out.append(r.idem_key)
    return out
