r"""Pool isolated-recovery W-sweep CSVs (ADR-0013 ticket 14) and (re)plot -- one function per plot.

Reads ``raw_trials.csv`` (frozen schema, see simulation/isolated_recovery_sim.py header)
from one or many run dirs, pools at trial (=seed) level, recomputes per-cell metrics
on the union and draws the figures. No sim re-run needed to redraw.

Manual use:
    from scripts.isolated_recovery_plots_from_csv import load, plot_silent, plot_all
    s = load()          # pools logs/isolated_recovery/* -> summary DataFrame
    plot_silent(s)      # writes logs/isolated_recovery_plots/silent_vs_ber_<span>.{png,pdf}
    plot_all(s)

CLI (PowerShell, env per memory how_to_run_sims):
    $env:LOG_FOLDER="./logs"; $env:PYTHONPATH="."; .\.venv\Scripts\python.exe scripts\isolated_recovery_plots_from_csv.py
    ... --runs "logs/isolated_recovery/*" --plots silent,isolation --min-trials 30

Cells (config, repair_span, arm, W, BER), pooled over seeds:
  recovery_rate       sum(recovered) / sum(T)     Wilson 95% CI
  silent_decode_rate  sum(silent)    / sum(T)     Wilson 95% CI  (MEASURED, may be > 0)
  recovery_ops        mean GF ops per recovery call (per seed pool), log y
Figures: per repair_span one file per metric, one panel per config, line per (arm, W);
plus the coeff-repair-isolation figure (coefficient_first vs ARC-only (b), whole-packet
BER, one column per arm).
"""
import argparse
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

# Arm colours kept in sync with scripts/recovery_plots_from_csv.py ARMS.
ARMS = {
    "keyless": {"color": "#588157", "label": "Keyless (orthogonal)"},
    "keyed":   {"color": "#3d405b", "label": "Keyed (MAC)"},
}
W_STYLE = {1: (":", "v"), 2: ("--", "s"), 3: ("-", "o")}  # (linestyle, marker) per W
CONFIG_LABEL = {
    "coefficient_first": "coefficient_first\n(whole-packet BER)",
    "arc_only_a": "ARC-only (a)\n(data-only BER)",
    "arc_only_b": "ARC-only (b)\n(whole-packet BER, symmetric drop)",
}
CONFIG_LABEL.update({
    "coefficient_first_info": "coefficient_first\n(payload-only BER, no salt/tag hits)",
    "arc_only_b_info": "ARC-only (b)\n(payload-only BER, symmetric drop)",
})
# Panel order; only configs present in the data are drawn.
CONFIGS = ("coefficient_first", "arc_only_a", "arc_only_b", "coefficient_first_info", "arc_only_b_info")
# Coeff-repair isolation pairs: (coefficient_first-config, ARC-only-(b)-config, error-model label, file suffix).
ISOLATION_PAIRS = (("coefficient_first", "arc_only_b", "whole-packet BER", ""),
                   ("coefficient_first_info", "arc_only_b_info", "payload-only BER", "_info"))
ISOLATION_COLOURS = ("#bc4749", "#457b9d")  # coefficient_first-role, ARC-only-(b)-role
# Columns that must agree for runs to be pooled (else the run is skipped).
COMPAT_COLS = ("schema_version", "gen_size", "T", "data_fields", "num_data_segments",
               "field_bits", "max_combined_hd", "candidates_budget")
DEFAULT_RUNS = "logs/isolated_recovery/*"
DEFAULT_OUT = "logs/isolated_recovery_plots"
DEFAULT_MIN_TRIALS = 30


# --------------------------------------------------------------------------- #
# stats
# --------------------------------------------------------------------------- #
def _wilson_halfwidth(successes, total, z=1.96):
    if total <= 0:
        return float("nan")
    p = successes / total
    denom = 1 + z * z / total
    return (z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))) / denom


def _z_halfwidth(std, n, z=1.96):
    if n < 2 or not np.isfinite(std):
        return float("nan")
    return z * std / math.sqrt(n)


# --------------------------------------------------------------------------- #
# load + pool + aggregate
# --------------------------------------------------------------------------- #
def discover(patterns):
    import glob
    paths = []
    for pat in patterns:
        full = pat if Path(pat).is_absolute() else str(_ROOT / pat)  # absolute or repo-relative
        for d in map(Path, sorted(glob.glob(full))):
            csv = d / "raw_trials.csv" if d.is_dir() else d
            if csv.name == "raw_trials.csv" and csv.exists():
                paths.append(csv)
    return paths


def load_pooled(paths):
    """Concat runs whose setup (COMPAT_COLS) matches the first run; others skipped."""
    frames, ref = [], None
    for p in paths:
        df = pd.read_csv(p)
        df["run_id"] = p.parent.name
        setup = df[list(COMPAT_COLS)].drop_duplicates()
        if len(setup) != 1:
            print(f"  ! {p.parent.name}: mixed setup inside one run; skipping")
            continue
        key = tuple(setup.iloc[0])
        if ref is None:
            ref = key
        if key != ref:
            print(f"  ! {p.parent.name}: setup {dict(zip(COMPAT_COLS, key))} != {dict(zip(COMPAT_COLS, ref))}; skipping")
            continue
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def aggregate(df, min_trials=DEFAULT_MIN_TRIALS):
    rows = []
    keys = ["config", "repair_span", "arm", "W", "bit_error_rate"]
    for (cfg, span, arm, W, ber), g in df.groupby(keys):
        n_targets = int(g["T"].sum())
        rec, sil = int(g["recovered"].sum()), int(g["silent"].sum())
        ops = g["recovery_ops"].astype(float)
        rows.append({
            "config": cfg, "repair_span": span, "arm": arm, "W": int(W), "bit_error_rate": float(ber),
            "n_trials": len(g), "n_runs": g["run_id"].nunique(), "n_targets": n_targets,
            "sparse": len(g) < min_trials,
            "recovered": rec, "silent": sil, "failed": int(g["failed"].sum()),
            "recovery_rate": rec / n_targets, "recovery_ci": _wilson_halfwidth(rec, n_targets),
            "silent_decode_rate": sil / n_targets, "silent_ci": _wilson_halfwidth(sil, n_targets),
            "mean_recovery_ops": float(ops.mean()), "ops_ci": _z_halfwidth(ops.std(ddof=1), len(g)),
            "h2h_keyless_only": int(g["h2h_keyless_only"].sum()), "h2h_keyed_only": int(g["h2h_keyed_only"].sum()),
            "h2h_both": int(g["h2h_both"].sum()), "h2h_neither": int(g["h2h_neither"].sum()),
        })
    out = pd.DataFrame(rows).sort_values(keys).reset_index(drop=True)
    first = df.iloc[0]
    out.attrs.update({c: first[c] for c in COMPAT_COLS}, min_trials=min_trials)
    return out


def load(runs=DEFAULT_RUNS, min_trials=DEFAULT_MIN_TRIALS):
    patterns = [runs] if isinstance(runs, str) else list(runs)
    paths = discover(patterns)
    if not paths:
        raise FileNotFoundError(f"no raw_trials.csv found for {patterns}")
    df = load_pooled(paths)
    if df.empty:
        raise ValueError("no compatible trials after pooling")
    return aggregate(df, min_trials)


# --------------------------------------------------------------------------- #
# plotting -- shared mechanics + one function per plot
# --------------------------------------------------------------------------- #
def _out(out_dir):
    d = Path(out_dir) if out_dir else _ROOT / DEFAULT_OUT
    d.mkdir(parents=True, exist_ok=True)
    return d


def _subtitle(summary, extra=""):
    a = summary.attrs
    return (f"G=gen_size={a.get('gen_size')}, T={a.get('T')}, {a.get('num_data_segments')} data segs x "
            f"{a.get('data_fields')} B, GF(2^{a.get('field_bits')}), max_hd={a.get('max_combined_hd')}, "
            f"bit-flip only, injected trust{extra}  (hollow = <{a.get('min_trials')} seeds)")


def _line(ax, s, valcol, errcol, color, W, label):
    s = s.sort_values("bit_error_rate")
    s = s[np.isfinite(s[valcol])]
    if s.empty:
        return
    ls, mk = W_STYLE.get(W, ("-", "o"))
    xs, ys = s["bit_error_rate"].to_numpy(), s[valcol].to_numpy()
    ax.plot(xs, ys, ls, color=color, linewidth=1.8, alpha=0.8, zorder=1)
    if errcol:
        err = s[errcol].to_numpy()
        m = np.isfinite(err)
        if m.any():
            lower = np.minimum(err[m], 0.9 * ys[m])  # metrics are >= 0; keeps log-y bars finite
            ax.errorbar(xs[m], ys[m], yerr=[lower, err[m]], fmt="none", ecolor=color, elinewidth=1,
                        capsize=2, alpha=0.7)
    for x, y, sparse in zip(xs, ys, s["sparse"].to_numpy()):
        ax.plot(x, y, marker=mk, markersize=5.5, color=color, markeredgecolor=color,
                markerfacecolor="white" if sparse else color, zorder=3)
    ax.plot([], [], ls, marker=mk, color=color, label=label)


def _dress(ax, ylabel=None, log_y=False, ylim=None):
    ax.set_xscale("log")
    if log_y:
        ax.set_yscale("log")
    if ylim:
        ax.set_ylim(*ylim)
    ax.set_xlabel("Bit error rate", fontsize=10, fontweight="bold")
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=10, fontweight="bold")
    ax.grid(True, linestyle="--", alpha=0.3)


def _save(fig, out_dir, name):
    d = _out(out_dir)
    for ext in ("png", "pdf"):
        fig.savefig(d / f"{name}.{ext}", dpi=300, bbox_inches="tight")
    plt.close(fig)
    return d


def _per_config_figure(summary, valcol, errcol, ylabel, title, key, out_dir, log_y=False, ylim=None):
    """One file per repair_span: a panel per config, a line per (arm, W)."""
    d = None
    for span in sorted(summary["repair_span"].unique()):
        sub = summary[summary["repair_span"] == span]
        present = [c for c in CONFIGS if c in set(sub["config"])]
        fig, axes = plt.subplots(1, len(present), figsize=(5 * len(present), 4.8), sharey=True, squeeze=False)
        axes = axes[0]
        for ax, cfg in zip(axes, present):
            c = sub[sub["config"] == cfg]
            for arm, meta in ARMS.items():
                for W in sorted(c["W"].unique()):
                    _line(ax, c[(c["arm"] == arm) & (c["W"] == W)], valcol, errcol,
                          meta["color"], W, f"{meta['label']}, W={W}")
            ax.set_title(CONFIG_LABEL[cfg], fontsize=10)
            _dress(ax, ylabel if ax is axes[0] else None, log_y, ylim)
        axes[-1].legend(fontsize=8, loc="best")
        fig.suptitle(f"{title}  [repair_span={span}]", fontsize=13, fontweight="bold", y=1.03)
        fig.text(0.5, 0.97, _subtitle(summary), ha="center", fontsize=8, alpha=0.7)
        d = _save(fig, out_dir, f"{key}_vs_ber_{span}")
    return d


# ---- one function per plot ------------------------------------------------- #
def plot_recovery(summary, out_dir=None):
    """Recovery rate (accepted AND correct) over the T targets vs BER."""
    return _per_config_figure(summary, "recovery_rate", "recovery_ci", "Recovery rate (per target)",
                              "Recovery rate vs BER", "recovery", out_dir, ylim=(-0.02, 1.02))


def plot_silent(summary, out_dir=None):
    """Silent-decode (wrong-accept) rate vs BER -- the axis W controls. Measured, may be > 0."""
    return _per_config_figure(summary, "silent_decode_rate", "silent_ci",
                              "Silent-decode rate (wrong-accept, per target)",
                              "Silent-decode rate vs BER (the W dial)", "silent", out_dir)


def plot_ops(summary, out_dir=None):
    """Mean recovery field-ops (total GF mul+add per recovery call) vs BER, log y."""
    return _per_config_figure(summary, "mean_recovery_ops", "ops_ci", "Mean GF ops per recovery call",
                              "Recovery field-ops vs BER", "ops", out_dir, log_y=True)


def plot_isolation(summary, out_dir=None):
    """Coeff-repair-stage isolation: coefficient_first vs ARC-only (b) under the same error
    model (one figure set per pair present: whole-packet, and payload-only if run).
    Columns = arm; rows = recovery rate, silent-decode rate, ops. The gap between the two
    configs within an arm is what the coeff-repair stage buys (and costs)."""
    d = None
    for cf_cfg, arc_cfg, model_label, suffix in ISOLATION_PAIRS:
        if {cf_cfg, arc_cfg} <= set(summary["config"]):
            d = _plot_isolation_pair(summary, cf_cfg, arc_cfg, model_label, suffix, out_dir)
    return d


def _plot_isolation_pair(summary, cf_cfg, arc_cfg, model_label, suffix, out_dir):
    colours = dict(zip((cf_cfg, arc_cfg), ISOLATION_COLOURS))
    d = None
    for span in sorted(summary["repair_span"].unique()):
        sub = summary[(summary["repair_span"] == span) & summary["config"].isin(colours)]
        fig, axes = plt.subplots(3, 2, figsize=(12, 11), sharex=True, sharey="row")
        rows = (("recovery_rate", "recovery_ci", "Recovery rate", False, (-0.02, 1.02)),
                ("silent_decode_rate", "silent_ci", "Silent-decode rate", False, None),
                ("mean_recovery_ops", "ops_ci", "Mean GF ops / recovery", True, None))
        for r, (valcol, errcol, ylabel, log_y, ylim) in enumerate(rows):
            for col, arm in enumerate(ARMS):
                ax = axes[r][col]
                a = sub[sub["arm"] == arm]
                for cfg, colour in colours.items():
                    for W in sorted(a["W"].unique()):
                        _line(ax, a[(a["config"] == cfg) & (a["W"] == W)], valcol, errcol, colour, W,
                              f"{cfg}, W={W}")
                _dress(ax, ylabel if col == 0 else None, log_y, ylim)
                if r == 0:
                    ax.set_title(ARMS[arm]["label"], fontsize=11, fontweight="bold")
                if r < 2:
                    ax.set_xlabel("")
        axes[0][1].legend(fontsize=8, loc="best")
        fig.suptitle(f"Coeff-repair-stage isolation: coefficient_first vs ARC-only (b)  [repair_span={span}]",
                     fontsize=13, fontweight="bold", y=1.0)
        fig.text(0.5, 0.975, _subtitle(summary, f", {model_label}"), ha="center", fontsize=8, alpha=0.7)
        fig.tight_layout(rect=(0, 0, 1, 0.97))
        d = _save(fig, out_dir, f"coeff_repair_isolation{suffix}_{span}")
    return d


def plot_silent_w1(summary, out_dir=None, setups=None, configs=("arc_only_a", "arc_only_b"), W=1, span="payload"):
    """Keyless-advantage figure: silent-decode rate vs BER at the weakest oracle (W=1) in
    the data-segment configs, keyless vs keyed. One panel per config; pass
    setups=[(label, summary), ...] to overlay several setups (e.g. gen6 vs gen10) as
    linestyles. Honest scope: this is the regime where keyless' free self-check wins;
    at W>=2 both arms are ~0 here (see plot_silent), and coefficient_first is excluded
    because of the keyless coeff-segment blind spot (ADR-0013 Results)."""
    setups = setups or [(None, summary)]
    styles = ("-", "--", ":", "-.")
    present = [c for c in configs if any(c in set(s["config"]) for _, s in setups)]
    fig, axes = plt.subplots(1, len(present), figsize=(6 * len(present), 4.8), sharey=True, squeeze=False)
    axes = axes[0]
    for ax, cfg in zip(axes, present):
        for (label, s), ls in zip(setups, styles):
            c = s[(s["config"] == cfg) & (s["repair_span"] == span) & (s["W"] == W)].sort_values("bit_error_rate")
            for arm, meta in ARMS.items():
                a = c[c["arm"] == arm]
                if a.empty:
                    continue
                xs, ys, err = (a[k].to_numpy() for k in ("bit_error_rate", "silent_decode_rate", "silent_ci"))
                ax.errorbar(xs, ys, yerr=[np.minimum(err, ys), err], fmt=ls, marker="o", markersize=5,
                            color=meta["color"], capsize=2, linewidth=1.8)
                if ax is axes[-1]:  # proxy handle so the legend shows the setup's linestyle
                    ax.plot([], [], ls, marker="o", color=meta["color"],
                            label=f"{meta['label']}" + (f" ({label})" if label else ""))
        ax.set_title(CONFIG_LABEL[cfg], fontsize=10)
        _dress(ax, "Silent-decode rate (wrong-accept, per target)" if ax is axes[0] else None)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    axes[-1].legend(fontsize=8, loc="upper left")
    fig.suptitle(f"Silent decodes at matched W={W}: keyless self-check vs keyed MAC  [repair_span={span}]",
                 fontsize=13, fontweight="bold", y=1.03)
    sub = _subtitle(setups[0][1])
    if len(setups) > 1:  # setups differ in gen_size/T/data_fields: name them instead of the first one's
        sub = "setups: " + "; ".join(f"{lbl}: G=T={s.attrs.get('gen_size')}, {s.attrs.get('data_fields')} B data"
                                     for lbl, s in setups) + ", GF(2^8), max_hd=2, bit-flip only, injected trust"
    fig.text(0.5, 0.97, sub, ha="center", fontsize=8, alpha=0.7)
    return _save(fig, out_dir, f"silent_w{W}_vs_ber_{span}")


PLOT_FUNCS = {
    "silent_w1": plot_silent_w1,
    "recovery": plot_recovery,
    "silent": plot_silent,
    "ops": plot_ops,
    "isolation": plot_isolation,
}


def plot_all(summary, out_dir=None):
    d = None
    for fn in PLOT_FUNCS.values():
        d = fn(summary, out_dir)
    return d


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", default=[DEFAULT_RUNS], help="glob(s) for run dirs or raw_trials.csv")
    ap.add_argument("--plots", default="all", help="comma list of " + ",".join(PLOT_FUNCS) + " or 'all'")
    ap.add_argument("--min-trials", type=int, default=DEFAULT_MIN_TRIALS, help="cells below this many seeds drawn hollow")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output dir (repo-relative or absolute)")
    args = ap.parse_args(argv)

    paths = discover(args.runs)
    if not paths:
        print(f"no raw_trials.csv found for {args.runs}")
        return
    print(f"pooling {len(paths)} run(s): " + ", ".join(p.parent.name for p in paths))
    df = load_pooled(paths)
    if df.empty:
        print("no compatible trials after pooling")
        return
    summary = aggregate(df, args.min_trials)
    out_dir = _out(_ROOT / args.out)
    summary.to_csv(out_dir / "pooled_summary.csv", index=False)
    keys = list(PLOT_FUNCS) if args.plots == "all" else [k.strip() for k in args.plots.split(",") if k.strip() in PLOT_FUNCS]
    for k in keys:
        PLOT_FUNCS[k](summary, out_dir)
    print(f"pooled {len(df)} rows -> {len(summary)} cells; wrote {len(keys)} plot set(s) + pooled_summary.csv to {out_dir}")


if __name__ == "__main__":
    main()
