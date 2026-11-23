"""Run every experiment and print the numbers the card is written from.

Nothing here is illustrative. Each block prints a value that appears in card.json, and the
card was written after reading this output -- not before.

  python3 -m impl.measure
"""
from __future__ import annotations

from collections import Counter

from . import handlers as H
from .delivery import delivery_stream
from .store import ASSIGN, INCREMENT, Clock, Store, distinct_keys, expected_totals

SEED = 20260906
N = 4000
ENTROPY = 10 ** 9          # payload amount space; stated because E5 depends on it


def _run(stream, handler, algebra, *, retry_gap: int = 0, **kw):
    store = Store(algebra=algebra, clock=Clock())
    responses = []
    for r in stream.deliveries:
        if retry_gap and r.attempt > 1:
            store.clock.tick(retry_gap)
        responses.append(handler(store, r, **kw))
    return store, responses


def _rows_wrong(store, stream, algebra) -> int:
    """How many rows hold the wrong value.

    A boolean CORRECT/WRONG cannot distinguish over-counting from computing a different
    function, and those are different defects with different fixes.
    """
    exp = expected_totals(stream, algebra)
    return sum(1 for k, v in exp.items() if store.total.get(k) != v)


def _verdict(store, stream, algebra) -> str:
    return "CORRECT" if _rows_wrong(store, stream, algebra) == 0 else "WRONG"


def header(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def main() -> None:
    print(f"seed={SEED}  n_logical_operations={N}  payload_amount_space={ENTROPY}")

    # ---------------------------------------------------------------- E1
    header("E1  the delivery stream itself")
    s = delivery_stream(N, seed=SEED, p_ack_lost=0.15, max_attempts=4, amount_space=ENTROPY)
    keys = distinct_keys(s)
    n_rows = len(set(r.logical_id for r in s.deliveries))
    print(f"  deliveries              {len(s.deliveries)}")
    print(f"  logical operations      {s.n_logical}")
    print(f"  distinct rows           {n_rows}")
    print(f"  duplicate deliveries    {s.n_duplicate_deliveries}")
    print(f"  duplicate ratio         {s.duplicate_ratio:.4f}")
    print(f"  attempts histogram      {dict(sorted(s.attempts_histogram.items()))}")
    retried = sum(v for k, v in s.attempts_histogram.items() if k >= 2)
    print(f"  operations retried >=1x {retried}  ({retried / N:.4f})")

    # ---------------------------------------------------------------- E2
    header("E2  outcome by shape x effect algebra  (the algebra chooses the shape)")
    print(f"  {'shape':<22}{'algebra':<11}{'dup_appl':>9}{'lost':>6}{'rows_wrong':>12}"
          f"{'verdict':>9}{'dedupe_writes':>15}")
    for algebra in (INCREMENT, ASSIGN):
        for label, fn, kw in (
                ("naive", H.naive, {}),
                ("natural_idempotent", H.natural_idempotent, {}),
                ("key_dedupe", H.key_dedupe, {}),
                ("conditional_write", H.conditional_write, {"expected": {}}),
                ("content_hash", H.content_hash_dedupe, {}),
                ("content_hash_scoped", H.content_hash_scoped, {}),
        ):
            st, _ = _run(s, fn, algebra, **kw)
            print(f"  {label:<22}{algebra:<11}{st.duplicate_applications():>9}"
                  f"{st.lost_operations(keys):>6}{_rows_wrong(st, s, algebra):>12}"
                  f"{_verdict(st, s, algebra):>9}{st.dedupe_writes:>15}")

    # ---------------------------------------------------------------- E3
    header("E3  ordering of the two writes, with a crash injected between them")
    print(f"  crash injected on the FIRST delivery of every retried operation "
          f"({retried} operations), so these counts are exact, not sampled.")
    print(f"  {'ordering':<18}{'dup_appl':>9}{'lost_ops':>10}{'rows_wrong':>12}{'verdict':>9}")
    retried_keys = {k for k, c in Counter(r.idem_key for r in s.deliveries).items() if c > 1}
    for label, fn in (("key_then_effect", H.key_then_effect),
                      ("effect_then_key", H.effect_then_key),
                      ("reserve_then_commit", H.reserve_then_commit),
                      ("atomic", H.atomic)):
        store = Store(algebra=INCREMENT, clock=Clock())
        for r in s.deliveries:
            try:
                fn(store, r, crash=(r.attempt == 1 and r.idem_key in retried_keys))
            except H.Crash:
                pass
        print(f"  {label:<18}{store.duplicate_applications():>9}"
              f"{store.lost_operations(keys):>10}{_rows_wrong(store, s, INCREMENT):>12}"
              f"{_verdict(store, s, INCREMENT):>9}")

    # ---------------------------------------------------------------- E4
    header("E4  TTL vs the retry window")
    gap = 20
    print(f"  retry_gap={gap} ticks, max_attempts=4, so the LAST retry of an operation can "
          f"arrive {gap * 3} ticks after the first delivery.")
    print(f"  {'ttl_ticks':>10}{'dup_appl':>10}{'re_exec_rate':>14}{'verdict':>9}")
    for ttl in (1, 10, 19, 20, 21, 40, 41, 59, 60, 61, 100):
        st, _ = _run(s, H.key_dedupe, INCREMENT, retry_gap=gap, ttl=ttl)
        dup = st.duplicate_applications()
        print(f"  {ttl:>10}{dup:>10}{dup / max(1, s.n_duplicate_deliveries):>14.4f}"
              f"{_verdict(st, s, INCREMENT):>9}")

    # ---------------------------------------------------------------- E5
    header("E5  content-hash dedupe: false merges, by payload entropy and by legitimate "
           "duplicates")
    print(f"  {'amount_space':>13}{'identical_rate':>15}{'unscoped_lost':>14}"
          f"{'scoped_lost':>12}{'unscoped_rate':>14}{'scoped_rate':>12}")
    for space in (1000, 10 ** 9):
        for rate in (0.0, 0.05, 0.25):
            s2 = delivery_stream(N, seed=SEED, p_ack_lost=0.15, max_attempts=4,
                                 identical_payload_rate=rate, amount_space=space)
            k2 = distinct_keys(s2)
            un, _ = _run(s2, H.content_hash_dedupe, INCREMENT)
            sc, _ = _run(s2, H.content_hash_scoped, INCREMENT)
            lu, ls = un.lost_operations(k2), sc.lost_operations(k2)
            print(f"  {space:>13}{rate:>15.2f}{lu:>14}{ls:>12}"
                  f"{lu / len(k2):>14.4f}{ls / len(k2):>12.4f}")

    # ---------------------------------------------------------------- E6
    header("E6  storing the key without storing the response")
    for cache in (True, False):
        st, resp = _run(s, H.key_dedupe, INCREMENT, cache_response=cache)
        replays = [r for r in resp if r.status in ("ok-replayed", "duplicate-no-body")]
        nobody = [r for r in resp if r.status == "duplicate-no-body"]
        print(f"  cache_response={str(cache):<6} replays={len(replays):>4}  "
              f"replies_without_a_body={len(nobody):>4}  "
              f"({len(nobody) / max(1, len(replays)):.4f} of replays)  "
              f"rows_wrong={_rows_wrong(st, s, INCREMENT)}  "
              f"verdict={_verdict(st, s, INCREMENT)}")

    # ---------------------------------------------------------------- E7
    header("E7  conditional write (CAS): correctness without a dedupe store")
    st, resp = _run(s, H.conditional_write, INCREMENT, expected={})
    conflicts = sum(1 for r in resp if r.status == "conflict")
    print(f"  conflicts returned      {conflicts}  "
          f"(= duplicate deliveries {s.n_duplicate_deliveries}: "
          f"{conflicts == s.n_duplicate_deliveries})")
    print(f"  duplicate applications  {st.duplicate_applications()}")
    print(f"  lost operations         {st.lost_operations(keys)}")
    print(f"  dedupe writes           {st.dedupe_writes}")
    print(f"  rows wrong              {_rows_wrong(st, s, INCREMENT)}")
    print(f"  verdict                 {_verdict(st, s, INCREMENT)}")
    print(f"  ambiguous conflicts     {conflicts}  -- a losing CAS cannot tell "
          f"'my own retry' from 'another writer'")

    # ---------------------------------------------------------------- E8
    header("E8  cost of the dedupe store, per shape (writes to durable state)")
    for label, fn, kw in (("key_dedupe", H.key_dedupe, {}),
                          ("conditional_write", H.conditional_write, {"expected": {}}),
                          ("natural_idempotent", H.natural_idempotent, {})):
        st, _ = _run(s, fn, ASSIGN, **kw)
        print(f"  {label:<20} dedupe_writes={st.dedupe_writes:>5}  "
              f"extra_state_rows={len(st.dedupe):>5}")


    # ---------------------------------------------------------------- E9
    header("E9  a reused idempotency key carrying a DIFFERENT request")
    print("  A client reuses one token for two genuinely different operations -- a real bug,")
    print("  and the one failure mode none of the content-based shapes can even see.")
    from .delivery import Request
    reused = [
        Request(logical_id="order-9", idem_key="tok-1",
                payload=(("amount", 100), ("currency", "USD")), attempt=1, delivery_seq=0),
        Request(logical_id="order-9", idem_key="tok-1",
                payload=(("amount", 250), ("currency", "USD")), attempt=1, delivery_seq=1),
    ]
    for label, fn, kw in (("key_dedupe", H.key_dedupe, {}),
                          ("reserve_then_commit", H.reserve_then_commit, {})):
        st = Store(algebra=INCREMENT, clock=Clock())
        out = [fn(st, r, **kw) for r in reused]
        detected = any(r.status == "key-reuse-rejected" for r in out)
        print(f"  {label:<20} statuses={[r.status for r in out]}")
        print(f"  {'':<20} second_request_body_returned="
              f"{out[1].body}  applied_total={st.total.get('order-9')}")
        print(f"  {'':<20} reuse_detected={detected}")



if __name__ == "__main__":
    main()
