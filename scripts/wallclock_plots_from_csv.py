r"""Wall-clock comparison keyless vs keyed (2026-10-09, meeting request): the R2/R3 recovery study and
the S2/S3 security sims, LINEAR y axes throughout. One function per plot.

Inputs
  recovery, isolated   <iso root>/iso_w/ (default logs/wallclock/recovery_rerun = current-code rerun; was <scaling root>)/*_payload_errors/raw_trials.csv (isolated_recovery_sim schema v4):
                       recovery_time_s = wall-clock of ONE recovery call (6 corrupted targets, both arms on the
                       identical corruption, measured back to back per seed inside the R2/R3 sweep, 6 workers).
                       config arc_only_a (payload errors, payload repair), HD 2, budget 20000.
  recovery, end-to-end <scaling root>/prod/*data_payload_payload/raw_trials.csv (pareto_sweep schema v2):
                       wall_time_s = one generation, send-until-decodable (admit + repair + decode).
                       Keyless and keyed ran as separate jobs (same machine, same 6 workers).
  security             logs/wallclock/security_bench/raw_timings.csv (simulation/security_wallclock_bench.py,
                       single process, idle machine).

BER axes are categorical (the 7 grid points, evenly spaced); y is linear everywhere. Colour = arm
(keyless #588157, keyed #3d405b, as in the scaling plots). Error bars = 95 % CI over seeds.

CLI (PowerShell; memory how_to_run_sims):
  $env:LOG_FOLDER="./logs"; $env:PYTHONPATH="."
  & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/wallclock_plots_from_csv.py
"""
import argparse
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

from scripts.scaling_plots_from_csv import ARM as _ARM, GRID, INK, INK_MUTED, _L_shades

# Thesis/slide variant (user 2026-10-09): short arm names, no caption under the figure (the specs go in the slide text).
ARM = {a: {**v, "label": a} for a, v in _ARM.items()}


def _save(fig, out_dir, name, caption=None):
    """caption is accepted (kept as documentation at each call site) but not drawn."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(out_dir / f"{name}.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out_dir / f"{name}.png"

SCALING_ROOT = _ROOT / "logs" / "scaling_acr"
# iso_w rerun on current code (2026-10-09; the R2/R3 iso_w keyed timings predate keyed fix f63b1be)
ISO_ROOT = _ROOT / "logs" / "wallclock" / "recovery_rerun"
SECURITY_CSV = _ROOT / "logs" / "wallclock" / "security_bench" / "raw_timings.csv"
OUT_DIR = _ROOT / "logs" / "wallclock" / "plots"
L50 = {100: 3, 300: 7, 1000: 21}          # df -> N with 50-byte data segments (one layout per payload size)
BERS = (1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2)
ARMS = ("keyless", "keyed")
Z = 1.96


# --------------------------------------------------------------------------- #
# loading
def _concat(pattern) -> pd.DataFrame:
    paths = sorted(glob.glob(str(pattern)))
    if not paths:
        raise FileNotFoundError(pattern)
    return pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)


def load_recovery(root=SCALING_ROOT, config="arc_only_a", span="payload", hd=2) -> pd.DataFrame:
    """Per-seed rows (both arms), one isolated-harness config. N = segments incl. the coeff segment."""
    raw = _concat(Path(root) / "iso_w" / "*_payload_errors" / "raw_trials.csv")
    raw = raw[(raw["config"] == config) & (raw["repair_span"] == span) & (raw["max_combined_hd"] == hd)].copy()
    raw = raw.drop_duplicates(subset=["data_fields", "num_data_segments", "arm", "W", "bit_error_rate", "seed"])
    raw["N"] = raw["num_data_segments"] + 1
    raw["L"] = raw["data_fields"] // raw["num_data_segments"]
    raw["time_ms"] = raw["recovery_time_s"] * 1e3
    return raw


def load_end_to_end(root=SCALING_ROOT, scope="data_payload_payload") -> pd.DataFrame:
    raw = _concat(Path(root) / "prod" / f"*_{scope}" / "raw_trials.csv")
    raw = raw[raw["strategy"] == "acr_only"].copy()
    raw["N"] = raw["n_segments"]
    raw["L"] = raw["data_fields"] // (raw["N"] - 1)
    return raw


def load_security(path=SECURITY_CSV) -> pd.DataFrame:
    return pd.read_csv(path)


def _mean_ci(v) -> tuple[float, float]:
    v = np.asarray(v, float)
    return v.mean(), (Z * v.std(ddof=1) / np.sqrt(len(v)) if len(v) > 1 else 0.0)


def _paired_ratio(a, b, n_boot=2000, seed=0) -> tuple[float, float, float]:
    """mean(b)/mean(a) with a paired bootstrap 95 % interval (resample seeds)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), size=(n_boot, len(a)))
    boot = b[idx].mean(axis=1) / a[idx].mean(axis=1)
    return b.mean() / a.mean(), *np.percentile(boot, [2.5, 97.5])


def _paired(raw, keys) -> pd.DataFrame:
    """keyless/keyed time_ms side by side per seed (inner join: only seeds both arms ran)."""
    p = raw.pivot_table(index=keys + ["seed"], columns="arm", values="time_ms").dropna().reset_index()
    return p


# --------------------------------------------------------------------------- #
# shared mechanics
def _style(ax):
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED, labelcolor=INK, labelsize=8)
    ax.set_ylim(bottom=0)


def _ber_label(b) -> str:
    m, e = f"{b:.0e}".split("e")
    return f"{m}e{int(e)}"


def _bars(ax, xs, groups, width=0.38, labels=True, loc="upper left"):
    """groups = {arm: (means, cis, hatched_mask)}; keyless left, keyed right."""
    for k, arm in enumerate(ARMS):
        if arm not in groups:
            continue
        means, cis, hatched = groups[arm]
        pos = np.asarray(xs, float) + (k - 0.5) * width
        for x, m, c, h in zip(pos, means, cis, hatched):
            if not np.isfinite(m):
                continue
            ax.bar(x, m, width, color="white" if h else ARM[arm]["color"], edgecolor=ARM[arm]["color"],
                   linewidth=1.2, hatch="////" if h else None, zorder=2)
            ax.errorbar(x, m, yerr=c, fmt="none", ecolor=INK_MUTED, elinewidth=0.9, capsize=2, zorder=3)
    if labels:
        from matplotlib.patches import Patch
        ax.legend(handles=[Patch(color=ARM[a]["color"], label=ARM[a]["label"]) for a in ARMS if a in groups],
                  fontsize=7.5, frameon=False, labelcolor=INK, loc=loc)


# --------------------------------------------------------------------------- #
# recovery (isolated harness)
def plot_recovery_time_L50(raw, out_dir=OUT_DIR, W=6, layouts=L50, bers=BERS, suffix=""):
    """Top: mean wall-clock of one recovery call vs BER (bars, linear). Bottom: keyed / keyless time ratio
    (paired bootstrap CI), 1 = equally fast. One column per payload size, all at L = 50 B segments."""
    fig, axes = plt.subplots(2, len(layouts), figsize=(4.4 * len(layouts), 5.6), squeeze=False,
                             gridspec_kw={"height_ratios": [2.2, 1]})
    rows = []
    for j, (df, n) in enumerate(layouts.items()):
        sub = raw[(raw["W"] == W) & (raw["data_fields"] == df) & (raw["N"] == n)]
        pr = _paired(sub, ["bit_error_rate"])
        groups, ratios = {a: ([], [], []) for a in ARMS}, []
        for b in bers:
            g = pr[pr["bit_error_rate"] == b]
            for arm in ARMS:
                m, c = _mean_ci(g[arm])
                groups[arm][0].append(m)
                groups[arm][1].append(c)
                groups[arm][2].append(False)
            r = _paired_ratio(g["keyless"], g["keyed"])
            ratios.append(r)
            rows.append(dict(data_fields=df, N=n, L=df // (n - 1), W=W, bit_error_rate=b, seeds=len(g),
                             keyless_ms=groups["keyless"][0][-1], keyed_ms=groups["keyed"][0][-1],
                             keyed_over_keyless=r[0], ratio_lo=r[1], ratio_hi=r[2]))
        xs = np.arange(len(bers))
        ax = axes[0][j]
        _bars(ax, xs, groups, labels=(j == 0))
        _style(ax)
        ax.set_xticks(xs, [])
        ax.set_title(f"payload {df} B, N={n} (L={df // (n - 1)})", color=INK, fontsize=10)
        if j == 0:
            ax.set_ylabel("ms per recovery call", color=INK, fontsize=9)
        ax2 = axes[1][j]
        r = np.array(ratios)
        ax2.axhline(1.0, color=INK_MUTED, linewidth=1, linestyle=":")
        ax2.errorbar(xs, r[:, 0], yerr=[r[:, 0] - r[:, 1], r[:, 2] - r[:, 0]], fmt="o", color=ARM["keyed"]["color"],
                     markersize=4.5, elinewidth=1, capsize=2)
        _style(ax2)
        ax2.set_ylim(0, max(2.0, float(np.nanmax(r[:, 2])) * 1.08))
        ax2.set_xticks(xs, [_ber_label(b) for b in bers])
        ax2.set_xlabel("bit error rate", color=INK, fontsize=9)
        if j == 0:
            ax2.set_ylabel("keyed / keyless\ntime ratio", color=INK, fontsize=9)
    path = _save(fig, out_dir, f"rec_time_vs_ber_L50_W{W}{suffix}",
                 f"Isolated recovery harness (rerun on current code), ACR-only, payload errors, W={W}, HD 2, g=6, GF(2^8). "
                 "Mean wall-clock of one recovery call over seeds (95% CI); ratio = mean(keyed)/mean(keyless), "
                 "paired bootstrap CI. Pure Python, both arms same field code.")
    return path, pd.DataFrame(rows)


def plot_recovery_time_per_packet_L50(raw, out_dir=OUT_DIR, W=6, layouts=L50, bers=BERS, suffix="", min_packets=20):
    """Recovery wall-clock per ACTUALLY corrupted target packet vs BER (bars, linear), L = 50 B layouts.
    Per cell: sum(call time) / sum(corrupted targets) over the seeds whose call had >= 1 corrupted target. Calls with
    nothing to repair are excluded (their fixed setup cost would otherwise be divided by ~0 packets at low BER); their
    mean time is reported in the caption instead. CI = bootstrap over seeds. The corrupted count is identical in both arms (paired injection). Hatched =
    fewer than `min_packets` corrupted packets in the cell (noisy)."""
    fig, axes = plt.subplots(1, len(layouts), figsize=(4.4 * len(layouts), 3.8), squeeze=False)
    rows, rng, idle = [], np.random.default_rng(0), {}
    for j, (df, n) in enumerate(layouts.items()):
        ax = axes[0][j]
        sub = raw[(raw["W"] == W) & (raw["data_fields"] == df) & (raw["N"] == n)]
        t = sub.pivot_table(index=["bit_error_rate", "seed"], columns="arm", values="time_ms").dropna()
        k = sub[sub["arm"] == "keyless"].set_index(["bit_error_rate", "seed"])["n_info_corrupted"]
        groups = {a: ([], [], []) for a in ARMS}
        for b in bers:
            tb = t.loc[b]
            kb = k.loc[b].reindex(tb.index).to_numpy(float)
            idle.setdefault(df, []).extend(tb.loc[kb == 0, ["keyless", "keyed"]].to_numpy(float).ravel())
            tb, kb = tb[kb > 0], kb[kb > 0]
            total = kb.sum()
            for arm in ARMS:
                x = tb[arm].to_numpy(float)
                if total == 0:
                    m, c = np.nan, 0.0
                else:
                    m = x.sum() / total
                    idx = rng.integers(0, len(x), size=(2000, len(x)))
                    den = kb[idx].sum(axis=1)
                    boot = x[idx].sum(axis=1)[den > 0] / den[den > 0]
                    c = (np.percentile(boot, 97.5) - np.percentile(boot, 2.5)) / 2
                groups[arm][0].append(m)
                groups[arm][1].append(c)
                groups[arm][2].append(total < min_packets)
                rows.append(dict(data_fields=df, N=n, W=W, arm=arm, bit_error_rate=b, seeds=len(x),
                                 corrupted_packets=int(total), ms_per_corrupted_packet=m))
        xs = np.arange(len(bers))
        _bars(ax, xs, groups, labels=(j == 0), loc="upper center")
        _style(ax)
        ax.set_xticks(xs, [_ber_label(b) for b in bers])
        ax.set_title(f"payload {df} B, N={n} (L={df // (n - 1)})", color=INK, fontsize=10)
        ax.set_xlabel("bit error rate", color=INK, fontsize=9)
        if j == 0:
            ax.set_ylabel("ms per corrupted packet", color=INK, fontsize=9)
    path = _save(fig, out_dir, f"rec_time_per_packet_L50_W{W}{suffix}",
                 f"Isolated recovery harness (rerun on current code), ACR-only, payload errors, W={W}, HD 2, g=6, GF(2^8). "
                 "Recovery wall-clock divided by the number of target packets that actually got bit errors, over calls with "
                 "at least one corrupted target; 95% bootstrap CI. Hatched = fewer than "
                 f"{min_packets} corrupted packets. Calls with nothing to repair (excluded) cost a fixed "
                 + " / ".join(f"{np.mean(v):.2f}" for v in idle.values()) + " ms ("
                 + " / ".join(f"{d} B" for d in idle) + ").")
    return path, pd.DataFrame(rows)


def plot_recovery_ratio_all_layouts(raw, out_dir=OUT_DIR, W=6, bers=BERS, suffix=""):
    """keyed / keyless wall-clock ratio vs BER, one line per segment count, one panel per payload size."""
    dfs = sorted(raw["data_fields"].unique())
    fig, axes = plt.subplots(1, len(dfs), figsize=(4.4 * len(dfs), 3.4), sharey=True, squeeze=False)
    xs = np.arange(len(bers))
    for j, df in enumerate(dfs):
        ax = axes[0][j]
        sub = raw[(raw["W"] == W) & (raw["data_fields"] == df)]
        shades = _L_shades(sub["L"].unique(), "keyed")
        ax.axhline(1.0, color=INK_MUTED, linewidth=1, linestyle=":")
        for (n, L), g in sub.groupby(["N", "L"]):
            pr = _paired(g, ["bit_error_rate"])
            r = [pr[pr["bit_error_rate"] == b] for b in bers]
            ys = [_paired_ratio(x["keyless"], x["keyed"])[0] if len(x) else np.nan for x in r]
            ax.plot(xs, ys, marker="s", color=shades[L], linewidth=1.8, markersize=4, label=f"N={n} (L={L})")
        _style(ax)
        ax.set_xticks(xs, [_ber_label(b) for b in bers])
        ax.set_title(f"payload {df} B", color=INK, fontsize=10)
        ax.set_xlabel("bit error rate", color=INK, fontsize=9)
        ax.legend(fontsize=7, frameon=False, labelcolor=INK, loc="upper left")
        if j == 0:
            ax.set_ylabel("keyed / keyless wall-clock", color=INK, fontsize=9)
    for ax in axes[0]:
        ax.set_ylim(0, 2.2)
    return _save(fig, out_dir, f"rec_time_ratio_all_layouts_W{W}{suffix}",
                 f"Isolated recovery harness (rerun on current code), ACR-only, payload errors, W={W}, HD 2. Ratio of mean recovery-call "
                 "wall-clock, keyed over keyless (>1 = keyed slower). Dotted line = equal.")


def plot_recovery_time_vs_N(raw, out_dir=OUT_DIR, W=6, bers=(1e-3, 3e-3)):
    """Recovery wall-clock vs segment count at fixed BER (bars, linear): segmentation vs arm."""
    dfs = sorted(raw["data_fields"].unique())
    fig, axes = plt.subplots(len(bers), len(dfs), figsize=(4.4 * len(dfs), 3.0 * len(bers)), squeeze=False)
    for i, b in enumerate(bers):
        for j, df in enumerate(dfs):
            ax = axes[i][j]
            sub = raw[(raw["W"] == W) & (raw["data_fields"] == df) & (raw["bit_error_rate"] == b)]
            pr = _paired(sub, ["N", "L"])
            layouts = sorted(pr[["N", "L"]].drop_duplicates().itertuples(index=False))
            groups = {a: ([], [], []) for a in ARMS}
            for n, L in layouts:
                g = pr[pr["N"] == n]
                for arm in ARMS:
                    m, c = _mean_ci(g[arm])
                    groups[arm][0].append(m)
                    groups[arm][1].append(c)
                    groups[arm][2].append(False)
            xs = np.arange(len(layouts))
            _bars(ax, xs, groups, labels=(i == 0 and j == 0), loc="upper right")
            _style(ax)
            ax.set_xticks(xs, [f"N={n}\nL={L}" for n, L in layouts])
            ax.set_title(f"payload {df} B, BER {_ber_label(b)}", color=INK, fontsize=10)
            if j == 0:
                ax.set_ylabel("ms per recovery call", color=INK, fontsize=9)
    return _save(fig, out_dir, f"rec_time_vs_N_W{W}",
                 f"Isolated recovery harness (rerun on current code), ACR-only, payload errors, W={W}, HD 2, g=6, GF(2^8): mean wall-clock "
                 "of one recovery call (6 corrupted packets) per segment layout, 95% CI. Shorter segments = less search.")


def plot_end_to_end_time_L50(e2e, out_dir=OUT_DIR, layouts=L50, bers=BERS[:6]):
    """End-to-end wall-clock per DECODED generation (send-until-decodable) vs BER, L = 50 B layouts.
    Hatched = fewer than all trials decoded in that arm; missing bar = nothing decoded."""
    fig, axes = plt.subplots(1, len(layouts), figsize=(4.4 * len(layouts), 3.6), squeeze=False)
    rows = []
    for j, (df, n) in enumerate(layouts.items()):
        ax = axes[0][j]
        sub = e2e[(e2e["data_fields"] == df) & (e2e["N"] == n)]
        groups = {a: ([], [], []) for a in ARMS}
        for b in bers:
            for arm in ARMS:
                g = sub[(sub["arm"] == arm) & (sub["bit_error_rate"] == b)]
                ok = g[g["decoded"].astype(bool)]
                m, c = _mean_ci(ok["wall_time_s"]) if len(ok) else (np.nan, 0.0)
                groups[arm][0].append(m)
                groups[arm][1].append(c)
                groups[arm][2].append(0 < len(ok) < len(g))
                rows.append(dict(data_fields=df, N=n, arm=arm, bit_error_rate=b, trials=len(g), decoded=len(ok),
                                 mean_wall_s_decoded=m))
        xs = np.arange(len(bers))
        _bars(ax, xs, groups, labels=(j == 0))
        _style(ax)
        ax.set_xticks(xs, [_ber_label(b) for b in bers])
        ax.set_title(f"payload {df} B, N={n} (L={df // (n - 1)})", color=INK, fontsize=10)
        ax.set_xlabel("bit error rate", color=INK, fontsize=9)
        if j == 0:
            ax.set_ylabel("s per decoded generation", color=INK, fontsize=9)
    path = _save(fig, out_dir, "e2e_time_vs_ber_L50",
                 "End-to-end (R2/R3 production runs, keyed pre-fix f63b1be, acr_only, payload errors, g=6, GF(2^8), 48-packet cap): mean wall-clock "
                 "of a decoded generation (admit + repair + decode), 95% CI. Hatched = not every trial decoded; no bar = none "
                 "decoded. Arms ran as separate jobs on the same machine.")
    return path, pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# security (benchmark)
def _security_lines(ax, sec, measure, x_kind_by_arm, scale=1.0):
    for arm in ARMS:
        g = sec[(sec["measure"] == measure) & (sec["arm"] == arm) & (sec["x_kind"] == x_kind_by_arm[arm])]
        stats = g.groupby("x")["time_us"].apply(lambda v: _mean_ci(v * scale))
        xs = np.array(stats.index, float)
        ys = np.array([s[0] for s in stats])
        es = np.array([s[1] for s in stats])
        ax.errorbar(xs, ys, yerr=es, color=ARM[arm]["color"], linestyle=ARM[arm]["ls"], marker=ARM[arm]["marker"],
                    linewidth=2, markersize=5, capsize=2, label=ARM[arm]["label"])


def plot_security_receiver(sec, measure="verify", out_dir=OUT_DIR, m=8, g=6, dfs=(12, 100, 1000)):
    """Receiver wall-clock vs checks per packet, one panel per payload size (linear)."""
    fig, axes = plt.subplots(1, len(dfs), figsize=(4.0 * len(dfs), 3.4), squeeze=False)
    sub = sec[(sec["field_bits"] == m) & (sec["gen_size"] == g)]
    unit, scale = ("ms", 1e-3) if measure == "admit" else ("µs", 1.0)
    for j, df in enumerate(dfs):
        ax = axes[0][j]
        _security_lines(ax, sub[sub["data_fields"] == df], measure, {"keyless": "checks", "keyed": "checks"}, scale)
        _style(ax)
        ax.set_xticks(range(1, g + 1))
        ax.set_title(f"payload {df} B" + (" (S2/S3 setting)" if df == 12 else ""), color=INK, fontsize=10)
        ax.set_xlabel("checks per packet W", color=INK, fontsize=9)
        if j == 0:
            ax.set_ylabel(f"{unit} per packet" if measure == "verify" else f"{unit} per admit call", color=INK, fontsize=9)
            ax.legend(fontsize=7.5, frameon=False, labelcolor=INK, loc="lower right" if measure == "admit" else "upper left")
    what = ("verification of one honest packet (accept path = full cost): keyless self-check + W witness inner "
            "products per segment, keyed W MAC tags per segment" if measure == "verify" else
            "production admit call on an all-honest pool of g+1 packets, S2/S3 receiver config (random witness/key "
            "subset, sticky, no repair); keyless builds the full pairwise agreement matrix (independent of W)")
    return _save(fig, out_dir, f"sec_{measure}_time_vs_checks_g{g}_m{m}",
                 f"Security wall-clock benchmark, GF(2^{m}), g={g}, N=2: {what}. Mean over 20 paired seeds, 95% CI. "
                 "Single process, pure Python, op-counting field as in the sims.")


def plot_security_attacker(sec, out_dir=OUT_DIR, m=8, g=6, df=12):
    """Attacker wall-clock per forged packet vs knowledge: S2 coeff forger, S3 tag polluter (linear)."""
    sub = sec[(sec["field_bits"] == m) & (sec["gen_size"] == g) & (sec["data_fields"] == df)]
    panels = [("forge_s2", "S2 forger (coefficient segment)", {"keyless": "observed_packets", "keyed": "leaked_keys"},
               "knowledge: keyless r observed packets / keyed k leaked keys"),
              ("forge_s3", "S3 tag polluter (one tag block)", {"keyless": "observed_packets", "keyed": "polluted_tags"},
               "keyless r observed packets / keyed t polluted tags")]
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.4), squeeze=False)
    for j, (measure, title, kinds, xlabel) in enumerate(panels):
        ax = axes[0][j]
        _security_lines(ax, sub, measure, kinds)
        _style(ax)
        ax.set_xticks(range(0, g + 1))
        ax.set_title(title, color=INK, fontsize=10)
        ax.set_xlabel(xlabel, color=INK, fontsize=9)
        if j == 0:
            ax.set_ylabel("µs per forged packet", color=INK, fontsize=9)
            ax.legend(fontsize=7.5, frameon=False, labelcolor=INK, loc="upper left")
    return _save(fig, out_dir, f"sec_attacker_time_g{g}_m{m}",
                 f"Security wall-clock benchmark, GF(2^{m}), g={g}, N=2, payload {df} B (forgers touch only the coefficient "
                 "segment / one tag block, so payload size does not matter). Mean over 20 paired seeds, 95% CI.")


def security_summary(sec) -> pd.DataFrame:
    rows = []
    for k, g in sec.groupby(["measure", "arm", "field_bits", "gen_size", "data_fields", "x_kind", "x"]):
        m, c = _mean_ci(g["time_us"])
        rows.append(dict(zip(["measure", "arm", "field_bits", "gen_size", "data_fields", "x_kind", "x"], k),
                         seeds=len(g), mean_us=m, ci95_us=c, mul_per_call=g["mul_per_call"].mean(),
                         ns_per_mul=1e3 * m / g["mul_per_call"].mean() if g["mul_per_call"].mean() else np.nan,
                         all_ok=int(g["ok"].all())))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
def plot_all(out_dir=OUT_DIR, scaling_root=SCALING_ROOT, security_csv=SECURITY_CSV, iso_root=ISO_ROOT):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = load_recovery(iso_root)
    for W in (6, 1):
        p, summ = plot_recovery_time_L50(raw, out_dir, W=W)
        print(plot_recovery_time_L50(raw, out_dir, W=W, bers=BERS[:-1], suffix="_no1e-2")[0])  # low BERs readable
        p, summ = plot_recovery_time_per_packet_L50(raw, out_dir, W=W)
        summ.to_csv(out_dir / f"recovery_time_per_packet_L50_W{W}.csv", index=False)
        print(p)
        print(plot_recovery_time_per_packet_L50(raw, out_dir, W=W, bers=BERS[:-1], suffix="_no1e-2")[0])
        summ.to_csv(out_dir / f"recovery_time_L50_W{W}.csv", index=False)
        print(p)
        print(plot_recovery_ratio_all_layouts(raw, out_dir, W=W))
        print(plot_recovery_ratio_all_layouts(raw, out_dir, W=W, bers=BERS[:-1], suffix="_no1e-2"))
    print(plot_recovery_time_vs_N(raw, out_dir))
    p, summ = plot_end_to_end_time_L50(load_end_to_end(scaling_root), out_dir)
    summ.to_csv(out_dir / "e2e_time_L50.csv", index=False)
    print(p)
    if Path(security_csv).exists():
        sec = load_security(security_csv)
        security_summary(sec).to_csv(out_dir / "security_summary.csv", index=False)
        for measure in ("verify", "admit"):
            print(plot_security_receiver(sec, measure, out_dir))
        print(plot_security_attacker(sec, out_dir))
        print(plot_security_attacker(sec, out_dir, g=4))
    else:
        print(f"no security timings at {security_csv} -- run simulation/security_wallclock_bench.py first")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--scaling-root", type=Path, default=SCALING_ROOT)
    ap.add_argument("--security-csv", type=Path, default=SECURITY_CSV)
    ap.add_argument("--iso-root", type=Path, default=ISO_ROOT, help="root holding iso_w/ (recovery timings)")
    args = ap.parse_args(argv)
    plot_all(args.out, args.scaling_root, args.security_csv, args.iso_root)


if __name__ == "__main__":
    main()
