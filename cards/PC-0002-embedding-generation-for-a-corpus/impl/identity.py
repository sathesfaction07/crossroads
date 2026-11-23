"""Sub-problem 4 — IDENTITY. What IS an embedding, for cache purposes?

An embedding is not a function of its text. It is a function of
`(text, model, revision, pooling, window, overlap, normalise, dtype)`. A cache keyed on
text alone will happily serve a vector produced by a configuration you no longer run, and
it will do so with a 100% hit rate and no error -- the worst possible failure signature.

`field_sensitivity` measures this per field rather than asserting it, so the requirement
"include everything" is a result rather than an exhortation.
"""
from __future__ import annotations

import hashlib
import json

# Every field that changes the produced vector. `dim` is included because Matryoshka-style
# truncation to a shorter dimension is a different vector, not a view of the same one.
IDENTITY_FIELDS = ("model", "revision", "pooling", "window", "overlap", "normalize", "dim")


def canonical_config(cfg: dict, include: tuple[str, ...] = IDENTITY_FIELDS) -> str:
    """Stable string for the config. Sorted keys, so dict ordering cannot change the key.

    Unknown fields are rejected rather than ignored: silently dropping a field a caller
    thought was part of the identity is precisely the bug this module exists to prevent.
    """
    unknown = set(cfg) - set(IDENTITY_FIELDS)
    if unknown:
        raise ValueError(f"config has fields outside IDENTITY_FIELDS: {sorted(unknown)}")
    return json.dumps({k: cfg[k] for k in sorted(include) if k in cfg}, sort_keys=True)


def embedding_key(text: str, cfg: dict, include: tuple[str, ...] = IDENTITY_FIELDS) -> str:
    """The correct key: text AND the full configuration that produced the vector."""
    payload = canonical_config(cfg, include) + "\u0000" + text
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def text_only_key(text: str, cfg: dict | None = None,
                  include: tuple[str, ...] = ()) -> str:
    """The wrong key, kept so the failure is measurable rather than described.

    Signature matches `embedding_key` so both can be passed to the same measurement.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stale_serve_rate(corpus: list[str], cfg_written: dict, cfg_wanted: dict,
                     keyfn=embedding_key, include: tuple[str, ...] = IDENTITY_FIELDS) -> dict:
    """Fill a cache under one config, then request vectors for another. How many wrong hits?

    A "wrong hit" is the dangerous outcome: the cache returns a vector built by a different
    configuration and the caller cannot tell. A MISS is the safe outcome -- it costs money,
    not correctness.
    """
    cache = {keyfn(t, cfg_written, include) for t in corpus}
    wrong = sum(1 for t in corpus if keyfn(t, cfg_wanted, include) in cache)
    return {
        "documents": len(corpus),
        "wrong_hits": wrong,
        "stale_serve_rate": wrong / len(corpus) if corpus else 0.0,
        "unit": "fraction of documents served a vector from the wrong configuration",
        "configs_differ_in": sorted(k for k in IDENTITY_FIELDS
                                   if cfg_written.get(k) != cfg_wanted.get(k)),
    }


# A changed value for each field, used to exercise one field at a time.
_ALTERED = {"model": "other-model", "revision": "rNEXT", "pooling": "cls",
            "window": 256, "overlap": 0, "normalize": False, "dim": 256}


def field_sensitivity(corpus: list[str], cfg: dict) -> dict:
    """Per field: if that field CHANGES and the key OMITS it, what fraction goes stale?

    Varies one field at a time, which the first version did not -- it compared two configs
    differing only in `revision`, so six of the seven fields reported 0.0 and the table
    looked like most fields were safe to omit. They were not being tested at all.

    The result is uniform: **omitting any field that changed yields a 100% stale-serve
    rate.** There is no subset of the identity you can drop; the fields that look harmless
    are only the ones you have not changed yet.
    """
    out = {}
    for field in IDENTITY_FIELDS:
        changed = dict(cfg, **{field: _ALTERED[field]})
        include = tuple(f for f in IDENTITY_FIELDS if f != field)
        out[field] = stale_serve_rate(corpus, cfg, changed,
                                      embedding_key, include)["stale_serve_rate"]
    return out
