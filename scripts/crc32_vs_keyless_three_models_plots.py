r"""Keyless vs CRC-32 (ACR) under three channel-error models x max HD 1..4 (ADR-0014, user 2026-10-17).

Input: <root>/*/raw_trials.csv from scripts/crc32_vs_keyless_three_models_runs.sh (isolated_recovery_sim schema
v5; configs arc_only_a = payload only, acr_only_tags = tag only, acr_only_data_tags = payload + tag; repair span
segment; arms keyless W 1..4 + crc_acr). Output (<root>/plots/, png + pdf):
  recovery_vs_ber_hd{h}     rows = error model, cols = payload size; keyless W4 (+ thin W1) vs CRC-ACR, Wilson CI
  recovery_vs_hd            rows = error model, cols = payload size; x = max HD, BER 1e-3 (solid) / 3e-3 (dashed)
  repair_time_ratio         CRC-ACR / keyless-W4 wall-clock (ratio of means) vs BER, one line per HD
  summary.csv               per cell rates + counts; silent_events.csv = every silent decode (seed, cell, arm, W)
  outcome_identity.csv      per (model, HD, W): targets where keyless W and CRC-ACR outcomes differ

CLI: $env:PYTHONPATH="."; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/crc32_vs_keyless_three_models_plots.py --root <dir>
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

KEYLESS, CRC = "#588157", "#4a3aa7"
MODELS = {"arc_only_a": "payload only", "acr_only_tags": "tag only", "acr_only_data_tags": "payload + tag"}
HD_LS = {1: ":", 2: "-.", 3: "--", 4: "-"}
Z = 1.96


def _wilson(k, n):
    if n <= 0:
        return math.nan, math.nan
    p, d = k / n, 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _style(ax):
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED, labelcolor=INK, labelsize=8)


def _save(fig, out, name):
    out.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(out / f"{name}.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out / name}.png")


def load(root: Path) -> pd.DataFrame:
    files = sorted(glob.glob(str(root / "*" / "raw_trials.csv")))
    assert files, f"no runs under {root}"
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    df = df[df.config.isin(MODELS)]
    df["arm_w"] = np.where(df.arm == "keyless", "keyless_W" + df.W.astype(str), df.arm)
    return df


def summary(df):
    g = df.groupby(["config", "data_fields", "num_data_segments", "max_combined_hd", "bit_error_rate", "arm_w"])
    s = g.agg(seeds=("seed", "nunique"), targets=("T", "sum"), corrupted=("n_arm_corrupted", "sum"),
              recovered=("recovered", "sum"), silent=("silent", "sum"), failed=("failed", "sum"),
              time_ms=("recovery_time_s", lambda x: 1e3 * x.mean())).reset_index()
    s["recovery_rate"] = s.recovered / s.targets
    s["silent_rate"] = s.silent / s.targets
    return s


def silent_events(df):
    return df[df.silent > 0][["config", "data_fields", "max_combined_hd", "bit_error_rate", "seed", "arm", "W",
                              "silent", "target_outcomes"]].sort_values(["config", "max_combined_hd", "arm", "W"])


def outcome_identity(df):
    key = ["config", "data_fields", "max_combined_hd", "bit_error_rate", "seed"]
    crc = df[df.arm == "crc_acr"].set_index(key).target_outcomes
    rows = []
    for (cfg, hd, w), kl in df[df.arm == "keyless"].groupby(["config", "max_combined_hd", "W"]):
        k = kl.set_index(key).target_outcomes
        c = crc.reindex(k.index)
        diff = sum(sum(a != b for a, b in zip(x, y)) for x, y in zip(k, c))
        rows.append(dict(config=cfg, max_hd=hd, W=w, targets=int(sum(len(x) for x in k)), differing_targets=int(diff)))
    return pd.DataFrame(rows)


def plot_recovery_vs_ber(s, out):
    dfs = sorted(s.data_fields.unique())
    for hd, sh in s.groupby("max_combined_hd"):
        fig, axes = plt.subplots(len(MODELS), len(dfs), figsize=(4.0 * len(dfs), 2.9 * len(MODELS)),
                                 sharex=True, sharey=True, squeeze=False)
        for i, (cfg, label) in enumerate(MODELS.items()):
            for j, d in enumerate(dfs):
                ax = axes[i][j]
                sd = sh[(sh.config == cfg) & (sh.data_fields == d)]
                for key, lab, col, mk, ls, lw in (("keyless_W1", "keyless W=1", _shade(KEYLESS, 0.5), "o", "-", 1.2),
                                                  ("keyless_W4", "keyless W=4", KEYLESS, "o", "-", 2.2),
                                                  ("crc_acr", "CRC-32 + ACR", CRC, "^", "--", 2.0)):
                    r = sd[sd.arm_w == key].sort_values("bit_error_rate")
                    if r.empty:
                        continue
                    if key != "keyless_W1":
                        ci = np.array([_wilson(k, n) for k, n in zip(r.recovered, r.targets)])
                        ax.fill_between(r.bit_error_rate, ci[:, 0], ci[:, 1], color=col, alpha=0.12, linewidth=0)
                    ax.plot(r.bit_error_rate, r.recovery_rate, ls, marker=mk, color=col, linewidth=lw,
                            markersize=5 if key == "keyless_W1" else 7, label=lab)
                ax.set_xscale("log")
                ax.set_ylim(-0.02, 1.02)
                if i == 0:
                    n = int(sd.num_data_segments.iloc[0]) if not sd.empty else 0
                    ax.set_title(f"payload {d} B ({n} x {d // max(n, 1)} B segments)", color=INK, fontsize=9.5)
                if j == 0:
                    ax.set_ylabel(f"{label}\nrecovered (fraction)", color=INK, fontsize=9)
                if i == len(MODELS) - 1:
                    ax.set_xlabel("bit error rate", color=INK, fontsize=9)
                _style(ax)
        axes[0][-1].legend(fontsize=7.5, frameon=False, labelcolor=INK, loc="lower left")
        fig.suptitle(f"Recovery by error model, max HD {hd} (repair span segment, budget 20000)", color=INK, fontsize=11)
        _save(fig, out, f"recovery_vs_ber_hd{hd}")


def plot_recovery_vs_hd(s, out, bers=(1e-3, 3e-3)):
    dfs = sorted(s.data_fields.unique())
    fig, axes = plt.subplots(len(MODELS), len(dfs), figsize=(4.0 * len(dfs), 2.9 * len(MODELS)),
                             sharex=True, sharey=True, squeeze=False)
    for i, (cfg, label) in enumerate(MODELS.items()):
        for j, d in enumerate(dfs):
            ax = axes[i][j]
            for ber, ls in zip(bers, ("-", "--")):
                for key, col, mk, lab in (("keyless_W4", KEYLESS, "o", "keyless W=4"), ("crc_acr", CRC, "^", "CRC-32 + ACR")):
                    r = s[(s.config == cfg) & (s.data_fields == d) & (s.bit_error_rate == ber) & (s.arm_w == key)] \
                        .sort_values("max_combined_hd")
                    if r.empty:
                        continue
                    ax.plot(r.max_combined_hd, r.recovery_rate, ls, marker=mk, color=col, linewidth=2,
                            markersize=7 if key == "crc_acr" else 6, markerfacecolor="white" if key == "crc_acr" else col,
                            label=f"{lab}, BER {ber:.0e}")
            ax.set_ylim(-0.02, 1.02)
            ax.set_xticks([1, 2, 3, 4])
            if i == 0:
                ax.set_title(f"payload {d} B", color=INK, fontsize=9.5)
            if j == 0:
                ax.set_ylabel(f"{label}\nrecovered (fraction)", color=INK, fontsize=9)
            if i == len(MODELS) - 1:
                ax.set_xlabel("max Hamming distance searched", color=INK, fontsize=9)
            _style(ax)
    axes[0][-1].legend(fontsize=7, frameon=False, labelcolor=INK, loc="lower right")
    fig.suptitle("Recovery vs search depth, by error model", color=INK, fontsize=11)
    _save(fig, out, "recovery_vs_hd")


def plot_time_ratio(df, out):
    dfs = sorted(df.data_fields.unique())
    fig, axes = plt.subplots(len(MODELS), len(dfs), figsize=(4.0 * len(dfs), 2.6 * len(MODELS)),
                             sharex=True, squeeze=False)
    for i, (cfg, label) in enumerate(MODELS.items()):
        for j, d in enumerate(dfs):
            ax = axes[i][j]
            sd = df[(df.config == cfg) & (df.data_fields == d)]
            for hd in sorted(sd.max_combined_hd.unique()):
                h = sd[sd.max_combined_hd == hd]
                k = h[h.arm_w == "keyless_W4"].groupby("bit_error_rate").recovery_time_s.mean()
                c = h[h.arm_w == "crc_acr"].groupby("bit_error_rate").recovery_time_s.mean()
                r = (c / k).dropna()
                ax.plot(range(len(r)), r.values, HD_LS.get(hd, "-"), marker="^", color=_shade(CRC, 0.4 + 0.15 * hd),
                        linewidth=1.8, markersize=5, label=f"HD {hd}")
                ax.set_xticks(range(len(r)), [f"{b:.0e}" for b in r.index], rotation=45, fontsize=7)
            ax.axhline(1.0, color=INK_MUTED, linewidth=1, linestyle=":")
            ax.set_ylim(bottom=0)
            if i == 0:
                ax.set_title(f"payload {d} B", color=INK, fontsize=9.5)
            if j == 0:
                ax.set_ylabel(f"{label}\nCRC-ACR / keyless W4", color=INK, fontsize=9)
            if i == len(MODELS) - 1:
                ax.set_xlabel("bit error rate", color=INK, fontsize=9)
            _style(ax)
    axes[0][-1].legend(fontsize=7, frameon=False, labelcolor=INK, loc="upper right")
    fig.suptitle("Repair wall-clock ratio (ratio of means; CRC = zlib in C, keyless = Python; contended machine)",
                 color=INK, fontsize=10)
    _save(fig, out, "repair_time_ratio")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="E:/projects/studienarbeit/logs/crc32_vs_keyless/recovery_three_models")
    a = ap.parse_args(argv)
    root = Path(a.root)
    out = root / "plots"
    out.mkdir(parents=True, exist_ok=True)
    df = load(root)
    s = summary(df)
    s.to_csv(out / "summary.csv", index=False)
    ev = silent_events(df)
    ev.to_csv(out / "silent_events.csv", index=False)
    ident = outcome_identity(df)
    ident.to_csv(out / "outcome_identity.csv", index=False)
    print(f"  silent events: {len(ev)} rows, {int(ev.silent.sum()) if len(ev) else 0} targets")
    print(ident.to_string(index=False))
    plot_recovery_vs_ber(s, out)
    plot_recovery_vs_hd(s, out)
    plot_time_ratio(df, out)


if __name__ == "__main__":
    main()
