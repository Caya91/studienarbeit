# 10 — Matched acceptance-oracle width W (both arms)

**In one line:** add a `W` width knob to *both* recovery-acceptance oracles so keyless
(orthogonality to W helper packets) and keyed (W verified MAC tags) gate a fix with the
same nominal collision `≈ q⁻ᵂ`. Foundation for [ADR-0013](../../../docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md); everything else blocks on it.

**Why first:** this is the load-bearing shared invariant — the W meaning must be *identical*
across the two oracles or the whole comparison is confounded. Get it right and tested before
anything is built on top.

## Files
- Keyless oracle: `is_orthogonal_to_trusted(field, candidate, trusted_packets)` — `playground/new_recovery.py:110`.
- Keyed oracle: `mac_verify_segment(field, keys, segment_slice, segment)` — `binary_ext_fields/segmented_mac_tagging.py:149`.
- Keyless call sites (thread W through, default unchanged): `binary_ext_fields/segmented_recovery.py` — `_search_pair_by_combined_search` (combined filter + both split verifies), `_search_single_by_bitflip`, `recover_unpaired_segment`, `_ic_refine_pair`.
- Keyed call sites: `binary_ext_fields/segmented_mac_recovery.py` — `_search_pair_mac`, `_bitflip_search_mac`, `classify_segment_trust_mac` (leave classification unchanged for now — W is recovery-acceptance only).

## Build to these (ADR-0013)
1. **Default = unchanged.** `W=None` ⇒ check ALL (keyless: whole trusted list; keyed: all tags). Every existing caller keeps today's behaviour — zero regression. New signatures take `W: int | None = None`.
2. **Keyless:** with `W`, check self-orthogonality (always, free, uncounted) AND orthogonality to the **first W** trusted packets only (`trusted_packets[:W]`).
3. **Keyed:** with `W`, recompute and compare only the **first W** tags (`keys[:W]`, `recv_tags[:W]`). Requires `num_keys ≥ W` (ticket 11 sets `num_keys=gen_size`).
4. **Recovery-acceptance only.** Do NOT touch `verify_count` / sniffing trust classification (kept for other sims per ADR-0013).

## Correctness guard (hard)
- The self-check stays mandatory in the keyless oracle regardless of W (it is free structure, not one of the W).
- **Default path unchanged:** with `W=None` the whole existing suite stays green — this is about not breaking existing callers, careful mechanics only. It is NOT a silent-decode ceiling: once W is capped, silent-decode is expected to move and is a *measured output* (see ADR-0013), not a regression.

**Blocked by:** — (do first).

**Status:** DONE (2026-09-20).

**Implementation notes:**
- Oracles gained `W: int | None = None` (None = today's behaviour): `is_orthogonal_to_trusted`
  (`playground/new_recovery.py`) caps the cross-check to `trusted_packets[:W]`, self-check
  always applied and uncounted; `mac_verify_segment` (`binary_ext_fields/segmented_mac_tagging.py`)
  verifies `keys[:W]` vs the first W tag symbols, asserts `W <= num_keys`.
- `W` threaded top-to-bottom through both arms (`segmented_recovery.py`,
  `segmented_mac_recovery.py`): `recover_uniform_hd(_mac)` / `recover_coefficient_first(_mac)`
  → `repair_segment(_mac)` → pair search + `_ic_refine_pair` + unpaired/bit-flip. **`W` is in
  BOTH pair caches' keys** (a cache built at one W must not be reused at another).
- Deliberately NOT capped (verified by grep audit): `classify_segment_trust_mac` (trust, out of
  scope), `check_mac_segmented` (ground-truth ok check), `new_recovery.py:388` non-segmented
  whole-packet oracle (default unchanged).
- New tests: `binary_ext_fields/tests/w_acceptance_width_test.py`.

**Done when:**
- [x] `W=None` default path unchanged: segmented + MAC + pipeline + tagging suites all green (exit 0). (Pre-existing unrelated failures only: `rref_test.py`, `procedural_rref_test.py` — files untouched by this change.)
- [x] Keyless rate test: empirical pass rate ~q⁻ᵂ (self-only 1255/20000≈1/16; +1 witness ratio 0.059≈1/16), monotonic in W, `W=None == W=len(trusted)`.
- [x] Keyed rate test: first-W-tags match at ~q⁻ᵂ (ratio 0.072≈1/16); `W>num_keys` asserts.
- [x] Keyless self-check rejects a non-self-orthogonal candidate even at W=0 / empty trusted.
- [x] W threaded through every keyless + keyed recovery-acceptance call site (grep audit clean); exact cap-semantics proven by deterministic construction tests (pass first k, fail k+1).
