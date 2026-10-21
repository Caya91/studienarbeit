r"""S3 plots: tag-pollution admit rate vs attacker knowledge, per verification width -- the S2 figure set
(scripts/verify_width_plots_from_csv.py) with y = ADMIT rate (a polluted packet carries honest content, so it
never decodes wrong). Reads raw_trials.csv of simulation/tag_pollution_attack_sim.py (pools run dirs).

  plot_random_grid(summary, m)  keyless (top) / keyed (bottom), receiver-secret random subset; a line per W
  plot_w1(summary)              W = 1 only: rows = field, cols = arm
  plot_vs_checks                MAIN figure (2026-10-05): both arms on one axis per field, x = checks per packet,
                                y = detection OR successful attack probability, keyless r levels + keyed t sets
  plot_footprint                does the number of changed tag symbols matter? keyless support sweep vs keyed t
  plot_noise                    random tag-region bit flips (no attacker), one figure per BER (s4_noise_*)
  plot_noise_vs_ber             same data, x = BER (log), y log: where keyless peaks, keyed vs keyless

CLI (PowerShell): $env:PYTHONPATH="."; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" `
  scripts/tag_pollution_plots_from_csv.py --runs "E:/projects/studienarbeit/logs/tag_pollution_attack/g4_*"
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

from scripts.verify_width_plots_from_csv import (
    GRID, INK, INK_MUTED, _measured, _place_low, _save, _shade, _style, _theory, _wlabel,
)
from simulation.knowledge_attack_sim import wilson
from simulation.tag_pollution_attack_sim import summarize, theory_admit, theory_noise

ARM = {"keyless": {"color": "#588157", "marker": "o", "x": "r = honest packets observed",
                   "title": "keyless: W witnesses"},
       "keyed": {"color": "#3d405b", "marker": "s", "x": "t = tags polluted (of g)", "title": "keyed: W of g tags"}}
YLABEL = "polluted packet admit rate"


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


def _xs(c):
    return np.arange(int(c["knowledge"].min()), int(c["knowledge"].max()) + 1)


def plot_random_grid(summary, m, g, out_dir):
    s = summary[(summary["field_bits"] == m) & (summary["gen_size"] == g)
                & ((summary["policy"] == "random") | (summary["width"] < 0))]
    fig, axes = plt.subplots(2, 1, figsize=(5.6, 7.0), sharey=True)
    for ax, arm in zip(axes, ARM):
        sub = s[s["arm"] == arm]
        ws = sorted(sub["width"].unique(), key=lambda w: 99 if w < 0 else w)
        low = {}
        for i, (w, t) in enumerate(zip(ws, np.linspace(0.45, 1.0, len(ws)))):
            c = sub[sub["width"] == w].sort_values("knowledge")
            ks = _xs(c)
            _theory(ax, ks, [theory_admit(arm, "random", int(k), None if w < 0 else int(w), g, 2 ** m) for k in ks],
                    "theory" if i == 0 else None)
            _measured(ax, c, _shade(ARM[arm]["color"], t), ARM[arm]["marker"], f"W = {_wlabel(w)}", low=low,
                      count="admitted")
        _place_low(ax, low)
        _style(ax)
        ax.set_xticks(sorted(sub["knowledge"].unique()))
        ax.set_title(f"{ARM[arm]['title']}, GF(2^{m}), g={g}", color=INK, fontsize=10)
        ax.set_ylabel(YLABEL, color=INK, fontsize=9)
        ax.set_xlabel(ARM[arm]["x"], color=INK, fontsize=9)
        ax.legend(loc="upper left" if arm == "keyless" else "upper right", fontsize=7.5, frameon=False, labelcolor=INK)
    return _save(fig, out_dir, f"s3_random_vs_knowledge_g{g}_m{m}", None)


def plot_w1(summary, g, out_dir):
    s = summary[(summary["width"] == 1) & (summary["policy"] == "random") & (summary["gen_size"] == g)]
    ms = sorted(s["field_bits"].unique())
    fig, axes = plt.subplots(len(ms), 2, figsize=(9.5, 3.2 * len(ms)), sharey=True, squeeze=False)
    for i, m in enumerate(ms):
        for j, arm in enumerate(ARM):
            ax = axes[i][j]
            c = s[(s["field_bits"] == m) & (s["arm"] == arm)].sort_values("knowledge")
            ks = _xs(c)
            _theory(ax, ks, [theory_admit(arm, "random", int(k), 1, g, 2 ** m) for k in ks], "theory")
            _measured(ax, c, ARM[arm]["color"], ARM[arm]["marker"], "measured", count="admitted")
            _style(ax)
            ax.set_xticks(sorted(c["knowledge"].unique()))
            ax.set_title(f"{ARM[arm]['title'].split(':')[0]}, GF(2^{m}), g={g}, 1 check", color=INK, fontsize=10)
            ax.set_xlabel(ARM[arm]["x"], color=INK, fontsize=9)
            if j == 0:
                ax.set_ylabel(YLABEL, color=INK, fontsize=9)
            if i == 0:
                ax.legend(loc="upper left" if arm == "keyless" else "upper right", fontsize=7.5, frameon=False, labelcolor=INK)
    return _save(fig, out_dir, f"s3_w1_random_g{g}", None)


METRICS = {"detection": "tag pollution detection probability", "success": "successful attack probability"}
KEYED_TS_SETS = ((1,), (1, 2, 3))   # keyed attackers shown (tags polluted); t = 1 is the strongest


def _keyless_rs(g):
    """Keyless observation levels shown: nothing seen, about half, all but one witness."""
    return sorted({0, (g - 1) // 2, g - 2})


def _params_text(s, g):
    """Plot parameters as one text block placed under the figure."""
    n, df = int(s["n_segments"].iloc[0]), int(s["data_fields"].iloc[0])
    trials = int(s["trials"].min())
    return (f"Parameters: generation size g = {g};  N = {n} segments (1 coefficient + {n - 1} data, {df} data symbols);  "
            f"checks per packet chosen by a receiver secret;  rejections remembered;  repair off (HD 0);\n"
            f"one forged packet, early strike;  tags of one random segment polluted;  {trials} trials per point, "
            f"95% Wilson CI;  dashed = theory.\n"
            f"Keyless: r = honest packets the attacker observed.  Keyed: t = MAC tags the attacker changes (leaked keys "
            f"only reproduce the honest tag, so they do not change a tags-only attack).")


def plot_vs_checks(summary, g, out_dir, metric="detection", keyed_ts=(1,)):
    """One panel per field, both arms on ONE axis: x = checks per packet (keyless witnesses, max g-1 / keyed tags,
    max g; the last point = check all), y = detection probability (1 - admit) or successful attack probability
    (admit). Keyless at a few observation levels r, keyed for each t in keyed_ts."""
    s = summary[(summary["gen_size"] == g) & ((summary["policy"] == "random") | (summary["width"] < 0))]
    ms = sorted(s["field_bits"].unique())
    det = metric == "detection"
    fig, axes = plt.subplots(1, len(ms), figsize=(4.2 * len(ms), 3.8), sharey=True, squeeze=False)
    rs = _keyless_rs(g)
    lines = ([("keyed", t, _shade(ARM["keyed"]["color"], sh), f"keyed, t = {t}")
              for t, sh in zip(keyed_ts, np.linspace(1.0, 0.5, len(keyed_ts)))]
             + [("keyless", r, _shade(ARM["keyless"]["color"], sh), f"keyless, r = {r}")
                for r, sh in zip(rs, np.linspace(1.0, 0.45, len(rs)))])
    for ax, m in zip(axes[0], ms):
        for arm, k, color, label in lines:
            c = s[(s["field_bits"] == m) & (s["arm"] == arm) & (s["knowledge"] == k)].copy()
            if c.empty:
                continue
            c["x"] = c["width"].where(c["width"] > 0, g - 1 if arm == "keyless" else g)
            c = c.sort_values("x")
            xs = c["x"].to_numpy()
            th = np.array([theory_admit(arm, "random", k, None if w < 0 else int(w), g, 2 ** m) for w in c["width"]])
            y, lo, hi = c["admit_rate"].to_numpy(), c["admit_lo"].to_numpy(), c["admit_hi"].to_numpy()
            if det:
                th, y, lo, hi = 1 - th, 1 - y, 1 - hi, 1 - lo
            ax.plot(xs, th, color=INK, linestyle=(0, (4, 3)), linewidth=0.9, zorder=2)
            ax.errorbar(xs, y, yerr=[np.clip(y - lo, 0, None), np.clip(hi - y, 0, None)], color=color,
                        marker=ARM[arm]["marker"], markersize=5, linewidth=2, capsize=2, zorder=3, label=label)
        _style(ax)
        ax.set_xticks(range(1, g + 1))
        ax.set_title(f"GF(2^{m}), g={g}", color=INK, fontsize=10)
        ax.set_xlabel("checks per packet  (keyless: witnesses, max g-1;  keyed: tags, max g)", color=INK, fontsize=8)
    axes[0][0].set_ylabel(METRICS[metric], color=INK, fontsize=9)
    handles, labels = axes[0][0].get_legend_handles_labels()
    handles.append(matplotlib.lines.Line2D([], [], color=INK, linestyle=(0, (4, 3)), linewidth=0.9))
    labels.append("theory")
    axes[0][0].legend(handles, labels, loc="lower right" if det else "upper right", fontsize=7, frameon=False,
                      labelcolor=INK)
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.text(0.01, 0.01, _params_text(s, g), ha="left", va="bottom", fontsize=7.5, color=INK, linespacing=1.5)
    name = f"s3_{metric}_vs_checks_g{g}_t{''.join(map(str, keyed_ts))}"
    for ext in ("png", "pdf"):
        fig.savefig(Path(out_dir) / f"{name}.{ext}", dpi=160)
    plt.close(fig)
    return Path(out_dir) / f"{name}.png"


def plot_footprint(summary, g, out_dir):
    """Does the NUMBER of changed tag symbols matter? Rows = checks W (1, 2, all), cols = field; x = tag symbols
    the attacker changes (keyless: bytes of the salt + g tag block, from the support sweep; keyed: t MAC tags, from
    the main sweep), y = successful attack probability. Keyless at a few r, keyed one line."""
    s = summary[(summary["gen_size"] == g) & ((summary["policy"] == "random") | (summary["width"] < 0))]
    sup = s[(s["arm"] == "keyless") & (s["support"] > 0)]
    keyed = s[(s["arm"] == "keyed") & (s["support"] < 0)]
    ms = sorted(sup["field_bits"].unique())
    ws = [w for w in (1, 2, -1) if w in set(sup["width"])]
    rs = _keyless_rs(g)
    fig, axes = plt.subplots(len(ws), len(ms), figsize=(4.2 * len(ms), 2.9 * len(ws)), sharey=True, sharex=True,
                             squeeze=False)
    for i, w in enumerate(ws):
        for j, m in enumerate(ms):
            ax = axes[i][j]
            series = [(keyed[(keyed["field_bits"] == m) & (keyed["width"] == w)], "keyed", None,
                       ARM["keyed"]["color"], "keyed (x = t MAC tags)")]
            series += [(sup[(sup["field_bits"] == m) & (sup["width"] == w) & (sup["knowledge"] == r)], "keyless", r,
                        _shade(ARM["keyless"]["color"], sh), f"keyless, r = {r} (x = tag-block bytes)")
                       for r, sh in zip(rs, np.linspace(1.0, 0.45, len(rs)))]
            for c, arm, r, color, label in series:
                if c.empty:
                    continue
                xcol = "knowledge" if arm == "keyed" else "support"
                c = c.sort_values(xcol)
                xs, y = c[xcol].to_numpy(), c["admit_rate"].to_numpy()
                wt = None if w < 0 else int(w)
                th = ([theory_admit("keyed", "random", int(t), wt, g, 2 ** m) for t in xs] if arm == "keyed" else
                      [theory_admit("keyless", "random", r, wt, g, 2 ** m, int(e)) for e in xs])
                ax.plot(xs, th, color=INK, linestyle=(0, (4, 3)), linewidth=0.9, zorder=2)
                ax.errorbar(xs, y, yerr=[np.clip(y - c["admit_lo"], 0, None), np.clip(c["admit_hi"] - y, 0, None)],
                            color=color, marker=ARM[arm]["marker"], markersize=5, linewidth=2, capsize=2, zorder=3,
                            label=label)
            _style(ax)
            ax.set_xticks(range(1, g + 2))
            ax.set_title(f"GF(2^{m}), g={g}, {'all' if w < 0 else w} check{'s' if w != 1 else ''} per packet",
                         color=INK, fontsize=9.5)
            if i == len(ws) - 1:
                ax.set_xlabel("tag symbols changed by the attacker", color=INK, fontsize=8.5)
            if j == 0:
                ax.set_ylabel("successful attack probability", color=INK, fontsize=9)
    handles, labels = axes[0][0].get_legend_handles_labels()
    handles.append(matplotlib.lines.Line2D([], [], color=INK, linestyle=(0, (4, 3)), linewidth=0.9))
    labels.append("theory")
    fig.legend(handles, labels, loc="upper center", ncol=len(labels), fontsize=7.5, frameon=False, labelcolor=INK,
               bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout(rect=(0, 0.09, 1, 0.96))
    n, df = int(s["n_segments"].iloc[0]), int(s["data_fields"].iloc[0])
    fig.text(0.01, 0.005,
             f"Parameters: generation size g = {g};  N = {n} segments (1 coefficient + {n - 1} data, {df} data symbols);  "
             f"checks chosen by a receiver secret;  rejections remembered;  repair off (HD 0);  one forged packet, "
             f"early strike;\n{int(sup['trials'].min())} trials per point, 95% Wilson CI;  dashed = theory.  "
             f"Keyless: the attacker changes x of the g+1 = {g + 1} tag-block bytes (salt + g tags) and stays valid "
             f"against the r packets it observed (needs x >= r+2;\nx = 1 breaks the self-check).  Keyed: the attacker "
             f"changes x of the g MAC tags.", ha="left", va="bottom", fontsize=7.5, color=INK, linespacing=1.5)
    name = f"s3_footprint_g{g}"
    for ext in ("png", "pdf"):
        fig.savefig(Path(out_dir) / f"{name}.{ext}", dpi=160)
    plt.close(fig)
    return Path(out_dir) / f"{name}.png"


NOISE_LABEL = {"keyed": "keyed HMAC", "keyless": "keyless HMAC"}


def _ber_label(ber):
    return f"{ber:.0e}".replace("e-0", "e-")


def plot_noise(summary, g, ber, out_dir):
    """Supervisor request 2026-10-08: random bit flips in the tag region instead of an attacker. One figure per
    BER, one panel per field: x = verifier packets (keyless) / keys (keyed) checked per packet, y = P(a packet
    with corrupted tags is admitted); keyed HMAC, keyless HMAC, theory (dashed)."""
    s = summary[(summary["gen_size"] == g) & (np.isclose(summary["ber"], ber))
                & ((summary["policy"] == "random") | (summary["width"] < 0))]
    ms = sorted(s["field_bits"].unique())
    fig, axes = plt.subplots(1, len(ms), figsize=(4.2 * len(ms), 3.6), sharey=True, squeeze=False)
    for ax, m in zip(axes[0], ms):
        for arm in ("keyed", "keyless"):
            c = s[(s["field_bits"] == m) & (s["arm"] == arm)].copy()
            if c.empty:
                continue
            c["x"] = c["width"].where(c["width"] > 0, g - 1 if arm == "keyless" else g)
            c = c.sort_values("x")
            xs, y = c["x"].to_numpy(), c["admit_rate"].to_numpy()
            ax.plot(xs, c["theory_admit"].to_numpy(), color=INK, linestyle=(0, (4, 3)), linewidth=0.9, zorder=4)
            ax.errorbar(xs, y, yerr=[np.clip(y - c["admit_lo"], 0, None), np.clip(c["admit_hi"] - y, 0, None)],
                        color=ARM[arm]["color"], marker=ARM[arm]["marker"], markersize=5, linewidth=2, capsize=2,
                        zorder=3, label=NOISE_LABEL[arm])
        _style(ax)
        ax.set_xticks(range(1, g + 1))
        ax.set_title(f"GF(2^{m}), g={g}, BER = {_ber_label(ber)}", color=INK, fontsize=10)
        ax.set_xlabel("verifier packets (keyless) / keys (keyed) per packet", color=INK, fontsize=8.5)
    axes[0][0].set_ylabel("successful attack probability", color=INK, fontsize=9)
    handles, labels = axes[0][0].get_legend_handles_labels()
    handles.append(matplotlib.lines.Line2D([], [], color=INK, linestyle=(0, (4, 3)), linewidth=0.9))
    labels.append("theory")
    axes[0][0].legend(handles, labels, loc="upper right", fontsize=7.5, frameon=False, labelcolor=INK)
    fig.tight_layout(rect=(0, 0.22, 1, 1))
    n, df = int(s["n_segments"].iloc[0]), int(s["data_fields"].iloc[0])
    sc = s[s["arm"] == "keyless"].groupby("field_bits")[["selfcheck_rate", "theory_selfcheck"]].mean()
    sc_txt = ";  ".join(f"GF(2^{m}) {100 * r.selfcheck_rate:.2f}% (theory {100 * r.theory_selfcheck:.2f}%)"
                        for m, r in sc.iterrows())
    fig.text(0.01, 0.01,
             f"Parameters: generation size g = {g};  N = {n} segments (1 coefficient + {n - 1} data, {df} data "
             f"symbols);  repair off (HD 0);  rejections remembered.\n"
             f"Noise: every tag-region bit of every segment (keyless: salt + g tags, keyed: g MAC tags) flips with "
             f"probability BER = {_ber_label(ber)};  only packets with >= 1 flipped bit are simulated.\n"
             f"Checked verifier packets / keys chosen by a receiver secret (keyless max g-1 = {g - 1}, keyed max "
             f"g = {g});  {int(s['trials'].min())} corrupted packets per point, 95% Wilson CI;  dashed = theory.\n"
             f"Corrupted keyless packets surviving the self-check: {sc_txt}.",
             ha="left", va="bottom", fontsize=7.2, color=INK, linespacing=1.5)
    name = f"s4_noise_ber{_ber_label(ber)}_g{g}"
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(Path(out_dir) / f"{name}.{ext}", dpi=160)
    plt.close(fig)
    return Path(out_dir) / f"{name}.png"


def plot_noise_vs_ber(summary, g, out_dir):
    """Random tag-region bit flips: x = BER (log), y = P(corrupted packet admitted) (log), one panel per field.
    Keyed / keyless at 1 check and at g-1 checks (keyless: all witnesses). Theory = dense dashed curves; measured
    = markers with 95% CI; a cell with 0 admits is drawn as a hollow 'v' at its 95% upper bound."""
    s = summary[(summary["gen_size"] == g) & (summary["ber"] > 0)
                & ((summary["policy"] == "random") | (summary["width"] < 0))].copy()
    s["checks"] = s["width"].where(s["width"] > 0, np.where(s["arm"] == "keyless", g - 1, g))
    ms = sorted(s["field_bits"].unique())
    grid = np.logspace(np.log10(s["ber"].min()), np.log10(0.5), 120)
    series = [("keyed", 1, 1.0), ("keyless", 1, 1.0), ("keyed", g - 1, 0.5), ("keyless", g - 1, 0.5)]
    fig, axes = plt.subplots(1, len(ms), figsize=(4.4 * len(ms), 3.9), sharey=True, squeeze=False)
    floor = 1e-7
    for ax, m in zip(axes[0], ms):
        for arm, w, shade in series:
            color = _shade(ARM[arm]["color"], shade)
            wt = None if (arm == "keyless" and w == g - 1) else w
            th = np.array([theory_noise(arm, wt, g, m, int(s["n_segments"].iloc[0]), b) for b in grid])
            ax.plot(grid, np.clip(th, floor / 10, None), color=color, linestyle=(0, (4, 3)), linewidth=1.1, zorder=2)
            c = s[(s["field_bits"] == m) & (s["arm"] == arm) & (s["checks"] == w)].sort_values("ber")
            if c.empty:
                continue
            hit = c[c["admitted"] > 0]
            y = hit["admit_rate"].to_numpy()
            ax.errorbar(hit["ber"], y, yerr=[np.clip(y - hit["admit_lo"], 0, None), np.clip(hit["admit_hi"] - y, 0, None)],
                        color=color, marker=ARM[arm]["marker"], markersize=5, linewidth=0, elinewidth=1.2, capsize=2,
                        zorder=3, label=f"{NOISE_LABEL[arm]}, {w} check{'s' if w > 1 else ''}")
            zero = c[c["admitted"] == 0]
            ax.plot(zero["ber"], zero["admit_hi"], linestyle="none", marker="v", markersize=5, markerfacecolor="none",
                    markeredgecolor=color, zorder=3)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_ylim(floor, 1.5)
        ax.grid(True, which="major", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=INK_MUTED, labelcolor=INK, labelsize=8)
        ax.set_title(f"GF(2^{m}), g={g}", color=INK, fontsize=10)
        ax.set_xlabel("bit error rate in the tag region", color=INK, fontsize=8.5)
    axes[0][0].set_ylabel("successful attack probability", color=INK, fontsize=9)
    handles, labels = axes[0][0].get_legend_handles_labels()
    handles += [matplotlib.lines.Line2D([], [], color=INK, linestyle=(0, (4, 3)), linewidth=1.1),
                matplotlib.lines.Line2D([], [], color=INK, linestyle="none", marker="v", markerfacecolor="none")]
    labels += ["theory", "0 admitted: 95% upper bound"]
    fig.legend(handles, labels, loc="upper center", ncol=len(labels), fontsize=7.5, frameon=False, labelcolor=INK,
               bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout(rect=(0, 0.12, 1, 0.93))
    n, df = int(s["n_segments"].iloc[0]), int(s["data_fields"].iloc[0])
    fig.text(0.01, 0.01,
             f"Parameters: generation size g = {g};  N = {n} segments (1 coefficient + {n - 1} data, {df} data symbols);  "
             f"repair off (HD 0);  rejections remembered;  checked verifier packets / keys chosen by a receiver secret.\n"
             f"Every tag-region bit of every segment flips with probability BER;  only packets with >= 1 flipped bit are "
             f"simulated;  {int(s['trials'].min())} corrupted packets per point, 95% Wilson CI.\n"
             f"Keyless {g - 1} checks = all witnesses;  keyed {g - 1} checks = {g - 1} of the {g} MAC keys.  "
             f"A measured 0 only bounds the rate below the hollow marker (~{100 * wilson(0, int(s['trials'].min()))[1]:.2f}%); "
             f"smaller theory values are not resolved by the simulation.",
             ha="left", va="bottom", fontsize=7.5, color=INK, linespacing=1.5)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    name = f"s4_noise_vs_ber_g{g}"
    for ext in ("png", "pdf"):
        fig.savefig(Path(out_dir) / f"{name}.{ext}", dpi=160)
    plt.close(fig)
    return Path(out_dir) / f"{name}.png"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", default=[str(_ROOT / "logs" / "tag_pollution_attack" / "g*"),
                                              str(_ROOT / "logs" / "tag_pollution_attack" / "support_g*"),
                                              str(_ROOT / "logs" / "tag_pollution_attack" / "noise_g*")])
    ap.add_argument("--out", default=str(_ROOT / "logs" / "tag_pollution_attack" / "plots"))
    a = ap.parse_args(argv)
    s = load(a.runs)
    main_s = s[(s["support"] < 0) & (s["ber"] == 0)]   # footprint / noise rows feed their own plots
    for g in sorted(main_s["gen_size"].unique()):
        for m in sorted(main_s[main_s["gen_size"] == g]["field_bits"].unique()):
            print("wrote", plot_random_grid(main_s, m, g, a.out))
        print("wrote", plot_w1(main_s, g, a.out))
        for metric in METRICS:
            for ts in KEYED_TS_SETS:
                print("wrote", plot_vs_checks(main_s, g, a.out, metric, ts))
        if (s[(s["gen_size"] == g)]["support"] > 0).any():
            print("wrote", plot_footprint(s[s["ber"] == 0], g, a.out))
    noise = s[s["ber"] > 0]
    for g in sorted(noise["gen_size"].unique()):
        for ber in sorted(noise[noise["gen_size"] == g]["ber"].unique()):
            print("wrote", plot_noise(noise, g, ber, a.out))
        print("wrote", plot_noise_vs_ber(noise, g, a.out))


if __name__ == "__main__":
    main()
