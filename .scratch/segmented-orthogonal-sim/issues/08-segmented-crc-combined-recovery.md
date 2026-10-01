# 08 — Segmented CRC arm with PRAC-style Combined Recovery

**Goal:** a keyless **CRC** arm that does real **Combined Recovery** (PRAC), segmented
identically to the orthogonal / MAC arms, so it sits on the SAME recovery / overhead /
completion-time / silent-pollution axes as our scheme and the keyed MAC benchmark. This
is the "CRC like in PRAC, with combined recovery" comparator — distinct from the two
existing single-packet CRC arms (`crc_localized` / `crc_whole`), which stay as the
bare-CRC floor.

## Why this is now buildable (it was retired before, correctly)

The old Fly-PRAC dependent-group CRC was retired in the 2026-08-06 pivot (ADR-0011) as a
misunderstanding. What makes it right THIS time: the segmented arms (orthogonal + MAC)
already established the correct pairing + combined-search structure, and CRC drops into
it verbatim as an oracle. The keyed MAC (`SegmentedMacScheme`) is the closest analog —
this arm is that arm **minus the key**.

## The one fact the whole port rests on: CRC is GF(2)-linear

Combined Recovery needs `T(A XOR B) == T(A) XOR T(B)` so the combined row's tag is
`Tc = T1 XOR T2`, a real verifiable tag (paper Algorithm 1 / `_search_pair_mac`). For a
CRC with **init 0, xorout 0** over equal-length slices this holds exactly — and
`crc_recovery.crc` is already init 0 / xorout 0. So the MAC arm's literal combined filter
ports verbatim, with `crc(slice) == tag` in place of `mac_verify_segment`. **This
linearity is the load-bearing claim and must be pinned by a test (below).**

## What to build (mirror the MAC arm 1:1)

Recovery is tag-agnostic below the oracle: `plan_pairing`, `SegmentTrust`,
`PairRecoveryResult`, `SegmentRepairOutcome`, `SegmentedRecoveryReport`,
`build_segments` are all reused unchanged from `segmented_recovery.py` /
`segmented_tagging.py`. Only the tag + verify differ.

1. **`binary_ext_fields/segmented_crc_tagging.py`** — mirror `segmented_mac_tagging.py`:
   - `CrcSegment` (like `MacSegment`, but the tag suffix is a fixed **CRC-16 = 2 bytes**
     per segment, not `num_keys` field symbols; `total_length = payload_length + 2`).
   - `layout_crc_segments(gen_size, data_len, num_data_segments)` via `build_segments`
     (identical column split — no `num_keys`, no keyset).
   - `crc_tag_segment(payload) -> 2 bytes` (CRC-16 over the segment payload).
   - `tag_generation_crc(...)` assembling `[coeff-payload | coeff-crc | data0-payload |
     data0-crc | ...]`.
   - `crc_verify_segment(slice, segment) -> bool` (recompute CRC over payload, compare
     to the 2 received tag bytes). Self-sufficient, keyless. **No salt** (a CRC of 0 is
     valid — same as the MAC, unlike the orthogonal self-tag's ADR-0010 salt).
   - `check_crc_segmented(...)` ground-truth per-segment check.
2. **`binary_ext_fields/segmented_crc_recovery.py`** — mirror `segmented_mac_recovery.py`:
   - `classify_segment_trust_crc`, `recover_pair_by_combined_search_crc` (combined filter
     = `crc_verify_segment(Sc_candidate)`; then split, accept first split where BOTH
     halves' CRC verify), `_search_single_by_bitflip_crc` (unpaired fallback),
     `repair_segment_crc`, `recover_uniform_hd_crc`, `recover_coefficient_first_crc`.
   - ACR localizer for `coefficient_first`: reuse the MAC localizer logic
     (`_make_arc_localizer_mac` is tag-independent except for how trust is decided —
     swap MAC verify for CRC verify). Consider hoisting a shared localizer rather than
     a third copy.
   - Per-pair persistence: reuse the `pair_cache` mechanism; the key needs NO key state
     (keyless), so `(slice_a, slice_b, columns, hd, budget)` fully determines the result.
3. **`SegmentedCrcScheme`** in `simulation/integrity_schemes.py` — mirror
   `SegmentedMacScheme` but with **no keyset hand-off** (keyless → simpler:
   `make_source` just tags, `new_instrument` needs no `_pending_keyset`). Op counter:
   reuse `CrcInstrument` (`crc_ops` / `correction_trials`) so cost is charged in CRC's
   native currency, next to the field-mul arms in spirit only. Register both strategies
   over `SEGMENTED_N_VALUES`, mirroring `SEGMENTED_MAC_SCHEMES`.
4. **Wire into `scheme_comparison_sim.py`** — add the new arm(s) to the segmented sweep
   so CRC-combined lands on the shared BER axes next to `orthogonal`, the segmented
   orthogonal N-arms, and the MAC benchmark.

## Design decisions to confirm (don't silently pick)

- **Tag width / overhead.** Natural is CRC-16 per segment = `N*16` bits, FAR below the
  orthogonal / MAC `N*gen_size*m` bits. Recommend reporting CRC at its true (low)
  overhead — the overhead axis is exactly where the keyless-but-insecure CRC looks cheap
  and the orthogonal tag "pays" for homomorphic-under-recoding + attack resistance.
  Flag it; don't overhead-inflate CRC to match.
- **Case-2 / IC-refinement (overlapping same-position errors).** Same limitation as the
  MAC arm. Scope THIS ticket to Case-1 combined recovery + unpaired bit-flip fallback
  (honest `pairs_failed` on overlap, never silent). Case-2 is ticket 07 — extend it to
  cover this arm too once landed.
- **Recoding.** CRC is NOT homomorphic over GF(2^m) scalar mult, so its tags do NOT
  survive relay recoding — single-hop only, exactly like HMAC (ADR-0009). The recovery
  sim is single-hop, so this is fine, but it must be **documented in the module docstring
  and asserted by a test** (the honest contrast to the MAC arm's survives-recoding test).

## Very thorough tests (the user's explicit ask)

Location: `binary_ext_fields/tests/` (peer of `segmented_mac_recovery_test.py`), split as
`segmented_crc_tagging_test.py` + `segmented_crc_recovery_test.py`. Read-not-just-run
style, matching the MAC test. Required cases:

> **Three cases below are user-confirmed MUST-HAVES (2026-08-26): the linearity anchor,
> the recoding-honesty test, and the silent/false-repair-floor measurement. These are
> not optional and not to be trimmed for expediency — they are the tests that make the
> whole CRC-vs-orthogonal comparison trustworthy (sound trick / honest limits / honest
> silent-error count). Marked ★ below.**

- [ ] ★ **Linearity anchor (load-bearing):** for random equal-length slices A, B over the
      field, `crc(A ^ B) == crc(A) ^ crc(B)` and `Tc == T1 ^ T2`. Without this the whole
      combined filter is unjustified — this is the test that proves the port is sound.
      Add a negative guard: a standard CRC variant (nonzero init or xorout) BREAKS this,
      so an implementer who swaps the CRC config trips the test instead of shipping a
      silently-wrong filter.
- [ ] **Tagging round-trip:** every packet of a fresh generation verifies in every
      segment; a single flipped payload/tag byte flips exactly that segment to broken.
- [ ] ★ **Recoding honesty:** a recoded packet's per-segment CRC does NOT match (assert
      the failure) — the deliberate contrast to `test_...tag_survives_recoding` in the MAC
      suite. Documents CRC's single-hop restriction as a tested fact. (Simple XOR mixing
      still survives — that's the linearity anchor; it's the field-scalar recoding a relay
      does that breaks CRC, and that's what this test exercises.)
- [ ] **Case-1 combined recovery through the production pipeline:** two packets each with
      disjoint errors in the same segment → `recover_uniform_hd_crc` recovers both,
      `pairs_recovered` increments, and the recovered halves re-verify against their own
      CRC (no silent decode).
- [ ] **Case-2 honest failure:** overlapping same-position errors that cancel in the XOR
      combine → `ok=False`, counted `pairs_failed`, NEVER a silent wrong-packet accept.
      (Flip to a recovery assertion when ticket 07 extends here.)
- [ ] ★ **Silent / false-repair floor:** construct or search a CRC-16 collision so the
      combined filter passes on a wrong split; assert it is caught by the per-half
      re-verify (or, if genuinely undetectable, that it is COUNTED as a silent decode,
      not hidden). CRC-16's ~2^-16 collision is materially higher than the MAC's q^-V —
      the goal is NOT to prove silent errors are zero (for 16 bits they can't be), it is
      to prove the harness MEASURES them and surfaces the count in `silent_decode_rate`.
      A wrong "repair" that no oracle can catch must land in that number, never be hidden.
- [ ] **`coefficient_first` ACR narrowing engages:** the data-segment localizer returns a
      narrowed column set once coefficients are trusted (same assertion as the MAC test).
- [ ] **Per-pair cache correctness:** a repeated admit round with unchanged bytes returns
      an identical result and spends no additional `correction_trials`.
- [ ] **Scheme-level parity:** `SegmentedCrcScheme.admit` on a polluted pool returns only
      code packets that decode to the true source; `silent_decode_rate` reported, and the
      arm runs to completion inside `scheme_comparison_sim` for a small BER sweep.

## Blocked by / relation

- Independent of 07 (Case-1 only); ideally re-touch after 07 to add Case-2 here.
- Feeds ticket 04's comparison figure (the third CRC-family line: bare-CRC floor vs
  PRAC-combined-CRC vs orthogonal/MAC).

## Status: ready-for-agent
