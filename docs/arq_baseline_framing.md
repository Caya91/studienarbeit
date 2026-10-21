# ARQ baseline framing (closes thesis requirement #3)

Requirement #3: "Evaluating detection speed and recovery effectiveness compared to
**conventional ARQ**." This note fixes what "conventional ARQ" means in this project so
the report can claim the comparison explicitly. **No new code is required** — the arm
already exists, unnamed.

## What "conventional ARQ" is here
Conventional ARQ = detect a corrupt packet, **drop it, and pull another** (retransmit)
until enough clean packets accumulate to decode. There is no in-place repair.

In `simulation/scheme_comparison_sim.py::run_recovery_trial`, this is exactly the
behaviour of the **CRC and homomorphic-MAC arms** when a check fails: the polluted
packet is not admitted, the loop pulls a fresh recoded packet, and `received` climbs.
So the retransmission-based arms *are* the ARQ reference.

## The ARQ comparison axis
`overhead = packets_to_decode / gen_size` (packets pulled to reach a decodable basis).

- **Conventional ARQ (CRC / MAC detect-and-drop):** overhead > 1 and rises with BER —
  every corrupted packet costs one extra transmission.
- **Orthogonal tag / segmented (repair in place):** admits corrupted packets and repairs
  them, so overhead stays near 1 — this is the headline gain over ARQ.
- `scripts/segmented_retransmit_sweep.py` already reports `retransmits =
  packets_to_decode - gen_size`, i.e. the ARQ cost, as a function of segment count N.

## Metrics that answer #3
| #3 sub-claim | Metric | Where |
|---|---|---|
| detection speed | packets/ticks until first corruption caught | comparison sim |
| recovery effectiveness vs ARQ | decode-success rate + overhead (transmissions) | comparison sim, retransmit sweep |
| cost of ARQ | `packets_to_decode - gen_size` | retransmit sweep |

## To do in the report (writing only)
1. State the definition above once (detect-drop-retransmit = conventional ARQ).
2. Label the CRC/MAC overhead curve as the ARQ reference line in the headline figure.
3. Frame the orthogonal/segmented overhead≈1 result as the gain over ARQ.

## Optional (only if a reviewer asks for a no-coding reference)
A pure uncoded stop-and-wait ARQ arm (no RLNC at all) could be added, but it is a
strictly weaker baseline than the CRC-on-coded arm already present and is **not required**
by the task. Keep as future work unless requested.
