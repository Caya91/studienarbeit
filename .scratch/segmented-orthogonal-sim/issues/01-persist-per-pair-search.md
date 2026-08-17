# 01 — Persist per-pair search results across rounds

**What to build:** The segmented scheme's `admit` no longer redoes the expensive combined-search for a broken pair when nothing about that pair has changed. When a pair of same-type broken segments is re-examined in a later round and neither their bytes nor the current trusted set has changed since the last attempt, the previous search outcome (found / not-found-within-budget) is reused instead of recomputed. High-error-rate sweep cells that currently run effectively forever complete in feasible time, and the time/op-count numbers become trustworthy rather than pessimistic.

**Blocked by:** None — can start immediately.

**Status:** DONE (branch `feat/01-per-pair-persistence`, commit 0bd19b3)

- [x] A broken pair whose segment bytes and trusted-set are unchanged since its last failed search is not searched again that round.
- [x] Cache is keyed so a change to either the pair's bytes or the relevant trusted set correctly invalidates the reused result.
- [x] Recovery correctness is unchanged vs. the recompute-every-round version (all segmented recovery tests pass; added 4 tests incl. cached==uncached output and zero-op hit).
- [x] A high-BER smoke cell that previously hung now completes in bounded time (BER=5e-3 N=3: 16.6s/trial cached vs 27.8s uncached, 1.67x, 91% hit rate).
- [x] segmented-scheme-sim-status note + the admit() code comment updated to reflect it is now implemented.

**Result:** exact-key memo, provably no behaviour change. A superset-failure-reuse variant (reuse a failed search when the trusted set only grew) was considered and deferred — 91% hit rate already; residual per-cell cost is ticket 02's runtime cap.
