"""Pool knowledge_attack sweep CSVs (ticket 17 Part B) and (re)plot from them.

Reads raw_trials.csv from one or more run dirs (simulation/knowledge_attack_sim.py --sweep),
pools every trial, recomputes per-cell counts / rates / Wilson CIs on the union (never
averages per-run rates), and draws:
  silent_vs_u.png         silent-decode rate vs u (production receiver, repair hd=1) -- F2, the main figure
  oracle_vs_u.png         strict-oracle pass rate vs u (tag strength alone) with q^-u theory
  repair_effect_keyed.png keyed admit rate with repair (hd=1) vs without (hd=0) -- only if hd=0 cells exist
  attacker_work_vs_u.png  attacker field muls per forgery vs u -- F6
  summary.csv             pooled per-cell table
u = verification constraints the attacker cannot compute (keyless g-1-r, keyed g-k). Rates
are drawn on a log axis; a cell with ZERO events is drawn as a hollow down-triangle at the
rule-of-3 upper bound 3/n instead of being dropped. Dashed = q^-u for that panel's field;
dotted = keyed repair-corrected theory; faint = GF(2^8) q^-u extrapolation.

CLI (PowerShell, main .venv, from the worktree/repo root):
  $env:LOG_FOLDER="./logs"; $env:PYTHONPATH="."; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/knowledge_attack_plots_from_csv.py --runs "logs/knowledge_attack/*" --out logs/knowledge_attack_plots

Manual use (each plot is its own function -- edit one, call one):
  from scripts.knowledge_attack_plots_from_csv import load, plot_silent, plot_oracle, plot_repair_effect, plot_attacker_work, plot_all
  s = load()                      # pools every run under logs/knowledge_attack/*, keeps N=2 -> per-cell summary rows
  s = load(["logs/knowledge_attack/main_g4_n2_t4000"], n=2)   # specific run dir(s) / N
  plot_silent(s, "logs/knowledge_attack_plots")               # one figure -> <out>/silent_vs_u.png
  plot_all(discover(["logs/knowledge_attack/*"]), "logs/knowledge_attack_plots")   # everything + summary.csv
Each plot_* takes (summary, out_dir) and returns the written PNG path (repair_effect: None if
the runs contain no hd=0 cells).
"""
import argparse
import csv
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from simulation.knowledge_attack_sim import (
    CSV_COLUMNS, N_SEGMENTS, summarize, theory_keyed_repair, theory_keyless_late, theory_pass, wilson, write_rows,
)

# Arm colours kept in sync with scripts/recovery_plots_from_csv.py ARMS (thesis-wide identity);
# strike is the secondary encoding (filled/solid = early, hollow/dashed = late).
ARM_STYLE = {
    "keyless": {"color": "#588157", "marker": "o", "label": "keyless (r observed pkts)"},
    "keyed":   {"color": "#3d405b", "marker": "s", "label": "keyed (k leaked keys)"},
}
STRIKE_STYLE = {"early": {"ls": "-", "fill": True}, "late": {"ls": "--", "fill": False}}
THEORY_GRAY = "#8a8a8a"
DEFAULT_RUNS = "logs/knowledge_attack/*"
PRODUCTION_HD = 1


def discover(patterns) -> list[Path]:
    paths = []
    for pat in patterns:
        p = Path(pat)
        candidates = sorted(p.parent.glob(p.name)) if p.is_absolute() else sorted(_ROOT.glob(pat))
        for d in candidates:
            f = d / "raw_trials.csv" if d.is_dir() else d
            if f.name == "raw_trials.csv" and f.exists():
                paths.append(f)
    return paths


def load_rows(paths) -> list[dict]:
    rows = []
    for p in paths:
        with Path(p).open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames != CSV_COLUMNS:
                print(f"  ! {p}: header does not match the frozen schema; skipped")
                continue
            rows.extend(reader)
    return rows


def _pick_n(summary, n=None) -> list[dict]:
    """Figures show ONE segment count so spot-check cells at other N never merge into a
    series. n=None -> the headline N_SEGMENTS if present, else the smallest N in the data."""
    ns = sorted({s["n_segments"] for s in summary})
    if not ns:
        return []
    if n is None:
        n = N_SEGMENTS if N_SEGMENTS in ns else ns[0]
    return [s for s in summary if s["n_segments"] == n]


def load(runs=(DEFAULT_RUNS,), n=None) -> list[dict]:
    """Pool raw_trials.csv from run-dir globs (relative to the repo root, or absolute) and
    return the per-cell summary rows for one N -- the input every plot_* function takes."""
    if isinstance(runs, (str, Path)):
        runs = [runs]
    paths = discover([str(r) for r in runs])
    print(f"pooling {len(paths)} run(s)")
    return _pick_n(summarize(load_rows(paths)), n)


def _series(summary, arm, strike, m, hd, n=None):
    pts = [s for s in summary if s["arm"] == arm and s["strike"] == strike and s["field_bits"] == m
           and s["hd"] == hd and (n is None or s["n_segments"] == n)]
    return sorted(pts, key=lambda s: s["u"])


def _rate_panel(ax, summary, m, hd, rate, lo, hi, count, n, extra_theory=True):
    """One field's panel: per (arm, strike) measured rates (Wilson bars, rule-of-3 for zeros)."""
    q = 2 ** m
    all_u = sorted({s["u"] for s in summary if s["field_bits"] == m})
    if not all_u:
        return
    us = list(range(min(all_u), max(all_u) + 1))
    ax.plot(us, [theory_pass(q, u) for u in us], ls="--", color=THEORY_GRAY, lw=1.5, label=f"theory $q^{{-u}}$, q={q}")
    if extra_theory:
        ax.plot(us, [theory_pass(256, u) for u in us], ls="-", color=THEORY_GRAY, lw=1, alpha=0.35,
                label="theory $q^{-u}$, GF(2^8)")
    for arm, st in ARM_STYLE.items():
        for strike, ss in STRIKE_STYLE.items():
            pts = _series(summary, arm, strike, m, hd, n)
            if not pts:
                continue
            face = st["color"] if ss["fill"] else "white"
            xs = [p["u"] + (0.06 if strike == "late" else 0) * (1 if arm == "keyed" else -1) for p in pts]
            hit = [(x, p) for x, p in zip(xs, pts) if p[count] > 0]
            zero = [(x, p) for x, p in zip(xs, pts) if p[count] == 0]
            if hit:
                hx = [x for x, _ in hit]
                hy = [p[rate] for _, p in hit]
                # clamp: at rate 1 the float Wilson bound can sit 1e-16 below the rate
                err = [[max(0.0, p[rate] - p[lo]) for _, p in hit], [max(0.0, p[hi] - p[rate]) for _, p in hit]]
                ax.errorbar(hx, hy, yerr=err, ls=ss["ls"], lw=2, color=st["color"], marker=st["marker"],
                            ms=8, mfc=face, mec=st["color"], capsize=3, label=f"{st['label']}, {strike}")
            if zero:
                ax.plot([x for x, _ in zero], [3.0 / p["trials"] for _, p in zero], ls="none", marker="v",
                        ms=8, mfc="white", mec=st["color"],
                        label=None if hit else f"{st['label']}, {strike}")
    ax.set_yscale("log")
    ax.set_xticks(us)
    g = next(s["gen_size"] for s in summary if s["field_bits"] == m)
    ax.set_xticklabels([f"{u}\nr={g - 1 - u if g - 1 - u >= 0 else '-'} | k={g - u}" for u in us], fontsize=9)
    ax.set_xlabel("u = constraints the attacker cannot compute\n(keyless r observed | keyed k leaked)")
    ax.set_title(f"GF(2^{m}), gen_size={g}")
    ax.grid(True, which="major", ls=":", alpha=0.4)
    # y-range follows THIS field's data + theory; the GF(2^8) line is allowed to leave the panel
    cells = [s for s in summary if s["field_bits"] == m and s["hd"] == hd]
    floor = min([theory_pass(q, max(us))] + [3.0 / s["trials"] for s in cells])
    ax.set_ylim(bottom=floor / 4, top=1.6)


def _field_axes(summary, title):
    ms = sorted({s["field_bits"] for s in summary})
    fig, axes = plt.subplots(1, len(ms), figsize=(6.2 * len(ms), 5.2), squeeze=False)
    fig.suptitle(title, fontsize=13, fontweight="bold")
    return ms, fig, axes[0]


def plot_silent(summary, out_dir, n=None):
    ms, fig, axes = _field_axes(summary, "Silent-decode rate vs attacker knowledge (one forged packet, production receiver)")
    for ax, m in zip(axes, ms):
        _rate_panel(ax, summary, m, PRODUCTION_HD, "silent_rate", "silent_lo", "silent_hi", "silent", n)
        g = next(s["gen_size"] for s in summary if s["field_bits"] == m)
        us = sorted({s["u"] for s in summary if s["field_bits"] == m and s["arm"] == "keyed"})
        ax.plot(us, [theory_keyed_repair(2 ** m, m, u, g, PRODUCTION_HD) for u in us], ls=":", lw=2,
                color=ARM_STYLE["keyed"]["color"], label="keyed theory incl. repair (hd=1)")
        if any(s["arm"] == "keyless" and s["strike"] == "late" and s["field_bits"] == m for s in summary):
            ul = sorted({s["u"] for s in summary if s["field_bits"] == m and s["arm"] == "keyless"})
            ax.plot(ul, [theory_keyless_late(2 ** m, u) for u in ul], ls=":", lw=2,
                    color=ARM_STYLE["keyless"]["color"], label="keyless late theory (peel tie-break)")
        ax.set_ylabel("silent-decode rate (log)")
    axes[0].legend(fontsize=8, loc="lower left")
    return _save(fig, out_dir, "silent_vs_u.png")


def plot_oracle(summary, out_dir, n=None):
    ms, fig, axes = _field_axes(summary, "Strict-oracle pass rate vs attacker knowledge (tag strength, no repair)")
    for ax, m in zip(axes, ms):
        _rate_panel(ax, summary, m, PRODUCTION_HD, "oracle_rate", "oracle_lo", "oracle_hi", "oracle_pass", n)
        ax.set_ylabel("P(forgery passes every check)")
    axes[0].legend(fontsize=8, loc="lower left")
    return _save(fig, out_dir, "oracle_vs_u.png")


def plot_repair_effect(summary, out_dir):
    hds = sorted({s["hd"] for s in summary if s["arm"] == "keyed"})
    if 0 not in hds or PRODUCTION_HD not in hds:
        return None
    ms, fig, axes = _field_axes(summary, "Keyed: the receiver's repair search corrects the forger's tag guesses")
    for ax, m in zip(axes, ms):
        g = next(s["gen_size"] for s in summary if s["field_bits"] == m)
        color = ARM_STYLE["keyed"]["color"]
        for hd, ls in ((0, "-"), (PRODUCTION_HD, "--")):
            pts = _series(summary, "keyed", "early", m, hd)
            if not pts:
                continue
            face = color if hd == 0 else "white"
            hit = [p for p in pts if p["forged_admitted"] > 0]
            zero = [p for p in pts if p["forged_admitted"] == 0]
            if hit:
                lo_hi = [wilson(p["forged_admitted"], p["trials"]) for p in hit]
                err = [[max(0.0, p["admit_rate"] - lo) for p, (lo, _) in zip(hit, lo_hi)],
                       [max(0.0, hi - p["admit_rate"]) for p, (_, hi) in zip(hit, lo_hi)]]
                ax.errorbar([p["u"] for p in hit], [p["admit_rate"] for p in hit], yerr=err, ls=ls, lw=2,
                            marker="s", ms=8, color=color, mfc=face, mec=color, capsize=3,
                            label=f"measured admit rate, repair hd={hd}")
            if zero:
                ax.plot([p["u"] for p in zero], [3.0 / p["trials"] for p in zero], ls="none", marker="v", ms=8,
                        mfc="white", mec=color, label=f"0 events (3/n bound), hd={hd}")
            ax.plot([p["u"] for p in pts], [theory_keyed_repair(2 ** m, m, p["u"], g, hd) for p in pts],
                    ls=":" if hd else "-.", color=THEORY_GRAY, lw=1.5, label=f"theory hd={hd}")
        ax.set_yscale("log")
        ax.set_xticks(sorted({s["u"] for s in summary if s["field_bits"] == m and s["arm"] == "keyed"}))
        ax.set_xlabel("u = unknown keys (g - k)")
        ax.set_ylabel("P(forged packet admitted)")
        ax.set_title(f"GF(2^{m}), gen_size={g}")
        ax.grid(True, ls=":", alpha=0.4)
    axes[0].legend(fontsize=8, loc="lower left")
    return _save(fig, out_dir, "repair_effect_keyed.png")


def plot_attacker_work(summary, out_dir):
    ms, fig, axes = _field_axes(summary, "Attacker field multiplications per forgery")
    for ax, m in zip(axes, ms):
        for arm, st in ARM_STYLE.items():
            pts = _series(summary, arm, "early", m, PRODUCTION_HD)
            if pts:
                ax.plot([p["u"] for p in pts], [p["attacker_mul_mean"] for p in pts], lw=2, marker=st["marker"],
                        ms=8, color=st["color"], label=st["label"])
        ax.set_xticks(sorted({s["u"] for s in summary if s["field_bits"] == m}))
        ax.set_xlabel("u = constraints the attacker cannot compute")
        ax.set_ylabel("field muls (mean)")
        ax.set_title(f"GF(2^{m})")
        ax.grid(True, ls=":", alpha=0.4)
    axes[0].legend(fontsize=9)
    return _save(fig, out_dir, "attacker_work_vs_u.png")


def _save(fig, out_dir, name) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    path = out_dir / name
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  plot: {path}")
    return path


def plot_all(paths, out_dir) -> list[Path]:
    rows = load_rows(paths)
    if not rows:
        print("  no rows to plot")
        return []
    summary = summarize(rows)
    write_rows(Path(out_dir) / "summary.csv", summary)   # keeps every N
    summary = _pick_n(summary)
    made = [plot_silent(summary, out_dir), plot_oracle(summary, out_dir),
            plot_repair_effect(summary, out_dir), plot_attacker_work(summary, out_dir)]
    return [p for p in made if p is not None]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", nargs="+", default=[DEFAULT_RUNS], help="run-dir globs (relative to repo root) or CSVs")
    ap.add_argument("--out", default="logs/knowledge_attack_plots")
    a = ap.parse_args(argv)
    paths = discover(a.runs)
    print(f"pooling {len(paths)} run(s)")
    plot_all(paths, a.out)


if __name__ == "__main__":
    main()
