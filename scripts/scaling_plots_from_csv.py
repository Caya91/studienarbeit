r"""R2/R3 scaling-study plots (2026-09-29): how packet size (df) and segmentation (N, i.e. data-
segment length L) change ACR-only recovery, over BER 1e-5 .. 1e-2. One function per plot.

Inputs (pooled at trial level, never averaged summaries):
  isolated harness  <root>/iso_w/*/raw_trials.csv, <root>/iso_hd/*/raw_trials.csv
                    (simulation/isolated_recovery_sim.py, schema v4; one run dir per (df, N, config set))
  end-to-end        <root>/prod/*/raw_trials.csv  (scripts/pareto_sweep.py schema v2, strategy acr_only)
Default root: logs/scaling_acr (main repo). ACR = algebraic consistency check (code: "arc").

Encoding (thesis): colour = arm (keyless #588157, keyed #3d405b), lightness = segment length L
(darker = shorter L = more segments), marker = arm (o keyless, s keyed), every line direct-labelled
with its N. Hollow marker = fewer than --min-trials trials, or (end-to-end) not every trial decoded.
Zero recovery / zero efficiency at high BER is plotted AS DATA (the decodability floor), never dropped.

CLI (PowerShell; memory how_to_run_sims):
  $env:LOG_FOLDER="./logs"; $env:PYTHONPATH="."
  & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/scaling_plots_from_csv.py --root E:/projects/studienarbeit/logs/scaling_acr
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

DEFAULT_ROOT = _ROOT / "logs" / "scaling_acr"
DEFAULT_MIN_TRIALS = 20
ARM = {"keyless": {"color": "#588157", "marker": "o", "ls": "-", "label": "keyless (orthogonal)"},
       "keyed": {"color": "#3d405b", "marker": "s", "ls": "--", "label": "keyed (MAC)"}}
INK, INK_MUTED, GRID = "#1f1f1e", "#6b6a64", "#e4e3dd"
CONFIG_TXT = {("arc_only_a", "payload"): "payload errors, payload repair",
              ("acr_only_data_tags", "payload"): "payload+tag errors, payload repair",
              ("acr_only_data_tags", "segment"): "payload+tag errors, payload+tag repair"}
SCOPE_TXT = {("data_payload", "payload"): "payload errors, payload repair",
             ("data_segment", "payload"): "payload+tag errors, payload repair",
             ("data_segment", "segment"): "payload+tag errors, payload+tag repair"}


# --------------------------------------------------------------------------- #
# stats + loading
def _wilson(k, n, z=1.96):
    if n <= 0:
        return float("nan")
    p = k / n
    return z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)


def _csvs(pattern):
    return [Path(p) for p in sorted(glob.glob(str(pattern)))]


def load_isolated(root=DEFAULT_ROOT, sub="iso_w", min_trials=DEFAULT_MIN_TRIALS) -> pd.DataFrame:
    paths = _csvs(Path(root) / sub / "*" / "raw_trials.csv")
    if not paths:
        raise FileNotFoundError(f"no isolated runs under {Path(root) / sub}")
    raw = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    key = ["data_fields", "num_data_segments", "config", "repair_span", "arm", "W", "bit_error_rate",
           "max_combined_hd", "candidates_budget"]
    raw = raw.drop_duplicates(subset=key + ["seed"])
    rows = []
    for k, g in raw.groupby(key):
        n_t = int(g["T"].sum())
        rec, sil = int(g["recovered"].sum()), int(g["silent"].sum())
        rows.append({**dict(zip(key, k)), "N": int(k[1]) + 1, "L": int(k[0]) // int(k[1]), "seeds": len(g),
                     "recovery_rate": rec / n_t, "recovery_ci": _wilson(rec, n_t),
                     "silent_rate": sil / n_t, "silent_ci": _wilson(sil, n_t),
                     "mean_ops": g["recovery_ops"].mean(), "mean_time_s": g["recovery_time_s"].mean()})
    s = pd.DataFrame(rows)
    s["sparse"] = s["seeds"] < min_trials
    return s


def load_production(root=DEFAULT_ROOT, min_trials=DEFAULT_MIN_TRIALS) -> pd.DataFrame:
    from scripts.pareto_from_csv import load_trials, summarize
    s = summarize(load_trials([str(Path(root) / "prod" / "*")]), min_trials)
    s = s[s["strategy"] == "acr_only"].copy()
    s["N"] = s["n_segments"].astype(int)
    s["L"] = s["data_fields"] // (s["N"] - 1)
    s["decode_rate"] = s["correct_rate"] + s["silent_rate"]
    return s


# --------------------------------------------------------------------------- #
# shared mechanics
def _shade(hex_color, t):
    """Mix white -> colour: t in (0, 1]; t = 1 is the arm colour itself."""
    c = np.array(matplotlib.colors.to_rgb(hex_color))
    return tuple(1 - t * (1 - c))


def _L_shades(Ls, arm):
    """Darker = shorter segments. Lightest step kept >= 0.4 so it stays visible on white."""
    Ls = sorted(Ls, reverse=True)
    ts = np.linspace(0.4, 1.0, len(Ls)) if len(Ls) > 1 else [1.0]
    return {L: _shade(ARM[arm]["color"], t) for L, t in zip(Ls, ts)}


def _style(ax, logx=True, logy=False, ylim=None, percent=False):
    ax.grid(True, which="major", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED, labelcolor=INK, labelsize=8)
    if logx:
        ax.set_xscale("log")
    if logy:
        ax.set_yscale("log")
    if ylim:
        ax.set_ylim(*ylim)
    if percent:
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))


def _series(ax, g, x, y, err, arm, color, hollow_col, label):
    g = g.sort_values(x)
    xs, ys = g[x].to_numpy(float), g[y].to_numpy(float)
    ax.plot(xs, ys, color=color, linestyle=ARM[arm]["ls"], linewidth=2, zorder=2, marker=ARM[arm]["marker"],
            markersize=5, label=label or None)
    if err is not None:
        e = g[err].to_numpy(float)
        ax.errorbar(xs, ys, yerr=[np.minimum(e, ys), e], fmt="none", ecolor=color, elinewidth=1, capsize=2, zorder=2)
    for xv, yv, h in zip(xs, ys, g[hollow_col].to_numpy(bool)):
        ax.plot(xv, yv, marker=ARM[arm]["marker"], markersize=6, color=color, markeredgewidth=1.5,
                markerfacecolor="white" if h else color, zorder=3, linestyle="none")


def _save(fig, out_dir, name, caption):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.text(0.5, 0.005, caption, ha="center", va="bottom", fontsize=7.5, color=INK_MUTED, wrap=True)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    for ext in ("png", "pdf"):
        fig.savefig(out_dir / f"{name}.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out_dir / f"{name}.png"


def _grid_by(summary, value_col, err_col, ylabel, x="bit_error_rate", hollow="sparse", logy=False, ylim=None,
             percent=False, xlabel="bit error rate (per payload bit)"):
    """rows = arm, cols = df; a line per N (lightness = L)."""
    dfs = sorted(summary["data_fields"].unique())
    arms = [a for a in ARM if a in set(summary["arm"])]
    fig, axes = plt.subplots(len(arms), len(dfs), figsize=(4.3 * len(dfs), 3.3 * len(arms)),
                             sharex=True, sharey=True, squeeze=False)
    for i, arm in enumerate(arms):
        for j, d in enumerate(dfs):
            ax = axes[i][j]
            sub = summary[(summary["arm"] == arm) & (summary["data_fields"] == d)]
            shades = _L_shades(sub["L"].unique(), arm)
            for (n, L), g in sub.groupby(["N", "L"]):
                _series(ax, g, x, value_col, err_col, arm, shades[L], hollow, f"N={n} (L={L})")
            _style(ax, logx=True, logy=logy, ylim=ylim, percent=percent)
            if i == 0:
                ax.set_title(f"payload {d} B", color=INK, fontsize=10)
                ax.legend(fontsize=7, frameon=False, labelcolor=INK, loc="best")
            if j == 0:
                ax.set_ylabel(f"{ARM[arm]['label']}\n{ylabel}", color=INK, fontsize=9)
            if i == len(arms) - 1:
                ax.set_xlabel(xlabel, color=INK, fontsize=9)
    return fig


# --------------------------------------------------------------------------- #
# isolated-harness plots
def _iso_pick(s, config="arc_only_a", span="payload", W=6, hd=2):
    return s[(s["config"] == config) & (s["repair_span"] == span) & (s["W"] == W) & (s["max_combined_hd"] == hd)]


def plot_iso_recovery_vs_ber(s, out_dir, config="arc_only_a", span="payload", W=6):
    fig = _grid_by(_iso_pick(s, config, span, W), "recovery_rate", "recovery_ci", "recovery rate",
                   ylim=(-0.03, 1.03), percent=True)
    return _save(fig, out_dir, f"iso_recovery_vs_ber_{config}_{span}_W{W}",
                 f"Isolated harness, ACR-only, {CONFIG_TXT[(config, span)]}; g=6, T=6 targets/seed, GF(2^8), "
                 f"HD 2, budget 20000, acceptance width W={W}. Lighter = longer data segments. Hollow = sparse.")


def plot_iso_silent_vs_ber(s, out_dir, config="arc_only_a", span="payload", W=1):
    fig = _grid_by(_iso_pick(s, config, span, W), "silent_rate", "silent_ci", "silent-decode rate",
                   ylim=(-0.03, 1.03), percent=True)
    return _save(fig, out_dir, f"iso_silent_vs_ber_{config}_{span}_W{W}",
                 f"Isolated harness, ACR-only, {CONFIG_TXT[(config, span)]}; wrong-accept per target at W={W}; "
                 "g=6, GF(2^8), HD 2, budget 20000.")


def plot_iso_ops_vs_ber(s, out_dir, config="arc_only_a", span="payload", W=6):
    sub = _iso_pick(s, config, span, W)
    sub = sub[sub["mean_ops"] > 0]
    fig = _grid_by(sub, "mean_ops", None, "recovery field ops (mean/seed)", logy=True)
    return _save(fig, out_dir, f"iso_ops_vs_ber_{config}_{span}_W{W}",
                 f"Isolated harness, ACR-only, {CONFIG_TXT[(config, span)]}; GF ops (mul+add) of the repair call per "
                 f"seed (6 targets), W={W}; zero-op cells (nothing to repair) omitted on the log axis.")


def plot_iso_vs_seglen(s, out_dir, bers=(1e-4, 1e-3, 3e-3), config="arc_only_a", span="payload", W=6):
    """Same L, bigger df: recovery vs segment length, a line per df, one panel per BER."""
    sub = _iso_pick(s, config, span, W)
    bers = [b for b in bers if b in set(sub["bit_error_rate"])]
    fig, axes = plt.subplots(1, len(bers), figsize=(4.3 * len(bers), 3.4), sharey=True, squeeze=False)
    dfs = sorted(sub["data_fields"].unique())
    for ax, b in zip(axes[0], bers):
        for arm in ARM:
            shades = {d: _shade(ARM[arm]["color"], t) for d, t in zip(dfs, np.linspace(0.45, 1.0, len(dfs)))}
            for d in dfs:
                g = sub[(sub["arm"] == arm) & (sub["data_fields"] == d) & (sub["bit_error_rate"] == b)]
                if len(g):
                    _series(ax, g, "L", "recovery_rate", "recovery_ci", arm, shades[d], "sparse",
                            f"{d} B" if arm == "keyless" else "")
        _style(ax, logx=False, ylim=(-0.03, 1.03), percent=True)
        ax.set_xscale("log", base=2)
        ticks = sorted(sub["L"].unique())
        ax.set_xticks(ticks, [str(t) for t in ticks])
        ax.minorticks_off()
        ax.set_title(f"BER = {b:.0e}", color=INK, fontsize=10)
        ax.set_xlabel("data-segment length L (bytes)", color=INK, fontsize=9)
    axes[0][0].set_ylabel("recovery rate", color=INK, fontsize=9)
    axes[0][0].legend(fontsize=7, frameon=False, labelcolor=INK, title="keyless, payload", title_fontsize=7)
    return _save(fig, out_dir, f"iso_recovery_vs_seglen_{config}_{span}_W{W}",
                 f"Isolated harness, ACR-only, {CONFIG_TXT[(config, span)]}, W={W}. Line per payload size "
                 "(lighter = smaller); circle/solid = keyless, square/dashed = keyed.")


def plot_iso_error_models(s, out_dir, layouts=None, W=6):
    """Payload-only errors vs payload+tag errors (payload / segment repair span), per layout."""
    layouts = layouts or sorted({(d, n) for d, n in zip(s["data_fields"], s["N"])})
    fig, axes = plt.subplots(1, len(layouts), figsize=(4.0 * len(layouts), 3.4), sharey=True, squeeze=False)
    styles = {("arc_only_a", "payload"): 1.0, ("acr_only_data_tags", "payload"): 0.45,
              ("acr_only_data_tags", "segment"): 0.72}
    for ax, (d, n) in zip(axes[0], layouts):
        for (cfg, span), t in styles.items():
            for arm in ARM:
                g = s[(s["config"] == cfg) & (s["repair_span"] == span) & (s["W"] == W) & (s["arm"] == arm)
                      & (s["data_fields"] == d) & (s["N"] == n) & (s["max_combined_hd"] == 2)]
                if len(g):
                    _series(ax, g, "bit_error_rate", "recovery_rate", None, arm, _shade(ARM[arm]["color"], t),
                            "sparse", "")
        _style(ax, ylim=(-0.03, 1.03), percent=True)
        ax.set_title(f"{d} B, N={n}", color=INK, fontsize=10)
        ax.set_xlabel("bit error rate", color=INK, fontsize=9)
    axes[0][0].set_ylabel("recovery rate", color=INK, fontsize=9)
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], color=_shade(ARM["keyless"]["color"], t), linewidth=2, label=CONFIG_TXT[k])
               for k, t in styles.items()]
    handles += [Line2D([], [], color=INK_MUTED, marker=ARM[a]["marker"], linestyle=ARM[a]["ls"], label=ARM[a]["label"])
                for a in ARM]
    fig.legend(handles=handles, loc="upper center", ncol=5, frameon=False, fontsize=7.5, bbox_to_anchor=(0.5, 1.06))
    return _save(fig, out_dir, f"iso_error_models_W{W}",
                 f"Isolated harness, ACR-only, W={W}, HD 2: payload-only errors vs errors that also hit the data "
                 "segments' salt/tag bytes, repaired over the payload only or over payload + salt/tags.")


# --------------------------------------------------------------------------- #
# end-to-end (send-until-decodable) plots
def _prod_pick(p, scope="data_payload", span="payload"):
    p = p[(p["error_scope"] == scope) & (p["repair_span"] == span)].copy()
    p["hollow"] = p["sparse"] | (p["decode_rate"] < 1)
    return p


def plot_prod_efficiency_vs_ber(p, out_dir, scope="data_payload", span="payload"):
    fig = _grid_by(_prod_pick(p, scope, span), "efficiency", None, "bit-efficiency (info/wire bits)",
                   hollow="hollow", ylim=(-0.02, 1.0))
    return _save(fig, out_dir, f"prod_efficiency_vs_ber_{scope}_{span}",
                 f"End-to-end ACR-only, {SCOPE_TXT[(scope, span)]}; g=6, GF(2^8), HD 2, cap 8g packets. Failed "
                 "generations deliver 0 info bits. Hollow = not every trial decoded (or sparse).")


def plot_prod_decode_rate_vs_ber(p, out_dir, scope="data_payload", span="payload"):
    fig = _grid_by(_prod_pick(p, scope, span), "decode_rate", None, "decoded within 8g packets",
                   hollow="hollow", ylim=(-0.03, 1.03), percent=True)
    return _save(fig, out_dir, f"prod_decode_rate_vs_ber_{scope}_{span}",
                 f"End-to-end ACR-only, {SCOPE_TXT[(scope, span)]}: share of generations decoded before the "
                 "48-packet cap (the decodability floor).")


def plot_prod_overhead_vs_ber(p, out_dir, scope="data_payload", span="payload"):
    sub = _prod_pick(p, scope, span)
    sub = sub[np.isfinite(sub["mean_overhead_decoded"])]
    fig = _grid_by(sub, "mean_overhead_decoded", None, "packets / g (decoded trials)", hollow="hollow", logy=True)
    return _save(fig, out_dir, f"prod_overhead_vs_ber_{scope}_{span}",
                 f"End-to-end ACR-only, {SCOPE_TXT[(scope, span)]}: mean packets per generation over decoded "
                 "trials (1 = no retransmission). Hollow = some trials hit the cap.")


def plot_prod_ops_vs_ber(p, out_dir, scope="data_payload", span="payload"):
    fig = _grid_by(_prod_pick(p, scope, span), "total_ops", None, "field ops per generation", hollow="hollow",
                   logy=True)
    return _save(fig, out_dir, f"prod_ops_vs_ber_{scope}_{span}",
                 f"End-to-end ACR-only, {SCOPE_TXT[(scope, span)]}: receiver field multiplications (scheme: "
                 "detection + repair) + RLNC decode, mean per generation.")


def _vs_df(p, col, ylabel, name, out_dir, bers, scope, span, logy):
    sub = _prod_pick(p, scope, span)
    bers = [b for b in bers if b in set(sub["bit_error_rate"])]
    fig, axes = plt.subplots(1, len(bers), figsize=(4.3 * len(bers), 3.4), sharey=True, squeeze=False)
    for ax, b in zip(axes[0], bers):
        for arm in ARM:
            g0 = sub[(sub["arm"] == arm) & (sub["bit_error_rate"] == b)]
            shades = _L_shades(g0["L"].unique(), arm)
            for L, g in g0.groupby("L"):
                if len(g) >= 2:  # a line needs the same L at >= 2 sizes
                    _series(ax, g, "data_fields", col, None, arm, shades[L], "hollow",
                            f"L={L}" if arm == "keyless" else "")
        _style(ax, logx=True, logy=logy)
        ax.set_title(f"BER = {b:.0e}", color=INK, fontsize=10)
        ax.set_xlabel("payload size (bytes)", color=INK, fontsize=9)
    axes[0][0].set_ylabel(ylabel, color=INK, fontsize=9)
    axes[0][0].legend(fontsize=7, frameon=False, labelcolor=INK, title="keyless", title_fontsize=7)
    return _save(fig, out_dir, name,
                 f"End-to-end ACR-only, {SCOPE_TXT[(scope, span)]}: line per data-segment length L present at "
                 "several sizes (darker = shorter L); circle/solid = keyless, square/dashed = keyed.")


def plot_prod_overhead_vs_df(p, out_dir, bers=(1e-4, 1e-3, 3e-3), scope="data_payload", span="payload"):
    return _vs_df(p[np.isfinite(p["mean_overhead_decoded"])], "mean_overhead_decoded",
                  "packets / g (decoded trials)", f"prod_overhead_vs_df_{scope}_{span}",
                  out_dir, bers, scope, span, logy=True)


def plot_prod_ops_vs_df(p, out_dir, bers=(1e-4, 1e-3, 3e-3), scope="data_payload", span="payload"):
    return _vs_df(p, "total_ops", "field ops per generation", f"prod_ops_vs_df_{scope}_{span}",
                  out_dir, bers, scope, span, logy=True)


def plot_prod_front(p, out_dir, scope="data_payload", span="payload"):
    from scripts.pareto_from_csv import plot_front
    sub = p[(p["error_scope"] == scope) & (p["repair_span"] == span)]
    return plot_front(sub, Path(out_dir) / f"front_{scope}_{span}")


# --------------------------------------------------------------------------- #
def plot_all(root=DEFAULT_ROOT, out_dir=None, min_trials=DEFAULT_MIN_TRIALS):
    out_dir = Path(out_dir or Path(root) / "plots")
    written = []
    try:
        s = load_isolated(root, "iso_w", min_trials)
        s.to_csv(out_dir.mkdir(parents=True, exist_ok=True) or out_dir / "iso_w_summary.csv", index=False)
        for cfg, span in CONFIG_TXT:
            if len(s[(s["config"] == cfg) & (s["repair_span"] == span)]):
                written += [plot_iso_recovery_vs_ber(s, out_dir, cfg, span), plot_iso_silent_vs_ber(s, out_dir, cfg, span),
                            plot_iso_ops_vs_ber(s, out_dir, cfg, span), plot_iso_vs_seglen(s, out_dir, config=cfg, span=span)]
        written.append(plot_iso_error_models(s, out_dir))
    except FileNotFoundError as e:
        print("skip isolated:", e)
    try:
        p = load_production(root, min_trials)
        p.to_csv(out_dir / "prod_summary.csv", index=False)
        for scope, span in SCOPE_TXT:
            if len(p[(p["error_scope"] == scope) & (p["repair_span"] == span)]):
                written += [fn(p, out_dir, scope=scope, span=span) for fn in
                            (plot_prod_efficiency_vs_ber, plot_prod_decode_rate_vs_ber, plot_prod_overhead_vs_ber,
                             plot_prod_ops_vs_ber, plot_prod_overhead_vs_df, plot_prod_ops_vs_df, plot_prod_front)]
    except (FileNotFoundError, SystemExit) as e:
        print("skip production:", e)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description="R2/R3 scaling plots (ACR-only).")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--min-trials", type=int, default=DEFAULT_MIN_TRIALS)
    a = ap.parse_args(argv)
    for w in plot_all(a.root, a.out, a.min_trials):
        print("wrote", w)


if __name__ == "__main__":
    main()
