# 18 — Early-exit keyed MAC verification (fair ops/time comparison)

**In one line:** make the keyed acceptance check stop at the first mismatching tag, like the keyless
check already does, so recovery ops/time are compared on equal footing.
[ADR-0013](../../../docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md).

**Why:** keyless (`is_orthogonal_to_trusted`) runs the self-check first and returns on failure, so a
wrong candidate (fails with prob. 255/256) costs 1 inner product at any W → keyless ops flat in W.
Keyed (`mac_verify_segment`) computes all W tags (`mac_tag_vector(keys[:W], …)`) before comparing →
every candidate costs W inner products → keyed ops grow ~+2.6k per W step. The "keyless cheaper at
W≥4" crossover (v2 W1–6 sweep) is this implementation asymmetry, not a scheme property. Accept/reject
decisions are identical either way → recovery/silent results are unaffected; only `recovery_ops`,
`recovery_mul/add`, `recovery_time_s` are biased against keyed at W>1.

## Build to these
1. Add `early_exit: bool = False` to `mac_verify_segment` (`binary_ext_fields/segmented_mac_tagging.py`):
   verify tag i (i < W) one at a time, return False on the first mismatch. Default False → every
   existing caller keeps today's op counts.
2. Thread it through the keyed recovery path the harness uses (`segmented_mac_recovery.py` entries →
   `repair_segment_mac` → pair search / unpaired) as a default-off param; the isolated harness
   (`simulation/isolated_recovery_sim.py`) passes `early_exit=True`.
3. Re-run the v2 W sweep (gen6, W=1–6, ARC-only a+b; ~50 min / 2000 seeds) for the cost columns.

## Done when
- [x] Test: `early_exit=True` returns the same bool as `False` on random valid/invalid slices, all W.
- [x] Test: harness outcomes (recovered/silent/failed per target) identical with/without early exit;
      keyed ops strictly ≤ without.
- [x] Default path unchanged: segmented MAC + recovery suites green, op counts identical.
- [x] Re-run done; `vs_w_payload.png` keyed ops ~flat in W; selling-points doc cost caveat (D)
      updated with the fair numbers.

**Blocked by:** —. **Status:** DONE (2026-09-24), branch `feat/keyed-early-exit-hd-frontier` @ a9ac6ef.

**Result** (v3 run, 500 seeds, gen6, W 1–6, ARC-only, payload, pooled over BER; plots
`logs/isolated_recovery_plots/v3_t18_W1-6_early_exit/`): keyed ops now ~flat in W (ARC a 6.1→6.7k,
ARC b 4.7→6.1k) vs keyless 20–21k → **keyed ≈3× cheaper at every W** (time 12–14 ms vs 31–32 ms).
The earlier "keyless cheaper at W≥4" crossover was entirely the verify asymmetry — retracted.
**Superseded by ticket 20:** the ≈3× included the post-repair pool check (keyless all-pairs ~15k
ops fixed). Repair-only, keyless = **2.0× keyed** (per-candidate 13-B self-check vs 6-B tag).
