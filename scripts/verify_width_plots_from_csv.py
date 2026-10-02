r"""S2 plots: forgery admit rate vs attacker knowledge, per verification width and witness policy.
Reads raw_trials.csv of simulation/verify_width_attack_sim.py (pools run dirs), one function per plot.

  plot_policy_grid(summary, m)  rows = arm, cols = policy (first | random); x = knowledge (r observed
                                packets / k leaked keys), y = admit rate; a line per width (darker =
                                wider check). Gray lines = theory (keyless random incl. the
                                re-evaluation term). Measured: arm-coloured markers + Wilson 95% CI.
  plot_w1(summary)              W = 1 only (the supervisor's case): first vs random, per field + arm.

CLI (PowerShell): $env:PYTHONPATH="."; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" `
  scripts/verify_width_plots_from_csv.py --runs "E:/projects/studienarbeit/logs/verify_width_attack/*"
"""
import argparse
import csv
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

from simulation.knowledge_attack_sim import wilson
from simulation.verify_width_attack_sim import summarize, theory_admit

ARM = {"keyless": {"color": "#588157", "marker": "o", "x": "r = honest packets observed",
                   "title": "keyless: W witnesses"},
       "keyed": {"color": "#3d405b", "marker": "s", "x": "k = keys leaked (of g)", "title": "keyed: W of g tags"}}
POLICY = {"first": "deterministic (first witnesses / first keys)", "random": "receiver-secret random subset"}
CAPTIONS = False   # 2026-10-02: descriptions live in the figure notes, not on the figure
INK, INK_MUTED, GRID, THEORY = "#1f1f1e", "#6b6a64", "#e4e3dd", "#9a9990"


def load(runs):
    rows = []
    for pat in runs:
        for d in sorted(glob.glob(pat)):
            p = Path(d) / "raw_trials.csv"
            if p.exists():
                rows += list(csv.DictReader(p.open()))
    if not rows:
        raise SystemExit(f"no raw_trials.csv under {runs}")
    return pd.DataFrame(summarize(rows))


def _shade(hex_color, t):
    c = np.array(matplotlib.colors.to_rgb(hex_color))
    return tuple(1 - t * (1 - c))


def _style(ax):
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED, labelcolor=INK, labelsize=8)
    ax.set_ylim(-0.03, 1.05)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))


def _wlabel(w):
    return "all" if w < 0 else str(w)


def _theory(ax, ks, ys, label=None):
    """Theory: black dashed line + hollow black markers, drawn UNDER the measured points."""
    ax.plot(ks, ys, color=INK, linestyle=(0, (4, 3)), linewidth=1.1, marker="o", markersize=7,
            markerfacecolor="none", markeredgecolor=INK, markeredgewidth=1, zorder=4, label=label)


def _label(ax, xv, yv, txt, offset, ha):
    ax.annotate(txt, (xv, yv), textcoords="offset points", xytext=offset, ha=ha, fontsize=7, color=INK, zorder=5,
                bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.85))


def _pct(yv):
    return f"{100 * yv:.1f}%" if yv < 0.995 else "100%"


def _measured(ax, c, color, marker, label=None, low=None):
    """low: dict x -> list of (y, text, color) collecting near-zero labels for _place_low (None = label all here)."""
    # silent-decode rate (every admitted forgery decoded wrong in all runs so far; plot the silent count itself)
    x, y = c["knowledge"].to_numpy(), c["silent_rate"].to_numpy()
    ci = [wilson(int(sv), int(t)) for sv, t in zip(c["silent"], c["trials"])]
    lo, hi = np.array([a for a, _ in ci]), np.array([b for _, b in ci])
    ax.errorbar(x, y, yerr=[np.clip(y - lo, 0, None), np.clip(hi - y, 0, None)], fmt="none", ecolor=color,
                elinewidth=1.2, capsize=3, zorder=2)
    ax.plot(x, y, color=color, linewidth=2, marker=marker, markersize=6, zorder=3, label=label)
    for xv, yv in zip(x, y):  # measured value above each point (figure notes carry the rest)
        if low is not None and yv < 0.12:
            low.setdefault(xv, []).append((yv, _pct(yv)))
        else:
            _label(ax, xv, yv, _pct(yv), (0, 7), "center")


def _place_low(ax, low):
    """Near-zero labels of several lines at one x: a column right of the points, highest value on top."""
    for xv, items in low.items():
        for rank, (yv, txt) in enumerate(sorted(items, reverse=True)):
            _label(ax, xv, 0.0, txt, (8, 4 + 9 * (len(items) - 1 - rank)), "left")


def _draw(ax, sub, arm, m, g, widths):
    ts = np.linspace(0.45, 1.0, len(widths))
    low = {}
    for i, (w, t) in enumerate(zip(widths, ts)):
        c = sub[sub["width"] == w].sort_values("knowledge")
        if c.empty:
            continue
        ks = np.arange(0, c["knowledge"].max() + 1)
        _theory(ax, ks, [theory_admit(arm, "random", int(k), None if w < 0 else int(w), g, 2 ** m) for k in ks],
                "theory" if i == 0 else None)
        _measured(ax, c, _shade(ARM[arm]["color"], t), ARM[arm]["marker"],
                  f"W = {_wlabel(w)}", low=low)
    _place_low(ax, low)


def _save(fig, out_dir, name, caption):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if caption and CAPTIONS:
        fig.text(0.5, 0.005, caption, ha="center", va="bottom", fontsize=7.5, color=INK_MUTED, wrap=True)
    fig.tight_layout(rect=(0, 0.05 if (caption and CAPTIONS) else 0, 1, 1))
    for ext in ("png", "pdf"):
        fig.savefig(out_dir / f"{name}.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out_dir / f"{name}.png"


def plot_random_grid(summary, m, out_dir):
    """Receiver-secret random subset only: keyless (top) and keyed (bottom), a line per width."""
    s = summary[(summary["field_bits"] == m) & ((summary["policy"] == "random") | (summary["width"] < 0))]
    g = int(s["gen_size"].iloc[0])
    fig, axes = plt.subplots(2, 1, figsize=(5.6, 7.0), sharey=True)
    for ax, arm in zip(axes, ARM):
        sub = s[s["arm"] == arm]
        widths = sorted(sub["width"].unique(), key=lambda w: 99 if w < 0 else w)
        _draw(ax, sub, arm, m, g, widths)
        _style(ax)
        ax.set_xticks(sorted(sub["knowledge"].unique()))
        ax.set_title(f"{ARM[arm]['title']}, GF(2^{m}), g={g}", color=INK, fontsize=10)
        ax.set_ylabel("silent decode rate", color=INK, fontsize=9)
        ax.set_xlabel(ARM[arm]["x"], color=INK, fontsize=9)
        ax.legend(loc="upper left", fontsize=7.5, frameon=False, labelcolor=INK)
    return _save(fig, out_dir, f"s2_random_vs_knowledge_m{m}",
                 f"S2: one forged packet (early strike, repair off), receiver checks a secret random subset of "
                 f"width W per packet and remembers rejections; {int(s['trials'].iloc[0])} trials/cell, 95% CI. "
                 "Dashed black + hollow = theory.")


def plot_w1(summary, out_dir):
    """Width 1, receiver-secret random choice only: rows = field, cols = arm."""
    s = summary[(summary["width"] == 1) & (summary["policy"] == "random")]
    ms = sorted(s["field_bits"].unique())
    fig, axes = plt.subplots(len(ms), 2, figsize=(9.5, 3.2 * len(ms)), sharey=True, squeeze=False)
    for i, m in enumerate(ms):
        for j, arm in enumerate(ARM):
            ax = axes[i][j]
            c = s[(s["field_bits"] == m) & (s["arm"] == arm)].sort_values("knowledge")
            g = int(c["gen_size"].iloc[0])
            ks = np.arange(0, c["knowledge"].max() + 1)
            _theory(ax, ks, [theory_admit(arm, "random", int(k), 1, g, 2 ** m) for k in ks], "theory")
            _measured(ax, c, ARM[arm]["color"], ARM[arm]["marker"], "measured")
            _style(ax)
            ax.set_xticks(sorted(c["knowledge"].unique()))
            ax.set_title(f"{ARM[arm]['title'].split(':')[0]}, GF(2^{m}), 1 check", color=INK, fontsize=10)
            ax.set_xlabel(ARM[arm]["x"], color=INK, fontsize=9)
            if j == 0:
                ax.set_ylabel("silent decode rate", color=INK, fontsize=9)
            if i == 0:
                ax.legend(loc="upper left", fontsize=7.5, frameon=False, labelcolor=INK)
    return _save(fig, out_dir, "s2_w1_random",
                 "S2, one secret random check per packet, rejections remembered. Theory: keyed k/g + (1-k/g)/q, "
                 "keyless r/(g-1) + (1-r/(g-1))/q. Filled = measured (95% CI), dashed black + hollow = theory.")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", default=[str(_ROOT / "logs" / "verify_width_attack" / "*")])
    ap.add_argument("--out", default=str(_ROOT / "logs" / "verify_width_attack" / "plots"))
    a = ap.parse_args(argv)
    s = load(a.runs)
    for m in sorted(s["field_bits"].unique()):
        print("wrote", plot_random_grid(s, m, a.out))
    print("wrote", plot_w1(s, a.out))


if __name__ == "__main__":
    main()
