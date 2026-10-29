r"""Plots + summary tables for the keyless vs CRC-32 comparison (ADR-0014).

Inputs (scripts/crc32_vs_keyless_runs.sh layout under --root):
  recovery/<run>/raw_trials.csv   isolated_recovery_sim schema v5, arms keyless (W 1..4) / crc_acr / crc_blind
                                  (W = -1), config arc_only_a (payload errors, payload repair)
  detection/<run>/*.csv           simulation/detection_comparison_sim.py output

Figures (--out, default <root>/plots), png + pdf:
  recovery_rate_hd{h}             recovered / targets vs BER, one panel per payload size; Wilson 95 % CI
  repair_time_hd{h}               wall-clock per recovery call, keyless vs CRC ACR-localized, LINEAR y,
                                  categorical BER axis (bars) + a CRC / keyless ratio row (ratio of means).
                                  Keyless at W = 4 (all 4 helpers: the same 4 tag bytes as the CRC-32); W 1-3
                                  are in recovery_summary.csv.
  repair_time_all_hd{h}           same incl. blind CRC, LOG y (blind is up to ~23x slower).
  recovery_vs_hd                  recovered / targets vs max HD (x = 1..4), one column per payload size, one row
                                  per BER (1e-3, 3e-3); keyless W=4 (+ thin W=1), CRC ACR, CRC blind; Wilson 95 %
                                  CI bars; points dodged sideways (crc_acr == keyless W>=2 would sit on top)
  detection_miss_vs_k            P(miss | exactly k flipped bits): k <= 4 exact counts, k = 5, 6 Monte Carlo
  detection_miss_vs_ber           P(miss | corrupted segment) vs BER: analytic line + Monte Carlo points
  detection_verify_time           wall-clock of one accept/reject check of one data segment
Tables: recovery_summary.csv, detection_summary.csv, silent_decodes_by_hd.csv (silent decodes per arm x W x
max HD, per payload size + pooled; the pooled arm x HD count table is also printed).

Colour = scheme: keyless #588157 (the project's keyless green; W levels = lighter -> darker shades of it),
CRC acr #4a3aa7, CRC blind #c98500. Shape/linestyle carry identity too (CVD/print safe).

CLI (PowerShell):
  $env:PYTHONPATH="."; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/crc32_vs_keyless_plots.py --root logs/crc32_vs_keyless
Ticket 21 (field backends): --runs GLOB picks the run dirs under recovery/ (default all), --keyless-backend
NAME names the keyless inner-product backend in the repair-time legend + titles (default: Python table loop),
e.g. --runs "*_table_*" / --runs "df*_hd2_seeds50" --keyless-backend galois.
"""
import argparse
import glob
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from scripts.scaling_plots_from_csv import GRID, INK, INK_MUTED, _shade

KEYLESS = "#588157"
ARM = {"keyless": {"color": KEYLESS, "marker": "o", "ls": "-", "label": "keyless (W=4)"},
       "crc_acr": {"color": "#4a3aa7", "marker": "^", "ls": "--", "label": "CRC-32, ACR-localized"},
       "crc_blind": {"color": "#c98500", "marker": "D", "ls": ":", "label": "CRC-32, blind"}}
W_LEVELS = (1, 2, 3, 4)
Z = 1.96


def _w_color(w, w_max=4):
    return _shade(KEYLESS, 0.5 + 0.5 * w / w_max)


def _wilson(k, n, z=Z):
    if n <= 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _style(ax):
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED, labelcolor=INK, labelsize=8)


def _save(fig, out_dir, name):
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(out_dir / f"{name}.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_dir / name}.png")


# ── recovery ────────────────────────────────────────────────────────────────

def load_recovery(root: Path, runs: str = "*") -> pd.DataFrame:
    files = sorted(glob.glob(str(root / "recovery" / runs / "raw_trials.csv")))
    assert files, f"no recovery runs matching {runs!r} under {root / 'recovery'}"
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    df["arm_w"] = np.where(df.arm.str.startswith("crc"), df.arm, df.arm + "_W" + df.W.astype(str))
    df["seg_bytes"] = df.data_fields // df.num_data_segments
    return df


def recovery_summary(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["data_fields", "num_data_segments", "max_combined_hd", "candidates_budget", "bit_error_rate",
                    "arm_w"])
    s = g.agg(seeds=("seed", "nunique"), targets=("T", "sum"), corrupted=("n_info_corrupted", "sum"),
              recovered=("recovered", "sum"), silent=("silent", "sum"), failed=("failed", "sum"),
              time_ms_mean=("recovery_time_s", lambda x: 1e3 * x.mean()),
              time_ms_sd=("recovery_time_s", lambda x: 1e3 * x.std(ddof=1)),
              field_ops_mean=("recovery_ops", "mean"), crc_bytes_mean=("recovery_crc_bytes", "mean")).reset_index()
    s["recovery_rate"] = s.recovered / s.targets
    s["silent_rate"] = s.silent / s.targets
    # recovered among the targets that actually had an error (the rest are trivially "recovered")
    s["recovery_rate_corrupted"] = (s.recovered - (s.targets - s.corrupted)) / s.corrupted.where(s.corrupted > 0)
    return s


def plot_recovery_rate(s: pd.DataFrame, out: Path):
    for hd, sh in s.groupby("max_combined_hd"):
        dfs = sorted(sh.data_fields.unique())
        fig, axes = plt.subplots(1, len(dfs), figsize=(4.2 * len(dfs), 3.6), sharey=True, squeeze=False)
        for ax, d in zip(axes[0], dfs):
            sd = sh[sh.data_fields == d]
            n = int(sd.num_data_segments.iloc[0])
            lines = [(f"keyless_W{w}", f"keyless W={w}", _w_color(w), "o", "-") for w in W_LEVELS] + \
                    [(a, ARM[a]["label"], ARM[a]["color"], ARM[a]["marker"], ARM[a]["ls"]) for a in ("crc_acr", "crc_blind")]
            for key, label, color, marker, ls in lines:
                r = sd[sd.arm_w == key].sort_values("bit_error_rate")
                if r.empty:
                    continue
                if key in ("keyless_W4", "crc_acr", "crc_blind"):   # bands for the headline lines only
                    ci = np.array([_wilson(k, n_) for k, n_ in zip(r.recovered, r.targets)])
                    ax.fill_between(r.bit_error_rate, ci[:, 0], ci[:, 1], color=color, alpha=0.12, linewidth=0)
                ax.plot(r.bit_error_rate, r.recovery_rate, ls, marker=marker, color=color, linewidth=2,
                        markersize=8 if marker != "o" else 6, markerfacecolor="white" if key == "crc_blind" else color,
                        markeredgewidth=1.4, label=label)
            ax.set_xscale("log")
            ax.set_ylim(-0.02, 1.02)
            ax.set_title(f"payload {d} B, {n} data segments of {d // n} B", color=INK, fontsize=10)
            ax.set_xlabel("bit error rate", color=INK, fontsize=9)
            _style(ax)
        axes[0][0].set_ylabel("targets recovered (fraction)", color=INK, fontsize=9)
        axes[0][-1].legend(fontsize=7.5, frameon=False, labelcolor=INK, loc="lower left")
        fig.suptitle(f"Recovery, keyless vs CRC-32 (payload errors, max HD {hd}, budget 20000)", color=INK, fontsize=11)
        _save(fig, out, f"recovery_rate_hd{hd}")


def _per_seed_ms(sd, key):
    """seed x BER table of one arm's recovery-call wall-clock in ms."""
    return sd[sd.arm_w == key].pivot_table(index="seed", columns="bit_error_rate", values="recovery_time_s") * 1e3


def _arm_label(arm, keyless_backend=None):
    """Legend label; ticket 21: the keyless line names its inner-product backend when given."""
    if arm == "keyless" and keyless_backend:
        return f"keyless (W=4, {keyless_backend})"
    return ARM[arm]["label"]


def plot_repair_time(df: pd.DataFrame, out: Path, keyless_backend: str | None = None):
    """Linear y (user preference), keyless vs CRC ACR-localized only -- the like-for-like pair
    (same ACR columns, same search, only the oracle differs). Blind CRC is up to ~23x slower and
    would flatten both bars, so it gets its own log-y figure (plot_repair_time_all)."""
    arms = {"keyless": "keyless_W4", "crc_acr": "crc_acr"}
    for hd, dh in df.groupby("max_combined_hd"):
        dfs = sorted(dh.data_fields.unique())
        bers = sorted(dh.bit_error_rate.unique())
        fig, axes = plt.subplots(2, len(dfs), figsize=(4.4 * len(dfs), 5.0), squeeze=False,
                                 gridspec_kw={"height_ratios": [2.2, 1]}, sharex="col")
        for j, d in enumerate(dfs):
            ax, ax2 = axes[0][j], axes[1][j]
            sd = dh[dh.data_fields == d]
            n = int(sd.num_data_segments.iloc[0])
            x = np.arange(len(bers))
            width = 0.38
            t = {a: _per_seed_ms(sd, k) for a, k in arms.items()}
            for i, a in enumerate(arms):
                m = np.array([t[a][b].mean() for b in bers])
                c = np.array([Z * t[a][b].std(ddof=1) / math.sqrt(t[a][b].count()) for b in bers])
                ax.bar(x + (i - 0.5) * width, m, width * 0.92, color=ARM[a]["color"], label=_arm_label(a, keyless_backend))
                ax.errorbar(x + (i - 0.5) * width, m, yerr=c, fmt="none", ecolor=INK_MUTED, elinewidth=0.9, capsize=2)
            r = np.array([t["crc_acr"][b].mean() / t["keyless"][b].mean() for b in bers])
            ax2.plot(x, r, ARM["crc_acr"]["ls"], marker=ARM["crc_acr"]["marker"], color=ARM["crc_acr"]["color"],
                     linewidth=1.8, markersize=7)
            for x_, r_ in zip(x, r):
                ax2.annotate(f"{r_:.1f}", (x_, r_), textcoords="offset points", xytext=(0, 7), ha="center",
                             fontsize=7, color=INK)
            ax2.axhline(1.0, color=INK_MUTED, linewidth=1, linestyle=":")
            ax2.set_ylim(0, max(1.5, float(np.nanmax(r)) * 1.3))
            ax.set_title(f"payload {d} B, {n} data segments of {d // n} B", color=INK, fontsize=10)
            ax2.set_xticks(x, [f"{b:.0e}" for b in bers], rotation=45)
            ax2.set_xlabel("bit error rate", color=INK, fontsize=9)
            for a_ in (ax, ax2):
                _style(a_)
            if j == 0:
                ax.set_ylabel("ms per recovery call\n(4 targets)", color=INK, fontsize=9)
                ax2.set_ylabel("CRC-ACR / keyless\n(ratio of means)", color=INK, fontsize=9)
        axes[0][-1].legend(fontsize=7.5, frameon=False, labelcolor=INK, loc="upper left")
        fig.suptitle(f"Repair wall-clock, keyless vs CRC-32 ACR-localized (max HD {hd}; mean, 95 % CI over seeds; "
                     f"CRC = zlib (C), keyless = {keyless_backend or 'Python'})",
                     color=INK, fontsize=10.5)
        _save(fig, out, f"repair_time_hd{hd}")


def plot_repair_time_all(df: pd.DataFrame, out: Path, keyless_backend: str | None = None):
    """All three arms incl. blind CRC on a LOG y (the spread is up to ~23x)."""
    arms = {"keyless": "keyless_W4", "crc_acr": "crc_acr", "crc_blind": "crc_blind"}
    for hd, dh in df.groupby("max_combined_hd"):
        dfs = sorted(dh.data_fields.unique())
        fig, axes = plt.subplots(1, len(dfs), figsize=(4.2 * len(dfs), 3.6), sharey=True, squeeze=False)
        for ax, d in zip(axes[0], dfs):
            sd = dh[dh.data_fields == d]
            n = int(sd.num_data_segments.iloc[0])
            for a, k in arms.items():
                t = _per_seed_ms(sd, k)
                bers = sorted(t.columns)
                m = np.array([t[b].mean() for b in bers])
                c = np.array([Z * t[b].std(ddof=1) / math.sqrt(t[b].count()) for b in bers])
                ax.fill_between(bers, np.maximum(m - c, m * 0.05), m + c, color=ARM[a]["color"], alpha=0.12, linewidth=0)
                ax.plot(bers, m, ARM[a]["ls"], marker=ARM[a]["marker"], color=ARM[a]["color"], linewidth=2,
                        markersize=7, markerfacecolor="white" if a == "crc_blind" else ARM[a]["color"],
                        markeredgewidth=1.4, label=_arm_label(a, keyless_backend))
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.set_title(f"payload {d} B, {n} data segments of {d // n} B", color=INK, fontsize=10)
            ax.set_xlabel("bit error rate", color=INK, fontsize=9)
            _style(ax)
        axes[0][0].set_ylabel("ms per recovery call (4 targets, log)", color=INK, fontsize=9)
        axes[0][0].legend(fontsize=7.5, frameon=False, labelcolor=INK, loc="upper left")
        fig.suptitle(f"Repair wall-clock incl. blind CRC-32 (max HD {hd}; mean, 95 % CI over seeds; "
                     f"CRC = zlib (C), keyless = {keyless_backend or 'Python'})", color=INK,
                     fontsize=10.5)
        _save(fig, out, f"repair_time_all_hd{hd}")


# key, label, colour, marker, linestyle, linewidth, x-dodge -- keyless W=1 thin (weakest acceptance check)
HD_LINES = (("keyless_W1", "keyless W=1", _w_color(1), "o", "-", 1.0, -0.135),
            ("keyless_W4", "keyless W=4", _w_color(4), "o", "-", 2.0, -0.045),
            ("crc_acr", ARM["crc_acr"]["label"], ARM["crc_acr"]["color"], "^", "--", 2.0, 0.045),
            ("crc_blind", ARM["crc_blind"]["label"], ARM["crc_blind"]["color"], "D", ":", 2.0, 0.135))
ARM_W_ORDER = [f"keyless_W{w}" for w in W_LEVELS] + ["crc_acr", "crc_blind"]


def _ber_txt(b):
    return f"{b:.0e}".replace("e-0", "e-")


def plot_recovery_vs_hd(s: pd.DataFrame, out: Path, bers=(1e-3, 3e-3)):
    """Recovery vs max combined HD: x = HD, one column per payload size, one row per BER. Error bars =
    Wilson 95 % CI over targets. Points are dodged sideways: crc_acr == keyless at W >= 2 (same columns,
    same search, only the oracle differs), so undodged their markers would hide each other."""
    dfs = sorted(s.data_fields.unique())
    hds = sorted(s.max_combined_hd.unique())
    bers = [b for b in bers if np.isclose(s.bit_error_rate, b).any()]
    fig, axes = plt.subplots(len(bers), len(dfs), figsize=(4.0 * len(dfs), 2.9 * len(bers) + 0.5),
                             sharex=True, sharey=True, squeeze=False)
    for i, b in enumerate(bers):
        for j, d in enumerate(dfs):
            ax = axes[i][j]
            sd = s[(s.data_fields == d) & np.isclose(s.bit_error_rate, b)]
            n = int(sd.num_data_segments.iloc[0])
            for key, label, color, marker, ls, lw, dx in HD_LINES:
                r = sd[sd.arm_w == key].sort_values("max_combined_hd")
                if r.empty:
                    continue
                x = r.max_combined_hd.to_numpy() + dx
                y = r.recovery_rate.to_numpy()
                ci = np.array([_wilson(k, n_) for k, n_ in zip(r.recovered, r.targets)])
                yerr = np.clip([y - ci[:, 0], ci[:, 1] - y], 0, None)   # rounding at p = 0 / 1
                ax.errorbar(x, y, yerr=yerr, fmt="none", ecolor=color, elinewidth=1.0, capsize=2.5)
                ax.plot(x, y, ls, marker=marker, color=color, linewidth=lw,
                        markersize=(4.5 if lw < 1.5 else 7 if marker != "o" else 6),
                        markerfacecolor="white" if key == "crc_blind" else color, markeredgewidth=1.3, label=label)
            ax.set_xticks(hds, [str(h) for h in hds])
            ax.set_ylim(-0.02, 1.02)
            ax.set_title(f"payload {d} B ({n} x {d // n} B), BER {_ber_txt(b)}", color=INK, fontsize=9.5)
            if i == len(bers) - 1:
                ax.set_xlabel("max Hamming distance searched", color=INK, fontsize=9)
            if j == 0:
                ax.set_ylabel("targets recovered (fraction)", color=INK, fontsize=9)
            _style(ax)
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=len(labels), fontsize=8,
               frameon=False, labelcolor=INK)
    budget = int(s.candidates_budget.iloc[0])
    fig.suptitle(f"Recovery vs max HD, keyless vs CRC-32 (payload errors, budget {budget} per search step; "
                 f"Wilson 95 % CI, points dodged)", color=INK, fontsize=10.5)
    _save(fig, out, "recovery_vs_hd")


def silent_by_hd(s: pd.DataFrame, out: Path) -> pd.DataFrame:
    """Silent decodes (accepted, but info columns wrong) per arm x W x max HD -- per payload size and pooled
    over payload sizes + BERs. Writes silent_decodes_by_hd.csv and prints the pooled count table."""
    keys = ["arm_w", "max_combined_hd"]
    per_df = s.groupby(keys + ["data_fields"])[["silent", "targets", "corrupted"]].sum().reset_index()
    pooled = s.groupby(keys)[["silent", "targets", "corrupted"]].sum().reset_index()
    pooled["data_fields"] = "all"
    t = pd.concat([per_df, pooled], ignore_index=True)
    t["silent_rate"] = t.silent / t.targets
    t["arm_w"] = pd.Categorical(t.arm_w, [a for a in ARM_W_ORDER if a in set(t.arm_w)], ordered=True)
    t = t.sort_values(["arm_w", "max_combined_hd"], kind="stable")
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "silent_decodes_by_hd.csv", index=False)
    piv = (pooled.pivot(index="arm_w", columns="max_combined_hd", values="silent")
           .reindex([a for a in ARM_W_ORDER if a in set(pooled.arm_w)]))
    tg = pooled.pivot(index="arm_w", columns="max_combined_hd", values="targets")
    print("  silent decodes per arm x max HD (all payload sizes + BERs; targets per cell: "
          + ", ".join(f"HD{h} {int(tg[h].max())}" for h in tg.columns) + "):")
    print(piv.fillna(-1).astype(int).replace(-1, "-").to_string())
    return t


# ── detection ───────────────────────────────────────────────────────────────

LEVEL_STYLE = {**{f"keyless_W{w}": dict(color=_w_color(w), marker="o",
                                        label="keyless self-check only" if w == 0 else f"keyless self + {w} helper{'s' * (w > 1)}")
                  for w in range(5)},
               "crc32": dict(color=ARM["crc_acr"]["color"], marker="^", label="CRC-32")}


def load_detection(root: Path):
    runs = sorted(glob.glob(str(root / "detection" / "*")))
    assert runs, f"no detection runs under {root / 'detection'}"
    run = Path(runs[-1])
    return {n: pd.read_csv(run / f"{n}.csv") for n in
            ("exact_counts", "analytic_ber", "mc_exact_k", "mc_ber", "verify_time")}, run


def detection_summary(d) -> pd.DataFrame:
    ex = d["exact_counts"].groupby(["level", "k"])[["undetected", "patterns"]].sum().reset_index()
    ex["p_miss"] = ex.undetected / ex.patterns
    ex["source"] = "exact"
    mk = d["mc_exact_k"].groupby(["level", "k"])[["missed", "trials"]].sum().reset_index()
    mk = mk[~mk.k.isin(ex.k.unique())].rename(columns={"missed": "undetected", "trials": "patterns"})
    mk["p_miss"] = mk.undetected / mk.patterns
    mk["source"] = "monte_carlo"
    return pd.concat([ex, mk], ignore_index=True).sort_values(["level", "k"])


def plot_detection_vs_k(summary: pd.DataFrame, seg_bytes, out: Path):
    levels = list(LEVEL_STYLE)
    ks = sorted(summary.k.unique())
    fig, ax = plt.subplots(figsize=(8.6, 3.8))
    width = 0.8 / len(levels)
    floor = 1e-14
    for i, lv in enumerate(levels):
        r = summary[summary.level == lv].set_index("k")
        xs = np.arange(len(ks)) + (i - (len(levels) - 1) / 2) * width
        ys = [r.p_miss.get(k, np.nan) for k in ks]
        st = LEVEL_STYLE[lv]
        ax.bar(xs, [y if y > 0 else np.nan for y in ys], width * 0.9, color=st["color"], label=st["label"],
               bottom=floor)
        zx = [x_ for x_, y in zip(xs, ys) if y == 0]
        ax.plot(zx, [floor * 3] * len(zx), "x", color=st["color"], markersize=5, markeredgewidth=1.4)
    ax.set_yscale("log")
    ax.set_ylim(floor, 1)
    ax.set_xticks(np.arange(len(ks)), [f"{k}{' (MC)' if k > 4 else ''}" for k in ks])
    ax.set_xlabel("flipped bits in the segment payload", color=INK, fontsize=9)
    ax.set_ylabel("P(error not detected)", color=INK, fontsize=9)
    ax.set_title(f"Detection per {seg_bytes} B data segment: k <= 4 exact count, k > 4 Monte Carlo; "
                 f"x = never missed (exact) / none seen (MC)", color=INK, fontsize=10)
    _style(ax)
    ax.legend(fontsize=7, frameon=False, labelcolor=INK, ncol=3, loc="upper right")
    _save(fig, out, "detection_miss_vs_k")


def plot_detection_vs_ber(d, out: Path):
    an = d["analytic_ber"].groupby(["level", "ber"]).p_miss_given_corrupted.mean().reset_index()
    mc = d["mc_ber"].groupby(["level", "ber"])[["missed", "corrupted_segments"]].sum().reset_index()
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    for lv, st in LEVEL_STYLE.items():
        a = an[an.level == lv].sort_values("ber")
        ax.plot(a.ber, a.p_miss_given_corrupted, "-", color=st["color"], linewidth=2, label=st["label"])
        m = mc[(mc.level == lv) & (mc.missed > 0)]
        ax.plot(m.ber, m.missed / m.corrupted_segments, st["marker"], color=st["color"], markersize=8,
                markerfacecolor="white", markeredgewidth=1.5)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("bit error rate", color=INK, fontsize=9)
    ax.set_ylabel("P(miss | segment corrupted)", color=INK, fontsize=9)
    ax.set_title("Detection vs BER: line = exact counts + tail model; open marker = Monte Carlo (only where > 0)",
                 color=INK, fontsize=9)
    _style(ax)
    ax.legend(fontsize=7, frameon=False, labelcolor=INK, loc="lower right")
    _save(fig, out, "detection_miss_vs_ber")


def plot_verify_time(d, out: Path, keyless_backend: str | None = None):
    vt = d["verify_time"].groupby("level").seconds_per_verify.mean() * 1e6
    seg = int(d["verify_time"].payload_bytes.iloc[0])
    levels = [lv for lv in LEVEL_STYLE if lv in vt.index]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    x = np.arange(len(levels))
    ax.bar(x, [vt[lv] for lv in levels], 0.7, color=[LEVEL_STYLE[lv]["color"] for lv in levels])
    for x_, lv in zip(x, levels):
        ax.text(x_, vt[lv], f"{vt[lv]:.1f}", ha="center", va="bottom", fontsize=7.5, color=INK)
    ax.set_xticks(x, [LEVEL_STYLE[lv]["label"].replace("keyless ", "keyless\n") for lv in levels], fontsize=7)
    ax.set_ylabel("µs per check", color=INK, fontsize=9)
    ax.set_title(f"One accept/reject check of a {seg} B data segment (CRC-32 = zlib, C; keyless = {keyless_backend or 'Python'})", color=INK,
                 fontsize=9.5)
    _style(ax)
    _save(fig, out, "detection_verify_time")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(_ROOT / "logs" / "crc32_vs_keyless"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--skip-detection", action="store_true")
    ap.add_argument("--runs", default="*", help="glob of run dirs under <root>/recovery (default: all)")
    ap.add_argument("--keyless-backend", default=None,
                    help="name of the keyless inner-product backend for the repair-time legend/titles "
                         "(e.g. galois); default = Python table loop, labels unchanged")
    a = ap.parse_args(argv)
    root = Path(a.root)
    out = Path(a.out) if a.out else root / "plots"
    df = load_recovery(root, a.runs)
    s = recovery_summary(df)
    out.mkdir(parents=True, exist_ok=True)
    s.to_csv(out / "recovery_summary.csv", index=False)
    print(f"  silent decodes, all recovery cells: {int(s.silent.sum())}")
    plot_recovery_rate(s, out)
    plot_repair_time(df, out, a.keyless_backend)
    plot_repair_time_all(df, out, a.keyless_backend)
    plot_recovery_vs_hd(s, out)
    silent_by_hd(s, out)
    if not a.skip_detection:
        d, run = load_detection(root)
        ds = detection_summary(d)
        ds.to_csv(out / "detection_summary.csv", index=False)
        seg = int(d["exact_counts"].payload_bytes.mode().iloc[0])
        plot_detection_vs_k(ds, seg, out)
        plot_detection_vs_ber(d, out)
        plot_verify_time(d, out, a.keyless_backend)


if __name__ == "__main__":
    main()
