"""Pool recovery_capability sweep CSVs and (re)plot from them -- one function per plot.

Decouples *plotting* from *running*: reads ``raw_trials.csv`` from one or more
sweep run dirs (see scripts/recovery_capability_sweep.py), pools every trial into
one table, recomputes per-cell metrics on the union, and draws the figures. So
you can fine-tune plot styling now against whatever data exists, and just re-run
this (no sim) as more runs land -- sparse points firm up on their own.

Manual use (each plot is its own function -- edit one, call one):
    from scripts.recovery_plots_from_csv import load, plot_ticks, plot_all
    s = load()            # pools all runs -> summary DataFrame (carries .attrs)
    plot_ticks(s)         # writes logs/accumulated_plots/ticks_vs_ber.{png,pdf}
    plot_all(s)           # every plot
Each plot_* takes (summary, out_dir=None); out_dir defaults to logs/accumulated_plots.

CLI (PowerShell; env vars per memory how_to_run_sims):
    $env:LOG_FOLDER="./logs"; $env:PYTHONPATH="."; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/recovery_plots_from_csv.py
    ... --runs "logs/recovery_capability_fast/*" --plots retransmits,ticks --min-trials 30 --gen 16

Why pool from raw_trials.csv and not summary.csv:
  * correct pooling -- rates/CI recomputed over the union of trials, not averaged
    across per-run means (wrong when trial counts differ);
  * retransmits (= packets_to_decode - gen_size) only exist at trial level;
  * the logical-tick completion cost (scheme_ops + decode_ops) is per-trial too.

Metric definitions (all "over decoded trials" unless noted):
  retransmits       packets_to_decode - gen_size          extra pkts to finish a gen
  overhead          mean(overhead ratio)                  packets_to_decode / gen_size
  pair_recovery     pairs_recovered / (recovered+failed)  denominator = pairs; Wilson 95% CI
  silent_decode     mean over ALL trials                  MUST be 0 (undetected wrong decode)
  ticks (total_ops) scheme_ops + decode_ops               field-ops to complete a gen (log y)
"""
import argparse
import math
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Arm styling -- kept in sync with scripts/recovery_capability_sweep.py ARMS.
ARMS = {
    "keyless": {"color": "#588157", "label": "Keyless HMAC (orthogonal)"},
    "keyed":   {"color": "#3d405b", "label": "Keyed HMAC (MAC)"},
}
GEN_LS = ["-", "--", ":", "-."]  # linestyle per gen_size when several are present
DEFAULT_RUNS = "logs/recovery_capability_*/*"
DEFAULT_OUT = "logs/accumulated_plots"
DEFAULT_MIN_TRIALS = 30


# --------------------------------------------------------------------------- #
# stats helpers
# --------------------------------------------------------------------------- #
def _z_halfwidth(mean, std, n, z=1.96):
    """Normal-approx half-width for a mean; nan if <2 samples."""
    if n is None or n < 2 or not np.isfinite(std):
        return float("nan")
    return z * std / math.sqrt(n)


def _wilson_halfwidth(successes, total, z=1.96):
    """95% Wilson interval half-width for a proportion; nan if no trials."""
    if total <= 0:
        return float("nan")
    p = successes / total
    denom = 1 + z * z / total
    return (z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))) / denom


def _parse_scheme(scheme):
    """('segmented_uniform_hd_n5') -> (strategy, N). Best-effort for the subtitle."""
    m = re.search(r"_n(\d+)$", scheme or "")
    n = int(m.group(1)) if m else None
    body = re.sub(r"_n\d+$", "", scheme or "")
    body = re.sub(r"^(segmented|mac)_", "", body)
    return body or "?", n


# --------------------------------------------------------------------------- #
# load + pool + aggregate
# --------------------------------------------------------------------------- #
def discover(patterns):
    """Expand glob patterns (relative to repo root) into raw_trials.csv paths."""
    paths = []
    for pat in patterns:
        for d in sorted(_ROOT.glob(pat)):
            csv = d / "raw_trials.csv" if d.is_dir() else d
            if csv.name == "raw_trials.csv" and csv.exists():
                paths.append(csv)
    return paths


def load_pooled(paths):
    """Concat every raw_trials.csv into one trial-level table.

    Guards run compatibility: each arm must map to a single scheme string across
    all runs (that string encodes strategy + N + field layout). A run that reuses
    an arm name for a different scheme is skipped with a warning so incomparable
    cells never get silently pooled. Returns (trials_df, arm_scheme).
    """
    arm_scheme, frames = {}, []
    for p in paths:
        df = pd.read_csv(p)
        df["run_id"] = p.parent.name
        skip = False
        for arm, sub in df.groupby("arm"):
            schemes = set(sub["scheme"].unique())
            if len(schemes) != 1:
                print(f"  ! {p.parent.name}: arm '{arm}' has mixed schemes {schemes}; skipping run")
                skip = True
                break
            sc = schemes.pop()
            if arm_scheme.setdefault(arm, sc) != sc:
                print(f"  ! {p.parent.name}: arm '{arm}' scheme '{sc}' "
                      f"!= established '{arm_scheme[arm]}'; skipping run")
                skip = True
                break
        if not skip:
            frames.append(df)
    if not frames:
        return pd.DataFrame(), arm_scheme
    return pd.concat(frames, ignore_index=True), arm_scheme


def aggregate(df, min_trials=DEFAULT_MIN_TRIALS):
    """Pooled per-(arm, gen_size, ber) metrics recomputed over all trials.

    Returns a DataFrame; config for subtitles is stashed in ``.attrs``
    (strategy, n_segments, min_trials) so plot_* functions need only the frame.
    """
    rows, strat, nseg = [], "?", None
    for (arm, gen, ber), g in df.groupby(["arm", "gen_size", "bit_error_rate"]):
        strat, nseg = _parse_scheme(g["scheme"].iloc[0])
        dec = g[g["decoded"]]
        n, n_dec = len(g), len(dec)
        retx = (dec["packets_to_decode"] - gen) if n_dec else pd.Series(dtype=float)
        ops = (dec["scheme_ops"] + dec["decode_ops"]) if n_dec else pd.Series(dtype=float)
        pr_ok, pr_no = int(g["pairs_recovered"].sum()), int(g["pairs_failed"].sum())
        pair_den = pr_ok + pr_no
        rows.append({
            "arm": arm, "gen_size": int(gen), "bit_error_rate": float(ber),
            "n_trials": n, "n_decoded": n_dec, "n_runs": g["run_id"].nunique(),
            "sparse": n < min_trials,
            "decode_success_rate": n_dec / n if n else float("nan"),
            "silent_decode_rate": float(g["silent_decode"].mean()) if n else float("nan"),
            "pair_recovery_rate": (pr_ok / pair_den) if pair_den else float("nan"),
            "pair_ci": _wilson_halfwidth(pr_ok, pair_den),
            "pair_denominator": pair_den,
            "mean_overhead": float(dec["overhead"].mean()) if n_dec else float("nan"),
            "mean_retransmits": float(retx.mean()) if n_dec else float("nan"),
            "retransmit_ci": _z_halfwidth(retx.mean(), retx.std(ddof=1), n_dec) if n_dec else float("nan"),
            "mean_total_ops": float(ops.mean()) if n_dec else float("nan"),
            "ops_ci": _z_halfwidth(ops.mean(), ops.std(ddof=1), n_dec) if n_dec else float("nan"),
        })
    out = pd.DataFrame(rows).sort_values(["arm", "gen_size", "bit_error_rate"]).reset_index(drop=True)
    out.attrs.update(strategy=strat, n_segments=nseg, min_trials=min_trials)
    return out


def load(runs=DEFAULT_RUNS, min_trials=DEFAULT_MIN_TRIALS, gen=None):
    """Convenience: discover -> pool -> aggregate. Returns the summary DataFrame.

    ``runs`` is a glob string or list of globs (repo-relative). ``gen`` keeps only
    one gen_size. This is the one-liner for manual/REPL use.
    """
    patterns = [runs] if isinstance(runs, str) else list(runs)
    paths = discover(patterns)
    if not paths:
        raise FileNotFoundError(f"no raw_trials.csv found for {patterns}")
    df, _ = load_pooled(paths)
    if df.empty:
        raise ValueError("no compatible trials after pooling")
    if gen is not None:
        df = df[df["gen_size"] == gen]
    return aggregate(df, min_trials)


# --------------------------------------------------------------------------- #
# plotting -- shared mechanics + one function per plot
# --------------------------------------------------------------------------- #
def _out(out_dir):
    d = Path(out_dir) if out_dir else _ROOT / DEFAULT_OUT
    d.mkdir(parents=True, exist_ok=True)
    return d


def _subtitle(summary):
    a = summary.attrs
    gens = ",".join(str(g) for g in sorted(summary["gen_size"].unique()))
    return (f"N={a.get('n_segments')} segments, gen_size={gens}, {a.get('strategy','?')}, "
            f"combined recovery (hollow = <{a.get('min_trials', DEFAULT_MIN_TRIALS)} trials)")


def _draw_series(ax, summary, valcol, errcol=None):
    """Both arms, all gen_sizes, for one metric column: faint connecting line,
    solid/hollow markers (hollow = sparse cell), CI bars, and n= labels.
    This is the shared mechanical part; per-plot identity lives in the plot_* fns.
    """
    gens = sorted(summary["gen_size"].unique())
    ls_for = {g: GEN_LS[i % len(GEN_LS)] for i, g in enumerate(gens)}
    for arm, meta in ARMS.items():
        sub = summary[summary["arm"] == arm]
        for gen in gens:
            s = sub[sub["gen_size"] == gen].sort_values("bit_error_rate")
            s = s[np.isfinite(s[valcol])]
            if s.empty:
                continue
            xs, ys = s["bit_error_rate"].to_numpy(), s[valcol].to_numpy()
            ax.plot(xs, ys, ls_for[gen], color=meta["color"], linewidth=2, alpha=0.35, zorder=1)
            if errcol and errcol in s:
                err = s[errcol].to_numpy()
                m = np.isfinite(err)
                if m.any():
                    ax.errorbar(xs[m], ys[m], yerr=err[m], fmt="none",
                                ecolor=meta["color"], elinewidth=1.2, capsize=3, zorder=2)
            for _, r in s.iterrows():
                sparse = bool(r["sparse"])
                ax.plot(r["bit_error_rate"], r[valcol], marker="o", markersize=7,
                        color=meta["color"], zorder=3,
                        markerfacecolor="white" if sparse else meta["color"],
                        markeredgecolor=meta["color"])
                ax.annotate(f"n={int(r['n_trials'])}", (r["bit_error_rate"], r[valcol]),
                            textcoords="offset points", xytext=(0, 7), ha="center",
                            fontsize=7, color=meta["color"], alpha=0.8)
            lbl = meta["label"] + (f" gen{gen}" if len(gens) > 1 else "")
            ax.plot([], [], ls_for[gen], color=meta["color"], linewidth=2, label=lbl)


def _finish(fig, ax, summary, key, title, out_dir):
    """Common axis dressing + save png+pdf. Returns the output dir."""
    ax.set_xscale("log")
    ax.set_xlabel("Bit error rate", fontsize=12, fontweight="bold")
    ax.grid(True, linestyle="--", alpha=0.3)
    ax.set_title(_subtitle(summary), fontsize=8.5, alpha=0.7)
    fig.suptitle(title, fontsize=13, fontweight="bold", y=0.98)
    if ax.get_legend_handles_labels()[1]:
        ax.legend(fontsize=9)
    fig.tight_layout()
    d = _out(out_dir)
    for ext in ("png", "pdf"):
        fig.savefig(d / f"{key}_vs_ber.{ext}", dpi=300, bbox_inches="tight")
    plt.close(fig)
    return d


# ---- one function per plot. Edit the body of the one you care about. -------- #
def plot_retransmits(summary, out_dir=None):
    """Mean retransmissions per generation (= extra packets to finish) vs BER."""
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    _draw_series(ax, summary, "mean_retransmits", "retransmit_ci")
    ax.set_ylabel("Mean retransmissions per generation", fontsize=12, fontweight="bold")
    return _finish(fig, ax, summary, "retransmits",
                   "Mean retransmissions per generation vs BER", out_dir)


def plot_overhead(summary, out_dir=None):
    """Mean transmission overhead ratio (packets_to_decode / gen_size) vs BER."""
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    _draw_series(ax, summary, "mean_overhead", None)
    ax.set_ylabel("Mean transmission overhead (ratio, decoded)", fontsize=12, fontweight="bold")
    return _finish(fig, ax, summary, "overhead",
                   "Mean transmission overhead vs BER", out_dir)


def plot_recovery(summary, out_dir=None):
    """Pair recovery rate (Wilson 95% CI) vs BER, y in [0, 1]."""
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    _draw_series(ax, summary, "pair_recovery_rate", "pair_ci")
    ax.set_ylim(-0.02, 1.02)
    ax.set_ylabel("Pair recovery rate", fontsize=12, fontweight="bold")
    return _finish(fig, ax, summary, "recovery", "Pair recovery rate vs BER", out_dir)


def plot_silent(summary, out_dir=None):
    """Silent-decode rate vs BER -- the safety metric, MUST stay 0."""
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    _draw_series(ax, summary, "silent_decode_rate", None)
    ax.set_ylabel("Silent-decode rate (MUST be 0)", fontsize=12, fontweight="bold")
    return _finish(fig, ax, summary, "silent",
                   "Silent-decode rate (MUST be 0) vs BER", out_dir)


def plot_ticks(summary, out_dir=None):
    """Logical-tick completion cost: mean field-ops (scheme_ops + decode_ops) per
    generation vs BER, log y. Deterministic stand-in for wall-clock time."""
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    _draw_series(ax, summary, "mean_total_ops", "ops_ci")
    ax.set_yscale("log")
    ax.set_ylabel("Mean field-ops per generation (logical ticks)", fontsize=12, fontweight="bold")
    return _finish(fig, ax, summary, "ticks",
                   "Mean field-ops per generation (logical ticks) vs BER", out_dir)


PLOT_FUNCS = {
    "retransmits": plot_retransmits,
    "overhead": plot_overhead,
    "recovery": plot_recovery,
    "silent": plot_silent,
    "ticks": plot_ticks,
}


def plot_all(summary, out_dir=None):
    """Draw every plot. Returns the output dir."""
    d = None
    for fn in PLOT_FUNCS.values():
        d = fn(summary, out_dir)
    return d


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", default=[DEFAULT_RUNS],
                    help="glob(s) for run dirs or raw_trials.csv paths (repo-relative)")
    ap.add_argument("--plots", default="all",
                    help="comma list of " + ",".join(PLOT_FUNCS) + " or 'all'")
    ap.add_argument("--min-trials", type=int, default=DEFAULT_MIN_TRIALS,
                    help=f"cells below this many trials drawn hollow (default {DEFAULT_MIN_TRIALS})")
    ap.add_argument("--gen", type=int, default=None, help="keep only this gen_size")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output dir (repo-relative)")
    args = ap.parse_args()

    paths = discover(args.runs)
    if not paths:
        print(f"no raw_trials.csv found for {args.runs}")
        return
    print(f"pooling {len(paths)} run(s):")
    for p in paths:
        print(f"  - {p.parent.name}")
    df, _ = load_pooled(paths)
    if df.empty:
        print("no compatible trials after pooling")
        return
    if args.gen is not None:
        df = df[df["gen_size"] == args.gen]

    summary = aggregate(df, args.min_trials)
    out_dir = _out(_ROOT / args.out)
    summary.to_csv(out_dir / "pooled_summary.csv", index=False)
    print(f"\npooled {len(df)} trials -> {summary['bit_error_rate'].nunique()} BERs, "
          f"arms {sorted(df['arm'].unique())}")
    print(summary[["arm", "gen_size", "bit_error_rate", "n_trials", "n_runs", "sparse"]]
          .to_string(index=False))

    keys = list(PLOT_FUNCS) if args.plots == "all" else \
        [k.strip() for k in args.plots.split(",") if k.strip() in PLOT_FUNCS]
    for k in keys:
        PLOT_FUNCS[k](summary, out_dir)
    print(f"\nwrote {len(keys)} plot(s) (png+pdf) + pooled_summary.csv to {out_dir}")


if __name__ == "__main__":
    main()
