# List of future improvements
What: These are ideas for optimisations later on to bring the overhead and needed operations down 
We will only implement these once all the functional steps are done.


Cheaper gate — the V-gate re-sniffs O(n²) each round (the ~2× ops). An incremental trust update per arrival would cut that; worth it only if op-count is a headline metric.

The model is comfortable up to gen≈20–30; beyond that the O(gen³)/round re-sniff makes sweeps painfully slow. The single highest-leverage change for scaling is Option B — sniff once per round and share the cross-check between recovery and the decode gate (and ideally update trust incrementally per arrival instead of re-scanning the whole pool), which would knock the per-round cost from ~2×gen³ toward gen² and make gen≥40 tractable.