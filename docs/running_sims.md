# Running simulations & scripts

Every sim/script imports `binary_ext_fields.generate_symbols`, which reads `LOG_FOLDER`
**at import time** (`pathlib.Path(os.getenv("LOG_FOLDER"))`). If it is unset the process
crashes on import with a `TypeError`. So two things must always be in place:

1. **Interpreter** — the main repo venv: `E:/projects/studienarbeit/.venv/Scripts/python.exe`
   (has numpy/matplotlib). **Git worktrees under `.claude/worktrees/*` have no own `.venv`** —
   always use the main repo's interpreter, even when running worktree code.
2. **Env** — `LOG_FOLDER` (e.g. `./logs`) and `PYTHONPATH=.`.
   `scheme_comparison_sim.py` does not self-default `LOG_FOLDER`; set it explicitly.

> **Shell — PowerShell.** The default shell here is PowerShell. The bash `VAR=value command`
> inline-env prefix does **not** work in PowerShell (it tries to run `LOG_FOLDER=./logs` as a
> command). In PowerShell set the vars first with `$env:`, then run. Each block below gives both
> forms; use the bash form only in Git Bash / WSL.

## Run worktree code (cwd = worktree so its modules are imported)

PowerShell:
```powershell
cd E:/projects/studienarbeit/.claude/worktrees/<worktree-name>
$env:LOG_FOLDER="./logs"; $env:PYTHONPATH="."
& "E:/projects/studienarbeit/.venv/Scripts/python.exe" `
  -c "from simulation.scheme_comparison_sim import run_segmented_n_sweep; run_segmented_n_sweep()"
```

bash:
```bash
cd E:/projects/studienarbeit/.claude/worktrees/<worktree-name>
LOG_FOLDER="./logs" PYTHONPATH=. \
  "E:/projects/studienarbeit/.venv/Scripts/python.exe" \
  -c "from simulation.scheme_comparison_sim import run_segmented_n_sweep; run_segmented_n_sweep()"
```

## First-class sweep entrypoints (`scheme_comparison_sim`)

Each experiment in `scheme_comparison_sim.py` is a named run — no source edit needed
(ticket 02). The segmented N×BER sweep:

PowerShell:
```powershell
$env:LOG_FOLDER="./logs"; $env:PYTHONPATH="."
& "E:/projects/studienarbeit/.venv/Scripts/python.exe" `
  -m simulation.scheme_comparison_sim segmented
```

bash:
```bash
LOG_FOLDER="./logs" PYTHONPATH=. \
  "E:/projects/studienarbeit/.venv/Scripts/python.exe" \
  -m simulation.scheme_comparison_sim segmented
```

Other names: `smoke`, `hd`, `recovery`, `attack`; no arg → `smoke` + `hd`. The segmented
run accepts `--cell-time-budget-s <sec>`: each (scheme, BER) cell runs up to `num_trials`
trials but stops adding new ones once that many wall-clock seconds elapse, so a slow
high-BER cell degrades to fewer trials instead of hanging the sweep. The `summary.csv`
`trials_run`/`capped` columns show which cells hit the cap (don't read a capped cell's
rates as full-confidence). A single in-flight trial always finishes, so actual wall time
can overshoot the budget by up to one trial.

## Long sweeps → background

High-BER segmented cells are slow (per-pair search recomputed every round, deferred —
see ADR-0012 / segmented sim status). Run detached:

PowerShell:
```powershell
$env:LOG_FOLDER="./logs"; $env:PYTHONPATH="."
Start-Process -NoNewWindow -RedirectStandardOutput logs/_run.out -RedirectStandardError logs/_run.err `
  "E:/projects/studienarbeit/.venv/Scripts/python.exe" -ArgumentList '-c','...'
```

bash:
```bash
LOG_FOLDER="./logs" PYTHONPATH=. nohup \
  "E:/projects/studienarbeit/.venv/Scripts/python.exe" -c "..." \
  > logs/_run.out 2>&1 &
```

## Output

Results land under `logs/<sim_name>/<timestamp>_trials<N>_gen<G>_m<M>/`:
`raw_results.csv`, `summary.csv`, and `*.png` plots. The run-dir naming comes from
`utils/log_helpers.get_run_log_dir`.
