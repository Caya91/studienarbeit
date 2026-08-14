"""Overnight headline run of the segmented N x BER sweep (ADR-0012, ticket 02).

Self-contained: sets LOG_FOLDER/PYTHONPATH before importing, so you can launch it
with just the venv python -- no env exports needed. Bumped trial count for a
meeting-grade run; the per-cell wall-time cap keeps the total bounded so a slow
high-BER cell can't eat the whole night.

Launch (see the bottom of this file's docstring for the detached form):
    E:/projects/studienarbeit/.venv/Scripts/python.exe scripts/run_overnight_segmented.py

Total runtime is bounded by CELL_BUDGET_S x (#cells). #cells = (1 baseline + N_values x
strategies) x #BERs. With the defaults below that's 7 schemes x 4 BERs = 28 cells, so the
worst case is 28 * 1800s = 14h, but only the ~6 high-BER segmented cells actually cap --
the fast cells finish in seconds, so a typical night is far shorter. Lower NUM_TRIALS or
CELL_BUDGET_S if your window is tighter.
"""

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

import matplotlib
matplotlib.use("Agg")  # headless: don't try to open a window overnight

from simulation.scheme_comparison_sim import run_segmented_n_sweep

# ── Knobs (edit these) ───────────────────────────────────────────────────────
NUM_TRIALS = 200      # per (scheme, BER) cell, capped by time below
CELL_BUDGET_S = 1800  # 30 min max per cell; a hot cell gets fewer than NUM_TRIALS

if __name__ == "__main__":
    run_dir = run_segmented_n_sweep(num_trials=NUM_TRIALS, cell_time_budget_s=CELL_BUDGET_S)
    print(f"\nOVERNIGHT RUN COMPLETE -> {run_dir}")
