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

from simulation.verify_width_attack_sim import summarize, theory_admit_reeval

ARM = {"keyless": {"color": "#588157", "marker": "o", "x": "r = honest packets observed",
                   "title": "keyless: vc witnesses"},
       "keyed": {"color": "#3d405b", "marker": "s", "x": "k = keys leaked (of g)", "title": "keyed: W of g tags"}}
POLICY = {"first": "deterministic (first witnesses / first keys)", "random": "receiver-secret random subset"}
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


def _draw(ax, sub, arm, m, g, widths):
    ts = np.linspace(0.45, 1.0, len(widths))
    for w, t in zip(widths, ts):
        c = sub[sub["width"] == w].sort_values("knowledge")
        if c.empty:
            continue
        color = _shade(ARM[arm]["color"], t)
        ks = np.arange(0, c["knowledge"].max() + 1)
        pol = c["policy"].iloc[0]
        th = [theory_admit_reeval(arm, pol, int(k), None if w < 0 else int(w), g, 2 ** m) for k in ks]
        ax.plot(ks, th, color=THEORY, linewidth=1, zorder=1)
        x, y = c["knowledge"].to_numpy(), c["admit_rate"].to_numpy()
        lo, hi = c["admit_lo"].to_numpy(), c["admit_hi"].to_numpy()
        ax.errorbar(x, y, yerr=[np.clip(y - lo, 0, None), np.clip(hi - y, 0, None)], fmt="none", ecolor=color, elinewidth=1, capsize=2, zorder=2)
        ax.plot(x, y, color=color, linewidth=1.6, marker=ARM[arm]["marker"], markersize=6, zorder=3,
                label=f"{'W' if arm == 'keyed' else 'vc'} = {_wlabel(w)}")


def _save(fig, out_dir, name, caption):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.text(0.5, 0.005, caption, ha="center", va="bottom", fontsize=7.5, color=INK_MUTED, wrap=True)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    for ext in ("png", "pdf"):
        fig.savefig(out_dir / f"{name}.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out_dir / f"{name}.png"


def plot_policy_grid(summary, m, out_dir):
    s = summary[summary["field_bits"] == m]
    g = int(s["gen_size"].iloc[0])
    fig, axes = plt.subplots(2, 2, figsize=(9.5, 6.4), sharey=True)
    for i, arm in enumerate(ARM):
        for j, pol in enumerate(POLICY):
            ax = axes[i][j]
            sub = s[(s["arm"] == arm) & ((s["policy"] == pol) | (s["width"] < 0))].copy()
            sub.loc[sub["width"] < 0, "policy"] = pol   # width=all is policy-free: draw it in both columns
            widths = sorted(sub["width"].unique(), key=lambda w: 99 if w < 0 else w)
            _draw(ax, sub, arm, m, g, widths)
            _style(ax)
            ax.set_xticks(sorted(sub["knowledge"].unique()))
            if i == 0:
                ax.set_title(POLICY[pol], color=INK, fontsize=10)
            if j == 0:
                ax.set_ylabel(f"{ARM[arm]['title']}\nforgery admitted", color=INK, fontsize=9)
                ax.legend(loc="upper left", fontsize=7.5, frameon=False, labelcolor=INK)
            ax.set_xlabel(ARM[arm]["x"], color=INK, fontsize=9)
    return _save(fig, out_dir, f"s2_admit_vs_knowledge_m{m}",
                 f"S2: one splice-free forged packet (early strike, repair off), GF(2^{m}), g={g}, N=2, "
                 f"{int(s['trials'].iloc[0])} paired trials/cell. Gray = theory (keyless random incl. the "
                 "re-evaluation term). Lighter = narrower check (vc = keyless witnesses, W = keyed tags).")


def plot_w1(summary, out_dir):
    s = summary[summary["width"] == 1]
    ms = sorted(s["field_bits"].unique())
    fig, axes = plt.subplots(len(ms), 2, figsize=(9.5, 3.2 * len(ms)), sharey=True, squeeze=False)
    for i, m in enumerate(ms):
        for j, arm in enumerate(ARM):
            ax = axes[i][j]
            for pol, t in (("first", 0.5), ("random", 1.0)):
                c = s[(s["field_bits"] == m) & (s["arm"] == arm) & (s["policy"] == pol)].sort_values("knowledge")
                g = int(c["gen_size"].iloc[0])
                ks = np.arange(0, c["knowledge"].max() + 1)
                ax.plot(ks, [theory_admit_reeval(arm, pol, int(k), 1, g, 2 ** m) for k in ks], color=THEORY,
                        linewidth=1, zorder=1)
                x, y = c["knowledge"].to_numpy(), c["admit_rate"].to_numpy()
                color = _shade(ARM[arm]["color"], t)
                ax.errorbar(x, y, yerr=[np.clip(y - c["admit_lo"].to_numpy(), 0, None), np.clip(c["admit_hi"].to_numpy() - y, 0, None)], fmt="none",
                            ecolor=color, elinewidth=1, capsize=2)
                ax.plot(x, y, color=color, marker=ARM[arm]["marker"], markersize=6, linewidth=1.6,
                        linestyle="--" if pol == "first" else "-", zorder=3)
                ax.annotate(pol, (x[1], y[1]), textcoords="offset points", xytext=(6, -10 if pol == "random" else 4),
                            fontsize=7, color=INK_MUTED)
            _style(ax)
            ax.set_xticks(sorted(c["knowledge"].unique()))
            ax.set_title(f"{ARM[arm]['title'].split(':')[0]}, GF(2^{m}), width 1", color=INK, fontsize=10)
            ax.set_xlabel(ARM[arm]["x"], color=INK, fontsize=9)
            if j == 0:
                ax.set_ylabel("forgery admitted", color=INK, fontsize=9)
    return _save(fig, out_dir, "s2_w1_first_vs_random",
                 "S2, single check per packet: deterministic choice (dashed) = 100% as soon as the attacker knows "
                 "the checked witness/key; receiver-secret choice (solid) = k/g + (1-k/g)/q (keyed), "
                 "r/(g-1) + (1-r/(g-1))/q + re-evaluation term (keyless). Gray = theory.")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", default=[str(_ROOT / "logs" / "verify_width_attack" / "*")])
    ap.add_argument("--out", default=str(_ROOT / "logs" / "verify_width_attack" / "plots"))
    a = ap.parse_args(argv)
    s = load(a.runs)
    for m in sorted(s["field_bits"].unique()):
        print("wrote", plot_policy_grid(s, m, a.out))
    print("wrote", plot_w1(s, a.out))


if __name__ == "__main__":
    main()
