# 13 — Isolated recovery comparison harness (injected trust, paired ground truth)

**In one line:** the harness that builds a pool of clean helpers + corrupted targets, injects
trust (no sniffing), runs the 3 configs × 2 arms on **identical** corruption, and collects
per-target head-to-head + rate/ops metrics.
[ADR-0013](../../../docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md).

**Why:** this is where the comparison actually happens — everything in tickets 10–12 is wiring
this needs.

## Files
- New harness module, e.g. `simulation/isolated_recovery_sim.py` (additive; do NOT modify
  `scheme_comparison_sim.py` / `integrity_schemes.py` recovery paths — reuse their pieces).
- Reuse: `binary_ext_fields/segmented_tagging.py`, `segmented_mac_tagging.py`, the recovery
  entries (tickets 10–12), and the error injector (`pollute_generation`, imported in
  `simulation/integrity_schemes.py` — inspect its signature first).

## Build to these (ADR-0013)
1. **Pool:** `G = gen_size` ground-truth-**clean** helper packets (fixed, never corrupted) —
   ARC basis (both arms) + keyless acceptance witnesses. Plus `T` target packets (knob,
   default `gen_size`), corrupted per config, scored on.
2. **Injected trust:** hand the recovery entries the helper set directly; do NOT run
   `classify_segment_trust(_mac)`. Broken/target set is ground truth (the harness knows what
   it corrupted).
3. **Paired ground truth (common random numbers):** one shared seed fixes source payload,
   coefficient vectors, and helper/target split for both arms. The error pattern on the
   **information columns `[coeff | payload]` is applied identically** to both arms. Tag/salt
   region is **seed-matched per-arm** (different layouts — keyless salt+orth tags vs keyed MAC
   tags), not byte-identical. In config (a) data-only, errors live only in payload ⇒ both arms
   face exactly the same corruption end to end.
4. **Configs (each × both arms):**
   - coefficient_first — whole-packet BER (uses coeff repair).
   - ARC-only (a) — data-only BER (ticket 12).
   - ARC-only (b) — whole-packet BER, symmetric drop (ticket 12).
5. **Metrics over T:** recovery rate, silent-decode rate, recovery field-ops (CountingField
   phase split), plus a **per-target head-to-head** record (target i: keyless {recovered /
   silent / failed} vs keyed {…}) → win/loss/tie.
6. Knobs: `W` (default sweep {1,2,3}), `G=gen_size`, `T=gen_size`, seed.

## Correctness guard (hard — mechanics, not silent-decode levels)
- **Wiring self-check:** data-only (a) at a *strong* oracle (large W) ⇒ silent-decode ≈ 0,
  because a strong oracle rejects wrong fixes. If it isn't ~0 there, the injection/oracle
  wiring is wrong. (At small W silent-decode is *expected* to rise — that's the measured
  result, not a bug.)
- Helpers are never scored and never mutated.
- The identical-`[coeff|payload]`-error invariant is asserted (diff the two arms' information
  columns pre-recovery ⇒ equal).

## Readable smoke (the user follows this)
Ship a `--smoke` mode: one seed, small `T`, one W, all 3 configs × 2 arms, printing a
human-readable block per config — a target-by-target table (`t# | injected err | keyless →
outcome | keyed → outcome`) then a summary line (`recovered k/T, silent s, fail f, ops …`) and
the head-to-head tally. See ticket 15 for the exact format; wire the hook here.

**Blocked by:** 10, 11, 12.

**Status:** TODO.

**Done when:**
- [ ] Pool builder: G clean helpers (fixed) + T targets; helpers never corrupted/scored.
- [ ] Injected-trust path bypasses sniffing; recovery entries accept an injected helper set.
- [ ] Paired injection: identical `[coeff|payload]` errors asserted; tags seed-matched.
- [ ] All 3 configs × 2 arms run; per-target head-to-head + rate/ops collected.
- [ ] Self-check: data-only (a) at large W ⇒ silent ≈ 0.
- [ ] `--smoke` prints the readable per-target + summary block (ticket 15 format).
