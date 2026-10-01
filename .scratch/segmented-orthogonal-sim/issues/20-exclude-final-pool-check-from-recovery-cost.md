# 20 — Exclude the final pool check from the harness recovery cost

**In one line:** stop charging the post-repair `report.ok` pool check to recovery ops/time in the
isolated harness; report it as its own column instead.
[ADR-0013](../../../docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md).

**Why:** every recovery entry ends with a whole-pool consistency check for `report.ok` —
keyless `check_orth_segmented` (all packet PAIRS, O(M²): ~15k ops fixed at gen6) vs keyed
`check_mac_segmented` (each packet vs own tags, O(M): ~3.5k). The harness never uses `report.ok`
(scoring is separate) but counts it inside the recovery window → a flat ~11.5k-op penalty on keyless.
Profile (ACR-only (a), W=2, HD=2): at BER 1e-3 it is 98 % of keyless ops; repair-only cost is
0.3k vs 0.2k; at 1e-2 repair-only is 15.1k vs 8.4k (≈1.8×, from the 13-B whole-segment self-check vs
keyed's 6-B payload tag). The reported "keyed ≈3× cheaper" (ticket 18) is inflated by this.

## Build to these
1. `final_check: bool = True` on the 6 recovery entries (`recover_uniform_hd`, `recover_arc_only`,
   `recover_coefficient_first` + `_mac` versions). False → skip the pool check, `report.ok = None`.
   Default True → every existing caller unchanged (ops + result).
2. Harness `run_config`: call entries with `final_check=False`; afterwards run the arm's pool check
   on the repaired pool in its own ops/time window → new per-arm CSV columns `final_check_ops`,
   `final_check_time_s` (schema v4). `recovery_ops/mul/add/time_s` = repair only.
3. Re-run T18 (W 1–6), T19a (HD payload), T19b (HD segment) with the same seeds; replot to new
   `v4_*` dirs. Outcomes must equal the v3 runs row for row.

## Done when
- [x] Test: harness outcomes identical with/without `final_check`; repair ops + final_check_ops ==
      old recovery_ops (same seed, per arm).
- [x] Default path unchanged (full suite green).
- [x] Re-runs done, outcomes == v3; ADR/ticket 18/selling-points doc cost statements updated with
      repair-only numbers (+ final-check cost stated separately).

**Blocked by:** —. **Status:** DONE (2026-09-25), branch `feat/keyed-early-exit-hd-frontier` @ f747bb7.

**Result** (v4 re-runs, same seeds; outcomes == v3 in all 690k rows; plots `logs/isolated_recovery_plots/v4_*`):
- Final pool check (now `final_check_ops`): keyless 14.98k fixed, keyed 2.7–3.4k.
- **Repair-only ops: keyless = 2.0× keyed at every BER and W** (ACR a W=2: 439 vs 256 at 1e-3,
  15.7k vs 8.7k at 1e-2; pooled W1–6: 5.5–6.1k vs 2.7–3.3k). Matches the per-candidate check cost
  (13-B whole-segment self-check vs 6-B payload tag). Time: keyless 14–15 ms vs keyed 10–13 ms (≈1.4×,
  Python overhead dilutes the ops ratio).
- HD sweep (ACR a, 1e-2, W=2, uncapped) repair-only mean ops keyless/keyed: HD2 15.8k/8.7k,
  HD3 54.9k/27.9k, HD4 148k/71k, HD5 320k/139k — ratio ~2–2.3 at every depth.
