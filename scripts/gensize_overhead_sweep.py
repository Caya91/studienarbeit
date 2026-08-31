"""Overhead-vs-generation-size sweep: keyed HMAC vs the segmented orthogonal scheme.

The other comparison drivers put BER on the x-axis at a fixed gen_size; this one
does the orthogonal cut the thesis also needs -- gen_size on the x-axis at a FIXED
BER -- so we can see how transmission overhead (packets_sent / gen_size) scales with
generation size for each scheme. One line per scheme, one figure per BER (default
1e-3 and 1e-5).

Two arms only (the user's "both schemes"):
  * hmac                       -- keyed HMAC-SHA-256, detect-and-drop.
  * segmented_<strategy>_n<N>  -- the segmented orthogonal self-tag (repairs).

Fairness across the gen_size axis: the segmented scheme has a rank floor
(each data-segment payload >= gen_size-1, i.e. data_fields >= (N-1)*(gen_size-1)),
so data_fields must GROW with gen_size. We pick data_fields = (N-1)*gen_size
(per-segment length = gen_size, a clean margin over the floor) and hand the SAME
data_fields to the HMAC arm at each point, so both schemes carry equal-size payloads
and the per-bit channel BER hits comparable packet lengths. A fresh SegmentedScheme
instance is built per gen_size because it fixes data_fields at construction.

CSV outputs (in the run dir) are the durable artifact -- plots are regenerated from
them, and other plots (e.g. per-trial distributions) can be too:
  * raw_results.csv  -- one row per trial.
  * summary.csv      -- one row per (scheme, BER, gen_size) cell; mean_overhead_decoded
                        is the headline y.

Run (main venv, LOG_FOLDER/PYTHONPATH required -- see docs/running_sims.md):
    LOG_FOLDER=./logs PYTHONPATH=. .venv/Scripts/python.exe \
        scripts/gensize_overhead_sweep.py --mode small
"""

import argparse
import csv
import os
import sys
from dataclasses import asdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from binary_ext_fields.custom_field import create_field
from simulation.integrity_schemes import AdmitConfig, HmacScheme, SegmentedScheme
from simulation.scheme_comparison_sim import run_recovery_trial, _run_capped_cell
from utils.log_helpers import get_run_log_dir

FIELD_M = 8

# Colours for the two arms.
SCHEME_COLOR = {"hmac": "#3d405b", "segmented": "#588157"}
BER_LINESTYLE = {1e-3: "-", 1e-5: "--"}


def _data_fields_for(gen_size: int, n_total: int) -> int:
    """Segmented rank floor: each of the (N-1) data-segments must be >= gen_size-1.
    Use per-segment length = gen_size (clean margin over the floor) so data_fields =
    (N-1)*gen_size. N=1 has no data-segments; fall back to gen_size (HMAC-only shape)."""
    num_data_segments = max(n_total - 1, 1)
    return num_data_segments * gen_size


def run_sweep(gen_sizes, bit_error_rates, num_trials, segmented_n, strategy,
              max_packets_factor, cell_time_budget_s) -> Path:
    run_dir = get_run_log_dir("gensize_overhead_sweep", trials=num_trials,
                              n=segmented_n, strat=strategy)
    base_field = create_field(FIELD_M)
    # AdmitConfig defaults min_pool_size=10 (a warm-up gate before the segmented arm
    # will repair). For gen_size<10 that gate floors overhead at 10/gen_size -- a pure
    # artifact, not a scheme cost. Per-gen we drop it to gen_size when gen_size is
    # smaller (the natural minimum: you can't decode below gen_size packets anyway), so
    # the small-gen points aren't inflated. hamming_distance stays 2 (combined recovery
    # needs HD>=2; HMAC ignores cfg entirely). Both knobs are recorded per row so the
    # aggregator can refuse to pool cells that used a different config.
    base_min_pool = AdmitConfig().min_pool_size
    hd = 2
    seg_name = f"segmented_{strategy}_n{segmented_n}"

    # Cheapest cells first so a checkpoint captures them BEFORE an expensive cell can
    # hang: low BER is orders of magnitude faster than high BER for the segmented arm
    # (its per-round combined search scales with the corrupted-packet count), so sweep
    # BERs ascending. hmac (detect-and-drop, no search) always precedes segmented.
    bers_cheap_first = sorted(bit_error_rates)

    raw_rows, summary_rows = [], []
    for gen_size in gen_sizes:
        data_fields = _data_fields_for(gen_size, segmented_n)
        eff_min_pool = min(base_min_pool, gen_size)   # drop the warm-up floor for small gens
        cfg = AdmitConfig(hamming_distance=hd, min_pool_size=eff_min_pool)
        hmac = HmacScheme()
        segmented = SegmentedScheme(num_data_segments=segmented_n - 1, data_fields=data_fields,
                                    strategy=strategy, name=seg_name)
        for scheme_key, scheme in (("hmac", hmac), ("segmented", segmented)):
            for ber in bers_cheap_first:
                print(f"=== scheme={scheme.name} gen_size={gen_size} "
                      f"data_fields={data_fields} BER={ber:g} ===", flush=True)
                results = _run_capped_cell(
                    lambda: run_recovery_trial(base_field, scheme, data_fields, gen_size, ber,
                                               cfg, max_packets_factor=max_packets_factor),
                    num_trials, cell_time_budget_s)
                trials_run = len(results)
                capped = trials_run < num_trials
                if capped:
                    print(f"    [capped] {trials_run}/{num_trials} trials at {cell_time_budget_s:g}s", flush=True)
                for trial_id, r in enumerate(results):
                    raw_rows.append({"scheme_key": scheme_key, "scheme": scheme.name,
                                     "gen_size": gen_size, "data_fields": data_fields,
                                     "bit_error_rate": ber, "hamming_distance": hd,
                                     "min_pool_size": eff_min_pool,
                                     "trial_id": trial_id, **asdict(r)})
                decoded = [r for r in results if r.decoded]
                summary_rows.append({
                    "scheme_key": scheme_key, "scheme": scheme.name,
                    "gen_size": gen_size, "data_fields": data_fields,
                    "bit_error_rate": ber, "hamming_distance": hd, "min_pool_size": eff_min_pool,
                    "trials": num_trials, "trials_run": trials_run, "capped": capped,
                    "correct_rate": sum(r.correct for r in results) / trials_run,
                    "decode_success_rate": len(decoded) / trials_run,
                    "timeout_rate": sum(r.status == "timeout" for r in results) / trials_run,
                    # HEADLINE y: mean transmission overhead (packets_sent / gen_size), over
                    # decoded trials only (a timeout has no meaningful overhead).
                    "mean_overhead_decoded": float(np.mean([r.overhead for r in decoded])) if decoded else float("nan"),
                    "std_overhead_decoded": float(np.std([r.overhead for r in decoded])) if decoded else float("nan"),
                    "wall_time_s_mean": float(np.mean([r.wall_time_s for r in results])),
                })
                # Checkpoint after EVERY cell: this run is never all-or-nothing again.
                # A single runaway trial (e.g. segmented gen=64 @ BER 1e-3) can still
                # overshoot the cell budget -- _run_capped_cell only checks between
                # trials -- but everything completed before it is already on disk, and
                # the plots reflect it. Full rewrite each time (rows are small).
                _write_csv(run_dir / "raw_results.csv", raw_rows)
                _write_csv(run_dir / "summary.csv", summary_rows)
                try:
                    _plot_overhead(summary_rows, bit_error_rates, seg_name, run_dir)
                except Exception as e:  # never let a mid-run plot glitch drop the checkpoint
                    print(f"    [plot skipped this checkpoint: {e}]", flush=True)

    print(f"\nDone. Results written to: {run_dir}")
    return run_dir


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written: {path}")


def _plot_overhead(summary_rows, bit_error_rates, seg_name, run_dir) -> None:
    """One figure per BER (overhead vs gen_size, hmac vs segmented) plus a combined
    figure overlaying all BERs (linestyle = BER)."""
    label = {"hmac": "keyed HMAC", "segmented": seg_name}

    # Per-BER figures.
    for ber in bit_error_rates:
        fig, ax = plt.subplots(figsize=(8, 5.5))
        for key in ("hmac", "segmented"):
            pts = sorted((row["gen_size"], row["mean_overhead_decoded"]) for row in summary_rows
                         if row["scheme_key"] == key and row["bit_error_rate"] == ber
                         and not np.isnan(row["mean_overhead_decoded"]))
            if not pts:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            ax.plot(xs, ys, "-", marker="o", color=SCHEME_COLOR[key], linewidth=2,
                    markersize=6, label=label[key])
        ax.axhline(1.0, color="grey", linestyle="-.", alpha=0.6, label="ideal = 1")
        ax.set_xlabel("Generation size", fontsize=12, fontweight="bold")
        ax.set_ylabel("Mean overhead (packets sent / gen_size)", fontsize=12, fontweight="bold")
        ax.set_title(f"Overhead vs generation size @ BER={ber:g}", fontsize=13, fontweight="bold")
        ax.yaxis.grid(True, linestyle="--", alpha=0.3)
        ax.legend(fontsize=10)
        plt.tight_layout()
        out = run_dir / f"overhead_vs_gensize_ber{ber:g}.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close(fig)
        print(f"Plot saved: {out}")

    # Combined figure: colour = scheme, linestyle = BER.
    fig, ax = plt.subplots(figsize=(9, 6))
    for key in ("hmac", "segmented"):
        for ber in bit_error_rates:
            pts = sorted((row["gen_size"], row["mean_overhead_decoded"]) for row in summary_rows
                         if row["scheme_key"] == key and row["bit_error_rate"] == ber
                         and not np.isnan(row["mean_overhead_decoded"]))
            if not pts:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            ax.plot(xs, ys, BER_LINESTYLE.get(ber, "-"), marker="o", color=SCHEME_COLOR[key],
                    linewidth=2, markersize=5, label=f"{label[key]} @ BER={ber:g}")
    ax.axhline(1.0, color="grey", linestyle="-.", alpha=0.6, label="ideal = 1")
    ax.set_xlabel("Generation size", fontsize=12, fontweight="bold")
    ax.set_ylabel("Mean overhead (packets sent / gen_size)", fontsize=12, fontweight="bold")
    ax.set_title("Overhead vs generation size: HMAC vs segmented", fontsize=13, fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=9)
    plt.tight_layout()
    out = run_dir / "overhead_vs_gensize_combined.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved: {out}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Overhead vs gen_size: HMAC vs segmented orthogonal.")
    parser.add_argument("--mode", choices=["small", "long"], default="small",
                        help="small = quick exploratory run; long = more trials + gen_sizes")
    parser.add_argument("--n", type=int, default=5, help="segmented total segments N (2/3/5)")
    parser.add_argument("--strategy", default="uniform_hd",
                        choices=["uniform_hd", "coefficient_first"])
    parser.add_argument("--trials", type=int, default=None, help="override trials/cell")
    parser.add_argument("--cell-time-budget-s", type=float, default=120.0)
    parser.add_argument("--gen-sizes", type=str, default=None,
                        help="comma-separated gen_sizes override, e.g. 4,8,16,32")
    args = parser.parse_args(argv)

    bers = [1e-3, 1e-5]
    if args.mode == "small":
        gen_sizes = [4, 8, 16]
        num_trials = args.trials or 15
        max_packets_factor = 15
    else:  # long
        gen_sizes = [4, 8, 16, 32, 64]
        num_trials = args.trials or 120
        max_packets_factor = 20
    if args.gen_sizes:
        gen_sizes = [int(x) for x in args.gen_sizes.split(",")]

    run_sweep(gen_sizes, bers, num_trials, args.n, args.strategy,
              max_packets_factor, args.cell_time_budget_s)


if __name__ == "__main__":
    main()
