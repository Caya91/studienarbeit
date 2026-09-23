> **UPDATE 2026-09-23: tickets 14, 15 (and 16) DONE — ADR-0013 status DONE, results in its "Results"
> section.** Sweep CSV `logs/isolated_recovery/20260923_005218_gen6_T6_seeds200/`, replot
> `scripts/isolated_recovery_plots_from_csv.py`, verification `simulation/isolated_recovery_verification_test.py`.
> Below is historical.

# Handoff addendum — tickets 14 & 15 (read HANDOFF-tickets-11-15.md first)

Tickets **10, 11, 12, 13 are DONE, tested, all suites green** (bar the two pre-existing
broken rref tests). This file is the delta since the original handoff. Read that one
first for the ADR/rules; this one tells you the exact API surface and gotchas 14/15 build on.

**Nothing is committed.** All work is uncommitted on branch `feat/01-per-pair-persistence`.
New/changed files:
- `binary_ext_fields/segmented_mac_tagging.py` — `mac_tag_overhead_symbols` (T11)
- `binary_ext_fields/segmented_recovery.py` — `recover_arc_only`; new params on `repair_segment`/entries
- `binary_ext_fields/segmented_mac_recovery.py` — `recover_arc_only_mac`; mirror params
- `simulation/isolated_recovery_sim.py` — the harness + `--smoke` (T13)
- tests: `binary_ext_fields/tests/keyed_overhead_parity_w_subset_test.py`,
  `binary_ext_fields/tests/arc_only_recovery_test.py`,
  `simulation/isolated_recovery_test.py`

## How to run (unchanged)
```powershell
$env:PYTHONPATH="."; $env:LOG_FOLDER="$env:TEMP\st_logs"; mkdir $env:LOG_FOLDER -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe simulation\isolated_recovery_sim.py --smoke
.\.venv\Scripts\python.exe simulation\isolated_recovery_test.py    # exit 0 = pass
```
Judge by EXIT CODE. `ic| ...` lines on stderr are arc_pl icecream debug — ignore them.

## The harness API you'll drive for ticket 14 (the W sweep)
`simulation/isolated_recovery_sim.py`:
- `build_paired_pools(field, gen_size, data_fields, num_data_segments, T, seed) -> PairedPools`
  (helpers = indices 0..gen_size-1, targets = gen_size..gen_size+T-1). `field` must be a
  `CountingField`.
- `run_config(pools, config, ber, W, seed, max_combined_hd=2, candidates_budget=20000) -> ConfigResult`
  where `config in ("coefficient_first","arc_only_a","arc_only_b")` (constant `CONFIGS`).
- `ConfigResult`: `.keyless`/`.keyed` are `ArmResult(outcomes, ops, recovered, silent, failed)`;
  also `.inj`, `.kl_packets`, `.kd_packets`. `head_to_head(kl.outcomes, kd.outcomes)`.
- Config → error model map is fixed: coefficient_first & arc_only_b = whole-packet BER,
  arc_only_a = data-only BER (`_CONFIG_MODEL`).

**Ticket 14 = freeze a CSV schema FIRST, then sweep `W∈{1,2,3}` × BER × 3 configs × 2 arms.**
Emit one row per (config, arm, W, BER, seed) with recovered/silent/failed/ops and the
head-to-head tally. The per-target detail already exists if you want a second CSV.
Silent-decode plot is first-class (ADR). Reuse `scripts/recovery_plots_from_csv.py`
patterns if it fits (see [[recovery_replot_tool]] memory). Average over several seeds —
T is small so single-seed rates are noisy.

## Metric decisions already made (change only deliberately)
- **Ops = total GF ops** (`field.mul_count + field.add_count`) per recovery call, reset
  before each. NOT the phase split: the keyed arm isn't phase-bucketed (`_count_phase` is
  keyless-only), so total is the only apples-to-apples number. If T14 wants recovery-only
  ops, you'd have to wrap the keyed search in `field.phase("recovery")` (additive) — decide
  with the user; I left it as total.
- **Scoring:** per target — `correct` = info-columns (payloads) == ground truth;
  `accepted` = acceptance oracle passes at W on every segment (keyless: self + orth to W
  helpers; keyed: `mac_verify_segment(W)`). recovered = accepted&correct, SILENT =
  accepted&¬correct, failed = ¬accepted.
- `coeff_clean_targets` compares the coeff **payload only** (not the per-arm tag region) —
  this is what makes ARC-only's drop symmetric across arms. Don't "fix" it to full-slice.

## The result you must NOT mistake for a bug (write it up in T15)
Whole-packet configs show **keyless recovery rate << keyed**. This is real and
ADR-anticipated, not a wiring error:
- keyless self-check covers ALL redundancy (salt + every tag) for free, so any tag/salt
  bit-flip fails self-check → the packet is rejected (failed) even when its DATA is fine;
- keyed only verifies W tags, so corruption in tags[W:] rides through → if the data is
  correct the target is (correctly) counted recovered.
So keyless trades whole-packet recovery rate for stronger integrity/lower silent-decode —
exactly the tradeoff the comparison exists to measure. **The clean apples-to-apples config
is arc_only_a (data-only BER): both arms face byte-identical corruption + identical method,
and at a strong W their per-target verdicts match exactly** (this is also the wiring
self-check in `simulation/isolated_recovery_test.py`).

## New parameters threaded (all default-off; existing callers/op-counts unchanged)
On `repair_segment` / `repair_segment_mac`:
- `drop_unlocalized=False` — ARC-only: drop (don't whole-segment-search) a broken packet the
  localizer can't narrow; counted in the new `SegmentRepairOutcome.dropped` field.
- `injected_trust: SegmentTrust|None` — use ground-truth trust instead of classify.
- `bitflip_only=False` (keyless only) — bypass the ADR-0002 exact solve in the unpaired +
  IC-refine paths so both arms use bit-flip only.
On the 4 entries (`recover_coefficient_first(_mac)`, `recover_arc_only(_mac)`):
- `injected_trust_by_segment: dict[str,SegmentTrust]|None`, plus `bitflip_only` on the
  keyless two. `recover_arc_only(_mac)` also take `basis_idx`, `coeff_clean_target_idx`.

## Ticket 15 (finalization gate) checklist notes
- No pytest here — "full suite green" = every `*_test.py` in `binary_ext_fields/tests/` and
  `simulation/` exits 0 except `rref_test.py` / `procedural_rref_test.py` (pre-existing).
- W=None default path is proven unchanged (all old segmented + MAC recovery tests pass).
- Elaborate correctness mostly already covered by the three new test files; 15 wants the
  edge cases (W=0 keyless, W=gen_size, odd broken count → unpaired path, helper set exactly
  gen_size) and the human-readable smoke (already shipped: `--smoke`, deterministic).
- Then flip ADR-0013 status to DONE with the measured silent-decode numbers from the T14 sweep.

Full context also in memory `[[isolated-recovery-comparison]]`.
