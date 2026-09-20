# 14 — W sweep + plots

**In one line:** sweep `W ∈ {1,2,3}` (× BER, × config, × arm) through the harness and produce
the comparison plots + CSV.
[ADR-0013](../../../docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md).

**Why:** the headline output — how recovery rate, silent-decode, and recovery-ops move with W
in each arm/config, and the coeff-repair-stage isolation (coefficient_first vs ARC-only-(b) at
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
3. A coeff-repair-isolation plot: coefficient_first vs ARC-only-(b), whole-packet BER, per arm.
4. Long runs: background per memory `how_to_run_sims` (.venv python + `LOG_FOLDER`/`PYTHONPATH`;
   PowerShell only per memory).

**Blocked by:** 13.

**Status:** TODO.

**Done when:**
- [ ] Frozen CSV schema documented at the top of the sweep module.
- [ ] Sweep runs W∈{1,2,3} × BER × 3 configs × 2 arms → CSV.
- [ ] Plots: recovery_rate, silent_decode, recovery_ops vs BER (line per arm,W); coeff-repair-isolation panel.
- [ ] Replot-from-CSV works (no re-run needed to redraw).
