# 15 — Elaborate verification + readable smoke (finalization gate)

**In one line:** before ADR-0013 is called done, prove — with elaborate tests, a full
regression pass, and a human-readable smoke report the user can follow — that it works as
intended and added no new errors (especially no new silent decodes).
[ADR-0013](../../../docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md).

**Why:** the W-oracle change touches the acceptance path in both arms, so the *mechanics* must
be careful and correct and the untouched paths must stay untouched. Note: silent-decode is a
**measured output that may rise** under capped-W bit-flip — that rise is a result to report,
NOT a regression. "No new errors" here means no bugs / no behaviour change on default+untouched
paths, not a silent-decode ceiling.

## A. No regressions on untouched/default paths (careful mechanics)
- [x] Full `pytest` suite green BEFORE any change (record baseline) and AFTER each ticket.
- [x] `W=None` default path proven behaviour-identical to pre-change (ticket 10) — the
      existing segmented + MAC recovery tests must pass unchanged.
- [x] Existing end-to-end sim + sniffing path untouched: a spot-run of
      `scheme_comparison_sim.py` (segmented sweep) matches a pre-change reference run.

## B. Elaborate correctness (works as intended)
- [x] W semantics match across arms: for the same W, empirical wrong-accept rate tracks
      `q⁻ᵂ` in both (keyed exact; keyless a floor, gap reported not hidden).
- [x] Injected-trust harness self-check: data-only (a) at large W ⇒ silent-decode ≈ 0.
- [x] Paired invariant: `[coeff|payload]` corruption byte-identical across arms (asserted).
- [x] Symmetric drop (b): identical dropped-target set across arms.
- [x] ACR-only == coefficient_first on data segments when coeffs clean.
- [x] Silent-decode is correctly **measured and reported** per (arm, config, W). It MAY rise vs
      the exact-solve/full-pool baseline (weaker capped-W bit-flip gate) — that rise is the
      result, not a failure. Verify the number is right, not that it's low.
- [x] Edge cases: W=0 (self-check only, keyless) and W=gen_size; T with an odd broken count
      (unpaired path); helper set exactly gen_size (ACR basis minimal).

## C. Readable smoke (the user follows this)
A `--smoke` run (ticket 13) that prints, per config, a block like:

```
=== config: ACR-only (data-only BER)  |  arm pair, W=2, seed=7, G=10, T=10 ===
 t# | injected errs         | KEYLESS        | KEYED
  0 | data[3] 1 bit         | recovered ✓    | recovered ✓
  1 | data[1],data[7] 2b    | recovered ✓    | SILENT ✗ (wrong-accept)
  2 | coeff[2] 1 bit        | failed  –      | failed  –
 ...
 summary  keyless: rec 8/10  silent 0  fail 2  ops 1.2e4
          keyed  : rec 7/10  silent 1  fail 2  ops 3.1e4
 head-to-head    keyless-only-win 2  keyed-only-win 1  both 6  neither 1
```
- [x] Legend printed once (✓ recovered / ✗ SILENT wrong-accept / – honest fail).
- [x] One block per config (3) × arm-pair; final overall tally.
- [x] Output is deterministic for a fixed seed (so the user can re-run and diff).
- [x] Runs fast (small T, one W) and is documented in one line of how-to (PowerShell, .venv).

**Blocked by:** 13 (smoke hook), 14 (sweep for the reference run); A/B testable as each ticket lands.

**Status:** DONE (2026-09-23).

**Implementation notes:**
- A: baseline + after suite (every `*_test.py` in `binary_ext_fields/tests/` + `simulation/`): all exit 0 bar
  pre-existing `rref_test.py` / `procedural_rref_test.py`. Reference run = temp worktree at `d72fa08`
  (pre-ticket-10), fixed-seed `run_recovery_trial` for all 8 segmented/MAC N=2,3 schemes (24 trials,
  wall-time dropped) → byte-identical incl. op counts. ("pytest" here = the script-style suite; no pytest installed.)
- B/C: new `simulation/isolated_recovery_verification_test.py` (9 tests): q⁻ᵂ Monte Carlo (keyed exact; keyless
  ≈q⁻⁽ᵂ⁺¹⁾ on random errors), keyless coeff-segment blind-spot mechanism (explains coefficient_first keyless
  silent decodes), constructed scoring buckets, W=0, W=gen_size (0 silent all configs), odd broken count
  (unpaired path asserted via `SegmentRepairOutcome`), helper set = identity gen_size, smoke determinism/shape,
  sweep CSV schema + replot. Paired invariant / data-only strong-W / symmetric drop / ACR-only==coefficient_first
  already covered by `isolated_recovery_test.py` + `arc_only_recovery_test.py`.
- Harness additions: `run_config(..., inj=)` (hand-built injection) and `ConfigResult.kl_report/kd_report`.
- Measured silent-decode numbers recorded in ADR-0013 "Results".

**Done when:** A, B, C all checked and the ADR-0013 status line is updated to DONE with the
measured silent-decode result recorded.
