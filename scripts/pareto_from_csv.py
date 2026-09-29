"""Pool Pareto-sweep trials, compute bit-efficiency / compute / recovery per cell, mark the
Pareto front, and plot -- one function per plot (edit one, call one).

Inputs (pooled at TRIAL level, never averaged summaries):
  * scripts/pareto_sweep.py runs      -> <run_dir>/raw_trials.csv  (schema v1)
  * ticket-03 N-sweep (legacy, df=48) -> <run_dir>/raw_results.csv (adapted: wire size
    measured from a real tagged source, pair_budget=100000, source="ticket03")
Cells are keyed by the full config (arm, gen, m, df, N, strategy, HD, pair_budget, BER,
source), so runs with different knobs never silently pool.

Per-cell metrics:
  efficiency        sum(info bits delivered) / sum(wire bits sent), over ALL trials.
                    Info = gen*df*m for a correct decode, 0 otherwise; wire = packets sent
                    x full packet (coeff + data + every segment's salt + tags). Failures
                    therefore cost bits without delivering any -- no separate filter needed.
  total_ops         mean(scheme_ops + decode_ops) per generation (deterministic field muls)
  pair_recovery     sum(pairs_recovered) / sum(pairs_recovered + pairs_failed)
  unpaired_recovery same for the unpaired (odd-one-out) path
  recovery_share    sum(recovery_ops) / sum(scheme_ops)  -- how much of the cost is repair
  silent_rate       HARD FILTER: a cell with any silent decode is never on the front
  wall_limit_rate   trials cut by the per-trial compute deadline (flagged, drawn hollow)
Pareto front, per (source, arm, strategy, BER): feasible cells not dominated in
(max efficiency, min total_ops).

CLI (PowerShell; memory how_to_run_sims):
  $env:LOG_FOLDER="./logs"; $env:PYTHONPATH="."
  & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/pareto_from_csv.py `
      --runs "E:/projects/studienarbeit/logs/pareto_sweep/*" --out E:/projects/studienarbeit/logs/pareto_plots/sweep
  ... --runs "E:/projects/studienarbeit/logs/scheme_comparison_segmented_n_sweep/20260916_215934_trials20_gen10_m8" `
      --out E:/projects/studienarbeit/logs/pareto_plots/ticket03
"""
import argparse
import glob
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DEFAULT_RUNS = str(_ROOT / "logs" / "pareto_sweep" / "*")
DEFAULT_OUT = str(_ROOT / "logs" / "pareto_plots")
DEFAULT_MIN_TRIALS = 10

# Categorical slots in fixed order (dataviz reference palette, validated light mode);
# a df value keeps its colour no matter which subset is plotted.
DF_COLORS = {48: "#2a78d6", 96: "#eb6834", 192: "#1baf7a"}
EXTRA_COLORS = ["#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
ARM_MARKERS = {"keyless": "o", "keyed": "s"}
INK, INK_MUTED, GRID = "#1f1f1e", "#6b6a64", "#e4e3dd"

CELL_KEYS = ["source", "arm", "gen_size", "field_m", "data_fields", "n_segments", "strategy",
             "error_scope", "repair_span", "hamming_distance", "pair_budget", "bit_error_rate"]


# --------------------------------------------------------------------------- #
# loading
def _load_sweep(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["source"] = "pareto_sweep"
    df["run"] = csv_path.parent.name
    return df


def _load_legacy(csv_path: Path, gen_size=10, field_m=8, data_fields=48) -> pd.DataFrame:
    """Ticket-03 raw_results.csv -> sweep schema. Segmented arms only (keyless = segmented_*,
    keyed = mac_*); wire size measured from a real tagged source, not re-derived by hand."""
    from binary_ext_fields.custom_field import create_field
    from scripts.pareto_sweep import _layout

    raw = pd.read_csv(csv_path)
    raw = raw[raw["scheme"].str.startswith(("segmented_", "mac_"))].copy()
    raw["arm"] = np.where(raw["scheme"].str.startswith("mac_"), "keyed", "keyless")
    field = create_field(field_m)
    layouts = {(a, n): _layout(a, int(n), data_fields, gen_size, field)
               for a, n in raw[["arm", "n"]].drop_duplicates().itertuples(index=False)}
    raw["n_segments"] = raw["n"].astype(int)
    raw["wire_symbols"] = [layouts[(a, n)][0] for a, n in zip(raw["arm"], raw["n"])]
    raw["seg_len_max"] = [layouts[(a, n)][2] for a, n in zip(raw["arm"], raw["n"])]
    raw["gen_size"], raw["field_m"], raw["data_fields"] = gen_size, field_m, data_fields
    raw["hamming_distance"], raw["pair_budget"] = 2, 100_000
    raw["info_bits_delivered"] = np.where(raw["correct"].astype(bool), gen_size * data_fields * field_m, 0)
    raw["wire_bits_sent"] = raw["packets_to_decode"] * raw["wire_symbols"] * field_m
    raw["source"] = "ticket03"
    raw["run"] = csv_path.parent.name
    return raw


def load_trials(runs) -> pd.DataFrame:
    frames = []
    for pattern in runs:
        for d in sorted(glob.glob(pattern)):
            d = Path(d)
            if (d / "raw_trials.csv").exists():
                frames.append(_load_sweep(d / "raw_trials.csv"))
            elif (d / "raw_results.csv").exists():
                frames.append(_load_legacy(d / "raw_results.csv"))
    if not frames:
        raise SystemExit(f"no raw_trials.csv / raw_results.csv under {runs}")
    t = pd.concat(frames, ignore_index=True)
    t["pair_budget"] = t["pair_budget"].fillna(-1).astype(int)  # -1 = None (unbounded)
    # schema v1 rows (and ticket-03) predate the 2026-09-29 knobs: whole-packet errors, payload span
    for col, default in (("error_scope", "whole_packet"), ("repair_span", "payload")):
        t[col] = t[col].fillna(default) if col in t else default
    for col in ("correct", "silent_decode", "decoded"):
        t[col] = t[col].astype(str).str.lower().isin(("true", "1"))
    return t


# --------------------------------------------------------------------------- #
# summary + front
def summarize(trials: pd.DataFrame, min_trials=DEFAULT_MIN_TRIALS) -> pd.DataFrame:
    rows = []
    for key, g in trials.groupby(CELL_KEYS, dropna=False):
        pr, pf = g["pairs_recovered"].sum(), g["pairs_failed"].sum()
        ur, uf = g["unpaired_recovered"].sum(), g["unpaired_failed"].sum()
        dec = g[g["correct"]]
        rows.append({
            **dict(zip(CELL_KEYS, key)),
            "seg_len_max": int(g["seg_len_max"].iloc[0]),
            "wire_symbols": int(g["wire_symbols"].iloc[0]),
            "n_trials": len(g),
            "correct_rate": g["correct"].mean(),
            "silent_rate": g["silent_decode"].mean(),
            "timeout_rate": (g["status"] == "timeout").mean(),
            "wall_limit_rate": (g["status"] == "wall_limit").mean(),
            "efficiency": g["info_bits_delivered"].sum() / g["wire_bits_sent"].sum(),
            "efficiency_max": g["data_fields"].iloc[0] / g["wire_symbols"].iloc[0],
            "mean_overhead_decoded": dec["overhead"].mean() if len(dec) else np.nan,
            "total_ops": (g["scheme_ops"] + g["decode_ops"]).mean(),
            "scheme_ops": g["scheme_ops"].mean(),
            "recovery_ops": g["recovery_ops"].mean(),
            "detection_ops": g["detection_ops"].mean(),
            "recovery_share": g["recovery_ops"].sum() / max(g["scheme_ops"].sum(), 1),
            "pair_recovery": pr / (pr + pf) if pr + pf else np.nan,
            "pairs_seen": pr + pf,
            "unpaired_recovery": ur / (ur + uf) if ur + uf else np.nan,
            "wall_mean_s": g["wall_time_s"].mean(),
            "runs": ",".join(sorted(g["run"].unique())),
        })
    s = pd.DataFrame(rows)
    s["sparse"] = s["n_trials"] < min_trials
    s["feasible"] = s["silent_rate"] == 0
    s["pareto"] = False
    for _, g in s[s["feasible"]].groupby(["source", "arm", "strategy", "error_scope", "repair_span",
                                          "bit_error_rate"]):
        for i, r in g.iterrows():
            dominated = ((g["efficiency"] >= r["efficiency"]) & (g["total_ops"] <= r["total_ops"])
                         & ((g["efficiency"] > r["efficiency"]) | (g["total_ops"] < r["total_ops"]))).any()
            s.loc[i, "pareto"] = not dominated
    return s.sort_values(["source", "arm", "bit_error_rate", "data_fields", "n_segments"]).reset_index(drop=True)


def load(runs=(DEFAULT_RUNS,), min_trials=DEFAULT_MIN_TRIALS) -> pd.DataFrame:
    """REPL convenience: s = load(); plot_front(s, out_dir)."""
    return summarize(load_trials(runs), min_trials)


# --------------------------------------------------------------------------- #
# plotting helpers
def _df_color(df_value, all_dfs):
    if df_value in DF_COLORS:
        return DF_COLORS[df_value]
    extras = [d for d in sorted(all_dfs) if d not in DF_COLORS]
    return EXTRA_COLORS[extras.index(df_value) % len(EXTRA_COLORS)]


def _style_ax(ax):
    ax.grid(True, which="major", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED, labelcolor=INK)


def _hollow(r) -> bool:
    return bool(r["sparse"]) or r["wall_limit_rate"] > 0


def _panels(summary):
    bers = sorted(summary["bit_error_rate"].unique())
    fig, axes = plt.subplots(1, len(bers), figsize=(5.2 * len(bers), 4.6), squeeze=False)
    return fig, axes[0], bers


def _legend(fig, summary):
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], color=_df_color(d, summary["data_fields"].unique()), marker="o",
                      linewidth=2, markersize=8, label=f"payload {d} B")
               for d in sorted(summary["data_fields"].unique())]
    if summary["arm"].nunique() > 1:
        handles += [Line2D([], [], color=INK_MUTED, marker=ARM_MARKERS[a], linestyle="none",
                           markersize=8, label=a) for a in sorted(summary["arm"].unique())]
    handles.append(Line2D([], [], color=INK_MUTED, marker="o", markerfacecolor="white",
                          linestyle="none", markersize=8, label="sparse / deadline-cut"))
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), frameon=False,
               fontsize=9, labelcolor=INK, bbox_to_anchor=(0.5, -0.02))


def _save(fig, out_dir, name):
    out_dir = Path(out_dir or DEFAULT_OUT)
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    for ext in ("png", "pdf"):
        fig.savefig(out_dir / f"{name}.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out_dir / f"{name}.png"


def _marks(ax, r, x, y, color):
    ax.plot(x, y, marker=ARM_MARKERS.get(r["arm"], "o"), markersize=8, color=color, zorder=3,
            markerfacecolor="white" if _hollow(r) else color, markeredgecolor=color,
            markeredgewidth=2, linestyle="none")


# --------------------------------------------------------------------------- #
# plots -- one function each, signature (summary, out_dir=None)
def plot_front(summary, out_dir=None):
    """Efficiency vs compute per BER; Pareto points joined by a step line, each point
    direct-labelled with its N. Up-and-left is better."""
    fig, axes, bers = _panels(summary)
    all_dfs = summary["data_fields"].unique()
    for ax, ber in zip(axes, bers):
        s = summary[summary["bit_error_rate"] == ber]
        for (_, arm, _), g in s.groupby(["source", "arm", "strategy"]):
            front = g[g["pareto"]].sort_values("total_ops")
            if len(front) > 1:
                ax.step(front["total_ops"], front["efficiency"], where="post", color=INK,
                        linewidth=1.5, alpha=0.6, zorder=2,
                        linestyle="-" if arm == "keyless" else "--")
        for _, r in s.iterrows():
            color = _df_color(r["data_fields"], all_dfs)
            _marks(ax, r, r["total_ops"], r["efficiency"], color)
            label = f"N={int(r['n_segments'])}" + ("*" if r["pareto"] else "")
            if not r["feasible"]:
                label += " (silent!)"
            ax.annotate(label, (r["total_ops"], r["efficiency"]), textcoords="offset points",
                        xytext=(6, 4), fontsize=8, color=INK if r["pareto"] else INK_MUTED)
        ax.set_xscale("log")
        ax.set_title(f"BER = {ber:.0e}", color=INK, fontsize=11)
        ax.set_xlabel("field ops per generation (scheme + decode, log)", color=INK)
        _style_ax(ax)
    axes[0].set_ylabel("bit-efficiency  (info bits / wire bits)", color=INK)
    fig.suptitle("Keyless segmented scheme: efficiency vs compute  (* = Pareto point)",
                 color=INK, fontsize=12)
    _legend(fig, summary)
    return _save(fig, out_dir, "pareto_front")


def _vs_seglen(summary, col, ylabel, title, name, out_dir, logy=False, ylim=None):
    fig, axes, bers = _panels(summary)
    all_dfs = summary["data_fields"].unique()
    for ax, ber in zip(axes, bers):
        s = summary[summary["bit_error_rate"] == ber]
        for (_, arm, _, d), g in s.groupby(["source", "arm", "strategy", "data_fields"]):
            g = g.sort_values("seg_len_max")
            g = g[np.isfinite(g[col])]
            if g.empty:
                continue
            color = _df_color(d, all_dfs)
            ax.plot(g["seg_len_max"], g[col], color=color, linewidth=2, alpha=0.45, zorder=1,
                    linestyle="-" if arm == "keyless" else "--")
            for _, r in g.iterrows():
                _marks(ax, r, r["seg_len_max"], r[col], color)
                ax.annotate(f"N={int(r['n_segments'])}", (r["seg_len_max"], r[col]),
                            textcoords="offset points", xytext=(0, 8), ha="center",
                            fontsize=7, color=INK_MUTED)
        if logy:
            ax.set_yscale("log")
        if ylim:
            ax.set_ylim(*ylim)
        ax.set_xscale("log", base=2)
        ticks = sorted(summary["seg_len_max"].unique())
        ax.set_xticks(ticks, [str(t) for t in ticks])
        ax.minorticks_off()
        ax.set_title(f"BER = {ber:.0e}", color=INK, fontsize=11)
        ax.set_xlabel("data-segment length L (bytes)", color=INK)
        _style_ax(ax)
    axes[0].set_ylabel(ylabel, color=INK)
    fig.suptitle(title, color=INK, fontsize=12)
    _legend(fig, summary)
    return _save(fig, out_dir, name)


def plot_efficiency_vs_seglen(summary, out_dir=None):
    return _vs_seglen(summary, "efficiency", "bit-efficiency (info / wire bits)",
                      "Bit-efficiency vs segment length", "efficiency_vs_seglen", out_dir)


def plot_ops_vs_seglen(summary, out_dir=None):
    return _vs_seglen(summary, "total_ops", "field ops per generation (log)",
                      "Compute vs segment length", "ops_vs_seglen", out_dir, logy=True)


def plot_pair_recovery_vs_seglen(summary, out_dir=None):
    return _vs_seglen(summary, "pair_recovery", "pair recovery rate",
                      "Combined-recovery pair success vs segment length",
                      "pair_recovery_vs_seglen", out_dir, ylim=(0, 1.05))


def plot_recovery_share_vs_seglen(summary, out_dir=None):
    return _vs_seglen(summary, "recovery_share", "recovery ops / scheme ops",
                      "Share of compute spent on repair", "recovery_share_vs_seglen", out_dir,
                      ylim=(0, 1.05))


PLOTS = {"front": plot_front, "efficiency": plot_efficiency_vs_seglen, "ops": plot_ops_vs_seglen,
         "pair_recovery": plot_pair_recovery_vs_seglen, "recovery_share": plot_recovery_share_vs_seglen}


def plot_all(summary, out_dir=None):
    return [fn(summary, out_dir) for fn in PLOTS.values()]


def main(argv=None):
    p = argparse.ArgumentParser(description="Pareto analysis + plots from sweep CSVs.")
    p.add_argument("--runs", nargs="+", default=[DEFAULT_RUNS], help="run dirs / globs")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--min-trials", type=int, default=DEFAULT_MIN_TRIALS)
    p.add_argument("--arm", choices=["keyless", "keyed", "both"], default="both")
    p.add_argument("--strategy", default="coefficient_first", help='or "all"')
    p.add_argument("--plots", default=",".join(PLOTS))
    a = p.parse_args(argv)

    s = load(a.runs, a.min_trials)
    if a.arm != "both":
        s = s[s["arm"] == a.arm]
    if a.strategy != "all":
        s = s[s["strategy"] == a.strategy]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    s.to_csv(out / "pareto_summary.csv", index=False)
    cols = ["arm", "bit_error_rate", "data_fields", "n_segments", "seg_len_max", "n_trials",
            "correct_rate", "silent_rate", "efficiency", "total_ops", "pair_recovery", "pareto"]
    with pd.option_context("display.width", 200, "display.max_rows", 500,
                           "display.float_format", "{:.4g}".format):
        print(s[cols].to_string(index=False))
    for name in a.plots.split(","):
        print("wrote", PLOTS[name](s, out))


if __name__ == "__main__":
    main()
