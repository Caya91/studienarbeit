"""CRC single-packet Hamming-distance recovery sweep (ADR-0011).

The standalone CRC experiment the supervisors asked for: corrupt one opaque data
packet at a known Hamming distance k in {1,2,3}, then try to repair it by
brute-forcing bit-combinations (up to HD 3) checked against a bare CRC, stopping
at the first match. Sweep packet size x CRC width x HD and report, per cell, the
outcome split -- correct / false-repair (silent error) / no-repair /
unresolved-within-budget -- plus the mean search cost, next to the analytic
false-repair estimate.

This is deliberately the *no-localization* baseline (every bit is suspect); the
comparison harness (phase 3) will give CRC ACR-localized suspect bits for a fair
fight. Metrics use the comparison's vocabulary so results transfer:
false-repair == "silent pollutions", correction_trials == the cost currency.

Runtime guard: a wide CRC never collides, so its HD-3 search runs to the full
candidate budget on every trial -- 1000x that is hours. Such a cell is
deterministically `unresolved-within-budget`, so once a probe of `min_trials` is
homogeneously unresolved we stop and report from the probe (the outcome cannot
change). This never fires on a cell that could hide a rare false-repair (those
stop early on the collision and are cheap), so no statistics are lost.
"""

import csv
import os
import random
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

import matplotlib.pyplot as plt
import numpy as np

from simulation.crc_recovery import (
    CrcInstrument, analytic_false_repair, attach, crc, recover, _flip_bits,
)
from utils.log_helpers import get_run_log_dir


# ── Sweep configuration (ADR-0011) ───────────────────────────────────────────
SIZES = [4, 8, 16, 32, 64]        # data_fields (bytes); n_bits = 8 * size
WIDTHS = [8, 16, 32]              # CRC widths; CRC-16 = PRAC/S-PRAC/QPPR anchor
HDS = [1, 2, 3]                  # true corruption Hamming distance (bits)
NUM_TRIALS = 1000
BUDGET = 1_000_000               # per-trial candidate cap (Q12)
MIN_TRIALS = 50                  # probe size for the unresolved-cell early-stop
# A wide CRC at high HD never collides: every trial runs the full C(n,hd) search
# to the true fix (correct), so it is both the most expensive cell AND the one MC
# learns nothing new about -- its analytic_fr is far below what 1000 draws could
# ever observe (ADR-0011). Below this analytic threshold we run only MIN_TRIALS
# and lean on the analytic tail estimate. This is what makes HD-3 finish.
SAFE_FR_THRESHOLD = 1e-3

OUTCOMES = ("correct", "false_repair", "no_repair", "unresolved_budget")


@dataclass
class CellResult:
    data_fields: int
    n_bits: int
    width: int
    true_hd: int
    trials_run: int
    correct_rate: float
    false_repair_rate: float          # == "silent pollutions"
    no_repair_rate: float
    unresolved_rate: float
    mean_trials: float                # mean candidates searched (cost)
    analytic_false_repair: float      # expected collision-passes before true fix
    budget_bound: bool                # cell stopped early as homogeneously unresolved
    fr_capped: bool                   # trials capped: collision-safe, analytic-reported


def run_trial(data_fields: int, width: int, hd: int, budget: int, rng) -> tuple[str, int]:
    """One corrupt-and-repair trial. Returns (outcome, candidates_searched)."""
    original = bytearray(rng.randrange(256) for _ in range(data_fields))
    reference = crc(bytes(original), width)                    # source-side tag (intact)
    received = _flip_bits(original, rng.sample(range(8 * data_fields), hd))
    inst = CrcInstrument()
    repaired, exhausted = recover(inst, received, reference, width, max_hd=3, budget=budget)
    if repaired is None:
        outcome = "unresolved_budget" if exhausted else "no_repair"
    elif bytes(repaired) == bytes(original):
        outcome = "correct"
    else:
        outcome = "false_repair"                              # silent: passed CRC, wrong packet
    return outcome, inst.correction_trials


def run_cell(data_fields: int, width: int, hd: int, num_trials: int, budget: int,
             min_trials: int, rng, safe_fr_threshold: float = SAFE_FR_THRESHOLD) -> CellResult:
    counts = {o: 0 for o in OUTCOMES}
    trial_costs: list[int] = []
    ran = 0
    n_bits = 8 * data_fields
    analytic = analytic_false_repair(n_bits, hd, width)
    # Collision-safe & expensive: cap trials, report the analytic tail (see above).
    effective_trials = min_trials if analytic < safe_fr_threshold else num_trials
    for _ in range(effective_trials):
        outcome, cost = run_trial(data_fields, width, hd, budget, rng)
        counts[outcome] += 1
        trial_costs.append(cost)
        ran += 1
        # Safe early-stop: only when EVERY trial so far exhausted the budget (a
        # deterministic infeasible cell -- a wide CRC that never collides). Cells
        # that could produce a rare false-repair are never homogeneously
        # unresolved, so this cannot hide one.
        if ran >= min_trials and counts["unresolved_budget"] == ran:
            break

    return CellResult(
        data_fields=data_fields, n_bits=n_bits, width=width, true_hd=hd,
        trials_run=ran,
        correct_rate=counts["correct"] / ran,
        false_repair_rate=counts["false_repair"] / ran,
        no_repair_rate=counts["no_repair"] / ran,
        unresolved_rate=counts["unresolved_budget"] / ran,
        mean_trials=float(np.mean(trial_costs)),
        analytic_false_repair=analytic,
        budget_bound=(counts["unresolved_budget"] == ran and ran < num_trials),
        fr_capped=(effective_trials < num_trials),
    )


def run_sweep(sizes=SIZES, widths=WIDTHS, hds=HDS, num_trials=NUM_TRIALS,
              budget=BUDGET, min_trials=MIN_TRIALS, seed=0) -> Path:
    run_dir = get_run_log_dir("crc_recovery_sim", trials=num_trials, budget=budget)
    rng = random.Random(seed)

    rows: list[dict] = []
    for hd in hds:
        print(f"\n=== HD {hd} ===")
        print(f"{'size':>5} {'nbits':>6} {'width':>6} {'correct':>8} {'false':>8} "
              f"{'norep':>8} {'unres':>8} {'mean_trials':>12} {'analytic_fr':>12} {'runs':>5}")
        for width in widths:
            for size in sizes:
                cell = run_cell(size, width, hd, num_trials, budget, min_trials, rng)
                rows.append(asdict(cell))
                flag = "*" if cell.budget_bound else ("~" if cell.fr_capped else " ")
                print(f"{size:>5} {cell.n_bits:>6} {width:>6} {cell.correct_rate:>8.3f} "
                      f"{cell.false_repair_rate:>8.3f} {cell.no_repair_rate:>8.3f} "
                      f"{cell.unresolved_rate:>8.3f} {cell.mean_trials:>12.1f} "
                      f"{cell.analytic_false_repair:>12.3e} {cell.trials_run:>4}{flag}")

    _write_csv(run_dir / "crc_recovery_summary.csv", rows)
    for hd in hds:
        _plot_heatmap(rows, hd, "false_repair_rate",
                      f"CRC false-repair (silent) rate -- HD {hd}",
                      run_dir / f"false_repair_hd{hd}.png")
    print(f"\n('*' = budget-bound cell, stopped early as homogeneously unresolved)")
    print(f"('~' = collision-safe cell, trials capped -- correct rests on analytic tail)")
    print(f"Done. Results written to: {run_dir}")
    return run_dir


def smoke_test() -> None:
    """Tiny, fast config for dev -- small packets, few trials, low budget."""
    print("smoke_test  (sizes=[4,8], widths=[8,16], trials=100, budget=5000)")
    run_sweep(sizes=[4, 8], widths=[8, 16], hds=[1, 2, 3],
              num_trials=100, budget=5000, min_trials=20)


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written: {path}")


def _plot_heatmap(rows, hd, metric, title, output_path) -> None:
    cells = [r for r in rows if r["true_hd"] == hd]
    if not cells:
        return
    sizes = sorted({r["data_fields"] for r in cells})
    widths = sorted({r["width"] for r in cells})
    grid = np.full((len(widths), len(sizes)), np.nan)
    lookup = {(r["width"], r["data_fields"]): r[metric] for r in cells}
    for i, w in enumerate(widths):
        for j, s in enumerate(sizes):
            grid[i, j] = lookup.get((w, s), np.nan)

    fig, ax = plt.subplots(figsize=(8, 4))
    im = ax.imshow(grid, cmap="magma", aspect="auto", vmin=0, vmax=1, origin="lower")
    ax.set_xticks(range(len(sizes)), [str(s) for s in sizes])
    ax.set_yticks(range(len(widths)), [f"CRC-{w}" for w in widths])
    ax.set_xlabel("packet size (bytes)", fontweight="bold")
    ax.set_ylabel("CRC width", fontweight="bold")
    ax.set_title(title, fontweight="bold")
    for i in range(len(widths)):
        for j in range(len(sizes)):
            v = grid[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                        color="white" if v < 0.6 else "black", fontsize=9)
    fig.colorbar(im, ax=ax, label=metric)
    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved: {output_path}")


if __name__ == "__main__":
    smoke_test()
    run_sweep()
