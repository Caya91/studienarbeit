# Recovery sim — deferred follow-ups (ADR-0007 bit-flip recovery)

Two known refinements to `simulation/recovery_sim.py` / `playground/new_recovery.py`,
deferred by decision. Recorded 2026-07-23.

## 1. Reset the op counter after sniffing

**What:** In `run_paired_trial`, `mul_ops`/`add_ops` currently count the *whole*
`recover_generation_bitflip` call, which includes `sniff_pool`. Reset the
`CountingField` counter *after* sniffing so the ops metric reflects only the
bit-flip search.

**Why:**
- `sniff_pool` is O(pool²) inner products — a large, roughly constant cost that
  is independent of `hamming_distance`.
- It swamps the search cost we actually want to study (at BER=0, ops ≈ 66.8k with
  *zero* recovery — pure sniff).
- It is identical for both modes, so it adds no signal to the A/B comparison, only
  offset.
- Consequence: "recovery cost vs d" plots are shifted by a constant and the
  d-scaling is compressed/masked.

**Cost of doing it:** `recover_generation_bitflip` must expose the sniff→search
boundary (e.g. reset the counter internally after sniff, or return sniff/search
ops separately). Minor API change.

**Keep as-is if:** you want "total cost to recover including detection" as the KPI
(also a defensible framing). Then document that sniff is included.

## 2. Cap `whole_packet` (mode A) at d ≤ 2

**What:** Restrict the exhaustive upper-bound mode to `hamming_distance` ≤ 2, or
run it with far fewer trials at d ≥ 3.

**Why:**
- Search size is C(packet_bits, d). For ~150-bit packets: d=2 → ~11k candidates,
  d=3 → ~550k candidates per broken packet.
- Each candidate costs M+1 inner products (the oracle).
- Measured: BER=0.004, d=2 already hit 5.5M ops/trial. d=3 × 100 trials is
  minutes-to-hours of runtime for a *baseline* whose only job is to bound mode B.
- Diminishing returns: A only differs from B at d ≥ 2 (at d=1 they are identical),
  and the multi-column cases A uniquely catches get rare fast at the low BERs where
  the trusted basis survives.

**Keep uncapped if:** you specifically want the d=3 multi-column upper bound and
can afford the runtime (e.g. a one-off run with NUM_TRIALS reduced).
