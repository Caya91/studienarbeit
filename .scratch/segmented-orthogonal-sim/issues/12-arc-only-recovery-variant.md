# 12 — ARC-only recovery variant (skip coeff-repair), both arms

**In one line:** a recovery config that ARC-localizes + bit-flips the data segments directly
from the injected helper basis, **without** the coefficient-first coeff-repair stage — so the
coeff-repair stage is removed as a source of arm-to-arm difference.
[ADR-0013](../../../docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md).

**Why:** coefficient_first's coeff-repair success can differ between arms and propagate into
which packets become coeff-trusted for ARC — a confound. ARC-only makes ARC availability
identical in both arms, isolating the pure data-segment recovery.

## Files
- `binary_ext_fields/segmented_recovery.py`: `recover_coefficient_first` / `_make_arc_localizer` / `repair_segment`.
- `binary_ext_fields/segmented_mac_recovery.py`: `recover_coefficient_first_mac` / `_make_arc_localizer_mac` / `repair_segment_mac`.

## Build to these (ADR-0013)
1. New entry (or `arc_only=True` flag) that: builds the ARC localizer from the **injected
   helper basis** (ticket 13 supplies it), then repairs the **data segments only** via
   ARC-narrowed pairing + bit-flip; the coeff segment is NOT repaired (coeffs assumed clean).
2. Runs in **both** error models (ticket 13 drives which):
   - **(a) data-only BER** — coeff block never corrupted; ARC always applies.
   - **(b) whole-packet BER** — a target whose coeff block is corrupted is **dropped
     symmetrically** in both arms (identical handling), never half-repaired.
3. Mirror the two arms exactly except the oracle — same as coefficient_first's `_mac` mirror.

## Correctness guard
- ARC-only must reduce to the same data-segment repair as coefficient_first *when coeffs are
  clean* — assert equivalence on a clean-coeff fixture (mechanics correctness).
- Symmetric drop in (b): identical set of dropped targets across arms for the same corruption.
- Silent-decode is **measured, not bounded** — ARC-only may differ from coefficient_first; the
  requirement is correct mechanics on clean coeffs, not a silent-decode level.

**Blocked by:** 10.

**Status:** TODO.

**Done when:**
- [ ] ARC-only entry/flag in both arms, coeff segment left unrepaired.
- [ ] Test: clean-coeff fixture → ARC-only data-segment result == coefficient_first data-segment result.
- [ ] Test (b): coeff-corrupted target dropped identically in both arms.
- [ ] Silent-decode recorded for ARC-only per arm (a measured output, no ceiling).
