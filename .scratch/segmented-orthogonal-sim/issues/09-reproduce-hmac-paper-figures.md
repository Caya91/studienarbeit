# 09 — Reproduce Fathi & Pahlevani HMAC-paper figures (keyless orthogonal vs keyed HMAC)

**Paper:** Fathi & Pahlevani 2025, *Enhancing Partial Packet Recovery in RLNC Using
Homomorphic Message Authentication Codes* ("Combined Recovery"), IEEE Comm. Letters
29(9). PDF: `C:\Users\marti\OneDrive\studienarbeit_docs\paper\Enhancing_Partial_Packet_Recovery_in_RLNC_Using_Homomorphic_Message_Authentication_Codes.pdf`.

**Goal:** redraw the paper's key figures with our **keyless orthogonal tag**
(`SegmentedScheme`) added as an extra arm alongside their **keyed homomorphic MAC**
(`SegmentedMacScheme`). Headline claim to demonstrate: the two are structurally the SAME
homomorphic tag; at equal tag width the keyless arm matches the keyed HMAC on collisions
and retransmissions — so collision resistance is a function of **tag width, not the key** —
while the keyless arm additionally survives recoding + white-box forgery analysis (ticket
06) that the paper's threat model never addresses (their paper has no adversary).

## Why buildable now

Both arms already exist and sit on shared axes: `SegmentedScheme` (keyless orthogonal) and
`SegmentedMacScheme` (keyed homomorphic MAC) in `simulation/integrity_schemes.py`.
`scheme_comparison_sim.run_recovery_sweep` already sweeps BER × scheme and emits every
metric we need (`correct_rate`, `silent_decode_rate`, `mean_overhead_decoded`,
`time_per_packet_s_mean`). What's missing: a **#segments sweep** and a **gen-size / payload
sweep** axis, plus an **8-bit tag variant** to reproduce the width collapse.

## Figures in the paper — pick list

| Fig | Shows | X-axis | Reproduce | Our metric |
|-----|-------|--------|-----------|------------|
| 1,2 | segmentation / flow schematics | — | skip | — |
| **3** | checksum collisions (CRC-8/16/32, HMAC-8/16) | # segments | **YES — anchor** | `silent_decode_rate × num_trials` = failures/1000 |
| **4** | avg packet retransmissions | # segments | **YES** | `mean_overhead_decoded` (extra pkts) |
| 5 | delay vs generation size | gen size | secondary (wall-clock) | `wall_time_s_mean` |
| 6 | delay vs payload size | payload | secondary | `wall_time_s_mean` |
| **7** | delay vs # segments | # segments | **YES — free from Fig-4 sweep** | `wall_time_s_mean` |
| **8** | delay vs BER | BER | **YES** | `wall_time_s_mean` |

Reproduce **3, 4, 7, 8**. **Fig 7 is nearly free**: it is the SAME sweep as Fig 4 (iterate
# segments at BER 10⁻⁴, g=15, payload 48 B) — only the plotted metric differs (delay per
generation instead of retransmissions). So `run_segment_sweep()` emits both Fig 4 and Fig 7
from one run. Figs 5–6 are the same idea on different axes (gen size / payload) → secondary.
Fig 3 is the strongest: it IS our silent-pollution axis and isolates the keyless-vs-keyed
difference. **All delay figures carry the wall-clock caveat** (pure-Python, single machine,
per `docs/comparison_methodology_notes.md`) — the comparison is fair *within our run*
because all arms share the same Python substrate, but absolute ms are not comparable to the
paper's numbers.

## Paper's fixed parameters (match for fairness)

- Field GF(2⁸); 1000 trials/cell.
- **Fig 3:** payload 48 B; correction repeated on 1000 faulty segments, **each with up to
  16 random bit errors**; Y = failures out of 1000 due to checksum collisions; sweep
  segment length (i.e. # segments). Schemes each have their checksum width (CRC-8/16/32,
  HMAC-8/16).
- **Fig 4:** payload 48 B, g=15, BER 10⁻⁴, 16-bit checksum each (S-PRAC/QPPR = CRC-16,
  Combined Recovery = HMAC-16). Y = avg retransmissions; sweep # segments.
- **Fig 8:** g=15, s=5, payload 10 B; sweep BER (their point: 10⁻³ → CR 9.18 ms vs QPPR
  16.59 vs S-PRAC 22.15).

**DECISION (locked 2026-08-31): use the fixed-injection model for Fig 3.** Match the
paper exactly — a fixed count of random bit errors **per segment**, not our BER coin-flip —
so collision counts are directly comparable. Keep the BER model for Fig 8 (delay-vs-BER).

### How to implement the fixed injector

The existing `pollute_random` (`binary_ext_fields/pollution.py:204`) flips each of the low
`field.bit_lenght` bits of every byte independently with prob = BER. The paper's Fig-3
model instead flips **exactly k distinct random bit positions** across the target span,
with k the "up to 16 bits of random errors". Add a sibling polluter:

```python
def pollute_fixed_bits(field, packet, num_bits, span=None, rng=random) -> bytearray:
    """Flip exactly `num_bits` distinct random bit positions within `span`
    (a (start, stop) byte range; whole packet if None). Only the low
    field.bit_lenght bits of each byte are eligible -- same constraint as
    pollute_random, so pollution stays inside the field / the recoverer's search
    space. Positions are sampled without replacement so num_bits is exact."""
    out = bytearray(packet)
    start, stop = span or (0, len(out))
    m = field.bit_lenght
    # global bit index = byte_offset * m + bit_pos, over the eligible low bits only
    total = (stop - start) * m
    num_bits = min(num_bits, total)
    for gidx in rng.sample(range(total), num_bits):
        byte_i = start + gidx // m
        bit_pos = gidx % m
        out[byte_i] ^= (1 << bit_pos)
    return out
```

Notes / decisions inside this:
- **Per-segment, not per-packet.** The paper's 16 errors are per *segment*. So the caller
  must invoke this once per segment payload span, not once for the whole wire packet — for
  the segmented arms, loop the segments' payload ranges (from `layout_mac_segments` /
  `layout_crc_segments`) and inject into each. A whole-packet call injecting `N_seg × k`
  bits is NOT equivalent (it doesn't guarantee ≥1 error per segment). Wire it at the
  segment level in `run_recovery_trial` / a new fixed-injection path, gated by a cfg flag
  (e.g. `error_model="fixed_bits"` vs `"ber"`), so the BER path stays untouched.
- **"up to 16" is a CEILING, not exactly 16.** The paper says "each with up to 16 bits of
  random errors" = at most 16, a variable count per segment — NOT a fixed 16. Draw
  `k = rng.randint(1, 16)` per segment (uniform 1..16). Lower bound is 1, not 0: a "faulty
  segment" with 0 errors is a contradiction, so exclude 0. The paper doesn't specify the
  distribution over 1..16 (uniform is the natural default) — if the redrawn Fig 3 comes
  out noticeably noisier/cleaner than theirs, that's the knob to revisit (try fixed k=16,
  or a different distribution) and note whichever we used. "bits" is literal bit-level
  flips (this paper says bits, not symbols) — matches the injector above.
- `rng.sample(range(total), num_bits)` gives distinct positions ⇒ exactly `num_bits`
  flips (BER coin-flips can't guarantee an exact count). Charge nothing to the field here
  (injection is channel noise, not attacker work) — plain `random`/`rng`, no CountingField.
- Test: assert exactly `num_bits` bit differences vs the original within `span`, and that
  no byte exceeds `field.max_value` (reuse `bit_error_rate_generation`'s diff logic).

## What to build

1. **8-bit MAC + orthogonal tag variants.** Currently the segmented MAC/orthogonal arms
   are wider. Add tag-width-8 variants (`num_keys` / tag width = 8 bits) so the width
   collapse (8-bit high collisions vs 16-bit ~zero) is reproducible for BOTH the keyed and
   keyless arm. Register in `SEGMENTED_SCHEMES` / MAC scheme list in
   `scheme_comparison_sim.py`.
2. **`run_segment_sweep()` in `simulation/scheme_comparison_sim.py`** — mirror
   `run_recovery_sweep` but iterate `SEGMENTED_N_VALUES` (num_data_segments) as the X-axis
   with BER pinned (Fig 3: fixed-error injector; Fig 4: BER 10⁻⁴). Emit the same summary
   rows. Plots:
   - Fig 3 redraw: `collisions = silent_decode_rate × num_trials` vs # segments, one line
     per scheme (orthogonal-8/16, hmac-8/16, optionally CRC-8/16/32 from `CrcScheme`).
   - Fig 4 redraw: `mean_overhead_decoded` vs # segments (Combined Recovery → 0; show
     orthogonal matches since both are homomorphic; detect-drop CRC stays non-zero).
3. **Fig 8 redraw:** reuse existing `run_recovery_sweep` with g=15, s=5, payload 10 B;
   plot `time_per_packet_s_mean` vs BER, orthogonal vs segmented_mac. Label wall-clock as
   indicative.
4. **(optional) gen-size / payload sweep** for Figs 5–6 if we want the full set — add a
   `run_gensize_sweep` axis. Low priority.

## Params & harness

- Run via main `.venv` python with `LOG_FOLDER` / `PYTHONPATH` env; background the sweeps
  (see `docs/running_sims.md`). Worktree `worktree-segmented-scheme-sim`.
- **Bump `num_trials` to 1000** for final figures (n=25 was too noisy in the CRC work).

## Acceptance

- Fig 3 redraw: 8-bit arms (both keyed + keyless) show high collisions; 16-bit orthogonal
  ≈ 16-bit HMAC ≈ 0 collisions. Keyless ≈ keyed at matched width = the headline.
- Fig 4 redraw: orthogonal and segmented_mac both → ~0 retransmissions; bare detect-drop
  arm non-zero.
- Fig 8 redraw: delay-vs-BER curves for both homomorphic arms, wall-clock caveated.
- Thesis paragraph drafted: "We reproduce Figs 3/4/8 adding a keyless orthogonal arm;
  at equal tag width keyless matches keyed HMAC on collisions/retransmissions (collision
  resistance ∝ width, not key), and additionally survives recoding + white-box forgery
  (§ ticket 06), which the keyed scheme's threat model omits."

## Related

Tickets 04 (arm build — done), 06 (attacker: keyless vs keyed MAC), 08 (PRAC CRC arm — can
share the segment-sweep plotting). Memory: `crc_hmac_comparison_baselines`,
`hmac_papers_attacker_models`, `segmented_scheme_sim_status`.
