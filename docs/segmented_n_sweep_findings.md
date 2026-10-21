# Segmented N-sweep findings (ticket 03)

Run: `logs/scheme_comparison_segmented_n_sweep/20260916_215934_trials20_gen10_m8/`
gen=10, m=8, 20 trials/cell, BER ∈ {1e-4, 5e-4, 1e-3, 5e-3}, 120 s/cell cap.
Ranking rule: correct-decode rate first, mean overhead tiebreak, then time/ops.

## Confidence caveat (read first)
The **5e-3 column is not trustworthy** — nearly every 5e-3 cell hit the time cap at
`trials_run = 1` (a single trial). N=2 also capped at 1e-3 (4 trials). Treat 1e-4 / 5e-4 /
1e-3 as the reliable range; 5e-3 is directional only. A dedicated high-BER run (larger cap,
fewer schemes) is needed if the 5e-3 regime becomes a headline.

## Best N and strategy
**Winner: keyless segmented, N=5, coefficient_first.**
Across the reliable BER range all keyless segmented variants tie at correct_rate = 1.0, so
the tiebreaks decide — and they move monotonically with N:

| variant (at BER 1e-3) | correct | overhead | wall s | scheme_ops |
|---|---|---|---|---|
| uniform_hd N2 | 1.0 | 1.30 | 57.5 (4 trials) | 55.9M |
| coeff_first N2 | 1.0 | 1.25 | 38.3 (4 trials) | 36.7M |
| uniform_hd N3 | 1.0 | 1.13 | 4.60 | 4.3M |
| coeff_first N3 | 1.0 | 1.11 | 4.33 | 4.1M |
| uniform_hd N5 | 1.0 | 1.10 | 2.00 | 1.8M |
| **coeff_first N5** | **1.0** | **1.09** | **1.50** | **1.38M** |

**More segments is strictly better here:** each segment's HD search space shrinks, so higher
N *lowers* overhead, wall-time, and op-count at once while holding recovery at 1.0. N=2 is so
slow it can't even finish 20 trials at 1e-3. N=5 is the best tested; higher N is bounded by
the rank floor at fixed payload (see `scripts/segmented_retransmit_sweep.py`).

## Strategy call: coefficient_first ≥ uniform_hd
coefficient_first has equal or lower overhead and time than uniform_hd at every N (never
worse on recovery). It is not a hard domination (both hit correct_rate 1.0 in-range), but it
is a consistent second-order win. **Recommend defaulting to coefficient_first; uniform_hd is
the prune candidate** — confirm with a higher-BER run before deleting, since the only cell
that separated them (N5 @ 5e-3, 1 trial) favored coefficient_first (1.0 vs timeout).

## Keyless vs keyed (headline, feeds ticket 09)
At N=5, 1e-3: keyless coeff_first = correct 1.0 / overhead 1.09 / silent 0.0 / 1.5 s;
keyed MAC coeff_first = correct 1.0 / overhead 1.04 / silent 0.0 / 2.78 s.
**Keyless matches the keyed benchmark on recovery (both 1.0) and silent-safety (both 0.0),
at slightly higher transmission overhead but lower computation — i.e. near-benchmark
performance with no key distribution.** This is the thesis's headline claim, now backed by data.

## Silent false-repair (the CRC hazard — the safety money-shot)
`crc_whole` (N=1) **silently decodes wrong**: silent_decode_rate 0.05 / 0.5 / 0.3 at
5e-4 / 1e-3 / 5e-3, dragging correct_rate to 0.5 at 1e-3. Every tag-based scheme —
orthogonal, keyless segmented, keyed MAC — holds **silent_decode = 0.0 everywhere**. This is
the direct empirical case for the tag over a checksum, and for the whole comparison axis.

## Figures produced (archived in the run dir)
recovery_rate / overhead / silent_decode / time_per_packet / wall_time / detection_ops /
recovery_ops / ic_refinement_failure — all `*_vs_ber_by_n.png`.

## Follow-ups
- [ ] High-BER (5e-3+) run with a larger per-cell cap to firm up that column + settle the
      uniform_hd prune.
- [ ] For ticket 09, redraw the keyless-vs-keyed panels at N=5 with the ARQ (CRC/MAC
      detect-drop-resend) reference labeled per `docs/arq_baseline_framing.md`.
