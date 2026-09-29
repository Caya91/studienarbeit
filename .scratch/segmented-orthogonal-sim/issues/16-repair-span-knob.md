# 16 — Repair-span knob (payload vs whole-segment), both arms

**In one line:** a `repair_span` knob on the recovery entries that decides which columns
the bit-flip repair may touch — `"payload"` (today: ACR-narrowed data columns only) or
`"segment"` (also the salt/tag redundancy columns) — so a corrupted salt/tag byte can be
repaired instead of honest-failing. [ADR-0013](../../../docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md).

**Why:** in the isolated harness (`bitflip_only=True`) the search is restricted to the
ACR-narrowed payload columns, so a whole-packet-BER flip that lands in the salt (keyless)
or tag (keyed) region is never searched — the packet honest-fails even when its *data* is
clean (the config-3 `info: none` targets). The default (non-`bitflip_only`) pipeline already
searches the whole segment in its unpaired fallback; this knob exposes that span in the
matched-method comparison so we can *measure* the recovery-vs-silent-decode tradeoff of
repairing redundancy bytes, per arm, on identical corruption.

## Files
- Keyless: `binary_ext_fields/segmented_recovery.py` — `_make_arc_localizer`,
  `recover_arc_only`, `recover_coefficient_first`; new shared helper `_redundancy_columns`.
- Keyed: `binary_ext_fields/segmented_mac_recovery.py` — `_make_arc_localizer_mac`,
  `recover_arc_only_mac`, `recover_coefficient_first_mac` (imports `_redundancy_columns`).
- Harness: `simulation/isolated_recovery_sim.py` — `run_config`, `run_smoke`, `print_smoke`,
  `main` (`--repair-span`).

## Build to these
1. **Default = unchanged.** `repair_span="payload"` ⇒ localizer returns exactly today's
   ACR-narrowed data columns. Every existing caller keeps today's behaviour — zero regression.
   New params take `repair_span: str = "payload"`.
2. **The span lives in the localizer.** `repair_span="segment"` ⇒ the localizer appends the
   data segment's redundancy columns (`range(payload_length, total_length)` — salt+tags
   keyless, tags keyed) to each *non-None* returned list. A `None` (unlocalizable, coeff
   untrusted) stays `None` — so `drop_unlocalized`'s symmetric drop is untouched.
3. **Rides the existing column plumbing.** No change to the search functions, `repair_segment`,
   or the pair-cache key: the searched columns already flow through `candidate_columns_for`
   and are already part of `_pair_cache_key` (a wider span is automatically a distinct key).
4. **Scope = data-segment ACR localizers only.** The coeff segment (repaired with
   `candidate_columns_for=lambda i: None`) keeps its current behaviour; this knob is about the
   data-segment repair span, matched across both arms.
5. **Harness:** thread `repair_span` through `run_config`/`run_smoke`, print it in the smoke
   header, add `--repair-span {payload,segment}` to `main`.

## Correctness guard (hard)
- `repair_span="payload"` default path unchanged: segmented + MAC + pipeline + ACR-only +
  harness suites all green (exit 0).
- Matched across arms: both arms take the same `repair_span` in the harness — keyless has one
  extra redundancy column (the salt byte) the keyed arm lacks; that asymmetry is the known
  salt-overhead item (ticket 11), not equalized here.
- **Silent-decode is measured, not bounded.** `"segment"` is expected to raise keyless
  silent-decode (a weak whole-segment search can accept a collision fix that passes the
  ~1/q oracle — see `segmented_recovery.py` `_ic_refine_pair` warning). The requirement is
  correct mechanics + honest reporting of the tradeoff, not a silent-decode level.

**Blocked by:** 10 (W), 12 (ACR-only entries), 13 (harness).

**Status:** DONE (2026-09-21).

**Implementation notes:**
- Shared helper `_redundancy_columns(segment)` (`segmented_recovery.py`) returns
  `range(payload_length, total_length)` — salt+tags (keyless) / tags (keyed); the keyed
  module imports it rather than mirroring it.
- `repair_span: str = "payload"` threaded top-to-bottom in both arms:
  `recover_arc_only(_mac)` / `recover_coefficient_first(_mac)` → `_make_arc_localizer(_mac)`.
  The localizer appends `extra` (redundancy cols) to each **non-None** result via
  `sorted(set(payload) | set(extra))`; `None` stays `None`. Asserts `repair_span in
  {payload, segment}`.
- **No change** to the search functions, `repair_segment(_mac)`, or the pair-cache key —
  the widened span rides `candidate_columns`, already in `_pair_cache_key`.
- Harness: `run_config` / `run_smoke` / `print_smoke` / `main` (`--repair-span`).
- New tests: `binary_ext_fields/tests/repair_span_test.py`.

**Done when:**
- [x] `repair_span` on both arms' entries + both localizer builders; default `"payload"` =
      zero regression (9 suites green, exit 0).
- [x] `"segment"` span: a salt/tag-only-corrupted, payload-clean target that honest-fails at
      `"payload"` (under `bitflip_only`, the comparison mode) is *recovered* at `"segment"`,
      byte-for-byte — asserted both arms.
- [x] `drop_unlocalized` symmetric-drop preserved: an unlocalizable packet returns `None`
      under both spans (localizer test).
- [x] Cache correctness: `"segment"` cols are a *strict superset* of `"payload"` cols ⇒
      distinct `candidate_columns` ⇒ distinct pair-cache key (localizer test).
- [x] `--repair-span` wired into `--smoke`; header shows `repair_span=…`.
- [x] Smoke re-run (seed 7, W=2): payload-span output reproduces the prior run byte-for-byte;
      at segment span config-3 (`arc_only_b`) keyless goes **0/8 → 3/8** (`info:none`/salt-hit
      t6, t12 now recover), keyed **4/8 → 6/8**. Silent-decode stayed 0 at this seed (the
      predicted rise is possible, not guaranteed per-seed); ops rose as expected (wider search).
