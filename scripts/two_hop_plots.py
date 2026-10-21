r"""Plots + summary table for ADR-0015 task 2: two-hop recoding, Source -> Relay (recodes) -> Sink.

Input: <root>/runs/<run>/raw_trials.csv (simulation/two_hop_sim.py, schema v1; every run dir is pooled,
duplicate (cell, trial) rows dropped). Symmetric runs (ber1 == ber2) are plotted against the BER;
asymmetric runs (--ber2 fixed) get their own figure set with suffix _ber2_<value>.

Figures (<root>/plots, png + pdf, dpi 160):
  silent_stall_vs_ber    row 1: silent wrong decodes at the sink (headline), row 2: timeouts (stall: no
                         decode within the cap), Wilson 95 % CI; one panel per payload size.
  packets_per_hop_vs_ber hop-1 and hop-2 packets until the sink decodes (mean of decoded generations,
                         hollow = not every generation decoded).
  relay_pollution_vs_ber corrupted hop-1 packets that entered the relay's recoding, per generation.
Table: two_hop_summary.csv (one row per scheme x policy x df x BER) incl. relay work per relayed packet.

Colour = scheme (keyless #588157, keyed #3d405b, CRC-32 #4a3aa7; the CRC blind relay in the extra CRC
colour #c98500 -- it is the one arm that decodes silently wrong), blind = dashed + lighter shade for
keyless / keyed; marker = scheme.

CLI (PowerShell):
  $env:PYTHONPATH="."; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/two_hop_plots.py --root E:/projects/studienarbeit/logs/two_hop_recoding
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

KEYLESS, KEYED, CRC, CRC_X = "#588157", "#3d405b", "#4a3aa7", "#c98500"
ARMS = {
    ("crc", "verify"): {"color": CRC, "marker": "^", "ls": "-", "label": "CRC-32, relay verifies + re-CRCs"},
    ("crc", "blind"): {"color": CRC_X, "marker": "D", "ls": "--", "label": "CRC-32, blind relay re-CRCs"},
    ("keyless", "verify"): {"color": KEYLESS, "marker": "o", "ls": "-", "label": "keyless, relay verifies"},
    ("keyless", "blind"): {"color": _shade(KEYLESS, 0.6), "marker": "o", "ls": "--", "label": "keyless, blind relay"},
    ("keyed", "verify"): {"color": KEYED, "marker": "s", "ls": "-", "label": "keyed, relay holds key + verifies"},
    ("keyed", "blind"): {"color": _shade(KEYED, 0.6), "marker": "s", "ls": "--", "label": "keyed, blind relay (no key)"},
}
Z = 1.96


def _wilson(k, n, z=Z):
    if n <= 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def load(root: Path) -> pd.DataFrame:
    paths = sorted(glob.glob(str(root / "runs" / "*" / "raw_trials.csv"))) \
        or sorted(glob.glob(str(root / "*" / "raw_trials.csv")))
    if not paths:
        raise FileNotFoundError(f"no runs under {root}")
    raw = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    return raw.drop_duplicates(subset=["scheme", "policy", "data_fields", "n_segments", "ber1", "ber2", "trial_idx"])


def summarize(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (scheme, policy, df, n, b1, b2), g in raw.groupby(["scheme", "policy", "data_fields", "n_segments", "ber1", "ber2"]):
        t = len(g)
        ok = g[g["status"] == "decoded"]
        k_sil = int((g["status"] == "silent_decode").sum())
        k_to = int((g["status"] == "timeout").sum())
        sl, sh = _wilson(k_sil, t)
        tl, th = _wilson(k_to, t)
        h1, h2 = ok["hop1_packets"].to_numpy(float), ok["hop2_packets"].to_numpy(float)
        relayed = g["hop2_packets"].sum()
        rows.append({
            "scheme": scheme, "policy": policy, "data_fields": df, "n_segments": n, "ber1": b1, "ber2": b2,
            "wire_bytes": int(g["wire_bytes"].iloc[0]), "max_ticks": int(g["max_ticks"].iloc[0]), "trials": t,
            "decoded": len(ok), "silent": k_sil, "timeouts": k_to,
            "decode_rate": len(ok) / t, "silent_rate": k_sil / t, "silent_lo": sl, "silent_hi": sh,
            "timeout_rate": k_to / t, "timeout_lo": tl, "timeout_hi": th,
            "relay_starved": int((g["first_emit_tick"] == 0).sum()),
            "hop1_mean": h1.mean() if len(h1) else math.nan,
            "hop1_ci": Z * h1.std(ddof=1) / math.sqrt(len(h1)) if len(h1) > 1 else math.nan,
            "hop2_mean": h2.mean() if len(h2) else math.nan,
            "hop2_ci": Z * h2.std(ddof=1) / math.sqrt(len(h2)) if len(h2) > 1 else math.nan,
            "relay_corrupted_rx_mean": g["relay_corrupted_rx"].mean(),
            "relay_polluted_inputs_mean": g["relay_polluted_inputs"].mean(),
            "relay_polluted_any": int((g["relay_polluted_inputs"] > 0).sum()),
            "hop2_polluted_mean": g["hop2_polluted_emitted"].mean(),
            "relay_dropped_mean": g["relay_dropped"].mean(),
            "sink_repaired_used_mean": ok["sink_repaired_used"].mean() if len(ok) else math.nan,
            "sink_wrong_used_total": int(g["sink_wrong_used"].sum()),
            # relay work per hop-1 packet received (check) / per relayed packet (re-tag, recoding)
            "relay_verify_crc_bytes_per_rx": g["relay_verify_crc_bytes"].sum() / g["hop1_packets"].sum(),
            "relay_retag_crc_bytes_per_tx": g["relay_retag_crc_bytes"].sum() / relayed if relayed else math.nan,
            "relay_check_mul_per_rx": g["relay_check_mul"].sum() / g["hop1_packets"].sum(),
            "relay_recode_mul_per_tx": g["relay_recode_mul"].sum() / relayed if relayed else math.nan,
            "relay_check_us_per_rx": 1e6 * g["relay_check_time_s"].sum() / g["hop1_packets"].sum(),
            "wall_s_mean": g["wall_time_s"].mean(),
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


def _line(ax, g, y, arm, lo=None, hi=None, err=None, hollow=None, x="ber1", dx=1.0):
    g = g.sort_values(x)
    g = g[np.isfinite(g[y].to_numpy(float))]
    if g.empty:
        return
    st = ARMS[arm]
    xs, ys = g[x].to_numpy(float) * dx, g[y].to_numpy(float)
    ax.plot(xs, ys, color=st["color"], ls=st["ls"], lw=1.7, zorder=2)
    if lo is not None:
        ax.errorbar(xs, ys, yerr=[np.maximum(0, ys - g[lo].to_numpy(float)), np.maximum(0, g[hi].to_numpy(float) - ys)], fmt="none",
                    ecolor=st["color"], elinewidth=0.9, capsize=2, zorder=2)
    elif err is not None:
        e = g[err].to_numpy(float)
        ax.errorbar(xs, ys, yerr=np.where(np.isfinite(e), e, 0), fmt="none", ecolor=st["color"], elinewidth=0.9,
                    capsize=2, zorder=2)
    hol = g[hollow].to_numpy(bool) if hollow else np.zeros(len(xs), bool)
    for xv, yv, h in zip(xs, ys, hol):
        ax.plot(xv, yv, marker=st["marker"], ms=5.2, color=st["color"], mew=1.3, mfc="white" if h else st["color"],
                ls="none", zorder=3)


# small horizontal offsets so lines that coincide (e.g. all at 0 %) stay distinguishable
_DX = {("crc", "verify"): 0.90, ("crc", "blind"): 0.95, ("keyless", "verify"): 1.0, ("keyless", "blind"): 1.05,
       ("keyed", "verify"): 1.10, ("keyed", "blind"): 1.15}


def _legend(fig, arms, ncol=3, y=-0.01):
    handles = [matplotlib.lines.Line2D([], [], color=ARMS[a]["color"], ls=ARMS[a]["ls"], marker=ARMS[a]["marker"],
                                       lw=1.7, ms=5.2, label=ARMS[a]["label"]) for a in arms]
    fig.legend(handles=handles, loc="lower center", ncol=ncol, frameon=False, fontsize=8.5, labelcolor=INK,
               bbox_to_anchor=(0.5, y))


def _settings(s, sym=True):
    hop = "same BER on both hops" if sym else f"hop-2 BER fixed at {s['ber2'].iloc[0]:g}"
    return (f"S -> relay (recodes, forwards from 3 usable packets) -> sink; g = 4, GF(2^8), 50 B data segments, "
            f"payload-only bit errors,\n{hop}; sink = ACR repair (HD 2); cap {int(s['max_ticks'].max())} ticks; "
            f"up to {int(s['trials'].max())} paired generations per point")


def _arms(s):
    return [a for a in ARMS if ((s["scheme"] == a[0]) & (s["policy"] == a[1])).any()]


def plot_silent_stall(s, out_dir, suffix="", sym=True):
    dfs = sorted(s["data_fields"].unique())
    arms = _arms(s)
    fig, axes = plt.subplots(2, len(dfs), figsize=(4.4 * len(dfs), 6.4), sharex=True, squeeze=False)
    for j, df in enumerate(dfs):
        sub = s[s["data_fields"] == df]
        for arm in arms:
            g = sub[(sub["scheme"] == arm[0]) & (sub["policy"] == arm[1])]
            _line(axes[0][j], g, "silent_rate", arm, lo="silent_lo", hi="silent_hi", dx=_DX[arm])
            _line(axes[1][j], g, "timeout_rate", arm, lo="timeout_lo", hi="timeout_hi", dx=_DX[arm])
        for i in (0, 1):
            _style(axes[i][j], percent=True)
            axes[i][j].set_ylim(-0.04, 1.04)
        axes[0][j].set_title(f"payload {df} B  (N = {int(sub['n_segments'].iloc[0])} segments)", color=INK, fontsize=10)
        axes[1][j].set_xlabel("bit error rate per hop (per payload bit)" if sym else "hop-1 bit error rate",
                              color=INK, fontsize=9)
    axes[0][0].set_ylabel("silent wrong decodes at the sink", color=INK, fontsize=9)
    axes[1][0].set_ylabel("stall: no decode within the cap", color=INK, fontsize=9)
    _legend(fig, arms)
    fig.suptitle("Two-hop recoding: a blind CRC relay turns hop-1 errors into silent wrong decodes;\n"
                 "keyless / keyed tags survive recoding and are caught end to end\n" + _settings(s, sym),
                 color=INK, fontsize=10)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    _save(fig, out_dir, "silent_stall_vs_ber" + suffix)


def plot_packets(s, out_dir, suffix="", sym=True):
    dfs = sorted(s["data_fields"].unique())
    arms = _arms(s)
    s = s.assign(partial=s["decode_rate"] < 1.0)
    cap = int(s["max_ticks"].max())
    fig, axes = plt.subplots(2, len(dfs), figsize=(4.4 * len(dfs), 6.4), sharex=True, squeeze=False)
    for j, df in enumerate(dfs):
        sub = s[s["data_fields"] == df]
        for arm in arms:
            g = sub[(sub["scheme"] == arm[0]) & (sub["policy"] == arm[1])]
            _line(axes[0][j], g, "hop1_mean", arm, err="hop1_ci", hollow="partial", dx=_DX[arm])
            _line(axes[1][j], g, "hop2_mean", arm, err="hop2_ci", hollow="partial", dx=_DX[arm])
        for i in (0, 1):
            _style(axes[i][j])
            axes[i][j].set_ylim(0, cap + 4)
            axes[i][j].axhline(cap, color=INK_MUTED, lw=0.8, ls="--", alpha=0.6)
        axes[0][j].set_title(f"payload {df} B  (N = {int(sub['n_segments'].iloc[0])} segments)", color=INK, fontsize=10)
        axes[1][j].set_xlabel("bit error rate per hop (per payload bit)" if sym else "hop-1 bit error rate",
                              color=INK, fontsize=9)
    axes[0][0].set_ylabel("hop-1 packets (source -> relay)\nuntil the sink decodes", color=INK, fontsize=9)
    axes[1][0].set_ylabel("hop-2 packets (relay -> sink)\nuntil the sink decodes", color=INK, fontsize=9)
    _legend(fig, arms)
    fig.suptitle("Packets per hop until the sink decodes (correctly decoded generations; hollow = not all decoded; "
                 f"dashed line = cap {cap})\n" + _settings(s, sym), color=INK, fontsize=10)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    _save(fig, out_dir, "packets_per_hop_vs_ber" + suffix)


def plot_relay_pollution(s, out_dir, suffix="", sym=True):
    dfs = sorted(s["data_fields"].unique())
    arms = _arms(s)
    fig, axes = plt.subplots(1, len(dfs), figsize=(4.4 * len(dfs), 3.5), sharex=True, squeeze=False)
    for j, df in enumerate(dfs):
        sub = s[s["data_fields"] == df]
        for arm in arms:
            g = sub[(sub["scheme"] == arm[0]) & (sub["policy"] == arm[1])].copy()
            g["frac_polluted"] = g["relay_polluted_any"] / g["trials"]
            _line(axes[0][j], g, "frac_polluted", arm, dx=_DX[arm])
        _style(axes[0][j], percent=True)
        axes[0][j].set_ylim(-0.04, 1.04)
        axes[0][j].set_title(f"payload {df} B  (N = {int(sub['n_segments'].iloc[0])} segments)", color=INK, fontsize=10)
        axes[0][j].set_xlabel("bit error rate per hop" if sym else "hop-1 bit error rate", color=INK, fontsize=9)
    axes[0][0].set_ylabel("generations in which a corrupted\nhop-1 packet entered a recoding", color=INK, fontsize=9)
    _legend(fig, arms, y=-0.04)
    fig.suptitle("Relay pollution: did the relay mix a corrupted hop-1 packet into its output?\n" + _settings(s, sym),
                 color=INK, fontsize=10)
    fig.tight_layout(rect=(0, 0.16, 1, 1))
    _save(fig, out_dir, "relay_pollution_vs_ber" + suffix)


def _save(fig, out_dir: Path, name: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(out_dir / f"{name}.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  {out_dir / (name + '.png')}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path("E:/projects/studienarbeit/logs/two_hop_recoding"))
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    out = a.out or a.root / "plots"
    raw = load(a.root)
    s = summarize(raw)
    out.mkdir(parents=True, exist_ok=True)
    s.sort_values(["ber2", "data_fields", "ber1", "scheme", "policy"]).to_csv(out / "two_hop_summary.csv", index=False)
    print(f"  {out / 'two_hop_summary.csv'}  ({len(raw)} trials, {len(s)} cells)")
    sym = s[s["ber1"] == s["ber2"]]
    if len(sym):
        plot_silent_stall(sym, out)
        plot_packets(sym, out)
        plot_relay_pollution(sym, out)
    for b2, asym in s[s["ber1"] != s["ber2"]].groupby("ber2"):
        tag = f"_ber2_{b2:g}"
        plot_silent_stall(asym, out, tag, sym=False)
        plot_packets(asym, out, tag, sym=False)


if __name__ == "__main__":
    main()
