# Plan: scale the recovery+decode sim to large generations

Recorded 2026-07-30. Not started. Context: `docs/recovery_decode_sim_session.md`.

## Problem

`recovery_decode_sim.py` per-round cost is ~2× `sniff_pool` (O(gen³) each) — one inside
`recover_generation_bitflip`, one in `_accepted_packets` (V>0) — re-scanning the whole
(keep-all) pool. Per trial ≈ O(gen³–gen⁴). Fine at gen≤20 (~0.4s/trial); ~40s/trial at
gen=80 → sweeps take hours. Measured ~10× cost per doubling of gen.

## Fix (in priority order)

1. **Sniff once per round, share it.** Have `recover_generation_bitflip` return its
   `(broken, trusted)`; feed that to the decode gate instead of re-sniffing. Wrinkle:
   recovery mutates the pool (repairs), so the post-repair set differs — either re-sniff
   only the changed packets, or gate the decode on trusted∪repaired directly.
2. **Incremental trust update.** Don't rebuild the O(P²) cross-check each round; on each
   new arrival, cross-check it against existing self-passers only (O(P)), maintaining
   running witness counts. Turns per-round cost gen³ → gen². Biggest win at high gen.
3. **Bound the pool** (optional). Keep-all makes P grow with overhead; a window or
   "freeze once trusted" cap limits P² blowup at high BER. Changes semantics — decide first.

## Validate

- Correctness: results must match current sim at gen=10 (decode%, silent%, overhead
  within noise) before/after — reuse `recovery_decode_test.py` invariants.
- Scaling: gen ∈ {10,20,40,80}, confirm per-trial cost drops from ~gen⁴ toward gen³/gen².

## Watch-outs

- `MIN_POOL_SIZE=10` is a fixed warm-up floor → inflates overhead for gen<10; scale it
  with gen if studying small generations.
- Behavioral note (already measured): higher gen raises V=0 silent-decode risk (0→0.17
  by gen=10 at BER=1e-3); V=2 still suppresses to 0 through gen=20. Re-confirm V=2 holds
  at gen≥40 after the rewrite.
