# 02 — Make the N-sweep a first-class runnable entrypoint

**What to build:** Running the segmented N-sweep is a normal, documented entrypoint rather than a commented-out line — a user (or agent) can launch it and get CSVs + plots without editing source. The runner also protects itself against high-error-rate cells that would otherwise run unbounded: each cell has a runtime cap so a slow cell degrades gracefully (fewer trials / recorded as capped) instead of hanging the whole sweep.

**Blocked by:** 01.

**Status:** DONE (branch `feat/01-per-pair-persistence`)

- [x] `run_segmented_n_sweep` is invocable as a first-class run: `python -m simulation.scheme_comparison_sim segmented` (argparse `main()`; also `smoke`/`hd`/`recovery`/`attack`, no-arg = smoke+hd). Produces raw + summary CSV and the four plots.
- [x] Per-cell runtime cap: `_run_capped_cell(trial_fn, num_trials, time_budget_s)` stops adding trials once `SEGMENTED_CELL_TIME_BUDGET_S` (default 120s, `--cell-time-budget-s`) elapses; always runs ≥1 trial. Verified: full-default sweep at 0.5s budget completed with variable trials/cell instead of hanging.
- [x] Capped condition visible: `trials_run` + `capped` columns in summary.csv; all rates divide by `trials_run`; `[capped]` print per hit cell.
- [x] Empty-legend warning fixed: `_plot_by_n_strategy` guards `legend()` behind `get_legend_handles_labels()[0]` (+ `plt.close(fig)` leak fix). Test asserts no legend warning.
- [x] Running instructions in `docs/running_sims.md` updated (first-class `-m ... segmented` + `--cell-time-budget-s`, main `.venv` + `LOG_FOLDER`/`PYTHONPATH`).

**Result:** cap is between-trials (a single in-flight trial always finishes, so wall time can overshoot by ≤1 trial). 7 new tests in `simulation/scheme_comparison_test.py`. Two-axis code-review clean; sole note (CLI can't pass `None` to disable, only large-value approximation) judged non-defect by both axes.
