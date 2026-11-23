"""Sub-problem 1 — CHUNKING. What are the units you embed?

This is first in the decomposition because every later decision depends on it: pooling
aggregates over units, batching pads to unit lengths, and the cache key must include the
chunk parameters or it silently serves vectors built under different units.

Everything here is exact index arithmetic, so all of it is `[executed]`.
"""
from __future__ import annotations

from typing import Iterable

from . import corpus as corpus_mod


def tokenize(text: str) -> list[str]:
    """Whitespace tokenisation, deliberately -- and read the correction below.

    A real pipeline uses the model's own tokenizer. This function returns WORDS.

    CORRECTED. This docstring previously argued that the subword factor "does NOT change
    any conclusion in this card, because every result here is a RATIO... Ratios are
    invariant to a roughly uniform rescaling of all lengths." That argument is FALSE, for
    two independent reasons:

      1. THE WINDOW DOES NOT RESCALE. docs_over and tokens_lost are evaluated against a
         window, and the window is a fixed model constant (512). If lengths scale by k, a
         512-TOKEN window is a 512/k WORD window -- a different point on the length CDF.
         On this card's own fixture, moving from a 512-word window to the 379-word window
         that corresponds to 512 tokens at k=1.35 raises docs_over 0.1405 -> 0.2220 (+58%)
         and tokens_lost 0.1634 -> 0.2477 (+52%). The ratios are not invariant.

      2. k IS NOT UNIFORM. Measured with real bert-base-uncased over 400 fixture documents,
         per-document k ranges 4.000 to 6.232. "Roughly uniform" fails on its own terms.

    Note the aggregate k on this fixture is 5.64, not the 1.2-1.5 of English prose, because
    the fixture is synthetic text built from repeated vocabulary and fragments heavily. That
    is a property of the FIXTURE, not of the world -- so it is NOT evidence that the card's
    conclusion is wrong for real corpora. It IS evidence that this fixture cannot support
    token-level claims. The figures in this card are WORD-level; treat them as a lower bound.

    See grounding/AUDIT-PC0002-impl-closed-loop.json.
    """
    return text.split()


def truncate(tokens: list[str], window: int) -> list[str]:
    return tokens[:window]


def truncation_loss(corpus: list[str], window: int) -> dict:
    """What truncate-and-forget actually costs, on this corpus.

    Two different numbers that are easy to conflate:
      - `docs_over`   : fraction of DOCUMENTS that lose any content at all
      - `tokens_lost` : fraction of ALL TOKENS in the corpus that are discarded

    They diverge sharply on a right-skewed corpus, and quoting the smaller one is a common
    way to make truncation look harmless.
    """
    lens = corpus_mod.token_lengths(corpus)
    total = sum(lens)
    lost = sum(max(0, n - window) for n in lens)
    over = sum(1 for n in lens if n > window)
    return {
        "window": window,
        "unit": "tokens (whitespace)",
        "docs_over": over / len(lens),
        "tokens_lost": lost / total,
        "worst_doc_lost_tokens": max((n - window) for n in lens) if lens else 0,
    }


def chunk_spans(length: int, window: int, overlap: int) -> list[tuple[int, int]]:
    """Half-open [start, end) spans covering `length` tokens.

    Raises on overlap >= window, which would make the stride non-positive and loop forever.
    That is a real bug in hand-rolled chunkers, so it is an explicit error rather than a
    hang.
    """
    if window <= 0:
        raise ValueError("window must be positive")
    if overlap < 0 or overlap >= window:
        raise ValueError(f"overlap {overlap} must satisfy 0 <= overlap < window {window}")
    stride = window - overlap
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        spans.append((start, min(length, start + window)))
        if start + window >= length:
            return spans
        start += stride


def chunk(tokens: list[str], window: int, overlap: int) -> list[list[str]]:
    return [tokens[s:e] for s, e in chunk_spans(len(tokens), window, overlap)]


def ngram_recall(length: int, window: int, overlap: int, k: int) -> float:
    """Fraction of k-token spans that survive INTACT inside at least one chunk.

    This is the measurable that tells you how to choose `overlap`, and it has an exact
    answer rather than a rule of thumb: a k-gram is destroyed only if every chunk boundary
    cuts it, so **overlap >= k-1 preserves every k-gram**. Below that, loss is proportional
    to the number of boundaries.

    Why it matters: a retrieval system that must match an 8-token phrase cannot use
    overlap=4, no matter how reasonable 4 looks.
    """
    total = max(0, length - k + 1)
    if total == 0:
        return 1.0
    covered: set[int] = set()
    for s, e in chunk_spans(length, window, overlap):
        for i in range(s, max(s, e - k + 1)):
            covered.add(i)
    return len(covered) / total


def corpus_ngram_recall(corpus: Iterable[str], window: int, overlap: int, k: int) -> float:
    """k-gram recall over a corpus, weighted by each document's k-gram count.

    Weighted, not a mean of per-document rates: an unweighted mean lets thousands of short
    documents (which have no boundaries and therefore perfect recall) hide the loss
    concentrated in the long tail.
    """
    num = den = 0.0
    for doc in corpus:
        length = len(tokenize(doc))
        count = max(0, length - k + 1)
        if count:
            num += ngram_recall(length, window, overlap, k) * count
            den += count
    return num / den if den else 1.0


def chunk_token_cost(corpus: list[str], window: int, overlap: int) -> dict:
    """Tokens actually sent to the model, vs tokens in the corpus.

    Chunk COUNT is a misleading cost measure and nearly fooled this card: at window=512 the
    counts for overlap=0 and overlap=32 are identical on this corpus, which reads as
    "overlap is free". It is not -- overlap re-sends `overlap` tokens per boundary, and that
    shows up in tokens, not in chunk count.
    """
    total = sum(len(tokenize(d)) for d in corpus)
    sent = 0
    for doc in corpus:
        for s, e in chunk_spans(len(tokenize(doc)), window, overlap):
            sent += e - s
    return {"corpus_tokens": total, "tokens_sent": sent,
            "overhead": sent / total - 1.0, "unit": "tokens (whitespace)"}


def chunks_per_corpus(corpus: list[str], window: int, overlap: int) -> int:
    """How many embedding calls chunking actually costs. Overlap is not free: it
    re-embeds `overlap` tokens per boundary, and that shows up directly in the bill.
    """
    return sum(len(chunk_spans(len(tokenize(d)), window, overlap)) for d in corpus)
