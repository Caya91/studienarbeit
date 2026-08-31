"""Re-plot overhead-vs-gen_size from a completed run's summary.csv, optionally zoomed
to a gen_size window -- so a sub-range figure (e.g. gen 7..30) is regenerated from the
CSV without re-running the sweep. The CSVs are the durable artifact; this is a pure
read-and-draw over them.

Usage (main venv; no LOG_FOLDER needed -- reads a CSV, imports nothing heavy):
    .venv/Scripts/python.exe scripts/gensize_overhead_replot.py \
        --run-dir logs/gensize_overhead_sweep/<run> --gmin 7 --gmax 30
"""

import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SCHEME_COLOR = {"hmac": "#3d405b", "segmented": "#588157"}
BER_LINESTYLE = {1e-3: "-", 1e-5: "--"}


def _load(summary_csv: Path):
    rows = []
    for r in csv.DictReader(summary_csv.open()):
        # capped/trials_run are only in per-run summaries; aggregated summaries omit them.
        rows.append({
            "scheme_key": r["scheme_key"], "scheme": r["scheme"],
            "gen_size": int(r["gen_size"]), "bit_error_rate": float(r["bit_error_rate"]),
            "trials_run": int(r.get("trials_run", 0) or 0),
            "capped": r.get("capped", "") == "True",
            "mean_overhead_decoded": float(r["mean_overhead_decoded"]),
        })
    return rows


def _series(rows, key, ber, gmin, gmax):
    pts = sorted((r["gen_size"], r["mean_overhead_decoded"]) for r in rows
                 if r["scheme_key"] == key and r["bit_error_rate"] == ber
                 and gmin <= r["gen_size"] <= gmax
                 and not np.isnan(r["mean_overhead_decoded"]))
    return [p[0] for p in pts], [p[1] for p in pts]


def replot(run_dir: Path, gmin: float, gmax: float, seg_label: str) -> None:
    rows = _load(run_dir / "summary.csv")
    bers = sorted({r["bit_error_rate"] for r in rows})
    label = {"hmac": "keyed HMAC", "segmented": seg_label}
    # Full range (default) writes the canonical filenames; a real window gets a _zoom tag.
    gens = [r["gen_size"] for r in rows]
    full_range = gmin <= (min(gens) if gens else 0) and gmax >= (max(gens) if gens else 0)
    tag = "" if full_range else f"_zoom{int(gmin)}-{int(gmax)}"
    win = "" if full_range else f"  (gen {int(gmin)}..{int(gmax)})"

    for ber in bers:
        fig, ax = plt.subplots(figsize=(8, 5.5))
        for key in ("hmac", "segmented"):
            xs, ys = _series(rows, key, ber, gmin, gmax)
            if xs:
                ax.plot(xs, ys, "-", marker="o", color=SCHEME_COLOR[key], linewidth=2,
                        markersize=6, label=label[key])
        ax.axhline(1.0, color="grey", linestyle="-.", alpha=0.6, label="ideal = 1")
        if not full_range:
            ax.set_xlim(gmin, gmax)
        ax.set_xlabel("Generation size", fontsize=12, fontweight="bold")
        ax.set_ylabel("Mean overhead (packets sent / gen_size)", fontsize=12, fontweight="bold")
        ax.set_title(f"Overhead vs generation size @ BER={ber:g}{win}",
                     fontsize=13, fontweight="bold")
        ax.yaxis.grid(True, linestyle="--", alpha=0.3)
        ax.legend(fontsize=10)
        plt.tight_layout()
        out = run_dir / f"overhead_vs_gensize_ber{ber:g}{tag}.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close(fig)
        print(f"Plot saved: {out}")

    # Combined zoom.
    fig, ax = plt.subplots(figsize=(9, 6))
    for key in ("hmac", "segmented"):
        for ber in bers:
            xs, ys = _series(rows, key, ber, gmin, gmax)
            if xs:
                ax.plot(xs, ys, BER_LINESTYLE.get(ber, "-"), marker="o", color=SCHEME_COLOR[key],
                        linewidth=2, markersize=5, label=f"{label[key]} @ BER={ber:g}")
    ax.axhline(1.0, color="grey", linestyle="-.", alpha=0.6, label="ideal = 1")
    if not full_range:
        ax.set_xlim(gmin, gmax)
    ax.set_xlabel("Generation size", fontsize=12, fontweight="bold")
    ax.set_ylabel("Mean overhead (packets sent / gen_size)", fontsize=12, fontweight="bold")
    ax.set_title(f"Overhead vs generation size{win}", fontsize=13, fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=9)
    plt.tight_layout()
    out = run_dir / f"overhead_vs_gensize_combined{tag}.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved: {out}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Zoomed re-plot of a gensize_overhead run.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--gmin", type=float, default=0)
    parser.add_argument("--gmax", type=float, default=1e9)
    parser.add_argument("--seg-label", default="segmented (N=5)")
    args = parser.parse_args(argv)
    replot(Path(args.run_dir), args.gmin, args.gmax, args.seg_label)


if __name__ == "__main__":
    main()
