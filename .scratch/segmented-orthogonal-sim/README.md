# Segmented orthogonal scheme — implementation tickets

Local tracker (no external issue tracker). One file per ticket in `issues/`, numbered in
dependency order (blockers first). Work the frontier: any ticket whose blockers are all done.

Sim code lives in worktree `worktree-segmented-scheme-sim`; run per `docs/running_sims.md`.

| # | Ticket | Blocked by | Status |
|---|--------|-----------|--------|
| 01 | Persist per-pair search results across rounds | — | ✅ done (0bd19b3) |
| 02 | Make the N-sweep a first-class runnable entrypoint (+ per-cell runtime cap) | 01 | ✅ done |
| 03 | Run full N-sweep and pick best N / strategy | 01, 02 | ✅ done — winner keyless N=5 coefficient_first (`docs/segmented_n_sweep_findings.md`) |
| 04 | Add CRC + matched homomorphic Combined-Recovery MAC arms to the comparison axis | 03 (figure); arm-build done | arm done; final figure after 07 |
| 05 | IC-refinement: port vs stay measure-only | 03 | ✅ decided → PORT (see 07) |
| 06 | Attacker comparison: keyless orthogonal vs keyed homomorphic MAC | 04 | ✅ done (2026-08-31) — `simulation/segmented_attack_sim.py` |
| 07 | Implement IC-refinement (Case-2 recovery) in both arms | — | ✅ done — MAC (2026-08-31) + orthogonal (2026-09-01) |
| 08 | Segmented CRC arm with PRAC-style Combined Recovery | — | ✂️ cut to future work (extra baseline, not required) |
| 09 | Reproduce HMAC-paper figures (keyless orthogonal vs keyed HMAC) | 04 (arms done) | ready — headline keyless-vs-keyed figure still to redraw |
| 10 | Matched acceptance-oracle width W (both arms) | — | ✅ done (ADR-0013) |
| 11 | Keyed arm: gen_size tags (overhead parity), verify only W | 10 | ✅ done |
| 12 | ACR-only recovery variant, both arms | 10 | ✅ done |
| 13 | Isolated recovery comparison harness | 10-12 | ✅ done |
| 14 | W sweep + plots | 13 | ✅ done |
| 15 | Elaborate verification + readable smoke | 13 | ✅ done |
| 16 | Repair-span knob (payload vs whole segment) | 13 | ✅ done |
| 17 | Security: segment-splice test + partial-knowledge forgery (keyless vs keyed) | — | ✅ done, merged 2026-09-29. **Open: splice fix vs limitation**; figures plan `security-figures-plan.md` |
| 18 | Early-exit keyed MAC verification | 13 | ✅ done |
| 19 | HD feasibility frontier (HD/budget sweep) | 13 | ✅ done |
| 20 | Exclude final pool check from recovery cost | 13 | ✅ done |

Frontier now (2026-09-29): tickets 01-07, 10-20 done and merged to main. Open: **09** (headline keyless-vs-keyed figure), the **splice fix-vs-limitation decision** (ticket 17), and the security figures plan (E1 repair-bait forger, E3 more seeds, re-check ticket-17 data after the unit-tag-column guard). **08** is cut to future work. Pareto sweep (`scripts/pareto_sweep.py`) also merged; unit-tag-column guard + verifiable exact-solve rule now in tagging/repair.

Sim code is on main; branches `feat/pareto-sweep` and `feat/security-sim` are fully merged (their worktrees are kept).

2026-09-29 (branch `feat/scaling-acr`, not merged): scaling + security re-check under ACR-only
(ACR = algebraic consistency check, formerly written "ARC"). Production `acr_only` strategy, error
scopes, inner-product fast path, S1/ticket-17 re-checks done (unchanged), S2 verification-width done at
GF(2^2/4), R2/R3 size x N x BER runs in `logs/scaling_acr/`. Note: `scaling-acr-study.md`.
The ticket-17 re-check after the unit-tag-column guard is DONE (no significant change).

Note on 04 / ticket C decisions (2026-08-26, IMPLEMENTED this session): the HMAC arm is the **matched homomorphic Combined-Recovery MAC** (segmented, tag-count-matched), not the flat plain-HMAC baseline — confirmed complete, 10/10 tests pass, already produced a 100-trial sweep. Comparison-figure decisions done in code: focus N=5 both strategies; drop 1e-2; HD=2 all arms; added silent-decode + wall-clock plot panels; overhead matched tag-for-tag (salt excluded from `SegmentedScheme.tag_overhead_bits`). The final headline figure waits for 07 so keyless recovery isn't undersold — but per ticket-07 decision 5 the figure is not a blocker. Case-2/IC-refinement is now decided (**port**, ticket 07).
