"""Recovery capability: keyless vs keyed HMAC, pair_recovery_rate vs BER.

Headline: does the keyed MAC arm recover more corrupted pairs than the keyless
orthogonal arm as error load rises? Under uniform_hd the two IC-refinement paths
differ by construction -- keyed does a per-half MAC bit-flip search (recovers
same-position overlaps), keyless does the exact linear solve that is a no-op
without ARC narrowing (overlaps fail honestly). So the curves are expected to
separate on overlapping errors, widening with BER. This script measures that.

Terminology (memory: scheme_naming_convention):
  keyed HMAC   = SegmentedMacScheme (mac_uniform_hd_n5)
  keyless HMAC = SegmentedScheme    (segmented_uniform_hd_n5)
both N=5, uniform_hd, combined recovery + IC-refinement (default).

Metrics per (arm, gen, BER) cell:
  pair_recovery_rate     = Spairs_recovered / S(pairs_recovered + pairs_failed)   [headline]
  unpaired_recovery_rate = Sunpaired_recovered / S(unpaired_recovered + unpaired_failed)
  silent_decode_rate     = Ssilent_decode / trials_run          [HARD GUARD -- must be 0]
  correct_rate           = Scorrect / trials_run
  decode_success_rate    = Sdecoded / trials_run
  mean_overhead_decoded  = mean(overhead) over decoded trials   [downstream cost]

Outputs (checkpointed after EVERY cell -- never all-or-nothing):
  raw_trials.csv     one row per trial, every recovery field
  summary.csv        one row per cell, the rates above + Wilson 95% CI on pair rate
                     + trials_run vs trials_requested + total wall time
  pair_recovery_vs_ber.png, silent_decode_vs_ber.png, overhead_vs_ber.png

Stages (see .scratch .../10-recovery-capability-runs.md):
  --stage smoke  gen=8,  BER {1e-5,1e-3},                 3 trials/arm  (~1-2 min)
  --stage fast   gen=16, BER {1e-5,1e-4,3e-4,1e-3,3e-3}, 15 trials/arm (~15-30 min)

Run: LOG_FOLDER=./logs PYTHONPATH=. .venv/Scripts/python.exe \
        scripts/recovery_capability_sweep.py --stage smoke
"""

import argparse
import csv
import math
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
from simulation.integrity_schemes import AdmitConfig, SegmentedScheme, SegmentedMacScheme
from simulation.scheme_comparison_sim import run_recovery_trial, _run_capped_cell
from utils.log_helpers import get_run_log_dir

FIELD_M = 8
N = 5
STRATEGY = "uniform_hd"
MAX_PACKETS_FACTOR = 20

ARMS = {
    "keyless": {"color": "#588157", "label": "keyless HMAC (orthogonal)"},
    "keyed":   {"color": "#3d405b", "label": "keyed HMAC (MAC)"},
}

STAGES = {
    "smoke": dict(gen_sizes=[8],  bers=[1e-5, 1e-3],                     trials=3,  budget=120.0),
    "fast":  dict(gen_sizes=[16], bers=[1e-5, 1e-4, 3e-4, 1e-3, 3e-3],  trials=15, budget=300.0),
}


def _make(arm, gen_size, data_fields):
    """(scheme, cfg) for one arm. Fairness (memory how_to_run_sims / gensize_overhead_sweep):
    data_fields=(N-1)*gen, hamming_distance=2, min_pool_size=min(10,gen)."""
    mp = min(10, gen_size)
    nds = N - 1
    if arm == "keyed":
        s = SegmentedMacScheme(num_data_segments=nds, data_fields=data_fields,
                               strategy=STRATEGY, name=f"mac_{STRATEGY}_n{N}")
    else:
        s = SegmentedScheme(num_data_segments=nds, data_fields=data_fields,
                            strategy=STRATEGY, name=f"segmented_{STRATEGY}_n{N}")
    return s, AdmitConfig(hamming_distance=2, min_pool_size=mp)


def _wilson_halfwidth(successes, total, z=1.96):
    """95% Wilson interval half-width for a proportion; nan if no trials."""
    if total <= 0:
        return float("nan")
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = (z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))) / denom
    lo, hi = centre - half, centre + half
    return (hi - lo) / 2


def _summarize(arm, gen_size, ber, trials_requested, results):
    n = len(results)
    pr_ok = sum(r.pairs_recovered for r in results)
    pr_no = sum(r.pairs_failed for r in results)
    up_ok = sum(r.unpaired_recovered for r in results)
    up_no = sum(r.unpaired_failed for r in results)
    silent = sum(1 for r in results if r.silent_decode)
    correct = sum(1 for r in results if r.correct)
    decoded_l = [r for r in results if r.decoded]
    pair_den = pr_ok + pr_no
    up_den = up_ok + up_no
    ovh = float(np.mean([r.overhead for r in decoded_l])) if decoded_l else float("nan")
    wall = sum(r.wall_time_s for r in results)
    return {
        "arm": arm, "gen_size": gen_size, "bit_error_rate": ber,
        "trials_requested": trials_requested, "trials_run": n,
        "pairs_recovered": pr_ok, "pairs_failed": pr_no,
        "pair_recovery_rate": (pr_ok / pair_den) if pair_den else float("nan"),
        "pair_rate_ci95_halfwidth": _wilson_halfwidth(pr_ok, pair_den),
        "pair_denominator": pair_den,
        "unpaired_recovered": up_ok, "unpaired_failed": up_no,
        "unpaired_recovery_rate": (up_ok / up_den) if up_den else float("nan"),
        "silent_decode_rate": silent / n if n else float("nan"),
        "correct_rate": correct / n if n else float("nan"),
        "decode_success_rate": len(decoded_l) / n if n else float("nan"),
        "mean_overhead_decoded": ovh,
        "total_wall_s": wall,
        "wall_s_per_trial": wall / n if n else float("nan"),
    }


def _write_raw(path, raw_rows):
    if not raw_rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(raw_rows[0].keys()))
        w.writeheader()
        w.writerows(raw_rows)


def _write_summary(path, summary_rows):
    if not summary_rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        w.writeheader()
        w.writerows(summary_rows)


def _plot(run_dir, summary_rows, gen_sizes):
    def _series(metric, arm, gen):
        pts = sorted((r["bit_error_rate"], r[metric]) for r in summary_rows
                     if r["arm"] == arm and r["gen_size"] == gen
                     and not (isinstance(r[metric], float) and math.isnan(r[metric])))
        return [p[0] for p in pts], [p[1] for p in pts]

    specs = [
        ("pair_recovery_rate", "Pair recovery rate", "pair_recovery_vs_ber.png", True),
        ("silent_decode_rate", "Silent-decode rate (MUST be 0)", "silent_decode_vs_ber.png", False),
        ("mean_overhead_decoded", "Mean overhead (pkts/gen)", "overhead_vs_ber.png", False),
    ]
    ls_for_gen = {g: s for g, s in zip(gen_sizes, ["-", "--", ":"])}
    for metric, ylabel, fname, unit_line in specs:
        fig, ax = plt.subplots(figsize=(8.5, 5.5))
        for arm, meta in ARMS.items():
            for gen in gen_sizes:
                xs, ys = _series(metric, arm, gen)
                if not xs:
                    continue
                lbl = meta["label"] + (f" gen{gen}" if len(gen_sizes) > 1 else "")
                ax.plot(xs, ys, ls_for_gen.get(gen, "-"), marker="o", color=meta["color"],
                        linewidth=2, markersize=6, label=lbl)
        ax.set_xscale("log")
        ax.set_xlabel("Bit error rate", fontsize=12, fontweight="bold")
        ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
        ax.set_title(f"{ylabel} vs BER (N={N}, {STRATEGY})", fontsize=12, fontweight="bold")
        ax.grid(True, linestyle="--", alpha=0.3)
        if unit_line:
            ax.set_ylim(-0.02, 1.02)
        if ax.get_legend_handles_labels()[1]:
            ax.legend(fontsize=9)
        plt.tight_layout()
        plt.savefig(run_dir / fname, dpi=300, bbox_inches="tight")
        plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=list(STAGES), default="smoke")
    args = ap.parse_args()
    cfg_stage = STAGES[args.stage]
    gen_sizes = cfg_stage["gen_sizes"]
    bers = sorted(cfg_stage["bers"])          # cheap-first: ascending BER
    trials = cfg_stage["trials"]
    budget = cfg_stage["budget"]

    run_dir = get_run_log_dir(f"recovery_capability_{args.stage}", trials=trials, n=N)
    base_field = create_field(FIELD_M)
    raw_rows, summary_rows = [], []
    silent_seen = False

    print(f"=== stage={args.stage} gens={gen_sizes} bers={bers} trials={trials} budget={budget}s ===",
          flush=True)
    for gen_size in gen_sizes:
        data_fields = (N - 1) * gen_size
        for ber in bers:                       # ascending -> cheap cells first
            for arm in ARMS:
                scheme, cfg = _make(arm, gen_size, data_fields)
                print(f"--- arm={arm} gen={gen_size} df={data_fields} BER={ber:g} ---", flush=True)
                results = _run_capped_cell(
                    lambda: run_recovery_trial(base_field, scheme, data_fields, gen_size, ber, cfg,
                                               max_packets_factor=MAX_PACKETS_FACTOR),
                    trials, budget)
                for r in results:
                    row = asdict(r)
                    row.update(arm=arm, gen_size=gen_size, bit_error_rate=ber)
                    raw_rows.append(row)
                s = _summarize(arm, gen_size, ber, trials, results)
                summary_rows.append(s)
                if s["silent_decode_rate"] and not math.isnan(s["silent_decode_rate"]):
                    silent_seen = True
                    print(f"    !!! SILENT DECODE rate={s['silent_decode_rate']:.3f} -- BUG, flag it", flush=True)
                print(f"    pair_rate={s['pair_recovery_rate']:.3f} "
                      f"(+/-{s['pair_rate_ci95_halfwidth']:.3f}, den={s['pair_denominator']}) "
                      f"silent={s['silent_decode_rate']:.3f} decode={s['decode_success_rate']:.3f} "
                      f"ovh={s['mean_overhead_decoded']:.2f} n={s['trials_run']}/{trials} "
                      f"wall={s['total_wall_s']:.1f}s", flush=True)
                # checkpoint after EVERY cell
                _write_raw(run_dir / "raw_trials.csv", raw_rows)
                _write_summary(run_dir / "summary.csv", summary_rows)
                _plot(run_dir, summary_rows, gen_sizes)

    print(f"\nDone -> {run_dir}")
    print(f"  summary.csv, raw_trials.csv, pair_recovery_vs_ber.png, "
          f"silent_decode_vs_ber.png, overhead_vs_ber.png")
    if silent_seen:
        print("  WARNING: non-zero silent-decode observed -- correctness guard tripped.")


if __name__ == "__main__":
    main()
