r"""Three plain figures, CRC-32 vs keyless HMAC (all 4 helpers as witnesses), 100 B packets (user 2026-10-20).

Data: isolated_recovery_sim run `logs/crc32_vs_keyless/simple_100B/run_seeds20000` (config arc_only_a = payload
errors, 2 x 50 B data segments, gen 4, W 4, crc_acr, BER 1e-5 / 1e-3, max HD 1..3, budget 20000). Rates are over
the CORRUPTED packets only (n_info_corrupted), so BER 1e-5 is not trivially 100 %.
  recovery.png       corrupted packets repaired to the original data (%)
  undetected.png     corrupted packets accepted although not the original data (%), i.e. silent decodes
  recovery_time.png  mean repair wall-clock per corrupted packet (ms), trials with >= 1 corrupted packet
No annotations on purpose: axes, title, legend only.

CLI: $env:PYTHONPATH="."; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/crc32_vs_keyless_simple_plots.py
"""
import argparse
import glob
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from scripts.scaling_plots_from_csv import GRID, INK, INK_MUTED

ARMS = {"crc_acr": ("CRC-32", "#4a3aa7"), "keyless": ("keyless HMAC", "#588157")}
BER_TITLE = {1e-5: "BER $10^{-5}$", 1e-3: "BER $10^{-3}$"}


def load(root):
    files = sorted(glob.glob(str(Path(root) / "*" / "raw_trials.csv")))
    assert files, f"no runs under {root}"
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    return df[(df.arm == "crc_acr") | (df.W == 4)]


def metrics(df):
    rows = []
    for (ber, hd, arm), g in df.groupby(["bit_error_rate", "max_combined_hd", "arm"]):
        corrupted = g.n_info_corrupted.sum()
        clean = (g["T"] - g.n_info_corrupted).sum()
        hit = g[g.n_info_corrupted > 0]
        rows.append(dict(ber=ber, hd=hd, arm=arm, corrupted=int(corrupted),
                         recovery=100 * (g.recovered.sum() - clean) / corrupted if corrupted else np.nan,
                         undetected=100 * g.silent.sum() / corrupted if corrupted else np.nan,
                         time_ms=1e3 * hit.recovery_time_s.sum() / hit.n_info_corrupted.sum() if len(hit) else np.nan))
    return pd.DataFrame(rows)


def _fmt(v):
    return "0" if v == 0 else (f"{v:.1f}" if abs(v) >= 10 else f"{v:.2f}")


def _figure(m, col, ylabel, title, out, name, ylim=None, sharey=True):
    bers = sorted(m.ber.unique())
    fig, axes = plt.subplots(1, len(bers), figsize=(4.2 * len(bers), 3.4), sharey=sharey, squeeze=False)
    for ax, ber in zip(axes[0], bers):
        hds = sorted(m.hd.unique())
        x = np.arange(len(hds))
        for i, (arm, (label, color)) in enumerate(ARMS.items()):
            r = m[(m.ber == ber) & (m.arm == arm)].set_index("hd").reindex(hds)
            vals = r[col].fillna(0).values
            bars = ax.bar(x + (i - 0.5) * 0.38, vals, 0.36, color=color, label=label)
            ax.bar_label(bars, labels=[_fmt(v) for v in vals], padding=2, fontsize=8, color=INK)
        ax.set_xticks(x, [str(h) for h in hds])
        ax.set_xlabel("max Hamming distance", color=INK, fontsize=10)
        ax.set_title(BER_TITLE.get(ber, f"BER {ber:g}"), color=INK, fontsize=10)
        ax.grid(True, axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors=INK_MUTED, labelcolor=INK, labelsize=9)
        if ylim:
            ax.set_ylim(*ylim)
    for ax in (axes[0] if not sharey else axes[0][:1]):
        ax.set_ylabel(ylabel, color=INK, fontsize=10)
    fig.suptitle(title, color=INK, fontsize=12)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=9, labelcolor=INK)
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(out / f"{name}.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out / name}.png")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="E:/projects/studienarbeit/logs/crc32_vs_keyless/simple_100B")
    a = ap.parse_args(argv)
    out = Path(a.root) / "plots"
    m = metrics(load(a.root))
    out.mkdir(parents=True, exist_ok=True)
    m.to_csv(out / "simple_metrics.csv", index=False)
    print(m.to_string(index=False))
    _figure(m, "recovery", "recovered packets (%)", "Recovery", out, "recovery", ylim=(0, 112))
    _figure(m, "undetected", "undetected corrupted packets (%)", "Undetected errors", out, "undetected",
            ylim=(0, max(1.0, float(np.nanmax(m.undetected)) * 1.2)))
    _figure(m, "time_ms", "time per corrupted packet (ms)", "Recovery time", out, "recovery_time", sharey=False)


if __name__ == "__main__":
    main()
