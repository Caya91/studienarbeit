# Segmented orthogonal scheme — implementation tickets

Local tracker (no external issue tracker). One file per ticket in `issues/`, numbered in
dependency order (blockers first). Work the frontier: any ticket whose blockers are all done.

Sim code lives in worktree `worktree-segmented-scheme-sim`; run per `docs/running_sims.md`.

| # | Ticket | Blocked by | Status |
|---|--------|-----------|--------|
| 01 | Persist per-pair search results across rounds | — | ✅ done (0bd19b3) |
| 02 | Make the N-sweep a first-class runnable entrypoint (+ per-cell runtime cap) | 01 | ✅ done |
| 03 | Run full N-sweep and pick best N / strategy | 01, 02 | ready |
| 04 | Add CRC + HMAC arms to the comparison axis | 03 | blocked |
| 05 | IC-refinement: port vs stay measure-only | 03 | blocked |

Frontier now: **03**.
