# Segmented orthogonal scheme — implementation tickets

Local tracker (no external issue tracker). One file per ticket in `issues/`, numbered in
dependency order (blockers first). Work the frontier: any ticket whose blockers are all done.

Sim code lives in worktree `worktree-segmented-scheme-sim`; run per `docs/running_sims.md`.

| # | Ticket | Blocked by | Status |
|---|--------|-----------|--------|
| 01 | Persist per-pair search results across rounds | — | ✅ done (0bd19b3) |
| 02 | Make the N-sweep a first-class runnable entrypoint (+ per-cell runtime cap) | 01 | ✅ done |
| 03 | Run full N-sweep and pick best N / strategy | 01, 02 | ready |
| 04 | Add CRC + matched homomorphic Combined-Recovery MAC arms to the comparison axis | 03 (figure); arm-build done | arm done; final figure after 07 |
| 05 | IC-refinement: port vs stay measure-only | 03 | ✅ decided → PORT (see 07) |
| 06 | Attacker comparison: keyless orthogonal vs keyed homomorphic MAC | 04 | ready (decisions locked 2026-08-26) |
| 07 | Implement IC-refinement (Case-2 recovery) in both arms | — | ready (decisions locked 2026-08-26) |
| 08 | Segmented CRC arm with PRAC-style Combined Recovery | — | ready |

Frontier now: **07** (Case-2 recovery — MAC arm first, then orthogonal) + **06** (attacker sim) + **08** (PRAC-style combined-recovery CRC arm). Tickets 06 & 07 have their decisions written into their files; implement in a later session.

Note on 04 / ticket C decisions (2026-08-26, IMPLEMENTED this session): the HMAC arm is the **matched homomorphic Combined-Recovery MAC** (segmented, tag-count-matched), not the flat plain-HMAC baseline — confirmed complete, 10/10 tests pass, already produced a 100-trial sweep. Comparison-figure decisions done in code: focus N=5 both strategies; drop 1e-2; HD=2 all arms; added silent-decode + wall-clock plot panels; overhead matched tag-for-tag (salt excluded from `SegmentedScheme.tag_overhead_bits`). The final headline figure waits for 07 so keyless recovery isn't undersold — but per ticket-07 decision 5 the figure is not a blocker. Case-2/IC-refinement is now decided (**port**, ticket 07).
