# 07 — IC-refinement: recover the overlapping-error pairs we currently drop

**In one line:** today, when two packets in a pair are both broken at the **same byte
position**, the two errors cancel inside the XOR-combined row and the pair can't be
split → we give up and count it as `pairs_failed`. This ticket recovers those pairs
instead, in both schemes. Decision (was ticket 05): **PORT it**, don't stay
measure-only — recovery is the axis we're maximising.

**Background (why it fails now):** combined recovery XORs the two broken slices and
searches the combined row for a low-weight fix, then tries to split that fix back
across the two packets. If both packets are wrong at the *same* position, that position
XORs to zero in the combined row — invisible to the search — so no split works. The
paper's fix ("IC-refinement" / single-position-swap, Algorithm 1 lines 21–23, worked
example steps 4–6): when the combined search comes up empty, notice the overlap and
fall back to correcting **each packet on its own** against its own tag over the
narrowed positions.

## Decisions made 2026-08-26 (this session) — build to these

### 1. Do the MAC arm FIRST, test it, THEN the orthogonal arm
Two arms need this (`binary_ext_fields/segmented_mac_recovery.py` and
`binary_ext_fields/segmented_recovery.py`). They are NOT the same difficulty:
- **MAC arm (do first):** a near-verbatim port of the paper. To correct one packet:
  brute-force the narrowed positions and accept the candidate whose **homomorphic MAC
  tag** recomputes to the transmitted tag. This is the same brute-force the arm already
  does, just on one packet instead of the combined pair. The swap-refine arithmetic is
  already prototyped in the anchor test
  `binary_ext_fields/tests/segmented_mac_recovery_test.py:126-135` — lift that into
  production rather than re-deriving it.
- **Orthogonal arm (do second, after the MAC arm passes):** keyless, so there is no
  per-packet tag to brute-force against. Instead route each failed-pair packet into the
  existing single-packet **linear solve** (`recover_unpaired_segment` / ADR-0002) over
  the narrowed positions — the keyless analog. Only start this once the MAC arm is done
  and measured.

### 2. Handle single-position overlap only (for now)
Only the case where the two errors land on **one** shared position. General multi-
position overlap is much more expensive and is out of scope here — a pair with
multi-position overlap may still fail honestly (counted as before). Single-position is
what the paper does and what the anchor test covers.

### 3. Cost limit: reuse `pair_budget`, but add an "unlimited" switch
This fallback fires exactly where most pairs are broken (high BER), so it can add a lot
of search. Cap it with the **existing `pair_budget`** so high-BER cells don't blow up.
BUT add a knob to **disable the cap entirely** (unlimited search) — needed for testing
things out without a limit getting in the way. (e.g. `pair_budget=None` ⇒ unlimited.)

### 4. Correctness guard — no new silent decodes (hard requirement, not optional)
Every packet corrected by this fallback must be re-checked against its **real
acceptance oracle** before it's accepted:
- MAC arm: its homomorphic tag must verify.
- Orthogonal arm: its self + cross-orthogonality checks must pass.
A wrong "fix" that happens to pass must never enter the decode. `silent_decode_rate`
must stay 0 after this change.

### 5. Figure is not blocking
We do **not** need a final headline figure gated on this. Numbers are still moving.
Feel free to generate figures to sanity-check the effect, but treat them as
non-final. (The eventual final N=5 comparison run will come after this lands, but it is
not a blocker for this ticket.)

## Why this matters (with an honest caveat)
In run `20260821_193812_trials100_gen10_m8` the keyless orthogonal arm sits at
correct ≈ 0.88–0.92 @ 1e-3 (vs the MAC's 1.0), partly because these overlapping-error
pairs go unrecovered; `ic_refinement_failure_rate` runs 0.15–0.55, rising toward ~0.8
at 5e-3. So the main wins are (a) closing the keyless arm's recovery gap and (b) holding
recovery deeper into high BER. Caveat: where the MAC already hits 1.0 (low BER), RLNC
redundancy was already covering these failures, so the lift there is small — the payoff
is the keyless gap and the high-BER regime.

**Blocked by:** — (implementable now). Supersedes ticket 05's "measure-only" option.

**Status:** ready-for-agent

**Done when:**
- [ ] MAC arm: overlap detected (combined search exhausts) → each half brute-forced over
      the narrowed positions against its own MAC tag; done and tested first.
- [ ] Orthogonal arm: same overlap detection → each half repaired by the single-packet
      linear solve over the narrowed positions; done after the MAC arm.
- [ ] Both use `pair_budget` for the fallback search, with an unlimited override.
- [ ] `silent_decode_rate` stays 0 (every corrected half re-verified against its real
      oracle).
- [ ] The tests that currently assert honest failure on overlapping errors
      (`test_recover_uniform_hd_mac_cannot_split_overlapping_errors` and its orthogonal
      twin) are updated to assert RECOVERY instead; a same-position overlap case added.
- [ ] A check run shows `ic_refinement_failure_rate` / `pairs_failed` drop and
      `correct_rate` rise (especially the keyless arm), silent still 0. (Figure
      non-final — see decision 5.)
- [ ] ADR-0012's IC-refinement item updated: decision = ported (was leaning
      measure-only; reversed because recovery is the priority).
