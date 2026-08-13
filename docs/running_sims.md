# Running simulations & scripts

Every sim/script imports `binary_ext_fields.generate_symbols`, which reads `LOG_FOLDER`
**at import time** (`pathlib.Path(os.getenv("LOG_FOLDER"))`). If it is unset the process
crashes on import with a `TypeError`. So two things must always be in place:

1. **Interpreter** — the main repo venv: `E:/projects/studienarbeit/.venv/Scripts/python.exe`
   (has numpy/matplotlib). **Git worktrees under `.claude/worktrees/*` have no own `.venv`** —
   always use the main repo's interpreter, even when running worktree code.
2. **Env** — `LOG_FOLDER` (e.g. `./logs`) and `PYTHONPATH=.`.
   `scheme_comparison_sim.py` does not self-default `LOG_FOLDER`; set it explicitly.

## Run worktree code (cwd = worktree so its modules are imported)

```bash
cd E:/projects/studienarbeit/.claude/worktrees/<worktree-name>
LOG_FOLDER="./logs" PYTHONPATH=. \
  "E:/projects/studienarbeit/.venv/Scripts/python.exe" \
  -c "from simulation.scheme_comparison_sim import run_segmented_n_sweep; run_segmented_n_sweep()"
```

## Long sweeps → background

High-BER segmented cells are slow (per-pair search recomputed every round, deferred —
see ADR-0012 / segmented sim status). Run detached:

```bash
LOG_FOLDER="./logs" PYTHONPATH=. nohup \
  "E:/projects/studienarbeit/.venv/Scripts/python.exe" -c "..." \
  > logs/_run.out 2>&1 &
```

## Output

Results land under `logs/<sim_name>/<timestamp>_trials<N>_gen<G>_m<M>/`:
`raw_results.csv`, `summary.csv`, and `*.png` plots. The run-dir naming comes from
`utils/log_helpers.get_run_log_dir`.
