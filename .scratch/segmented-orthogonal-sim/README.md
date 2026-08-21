# Segmented orthogonal scheme — implementation tickets

Local tracker (no external issue tracker). One file per ticket in `issues/`, numbered in
dependency order (blockers first). Work the frontier: any ticket whose blockers are all done.

Sim code lives in worktree `worktree-segmented-scheme-sim`; run per `docs/running_sims.md`.

| # | Ticket | Blocked by | Status |
|---|--------|-----------|--------|
| 01 | Persist per-pair search results across rounds | — | ✅ done (0bd19b3) |
| 02 | Make the N-sweep a first-class runnable entrypoint (+ per-cell runtime cap) | 01 | ✅ done |
| 03 | Run full N-sweep and pick best N / strategy | 01, 02 | ready |
| 04 | Add CRC + matched homomorphic Combined-Recovery MAC arms to the comparison axis | 03 (figure); arm-build in progress | in-progress |
| 05 | IC-refinement: port vs stay measure-only | 03 | blocked |
| 06 | Smart-attacker spectrum: keyless orthogonal vs keyed homomorphic MAC | 04 | blocked |

Frontier now: **03** (sweep) + **04 arm-build** (matched homomorphic Combined-Recovery MAC, being implemented; the comparison *figure* still waits on 03).

Note on 04: the HMAC arm is the **matched homomorphic Combined-Recovery MAC** (segmented, tag-count-matched for overhead parity), not the flat plain-HMAC baseline. Case-2/IC-refinement stays measure-only in the arm (see 05).
