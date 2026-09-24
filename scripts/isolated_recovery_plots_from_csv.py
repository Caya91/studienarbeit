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
W_STYLE = {1: (":", "v"), 2: ("--", "s"), 3: ("-", "o"),  # (linestyle, marker) per W
           4: ("-.", "D"), 5: ((0, (5, 1)), "^"), 6: ((0, (1, 1)), "P")}
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
# Columns that must agree for runs to be pooled (else the run is skipped). Missing
# columns (older schemas) count as their own value, so old/new runs never mix.
COMPAT_COLS = ("schema_version", "gen_size", "T", "data_fields", "num_data_segments",
               "field_bits", "keyed_early_exit")
# Search-depth dimensions (ticket 19): part of the cell key, may vary inside one run.
VARIANT_COLS = ("max_combined_hd", "candidates_budget")
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
        for c in COMPAT_COLS:
            if c not in df:
                df[c] = -999  # sentinel: column absent in this schema version
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
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    # A (cell, seed) row is deterministic, so the same seed in two runs is a repeat, not a
    # new sample -- keep the first copy so re-runs never inflate n or narrow the CIs.
    key = ["config", "arm", "repair_span", "W", "bit_error_rate", *VARIANT_COLS, "seed"]
    dup = out.duplicated(subset=key, keep="first")
    if dup.any():
        print(f"  ! dropped {int(dup.sum())} duplicate (cell, seed) rows (same seeds in several runs)")
        out = out[~dup].reset_index(drop=True)
    return out


def aggregate(df, min_trials=DEFAULT_MIN_TRIALS):
    rows = []
    keys = ["config", "repair_span", "arm", "W", "bit_error_rate", *VARIANT_COLS]
    for (cfg, span, arm, W, ber, hd, budget), g in df.groupby(keys):
        n_targets = int(g["T"].sum())
        rec, sil = int(g["recovered"].sum()), int(g["silent"].sum())
        ops = g["recovery_ops"].astype(float)
        rows.append({
            "config": cfg, "repair_span": span, "arm": arm, "W": int(W), "bit_error_rate": float(ber),
            "max_combined_hd": int(hd), "candidates_budget": int(budget),
            "n_trials": len(g), "n_runs": g["run_id"].nunique(), "n_targets": n_targets,
            "sparse": len(g) < min_trials,
            "recovered": rec, "silent": sil, "failed": int(g["failed"].sum()),
            "recovery_rate": rec / n_targets, "recovery_ci": _wilson_halfwidth(rec, n_targets),
            "silent_decode_rate": sil / n_targets, "silent_ci": _wilson_halfwidth(sil, n_targets),
            "mean_recovery_ops": float(ops.mean()), "ops_ci": _z_halfwidth(ops.std(ddof=1), len(g)),
            "ops_p95": float(ops.quantile(0.95)), "ops_max": float(ops.max()),
            # schema v2 columns (NaN for v1 runs, which lack them)
            **{f"mean_{c}": (float(g[f"recovery_{c}"].astype(float).mean()) if f"recovery_{c}" in g else float("nan"))
               for c in ("mul", "add", "time_s")},
            "time_ci": (_z_halfwidth(g["recovery_time_s"].astype(float).std(ddof=1), len(g))
                        if "recovery_time_s" in g else float("nan")),
            "h2h_keyless_only": int(g["h2h_keyless_only"].sum()), "h2h_keyed_only": int(g["h2h_keyed_only"].sum()),
            "h2h_both": int(g["h2h_both"].sum()), "h2h_neither": int(g["h2h_neither"].sum()),
        })
    out = pd.DataFrame(rows).sort_values(keys).reset_index(drop=True)
    first = df.iloc[0]
    out.attrs.update({c: first[c] for c in COMPAT_COLS}, min_trials=min_trials)
    variants = df[list(VARIANT_COLS)].drop_duplicates()
    if len(variants) == 1:  # single search depth -> name it in subtitles
        out.attrs.update({c: variants.iloc[0][c] for c in VARIANT_COLS})
    return out


def variants(summary):
    """Yield (label, sub-summary) per (max_combined_hd, candidates_budget) present, with
    attrs naming that variant -- so the single-depth plots can be drawn per variant."""
    for (hd, bud), sub in summary.groupby(list(VARIANT_COLS)):
        sub = sub.reset_index(drop=True)
        sub.attrs = {**summary.attrs, "max_combined_hd": int(hd), "candidates_budget": int(bud)}
        yield f"hd{int(hd)}_{_budget_label(bud)}", sub


def _budget_label(bud):
    return "nocap" if int(bud) < 0 else f"cap{int(bud)}"


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
    bud = a.get("candidates_budget")
    budget = "" if bud is None else (", no budget" if int(bud) < 0 else f", budget {int(bud)}")
    return (f"G=gen_size={a.get('gen_size')}, T={a.get('T')}, {a.get('num_data_segments')} data segs x "
            f"{a.get('data_fields')} B, GF(2^{a.get('field_bits')}), max_hd={a.get('max_combined_hd', 'swept')}"
            f"{budget}, bit-flip only, injected trust{extra}  (hollow = <{a.get('min_trials')} seeds)")


def _line(ax, s, valcol, errcol, color, W, label):
    s = s.sort_values("bit_error_rate")
    s = s[np.isfinite(s[valcol])]
    if s.empty:
        return
    ls, mk = W_STYLE.get(W, ("-", "o"))
    xs, ys = s["bit_error_rate"].to_numpy(), s[valcol].to_numpy()
    ax.plot(xs, ys, linestyle=ls, color=color, linewidth=1.8, alpha=0.8, zorder=1)
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
    ax.plot([], [], linestyle=ls, marker=mk, color=color, label=label)


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


def plot_time(summary, out_dir=None):
    """Mean wall-clock seconds per recovery call vs BER, log y (schema v2 runs only).
    Load-dependent -- compare arms within one run; ops is the deterministic metric."""
    if not np.isfinite(summary.get("mean_time_s", pd.Series(dtype=float))).any():
        print("  plot_time: no recovery_time_s in these runs (schema v1) -- skipped")
        return None
    return _per_config_figure(summary, "mean_time_s", "time_ci", "Mean wall-clock s per recovery call",
                              "Recovery wall-clock time vs BER", "time", out_dir, log_y=True)


VS_W_METRICS = (("recovery_rate", "recovery_ci", "Recovery rate", False),
                ("silent_decode_rate", "silent_ci", "Silent-decode rate", False),
                ("mean_recovery_ops", "ops_ci", "Mean GF ops / recovery", True),
                ("mean_time_s", "time_ci", "Mean wall-clock s / recovery", True))
VS_W_BER_MARKERS = ("o", "s", "^", "D", "v", "P")


def plot_vs_w(summary, out_dir=None, bers=None):
    """Metrics vs W (x axis) -- rows = recovery / silent / ops / time, columns = configs,
    a line per (arm, BER). `bers` picks which BERs to draw (default: lowest, a middle
    one, highest). One file per repair_span: vs_w_<span>.{png,pdf}."""
    d = None
    all_bers = sorted(summary["bit_error_rate"].unique())
    if bers is None:
        bers = sorted({all_bers[0], all_bers[len(all_bers) // 2], all_bers[-1]})
    metrics = [m for m in VS_W_METRICS if m[0] in summary and np.isfinite(summary[m[0]]).any()]
    for span in sorted(summary["repair_span"].unique()):
        sub = summary[summary["repair_span"] == span]
        present = [c for c in CONFIGS if c in set(sub["config"])]
        fig, axes = plt.subplots(len(metrics), len(present), figsize=(5.5 * len(present), 3.6 * len(metrics)),
                                 sharex=True, squeeze=False)
        for r, (valcol, errcol, ylabel, log_y) in enumerate(metrics):
            for col, cfg in enumerate(present):
                ax = axes[r][col]
                c = sub[sub["config"] == cfg]
                for arm, meta in ARMS.items():
                    for ber, mk in zip(bers, VS_W_BER_MARKERS):
                        s = c[(c["arm"] == arm) & np.isclose(c["bit_error_rate"], ber)].sort_values("W")
                        if s.empty:
                            continue
                        xs, ys, err = s["W"].to_numpy(), s[valcol].to_numpy(), s[errcol].to_numpy()
                        m = np.isfinite(err)
                        ax.errorbar(xs[m], ys[m], yerr=[np.minimum(err[m], 0.9 * ys[m]), err[m]], fmt="none",
                                    ecolor=meta["color"], elinewidth=1, capsize=2, alpha=0.6)
                        ax.plot(xs, ys, "-", marker=mk, color=meta["color"], linewidth=1.6, markersize=5,
                                alpha=0.35 + 0.65 * (bers.index(ber) + 1) / len(bers),
                                label=f"{meta['label']}, BER {ber:g}")
                if log_y:
                    ax.set_yscale("log")
                ax.set_xticks(sorted(c["W"].unique()))
                ax.grid(True, linestyle="--", alpha=0.3)
                if r == 0:
                    ax.set_title(CONFIG_LABEL[cfg], fontsize=10)
                if col == 0:
                    ax.set_ylabel(ylabel, fontsize=10, fontweight="bold")
                if r == len(metrics) - 1:
                    ax.set_xlabel("Recovery-acceptance width W", fontsize=10, fontweight="bold")
        axes[0][-1].legend(fontsize=7, loc="best")
        fig.suptitle(f"Metrics vs acceptance width W  [repair_span={span}]", fontsize=13, fontweight="bold", y=1.035)
        fig.text(0.5, 1.0, _subtitle(summary), ha="center", fontsize=8, alpha=0.7)
        fig.tight_layout(rect=(0, 0, 1, 0.98))
        d = _save(fig, out_dir, f"vs_w_{span}")
    return d


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
                     fontsize=13, fontweight="bold", y=1.035)
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


# ---- ticket 19: search depth (HD) plots --------------------------------------- #
VS_HD_METRICS = (("recovery_rate", "recovery_ci", "Recovery rate", False),
                 ("silent_decode_rate", "silent_ci", "Silent-decode rate", False),
                 ("mean_recovery_ops", "ops_ci", "Mean GF ops / recovery", True),
                 ("ops_p95", None, "p95 GF ops / recovery", True),
                 ("mean_time_s", "time_ci", "Mean wall-clock s / recovery", True))


def plot_vs_hd(summary, out_dir=None):
    """Metrics vs search depth HD (x axis): rows = recovery / silent / mean ops / p95 ops /
    time, columns = BER, a line per (arm, W). One file per (config, repair_span, budget):
    vs_hd_<config>_<span>_<budget>.{png,pdf}."""
    if summary["max_combined_hd"].nunique() < 2:
        print("  plot_vs_hd: only one HD in the data -- skipped")
        return None
    d = None
    metrics = [m for m in VS_HD_METRICS if m[0] in summary and np.isfinite(summary[m[0]]).any()]
    for (cfg, span, bud), sub in summary.groupby(["config", "repair_span", "candidates_budget"]):
        bers = sorted(sub["bit_error_rate"].unique())
        fig, axes = plt.subplots(len(metrics), len(bers), figsize=(4 * len(bers), 3.2 * len(metrics)),
                                 sharex=True, sharey="row", squeeze=False)
        for r, (valcol, errcol, ylabel, log_y) in enumerate(metrics):
            for col, ber in enumerate(bers):
                ax = axes[r][col]
                c = sub[np.isclose(sub["bit_error_rate"], ber)]
                for arm, meta in ARMS.items():
                    for W in sorted(c["W"].unique()):
                        s_ = c[(c["arm"] == arm) & (c["W"] == W)].sort_values("max_combined_hd")
                        if s_.empty:
                            continue
                        ls, mk = W_STYLE.get(W, ("-", "o"))
                        xs, ys = s_["max_combined_hd"].to_numpy(), s_[valcol].to_numpy()
                        if errcol:
                            err = s_[errcol].to_numpy()
                            m = np.isfinite(err)
                            ax.errorbar(xs[m], ys[m], yerr=[np.minimum(err[m], 0.9 * ys[m]), err[m]], fmt="none",
                                        ecolor=meta["color"], elinewidth=1, capsize=2, alpha=0.6)
                        ax.plot(xs, ys, linestyle=ls, marker=mk, color=meta["color"], linewidth=1.6,
                                markersize=5, label=f"{meta['label']}, W={W}")
                if log_y:
                    ax.set_yscale("log")
                ax.set_xticks(sorted(c["max_combined_hd"].unique()))
                ax.grid(True, linestyle="--", alpha=0.3)
                if r == 0:
                    ax.set_title(f"BER {ber:g}", fontsize=10)
                if col == 0:
                    ax.set_ylabel(ylabel, fontsize=9, fontweight="bold")
                if r == len(metrics) - 1:
                    ax.set_xlabel("Search depth HD (max_combined_hd)", fontsize=9, fontweight="bold")
        axes[0][-1].legend(fontsize=7, loc="best")
        fig.suptitle(f"Metrics vs search depth HD -- {CONFIG_LABEL.get(cfg, cfg).replace(chr(10), ' ')}  "
                     f"[repair_span={span}, {_budget_label(bud)}]", fontsize=12, fontweight="bold", y=1.035)
        fig.text(0.5, 1.0, _subtitle(summary), ha="center", fontsize=8, alpha=0.7)
        fig.tight_layout(rect=(0, 0, 1, 0.98))
        d = _save(fig, out_dir, f"vs_hd_{cfg}_{span}_{_budget_label(bud)}")
    return d


def plot_pareto(summary, out_dir=None, cost="mean_recovery_ops"):
    """'How far to push HD': recovery rate vs cost (log x), one point per HD (labelled),
    a line per (arm, W); rows = configs, columns = BER. One file per (span, budget):
    pareto_<span>_<budget>.{png,pdf}. cost='ops_p95' draws the tail-cost version."""
    if summary["max_combined_hd"].nunique() < 2:
        print("  plot_pareto: only one HD in the data -- skipped")
        return None
    d = None
    for (span, bud), sub in summary.groupby(["repair_span", "candidates_budget"]):
        cfgs = [c for c in CONFIGS if c in set(sub["config"])]
        bers = sorted(sub["bit_error_rate"].unique())
        fig, axes = plt.subplots(len(cfgs), len(bers), figsize=(4 * len(bers), 3.6 * len(cfgs)),
                                 sharey="row", squeeze=False)
        for r, cfg in enumerate(cfgs):
            for col, ber in enumerate(bers):
                ax = axes[r][col]
                c = sub[(sub["config"] == cfg) & np.isclose(sub["bit_error_rate"], ber)]
                for arm, meta in ARMS.items():
                    for W in sorted(c["W"].unique()):
                        s_ = c[(c["arm"] == arm) & (c["W"] == W)].sort_values("max_combined_hd")
                        if s_.empty:
                            continue
                        ls, mk = W_STYLE.get(W, ("-", "o"))
                        ax.plot(s_[cost], s_["recovery_rate"], linestyle=ls, marker=mk, color=meta["color"],
                                linewidth=1.4, markersize=5, label=f"{meta['label']}, W={W}")
                        if W == max(c["W"].unique()):
                            for x, y, hd in zip(s_[cost], s_["recovery_rate"], s_["max_combined_hd"]):
                                ax.annotate(f"HD{int(hd)}", (x, y), textcoords="offset points", xytext=(3, -9),
                                            fontsize=6, color=meta["color"])
                ax.set_xscale("log")
                ax.grid(True, linestyle="--", alpha=0.3)
                if r == 0:
                    ax.set_title(f"BER {ber:g}", fontsize=10)
                if col == 0:
                    ax.set_ylabel(f"{CONFIG_LABEL.get(cfg, cfg)}\nRecovery rate", fontsize=8, fontweight="bold")
                if r == len(cfgs) - 1:
                    ax.set_xlabel("p95 GF ops / recovery" if cost == "ops_p95" else "Mean GF ops / recovery",
                                  fontsize=9, fontweight="bold")
        axes[0][-1].legend(fontsize=7, loc="lower right")
        fig.suptitle(f"Recovery vs cost across search depth HD  [repair_span={span}, {_budget_label(bud)}]",
                     fontsize=12, fontweight="bold", y=1.035)
        fig.text(0.5, 1.0, _subtitle(summary), ha="center", fontsize=8, alpha=0.7)
        fig.tight_layout(rect=(0, 0, 1, 0.98))
        suffix = "_p95" if cost == "ops_p95" else ""
        d = _save(fig, out_dir, f"pareto{suffix}_{span}_{_budget_label(bud)}")
    return d


def budget_effect(df):
    """Capped vs uncapped at the same (cell, HD, seed): share of seeds whose outcome counts
    differ (= the budget truncated the search), recovery / silent delta, ops ratio.
    Needs both a capped budget and 'none' (-1) in the data; returns None otherwise."""
    if not ((df["candidates_budget"] < 0).any() and (df["candidates_budget"] >= 0).any()):
        return None
    k = ["config", "repair_span", "arm", "W", "bit_error_rate", "max_combined_hd", "seed"]
    unc = df[df["candidates_budget"] < 0].set_index(k)
    rows = []
    for bud, cap in df[df["candidates_budget"] >= 0].groupby("candidates_budget"):
        j = cap.set_index(k).join(unc, rsuffix="_unc", how="inner")
        changed = (j[["recovered", "silent", "failed"]].to_numpy()
                   != j[["recovered_unc", "silent_unc", "failed_unc"]].to_numpy()).any(axis=1)
        j = j.assign(changed=changed).reset_index()
        for key, g in j.groupby(["config", "repair_span", "arm", "W", "bit_error_rate", "max_combined_hd"]):
            T = g["T"].sum()
            rows.append(dict(zip(["config", "repair_span", "arm", "W", "bit_error_rate", "max_combined_hd"], key),
                             budget=int(bud), n_seeds=len(g), seeds_truncated=float(g["changed"].mean()),
                             d_recovery_rate=(g["recovered"].sum() - g["recovered_unc"].sum()) / T,
                             d_silent_rate=(g["silent"].sum() - g["silent_unc"].sum()) / T,
                             ops_ratio_capped_over_uncapped=g["recovery_ops"].mean() / g["recovery_ops_unc"].mean()))
    return pd.DataFrame(rows)


PLOT_FUNCS = {
    "vs_hd": plot_vs_hd,
    "pareto": plot_pareto,
    "silent_w1": plot_silent_w1,
    "time": plot_time,
    "vs_w": plot_vs_w,
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
    hd_keys = [k for k in keys if k in ("vs_hd", "pareto")]
    per_variant = [k for k in keys if k not in hd_keys]
    for k in hd_keys:  # across search depths -> top-level dir
        PLOT_FUNCS[k](summary, out_dir)
    if "pareto" in hd_keys:
        plot_pareto(summary, out_dir, cost="ops_p95")
    many = summary[list(VARIANT_COLS)].drop_duplicates().shape[0] > 1
    for label, sub in (variants(summary) if many else [(None, summary)]):
        vdir = out_dir / label if label else out_dir  # one subdir per (HD, budget) when several
        for k in per_variant:
            PLOT_FUNCS[k](sub, vdir)
    be = budget_effect(df)
    if be is not None:
        be.to_csv(out_dir / "budget_effect.csv", index=False)
        print("budget effect (share of seeds whose outcome the cap changed), by HD:")
        print(be.groupby("max_combined_hd")["seeds_truncated"].agg(["mean", "max"]).round(4).to_string())
    print(f"pooled {len(df)} rows -> {len(summary)} cells; wrote {len(keys)} plot set(s) + pooled_summary.csv to {out_dir}")


if __name__ == "__main__":
    main()
