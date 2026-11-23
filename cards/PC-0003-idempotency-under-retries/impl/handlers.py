"""The solution shapes, and the three orderings of the dedupe write.

Each handler takes (store, request) and returns a Response. The instrumentation lives in the
store, so the handlers stay small enough to read -- which matters because the difference
between a correct and a silently-wrong handler here is two lines.
"""
from __future__ import annotations

import hashlib

from .store import ASSIGN, INCREMENT, Response

DEFAULT_TTL = 100


def naive(store, req) -> Response:
    """No protection. Present as the baseline the card has to beat."""
    store.apply(req)
    return Response("ok", req.payload)


def natural_idempotent(store, req) -> Response:
    """Express the operation as a state ASSIGNMENT, so replay is harmless by construction.

    No dedupe store, no TTL, no key. When it is available it dominates every other shape.

    It is available only when the effect is expressible as an assignment. Forcing it onto an
    INCREMENT workload does not raise -- it silently computes a different function (last
    write wins instead of a sum), which is why this is measured rather than argued.
    """
    store.apply(req, force_assign=True)
    return Response("ok", req.payload)


def key_dedupe(store, req, *, ttl: int = DEFAULT_TTL,
               cache_response: bool = True) -> Response:
    """Client-supplied idempotency key, with the prior response recorded alongside it.

    `cache_response=False` models the common half-implementation: the key is remembered, so
    the effect is not repeated, but the original response is gone -- so the retry gets a
    different answer than the first attempt, and a client that needs the response body
    (an id, a receipt) cannot proceed even though its operation succeeded.
    """
    rec = store.get_dedupe(req.idem_key)
    if rec is not None:
        if rec.response is None:
            return Response("duplicate-no-body", None)
        return Response("ok-replayed", rec.response)
    store.apply(req)
    store.put_dedupe(req.idem_key, req.payload if cache_response else None, ttl)
    return Response("ok", req.payload)


def content_hash_dedupe(store, req, *, ttl: int = DEFAULT_TTL) -> Response:
    """Derive the dedupe key from the payload instead of taking one from the client.

    Attractive because it needs no client cooperation. It defines "the same request" as "the
    same bytes", which merges operations that are legitimately identical -- two separate $10
    charges become one. The failure is silent and looks like successful deduplication.
    """
    digest = hashlib.sha256(repr(req.payload).encode()).hexdigest()
    rec = store.get_dedupe(digest)
    if rec is not None:
        return Response("ok-replayed", rec.response)
    store.apply(req)
    store.put_dedupe(digest, req.payload, ttl)
    return Response("ok", req.payload)


def content_hash_scoped(store, req, *, ttl: int = DEFAULT_TTL) -> Response:
    """Content hash scoped to the TARGET ROW: key = hash(logical_id, payload).

    Isolates the two defects the unscoped version conflates. Scoping fixes cross-row merging
    (two different orders that happen to carry the same payload). It does NOT fix same-row
    legitimate duplicates, because those differ in neither row nor bytes -- and no function of
    the request content can separate them. That is the argument for taking a key FROM THE
    CLIENT: only the caller knows whether it meant one operation or two.
    """
    digest = hashlib.sha256(f"{req.logical_id}|{req.payload!r}".encode()).hexdigest()
    rec = store.get_dedupe(digest)
    if rec is not None:
        return Response("ok-replayed", rec.response)
    store.apply(req)
    store.put_dedupe(digest, req.payload, ttl)
    return Response("ok", req.payload)


def conditional_write(store, req, *, expected: dict) -> Response:
    """Compare-and-set on the target row's version. No dedupe store, nothing to expire.

    `expected` is caller-owned and models the client reading the row version BEFORE its first
    attempt and reusing that value on every retry. The first attempt matches and applies; the
    retry carries a now-stale version and is rejected.

    The first version compared `req.attempt - 1` against the row version -- but three
    operations share a row here, so it compared an attempt counter against a counter other
    operations also advanced. It reported 2,355 lost operations, which was a defect in the
    simulator, not a property of CAS. Worth stating because the wrong number was plausible.

    The real cost is ambiguity: a losing CAS cannot distinguish "my own earlier attempt
    already applied this" from "a different writer got there first".
    """
    if req.idem_key not in expected:
        expected[req.idem_key] = store.version.get(req.logical_id, 0)
    if store.version.get(req.logical_id, 0) != expected[req.idem_key]:
        return Response("conflict", None)
    store.apply(req)
    return Response("ok", req.payload)


# --------------------------------------------------------------------------------------
#  The dedupe write has three possible orderings and two of them are wrong. This is the
#  part that cannot be reasoned about safely, so it is measured: a crash is injected
#  between the two writes and the outcome is counted.
# --------------------------------------------------------------------------------------
class Crash(Exception):
    pass


def key_then_effect(store, req, *, crash: bool = False, ttl: int = DEFAULT_TTL) -> Response:
    """Record the key, then apply the effect. A crash between them LOSES the effect forever:
    the retry sees the key, concludes the work is done, and returns success."""
    rec = store.get_dedupe(req.idem_key)
    if rec is not None:
        return Response("ok-replayed", rec.response)
    store.put_dedupe(req.idem_key, req.payload, ttl)
    if crash:
        raise Crash("crashed after recording the key, before applying the effect")
    store.apply(req)
    return Response("ok", req.payload)


def effect_then_key(store, req, *, crash: bool = False, ttl: int = DEFAULT_TTL) -> Response:
    """Apply the effect, then record the key. A crash between them DUPLICATES the effect:
    the retry finds no key and applies it again."""
    rec = store.get_dedupe(req.idem_key)
    if rec is not None:
        return Response("ok-replayed", rec.response)
    store.apply(req)
    if crash:
        raise Crash("crashed after applying the effect, before recording the key")
    store.put_dedupe(req.idem_key, req.payload, ttl)
    return Response("ok", req.payload)


def request_hash(req) -> str:
    return hashlib.sha256(repr(req.payload).encode()).hexdigest()[:16]


def reserve_then_commit(store, req, *, crash: bool = False,
                        ttl: int = DEFAULT_TTL) -> Response:
    """Key-first, but the reservation records whether the effect COMMITTED.

    This is what real internal code does, and it dissolves the choice E3 appears to force.
    A crash between reserving and applying leaves a reservation with `committed=False`; the
    retry sees it, recognises its own request by `request_hash`, and RESUMES -- so the effect
    is neither lost (key_then_effect) nor duplicated (effect_then_key), without needing one
    atomic transaction spanning the dedupe store and the business state.

    The `request_hash` comparison additionally rejects a reused token carrying a different
    request, which none of the other shapes here detect at all: they would silently return the
    FIRST operation's response for a genuinely different second operation.
    """
    rh = request_hash(req)
    res = store.get_reservation(req.idem_key)

    if res is None:
        store.put_reservation(req.idem_key, req.logical_id, rh, ttl)
        if crash:
            raise Crash("crashed after reserving, before applying -- but resumable")
        store.apply(req)
        store.commit_reservation(req.idem_key, req.payload)
        return Response("ok", req.payload)

    if res.request_hash != rh:
        return Response("key-reuse-rejected", None)
    if res.committed:
        return Response("ok-replayed", res.response)

    # Reserved but never committed: a previous attempt died mid-flight. Take it over.
    if crash:
        raise Crash("crashed again while resuming; still resumable")
    store.apply(req)
    store.commit_reservation(req.idem_key, req.payload)
    return Response("ok-resumed", req.payload)



def atomic(store, req, *, crash: bool = False, ttl: int = DEFAULT_TTL) -> Response:
    """Both writes commit together or neither does. A crash leaves the operation retryable
    and unapplied, which is the only safe state."""
    rec = store.get_dedupe(req.idem_key)
    if rec is not None:
        return Response("ok-replayed", rec.response)
    if crash:
        raise Crash("crashed before the transaction committed; nothing was written")
    store.apply(req)
    store.put_dedupe(req.idem_key, req.payload, ttl)
    return Response("ok", req.payload)
