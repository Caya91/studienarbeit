# Incremental recovery+decode sim — session summary

Recorded 2026-07-30. Condensed record of what was decided and built this session, for
the next agent. New code: `simulation/recovery_decode_sim.py`, `simulation/recovery_decode_test.py`.

## Starting point (question)

In the one-shot `simulation/recovery_sim.py`, at BER ≥ 5e-3 recovery collapsed to ~0
*and* recovery mul-ops dropped. **Cause (single mechanism):** too few packets survive
clean → the pool never assembles a `gen_size` trusted basis → `recover_generation_bitflip`
short-circuits to `"waiting"` **before** the bit-flip search. Both the lost recovery and
the vanished ops are the same short-circuit; residual ops are just the sniff. This is
correct behaviour of a one-shot model, but **not RLNC** — RLNC keeps sending fresh coded
packets until decoding is possible.

## What we built: `recovery_decode_sim.py`

Sequential model. Per trial, an **arrival loop**: each round 1 fresh recoded packet
(`recode_rlnc_without_coeffs` count=1, new random coeff row), polluted at BER, appended
to a growing pool. Recovery runs on the whole pool each round; `"waiting"` is
non-terminal. Stop when the accepted packets reach full rank (**decodable**) or a cap of
`MAX_PACKETS_FACTOR`(=12)×gen_size arrivals (**timeout**).

Design decisions (locked): **1 packet/round**, **keep all packets** (no window), **cap
by total packets received**. One `CountingField` per trial → cumulative mul-ops to stop.

**Ground truth:** `_try_decode` actually re-decodes (`calculate_rref` → `invert_pivot_rows`)
and compares decoded systematic symbols to the known source. So `correct=False` with
`decoded=True` is a real **silent decode** (basis held a wrong packet), not a proxy.

**Metrics (replace one-shot recovery_rate):** `decode_success_rate`,
`overhead = packets_received/gen_size` (RLNC coding-overhead curve),
`silent_decode_rate` (the real safety metric), `mul_ops`. The old BER≥5e-3 "wall" now
appears as rising overhead (~1.0 → ~3 → ~7), diverging into timeouts only at 1e-2.

Entry points: `run_sweep()` (single-V baseline), `run_verify_sweep()` (BER×V),
`smoke_test()`.

## Key finding: silent decodes, and the fix

At V=0, silent decodes are common at BER≥5e-3 (0.52 @5e-3, 0.93 @1e-2). Raising the
recovery oracle's `verify_count` did **not** help → they are **not** oracle-admitted bad
repairs. They are **self-check false positives**: a corrupted packet that passes
`check_orth_packet` is never flagged broken, so it enters the decode basis on self-check
alone and poisons the whole generation. (The one-shot sim reported silent_failure≈0
because it only scored per-*packet* recovery; one sniff-missed packet corrupts the
entire *generation*.)

**Fix (decided + implemented): cross-verify before admitting to the decode basis.**
`_accepted_packets` now takes `decode_verify_count` V: admit a packet only if it also
cross-checks orthogonal to ≥ V other self-passers (= `sniff_pool`'s trust rule at
`min_trust_count=V`). V is distinct from the recovery oracle's `verify_count`.

**Result (100 trials/cell, run `logs/recovery_decode_verify_sweep/20260730_180042_trials100_gen10_m8/`):**
- **V=2 is optimal** — silent_decode_rate = 0 across the whole BER sweep; V=0 → 0.52/0.93,
  V=1 still leaks (0.07/0.20); V=3,5 identical to V=2 (diminishing returns).
- Suppression ~7×/verification (geometric, but below the naive `field_size^-V` bound
  because high-BER witnesses aren't all clean).
- Cost: overhead +14%, ~2.3× mul-ops @5e-3 (the O(n²) cross-check rescans); trivial at
  BER≤1e-3.
- At 1e-2 no V restores liveness: decode-success plateaus ~0.61–0.65 (clean-packet
  scarcity within the cap). V=2's role there is **fail-safe conversion** — silent wrong
  decodes become honest timeouts (~39%).

Default the decode gate to **V=2** for anything decoding-related. `DECODE_VERIFY_COUNT`
module default is still 0 (baseline for the sweep); set V=2 when using the model as the
recommended system.

## Loop optimisation (Option A, implemented by user)

The trial loop skips `_accepted_packets`/`_try_decode` on `"waiting"` rounds. **Verified
safe:** decodes never land on a waiting round at the current settings, because
cross-orthogonality witnesses accumulate in bulk — by the time a V-cross-verified
full-rank basis exists you have already left `"waiting"`. **Caveat:** this holds because
`decode_verify_count (2) ≤ min_trust_count (4)`; if V is pushed well below
`min_trust_count`, decodable-while-waiting rounds can reappear and the skip would drop
them. (Considered but not done: Option B — sniff once and share the O(n²) cross-check
between recovery and the decode gate; blocked by a real wrinkle — recovery mutates the
pool via repairs, so the two sniffs are on different pools.)

## Test bench: `recovery_decode_test.py`

Self-contained (no pytest; tiny PASS/FAIL harness, sets exit code). Runs directly:
`.venv/Scripts/python.exe simulation/recovery_decode_test.py`. Small sizes (GF(2^8),
gen_size=3, 2 data symbols) keep tables readable. Two halves:

- **Demos** (`demo_sniff`, `demo_try_decode`, `demo_accepted`) — narrated aligned-table
  walkthroughs that print the internal reasoning (self-check, witness counts, RREF/
  inversion, decoded-vs-source), not just return values.
- **19 deterministic tests** covering `sniff_pool` (warm-up gate, exclusive trust
  threshold, self-check failure → broken, broken packets lower witness counts, **false
  positive self-passes but is excluded from trusted**), `_try_decode` (too-few,
  underdetermined, clean, recoded full-rank, **silently-wrong → decoded-but-wrong**,
  redundant rows), and `_accepted_packets` (V=0 admits fp / no min_pool_size gate; V>0
  excludes fp and equals `sniff_pool` trusted; warm-up gate), plus an **integration
  test**: the same pool silently decodes wrong at V=0 and safely waits at V=1.

Self-check false positives are constructed deterministically by
`find_self_check_false_positive` (search bit-flips for one that self-passes but is
orthogonal to no other packet).

## Open follow-ups (not started)

1. Add BER points 2e-3, 3e-3 to sharpen the safety/liveness knee for a clean thesis figure.
2. Cheaper V-gate: incremental per-arrival trust update instead of the O(n²) re-sniff
   every round (only worth it if op-count becomes a headline metric).
3. Consider promoting the V=2 cross-verification decision to a formal ADR (ADR-0008).

## Related

- Memory: `recovery_decode_sim.md` (index in `MEMORY.md`).
- One-shot sim follow-ups: `docs/recovery_sim_followups.md`.
- Trust model: `docs/adr/0004-sniffing-trust-model.md`; defer-until-trusted:
  `docs/adr/0003-...`; acceptance oracle: `docs/adr/0001-...`.
