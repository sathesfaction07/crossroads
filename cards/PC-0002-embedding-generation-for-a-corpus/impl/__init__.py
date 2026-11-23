"""PC-0002 — embedding generation for a corpus.

Five modules, one per decomposition node, so the code layout IS the problem breakdown:

    chunking.py    node 1  what are the units?
    pooling.py     node 2  many token vectors -> one vector
    throughput.py  node 3  what does a batch actually cost?
    identity.py    node 4  what is an embedding, for cache purposes?
    metric.py      node 5  which similarity, on which vectors?
    pipeline.py    Shape A, composed in the decomposition's topological order

Stdlib only, on purpose. numpy, torch and transformers are all importable in the
environment this card was written in, and are still not used: if `[executed]` depended on a
model download it would mean "this ran once on the author's machine" instead of "this runs
wherever the gate runs". The cost of that choice is stated plainly in the card -- no claim
here is about embedding QUALITY, because quality cannot be measured without a real model.
"""
