# 11 — Keyed arm: carry gen_size tags (overhead parity), verify only W

**In one line:** the keyed MAC arm carries `num_keys = gen_size` tags on the wire (matching
the keyless arm's `gen_size` tag columns) but verifies only the **W-subset** at
recovery/trust — so overhead is fair and collision resistance is the tunable W.
[ADR-0013](../../../docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md).

**Why:** without this the keyed arm's wire overhead and its W don't line up with the keyless
arm — the comparison is unfair on both the overhead axis and the silent-decode axis.

## Files
- `binary_ext_fields/segmented_mac_tagging.py`: `layout_mac_segments(gen_size, data_len, num_data_segments, num_keys)`, `generate_keyset`, `mac_tag_vector`, `mac_verify_segment`.
- Config surface for the isolated harness (ticket 13) sets `num_keys = gen_size`.

## Build to these
1. In the isolated harness the keyed scheme is configured with `num_keys = gen_size`
   (keyless carries `gen_size` tag columns + 1 salt byte/segment; the 1 salt symbol is a
   negligible, separately-noted overhead detail — do NOT try to pad the keyed arm to match it).
2. Recovery/trust verify the **first W** tags (ticket 10's `W` on `mac_verify_segment`); the
   remaining `gen_size − W` tags ride the wire unused-at-recovery (that's the point: overhead
   parity without buying extra collision resistance for free).
3. Keys are i.i.d. from `generate_keyset`, so first-W are independent ⇒ `q⁻ᵂ` is exact for
   the keyed arm (contrast keyless helper-dependence — a reported result, not a bug).

## Correctness guard
- `num_keys = gen_size` must not change the homomorphic property (recoded packet's tags still
  verify) — assert with the existing recoding check.
- Overhead accounting in the harness reports keyed tag bytes = `gen_size` per segment.

**Blocked by:** 10 (needs the W-subset verify).

**Status:** TODO.

**Done when:**
- [ ] Keyed scheme instantiated with `num_keys = gen_size` builds, tags, and verifies.
- [ ] Test: only first-W tags consulted at recovery acceptance (W < gen_size), extra tags present on the wire.
- [ ] Test: homomorphism holds at `num_keys = gen_size` (recode → all tags still verify).
- [ ] Overhead readout: keyed = `gen_size` tag symbols/segment; noted vs keyless `gen_size + 1(salt)`.
