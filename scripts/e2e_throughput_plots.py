r"""Plots + summary table for ADR-0015 task 1: end-to-end transmissions / goodput vs BER against a
conventional-ARQ baseline (CRC-32: detect, drop, pull another coded packet).

Input (scripts/e2e_throughput_runs.sh layout): <root>/runs/<arm>/raw_trials.csv, scripts/pareto_sweep.py
schema v4, arms keyless | keyed | crc_arq | crc_acr; gen 4, df 100/300/1000 (N 3/7/21), payload-only errors.

Figures (<root>/plots, png + pdf, dpi 160):
  transmissions_vs_ber   row 1: packets received until decodable (mean over decoded generations, 95 % CI;
                         hollow = not every generation decoded within the cap -> mean of the decoded ones),
                         + the exact ARQ expectation 4.0039 / (1 - BER)^(8 df) (thin line, uncapped);
                         row 2: decoded within the cap (Wilson 95 % CI).
  goodput_vs_ber         row 1: info bytes delivered / wire bytes sent (ratio of totals over ALL generations;
                         a timeout counts its 64 packets, no info) + ARQ expectation without cap;
                         row 2: goodput per tick on one link = info bytes / packets (one packet per tick).
  repair_activity        wire-corrupted packets received and repaired packets inside the decode basis, per
                         decoded generation (the repair arms; ARQ by construction 0).
Table: e2e_summary.csv (one row per arm x df x BER).

Colour = arm: keyless #588157, keyed #3d405b, CRC-32 ARQ #4a3aa7, CRC-32 + ACR #c98500; marker + line style
carry the identity too (CVD / print safe).

CLI (PowerShell):
  $env:PYTHONPATH="."; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/e2e_throughput_plots.py --root E:/projects/studienarbeit/logs/e2e_throughput
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
import matplotlib.ticker
import numpy as np
import pandas as pd

from scripts.scaling_plots_from_csv import GRID, INK, INK_MUTED, _shade

ARM = {
    "keyless": {"color": "#588157", "marker": "o", "ls": "-", "label": "keyless (orthogonal tag) + ACR repair"},
    "keyed": {"color": "#3d405b", "marker": "s", "ls": "-.", "label": "keyed (homomorphic MAC) + ACR repair"},
    "crc_arq": {"color": "#4a3aa7", "marker": "^", "ls": "--", "label": "CRC-32 ARQ (drop + resend)"},
    "crc_acr": {"color": "#c98500", "marker": "D", "ls": ":", "label": "CRC-32 + ACR repair (S-PRAC-like)"},
}
Z = 1.96
Q = 256


def expected_clean_needed(g: int, q: int = Q) -> float:
    """E[# uniform random GF(q)^g vectors until rank g] = sum_{i<g} 1 / (1 - q^(i-g))."""
    return sum(1.0 / (1.0 - q ** (i - g)) for i in range(g))


def arq_expected_transmissions(ber, df, g):
    """Exact ARQ expectation on the payload-only channel: packet survives with p = (1-BER)^(8 df)."""
    p = (1.0 - np.asarray(ber, float)) ** (8 * df)
    return expected_clean_needed(g) / p


def _wilson(k, n, z=Z):
    if n <= 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _ratio_ci(num, den, z=Z):
    """Ratio of totals R = sum num / sum den with a delta-method half-width."""
    num, den = np.asarray(num, float), np.asarray(den, float)
    n = len(num)
    if n == 0 or den.sum() == 0:
        return math.nan, math.nan
    r = num.sum() / den.sum()
    if n < 2:
        return r, math.nan
    resid = num - r * den
    se = math.sqrt(resid.var(ddof=1) / n) / den.mean()
    return r, z * se


def load(root: Path) -> pd.DataFrame:
    paths = sorted(glob.glob(str(root / "runs" / "*" / "raw_trials.csv"))) \
        or sorted(glob.glob(str(root / "*" / "raw_trials.csv")))      # e.g. --root .../_smoke
    if not paths:
        raise FileNotFoundError(f"no runs under {root / 'runs'}")
    raw = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    return raw.drop_duplicates(subset=["arm", "data_fields", "n_segments", "bit_error_rate", "trial_idx"])


def summarize(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (arm, df, n, ber), g in raw.groupby(["arm", "data_fields", "n_segments", "bit_error_rate"]):
        gen = int(g["gen_size"].iloc[0])
        ok = g[g["correct"].astype(bool)]
        k, t = len(ok), len(g)
        lo, hi = _wilson(k, t)
        sil = int(g["silent_decode"].astype(bool).sum())
        tx = ok["packets_to_decode"].to_numpy(float)
        tx_ci = Z * tx.std(ddof=1) / math.sqrt(len(tx)) if len(tx) > 1 else math.nan
        gp, gp_ci = _ratio_ci(g["info_bits_delivered"], g["wire_bits_sent"])
        gt, gt_ci = _ratio_ci(g["info_bits_delivered"] / 8, g["packets_to_decode"])
        rows.append({
            "arm": arm, "data_fields": df, "n_segments": n, "bit_error_rate": ber, "gen_size": gen,
            "wire_bytes": int(g["wire_symbols"].iloc[0]), "trials": t, "decoded": k, "silent": sil,
            "timeouts": int((g["status"] == "timeout").sum()), "wall_limit": int((g["status"] == "wall_limit").sum()),
            "decode_rate": k / t, "decode_lo": lo, "decode_hi": hi,
            "tx_mean": tx.mean() if len(tx) else math.nan, "tx_ci": tx_ci,
            "retx_mean": tx.mean() - gen if len(tx) else math.nan,
            "arq_expected_tx": float(arq_expected_transmissions(ber, df, gen)),
            "goodput": gp, "goodput_ci": gp_ci, "goodput_per_tick_bytes": gt, "goodput_per_tick_ci": gt_ci,
            "corrupted_rx_mean": ok["n_corrupted_rx"].mean() if k else math.nan,
            "repaired_used_mean": ok["repaired_used"].mean() if k else math.nan,
            "wrong_used_total": int(g["wrong_used"].sum()),
            "pairs_recovered_mean": ok["pairs_recovered"].mean() if k else math.nan,
            "unpaired_recovered_mean": ok["unpaired_recovered"].mean() if k else math.nan,
            "scheme_mul_mean": ok["scheme_ops"].mean() if k else math.nan,
            "decode_mul_mean": ok["decode_ops"].mean() if k else math.nan,
            "crc_bytes_mean": ok["crc_bytes"].mean() if k else math.nan,
            "wall_s_mean_decoded": ok["wall_time_s"].mean() if k else math.nan,
        })
    return pd.DataFrame(rows)


def _style(ax, percent=False):
    ax.grid(True, which="major", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED, labelcolor=INK, labelsize=8)
    ax.set_xscale("log")
    if percent:
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))


def _line(ax, g, x, y, arm, err=None, hollow=None, label=True):
    g = g.sort_values(x)
    g = g[np.isfinite(g[y].to_numpy(float))]
    if g.empty:
        return
    st = ARM[arm]
    xs, ys = g[x].to_numpy(float), g[y].to_numpy(float)
    ax.plot(xs, ys, color=st["color"], ls=st["ls"], lw=1.8, zorder=2, label=st["label"] if label else None)
    if err is not None:
        e = g[err].to_numpy(float) if isinstance(err, str) else None
        if e is not None:
            ax.errorbar(xs, ys, yerr=np.where(np.isfinite(e), e, 0), fmt="none", ecolor=st["color"], elinewidth=0.9,
                        capsize=2, zorder=2)
    hol = g[hollow].to_numpy(bool) if hollow else np.zeros(len(xs), bool)
    for xv, yv, h in zip(xs, ys, hol):
        ax.plot(xv, yv, marker=st["marker"], ms=5.5, color=st["color"], mew=1.4,
                mfc="white" if h else st["color"], ls="none", zorder=3)


def _save(fig, out_dir: Path, name: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(out_dir / f"{name}.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  {out_dir / (name + '.png')}")


def _settings(s):
    t = s["trials"].max()
    return (f"single hop, g = 4, GF(2^8), 50 B data segments, payload-only bit errors, HD 2, budget 20000, "
            f"cap 64 packets, up to {t} generations per point")


def _legend(fig, axes, arms, extra=()):
    handles = [matplotlib.lines.Line2D([], [], color=ARM[a]["color"], ls=ARM[a]["ls"], marker=ARM[a]["marker"],
                                       lw=1.8, ms=5.5, label=ARM[a]["label"]) for a in arms]
    handles += list(extra)
    fig.legend(handles=handles, loc="lower center", ncol=min(3, len(handles)), frameon=False, fontsize=8.5,
               labelcolor=INK, bbox_to_anchor=(0.5, -0.01))


def plot_transmissions(s: pd.DataFrame, out_dir: Path):
    dfs = sorted(s["data_fields"].unique())
    arms = [a for a in ARM if a in set(s["arm"])]
    fig, axes = plt.subplots(2, len(dfs), figsize=(4.4 * len(dfs), 6.6), sharex=True,
                             gridspec_kw={"height_ratios": [2.0, 1.0]}, squeeze=False)
    s = s.assign(partial=s["decode_rate"] < 1.0)
    cap = 64
    for j, df in enumerate(dfs):
        ax, axr = axes[0][j], axes[1][j]
        sub = s[s["data_fields"] == df]
        n = int(sub["n_segments"].iloc[0])
        bers = np.logspace(np.log10(sub["bit_error_rate"].min()), np.log10(sub["bit_error_rate"].max()), 200)
        ax.plot(bers, arq_expected_transmissions(bers, df, 4), color=ARM["crc_arq"]["color"], lw=0.9, ls=(0, (1, 1.5)),
                alpha=0.9, zorder=1)
        for arm in arms:
            g = sub[sub["arm"] == arm]
            _line(ax, g, "bit_error_rate", "tx_mean", arm, err="tx_ci", hollow="partial")
            _line(axr, g, "bit_error_rate", "decode_rate", arm)
        ax.axhline(4, color=INK_MUTED, lw=0.8, ls="-", alpha=0.5)
        ax.axhline(cap, color=INK_MUTED, lw=0.8, ls="--", alpha=0.6)
        ax.text(sub["bit_error_rate"].min(), cap + 1.2, "cap 64", fontsize=7, color=INK_MUTED, va="bottom")
        ax.text(sub["bit_error_rate"].min(), 4 - 1.2, "g = 4", fontsize=7, color=INK_MUTED, va="top")
        ax.set_ylim(0, cap + 8)
        axr.set_ylim(-0.04, 1.04)
        _style(ax)
        _style(axr, percent=True)
        ax.set_title(f"payload {df} B  (N = {n} segments)", color=INK, fontsize=10)
        axr.set_xlabel("bit error rate (per payload bit)", color=INK, fontsize=9)
        if j == 0:
            ax.set_ylabel("packets received until decodable\n(mean of decoded generations)", color=INK, fontsize=9)
            axr.set_ylabel("decoded within 64 packets", color=INK, fontsize=9)
    arq_line = matplotlib.lines.Line2D([], [], color=ARM["crc_arq"]["color"], lw=0.9, ls=(0, (1, 1.5)),
                                       label="CRC-32 ARQ, exact expectation without cap")
    _legend(fig, axes, arms, extra=[arq_line])
    fig.suptitle("Transmissions until decodable vs BER: repair in place vs conventional ARQ\n" + _settings(s),
                 color=INK, fontsize=10.5)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    _save(fig, out_dir, "transmissions_vs_ber")


def plot_goodput(s: pd.DataFrame, out_dir: Path):
    dfs = sorted(s["data_fields"].unique())
    arms = [a for a in ARM if a in set(s["arm"])]
    fig, axes = plt.subplots(2, len(dfs), figsize=(4.4 * len(dfs), 6.6), sharex=True, squeeze=False)
    for j, df in enumerate(dfs):
        ax, axt = axes[0][j], axes[1][j]
        sub = s[s["data_fields"] == df]
        n = int(sub["n_segments"].iloc[0])
        crc_wire = sub[sub["arm"] == "crc_arq"]["wire_bytes"]
        if len(crc_wire):
            bers = np.logspace(np.log10(sub["bit_error_rate"].min()), np.log10(sub["bit_error_rate"].max()), 200)
            gp = 4 * df / (arq_expected_transmissions(bers, df, 4) * int(crc_wire.iloc[0]))
            ax.plot(bers, gp, color=ARM["crc_arq"]["color"], lw=0.9, ls=(0, (1, 1.5)), zorder=1)
            axt.plot(bers, 4 * df / arq_expected_transmissions(bers, df, 4), color=ARM["crc_arq"]["color"], lw=0.9,
                     ls=(0, (1, 1.5)), zorder=1)
        for arm in arms:
            g = sub[sub["arm"] == arm]
            _line(ax, g, "bit_error_rate", "goodput", arm, err="goodput_ci")
            _line(axt, g, "bit_error_rate", "goodput_per_tick_bytes", arm, err="goodput_per_tick_ci")
        ax.set_ylim(-0.03, 1.0)
        axt.set_ylim(bottom=-0.03 * df)
        _style(ax, percent=True)
        _style(axt)
        ax.set_title(f"payload {df} B  (N = {n} segments)", color=INK, fontsize=10)
        axt.set_xlabel("bit error rate (per payload bit)", color=INK, fontsize=9)
        if j == 0:
            ax.set_ylabel("goodput = info bytes delivered\n/ wire bytes sent", color=INK, fontsize=9)
            axt.set_ylabel("goodput per tick, one link\n(info bytes / packet slot)", color=INK, fontsize=9)
    arq_line = matplotlib.lines.Line2D([], [], color=ARM["crc_arq"]["color"], lw=0.9, ls=(0, (1, 1.5)),
                                       label="CRC-32 ARQ, exact expectation without cap")
    _legend(fig, axes, arms, extra=[arq_line])
    fig.suptitle("Goodput vs BER (real wire bytes: tags, keyless salt, CRCs, coefficients, retransmissions)\n"
                 + _settings(s) + "; a timeout counts its packets, no info", color=INK, fontsize=10.5)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    _save(fig, out_dir, "goodput_vs_ber")


def plot_repair_activity(s: pd.DataFrame, out_dir: Path):
    dfs = sorted(s["data_fields"].unique())
    arms = [a for a in ("keyless", "keyed", "crc_acr") if a in set(s["arm"])]
    fig, axes = plt.subplots(1, len(dfs), figsize=(4.4 * len(dfs), 3.6), sharex=True, squeeze=False)
    for j, df in enumerate(dfs):
        ax = axes[0][j]
        sub = s[(s["data_fields"] == df) & (s["decoded"] > 0)]
        for arm in arms:
            g = sub[sub["arm"] == arm]
            _line(ax, g, "bit_error_rate", "repaired_used_mean", arm)
            g2 = g.sort_values("bit_error_rate")
            ax.plot(g2["bit_error_rate"], g2["corrupted_rx_mean"], color=_shade(ARM[arm]["color"], 0.45),
                    ls=ARM[arm]["ls"], lw=1.0, zorder=1)
        _style(ax)
        ax.set_title(f"payload {df} B  (N = {int(s[s['data_fields'] == df]['n_segments'].iloc[0])})",
                     color=INK, fontsize=10)
        ax.set_xlabel("bit error rate (per payload bit)", color=INK, fontsize=9)
        if j == 0:
            ax.set_ylabel("packets per decoded generation", color=INK, fontsize=9)
    thin = matplotlib.lines.Line2D([], [], color=_shade(INK_MUTED, 0.6), lw=1.0, label="thin: corrupted packets received")
    thick = matplotlib.lines.Line2D([], [], color=INK_MUTED, lw=1.8, marker="o", label="marked: repaired + used in the decode")
    _legend(fig, axes, arms, extra=[thick, thin])
    fig.suptitle("Repair activity: wire-corrupted packets that were repaired and used in the decode basis\n"
                 + _settings(s), color=INK, fontsize=10.5)
    fig.tight_layout(rect=(0, 0.13, 1, 1))
    _save(fig, out_dir, "repair_activity")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path("E:/projects/studienarbeit/logs/e2e_throughput"))
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    out = a.out or a.root / "plots"
    raw = load(a.root)
    s = summarize(raw)
    out.mkdir(parents=True, exist_ok=True)
    s.sort_values(["data_fields", "bit_error_rate", "arm"]).to_csv(out / "e2e_summary.csv", index=False)
    print(f"  {out / 'e2e_summary.csv'}  ({len(raw)} trials, {len(s)} cells)")
    plot_transmissions(s, out)
    plot_goodput(s, out)
    plot_repair_activity(s, out)


if __name__ == "__main__":
    main()
