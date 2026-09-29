# 14 — W sweep + plots

**In one line:** sweep `W ∈ {1,2,3}` (× BER, × config, × arm) through the harness and produce
the comparison plots + CSV.
[ADR-0013](../../../docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md).

**Why:** the headline output — how recovery rate, silent-decode, and recovery-ops move with W
in each arm/config, and the coeff-repair-stage isolation (coefficient_first vs ACR-only-(b) at
whole-packet BER).

## Files
- `simulation/isolated_recovery_sim.py` (ticket 13): sweep entrypoint + CSV writer.
- Reuse plotting helpers from `simulation/scheme_comparison_sim.py` (`_plot_by_n_strategy` and
  friends) where they fit; otherwise a small local plotter.
- Consider `scripts/recovery_plots_from_csv.py` pattern (CSV-pooled replot) so plots can be
  regenerated without re-running (memory: recovery-replot-tool).

## Build to these
1. Freeze a **CSV schema** first (one row per (config, arm, W, BER, trial): recovery_rate,
   silent_decode_rate, recovery_ops, plus head-to-head win/loss/tie counts). Freezing this is
   the gate that would let plotting be split off if ever needed.
2. Plots vs BER, one line per (arm, W); separate panels/files per config. Silent-decode plot is
   first-class (it's the axis W controls).
3. A coeff-repair-isolation plot: coefficient_first vs ACR-only-(b), whole-packet BER, per arm.
4. Long runs: background per memory `how_to_run_sims` (.venv python + `LOG_FOLDER`/`PYTHONPATH`;
   PowerShell only per memory).

**Blocked by:** 13.

**Status:** DONE (2026-09-23).

**Implementation notes:**
- Schema v1 (`CSV_SCHEMA_VERSION`, `CSV_COLUMNS`) documented in the module header of
  `simulation/isolated_recovery_sim.py`; every row is checked against it (`result_rows`) and
  the writer uses `extrasaction="raise"`. One row per (config, arm, repair_span, W, BER, seed).
- `repair_span` (ticket 16) added as a sweep dimension; plots split per span.
- `run_sweep` / `sweep_seed` / `--sweep --seeds N --workers K`; one pool per seed, seeds
  parallel, CSV rewritten (seed-sorted) as each seed lands → part-way replot possible.
  Injection depends on (seed, BER) only → W/span variants of a cell are paired too.
- Grid: gen_size=G=T=6, 3 data segs × 6 B, GF(2^8), max_hd=2, budget 20000,
  BER ∈ {1e-3, 2e-3, 4e-3, 6e-3, 1e-2}, W ∈ {1,2,3}, 200 seeds (~24 s/seed serial).
- Replot: `scripts/isolated_recovery_plots_from_csv.py` (pools `logs/isolated_recovery/*`,
  one function per plot: `plot_recovery/plot_silent/plot_ops/plot_isolation`, Wilson CIs,
  hollow = < min-trials seeds) → `logs/isolated_recovery_plots/`.
- Test: `simulation/isolated_recovery_verification_test.py::test_sweep_csv_frozen_schema_and_replot`.

**Done when:**
- [x] Frozen CSV schema documented at the top of the sweep module.
- [x] Sweep runs W∈{1,2,3} × BER × 3 configs × 2 arms (× 2 repair spans) → CSV.
- [x] Plots: recovery_rate, silent_decode, recovery_ops vs BER (line per arm,W); coeff-repair-isolation panel.
- [x] Replot-from-CSV works (no re-run needed to redraw).
