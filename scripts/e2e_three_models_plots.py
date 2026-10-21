r"""Plots + tables for the ADR-0015 follow-up (2026-10-17): end-to-end single hop under three channel-error
models x max search depth HD 1..4 (scripts/e2e_three_models_runs.sh).

Input: <root>/<scope>/hd<k>/<arm>/raw_trials.csv and <root>/<scope>/arq/crc_arq/raw_trials.csv (pareto_sweep
schema v4). scope = data_payload | data_tags_only | data_segment; arms keyless | keyed | crc_acr (repair, per HD),
crc_arq (drop + resend, no repair -> HD-independent, drawn in every HD row).

Figures (<out>, png + pdf, dpi 160), one set per error model <scope>:
  transmissions_<scope>   rows = max HD 1..4, cols = payload size: packets received until decodable (mean of the
                          decoded generations, 95 % CI; hollow = not every generation decoded within the cap)
                          + exact ARQ expectation 4.0039 / (1 - BER)^(bits in scope) (thin dotted, uncapped).
  decode_rate_<scope>     same grid: decoded within the 64-packet cap (Wilson 95 % CI as error bars).
  goodput_<scope>         same grid: info bytes delivered / wire bytes sent (ratio of totals over ALL generations;
                          timeouts count their packets, no info) + ARQ expectation.
  tx_vs_hd_<scope>        compact: packets until decodable vs max HD at BER 1e-3 (row 1) and 3e-3 (row 2), cols =
                          payload; label = decode % where < 100 %; ARQ = horizontal line (HD-independent).
Tables: three_models_summary.csv (scope x HD x arm x df x BER), silent_decodes.csv (every silent wrong decode,
with seed / cell), three_models_compact.csv (BER 1e-4 / 1e-3 / 3e-3, HD 2 and 4: tx + decode %).

CLI (PowerShell):
  $env:PYTHONPATH="."; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/e2e_three_models_plots.py `
      --root E:/projects/studienarbeit/logs/e2e_throughput/three_models_hd1-4
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
import matplotlib.lines
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from scripts.e2e_throughput_plots import ARM, Z, _line, _save, _style, expected_clean_needed, summarize
from scripts.scaling_plots_from_csv import INK, INK_MUTED

SCOPES = {
    "data_payload": "payload-only bit errors",
    "data_tags_only": "tag-only bit errors (data-segment salt+tag / MAC / CRC bytes)",
    "data_segment": "payload + tag bit errors",
}
CRC_BYTES = 4
CAP = 64
ARMS_ORDER = ("keyless", "keyed", "crc_acr", "crc_arq")


def scope_bits(scope: str, df: int, n: int) -> int:
    """Bits the channel may flip per CRC-32 wire packet under `scope` (data segments only, coeffs clean)."""
    tag = CRC_BYTES * (n - 1)
    return 8 * {"data_payload": df, "data_tags_only": tag, "data_segment": df + tag}[scope]


def arq_expected(ber, scope, df, n, g=4):
    """Exact CRC-32 ARQ expectation: packet survives with p = (1 - BER)^(bits in scope) (no cap)."""
    return expected_clean_needed(g) / (1.0 - np.asarray(ber, float)) ** scope_bits(scope, df, n)


def load(root: Path) -> pd.DataFrame:
    paths = sorted(p for p in glob.glob(str(root / "*" / "*" / "*" / "raw_trials.csv"))
                   if not Path(p).relative_to(root).parts[0].startswith("_"))   # skip _smoke / _aborted
    if not paths:
        raise FileNotFoundError(f"no runs under {root}")
    frames = []
    for p in paths:
        d = pd.read_csv(p)
        d["hd_dir"] = Path(p).parents[1].name          # hd<k> | arq
        frames.append(d)
    raw = pd.concat(frames, ignore_index=True)
    return raw.drop_duplicates(subset=["error_scope", "hd_dir", "arm", "data_fields", "n_segments",
                                       "bit_error_rate", "trial_idx"])


def summarize_all(raw: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (scope, hd_dir), g in raw.groupby(["error_scope", "hd_dir"]):
        s = summarize(g)
        s.insert(0, "error_scope", scope)
        s.insert(1, "max_hd", -1 if hd_dir == "arq" else int(hd_dir[2:]))
        s["pairs_failed_mean"] = [g[(g.arm == r.arm) & (g.data_fields == r.data_fields)
                                    & (g.bit_error_rate == r.bit_error_rate) & g.correct.astype(bool)]
                                  ["pairs_failed"].mean() for r in s.itertuples()]
        s["arq_expected_tx_scope"] = [float(arq_expected(r.bit_error_rate, scope, r.data_fields, r.n_segments))
                                      for r in s.itertuples()]
        s["budget_capped"] = s["trials"] < raw["trial_idx"].max() + 1
        out.append(s)
    return pd.concat(out, ignore_index=True)


def _rows_for(s, scope, hd):
    """Repair arms at this HD + the (HD-independent) ARQ rows."""
    return pd.concat([s[(s.error_scope == scope) & (s.max_hd == hd)],
                      s[(s.error_scope == scope) & (s.arm == "crc_arq")]], ignore_index=True)


def _legend(fig, arms, extra=()):
    handles = [matplotlib.lines.Line2D([], [], color=ARM[a]["color"], ls=ARM[a]["ls"], marker=ARM[a]["marker"],
                                       lw=1.8, ms=5.5, label=ARM[a]["label"]) for a in arms] + list(extra)
    fig.legend(handles=handles, loc="lower center", ncol=min(3, len(handles)), frameon=False, fontsize=8.5,
               labelcolor=INK, bbox_to_anchor=(0.5, 0.0))


def _settings(s, scope):
    sub = s[s.error_scope == scope]
    rep, arq = sub[sub.arm != "crc_arq"]["trials"].max(), sub[sub.arm == "crc_arq"]["trials"].max()
    t = f"{int(rep)} (repair arms) / {int(arq)} (ARQ)" if rep == rep and arq == arq and rep != arq else int(sub["trials"].max())
    return (f"single hop, g = 4, GF(2^8), 50 B data segments, {SCOPES[scope]}, coefficients clean, repair span "
            f"segment, budget 20000 / search, cap 64 packets, up to {t} generations per point")


def _grid(s, scope, metric, out_dir):
    hds = sorted(h for h in s[s.error_scope == scope]["max_hd"].unique() if h > 0)
    dfs = sorted(s["data_fields"].unique())
    if not hds:
        return
    fig, axes = plt.subplots(len(hds), len(dfs), figsize=(4.3 * len(dfs), 2.75 * len(hds) + 0.9),
                             sharex=True, squeeze=False)
    arms_seen = set()
    for i, hd in enumerate(hds):
        rows = _rows_for(s, scope, hd).assign(partial=lambda d: d["decode_rate"] < 1.0)
        for j, df in enumerate(dfs):
            ax = axes[i][j]
            sub = rows[rows.data_fields == df]
            if sub.empty:
                continue
            n = int(sub["n_segments"].iloc[0])
            bers = np.logspace(np.log10(sub.bit_error_rate.min()), np.log10(sub.bit_error_rate.max()), 200)
            arq_tx = arq_expected(bers, scope, df, n)
            arq_style = dict(color=ARM["crc_arq"]["color"], lw=0.9, ls=(0, (1, 1.5)), zorder=1)
            for arm in ARMS_ORDER:
                g = sub[sub.arm == arm]
                if g.empty:
                    continue
                arms_seen.add(arm)
                if metric == "tx":
                    _line(ax, g, "bit_error_rate", "tx_mean", arm, err="tx_ci", hollow="partial")
                elif metric == "decode":
                    jit = {"keyless": 0.92, "keyed": 0.97, "crc_acr": 1.03, "crc_arq": 1.08}[arm]  # overlap at 100 %
                    g = g.assign(lo_err=(g.decode_rate - g.decode_lo).clip(lower=0), hi_err=(g.decode_hi - g.decode_rate).clip(lower=0),
                                 x_j=g.bit_error_rate * jit)
                    _line(ax, g, "x_j", "decode_rate", arm)
                    gg = g.sort_values("x_j")
                    ax.errorbar(gg.x_j, gg.decode_rate, yerr=[gg.lo_err, gg.hi_err], fmt="none",
                                ecolor=ARM[arm]["color"], elinewidth=0.8, capsize=2)
                else:
                    _line(ax, g, "bit_error_rate", "goodput", arm, err="goodput_ci")
            if metric == "tx":
                ax.plot(bers, arq_tx, **arq_style)
                ax.axhline(4, color=INK_MUTED, lw=0.8, alpha=0.5)
                ax.axhline(CAP, color=INK_MUTED, lw=0.8, ls="--", alpha=0.6)
                ax.set_ylim(0, CAP + 8)
                _style(ax)
            elif metric == "decode":
                ax.set_ylim(-0.04, 1.04)
                _style(ax, percent=True)
            else:
                crc_wire = sub[sub.arm == "crc_arq"]["wire_bytes"]
                if len(crc_wire):
                    ax.plot(bers, 4 * df / (arq_tx * int(crc_wire.iloc[0])), **arq_style)
                ax.set_ylim(-0.03, 1.0)
                _style(ax, percent=True)
            if i == 0:
                ax.set_title(f"payload {df} B  (N = {n} segments)", color=INK, fontsize=10)
            if i == len(hds) - 1:
                ax.set_xlabel("bit error rate (per bit in the error scope)", color=INK, fontsize=9)
            if j == 0:
                ylab = {"tx": "packets until\ndecodable", "decode": "decoded within\n64 packets",
                        "goodput": "goodput (info /\nwire bytes)"}[metric]
                ax.set_ylabel(f"max HD {hd}\n{ylab}", color=INK, fontsize=9)
    extra = [matplotlib.lines.Line2D([], [], color=ARM["crc_arq"]["color"], lw=0.9, ls=(0, (1, 1.5)),
                                     label="CRC-32 ARQ, exact expectation without cap")] if metric != "decode" else []
    _legend(fig, [a for a in ARMS_ORDER if a in arms_seen], extra)
    title = {"tx": "Packets received until decodable (mean of decoded generations; hollow = not all decoded)",
             "decode": "Generations decoded within the 64-packet cap (Wilson 95 % CI; arms offset slightly in x)",
             "goodput": "Goodput = info bytes delivered / wire bytes sent (all generations; timeouts count)"}[metric]
    fig.suptitle(f"{title}\n{_settings(s, scope)}", color=INK, fontsize=10)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    _save(fig, out_dir, f"{ {'tx': 'transmissions', 'decode': 'decode_rate', 'goodput': 'goodput'}[metric] }_{scope}")


def _compact(s, scope, out_dir, bers=(1e-3, 3e-3)):
    sub = s[s.error_scope == scope]
    hds = sorted(h for h in sub["max_hd"].unique() if h > 0)
    dfs = sorted(sub["data_fields"].unique())
    if not hds:
        return
    fig, axes = plt.subplots(len(bers), len(dfs), figsize=(4.0 * len(dfs), 3.0 * len(bers) + 0.8), squeeze=False)
    arms_seen = set()
    for i, ber in enumerate(bers):
        for j, df in enumerate(dfs):
            ax = axes[i][j]
            cell = sub[(sub.data_fields == df) & np.isclose(sub.bit_error_rate, ber)]
            for k, arm in enumerate(ARMS_ORDER):
                g = cell[cell.arm == arm].sort_values("max_hd")
                if g.empty:
                    continue
                arms_seen.add(arm)
                st = ARM[arm]
                if arm == "crc_arq":
                    r = g.iloc[0]
                    if np.isfinite(r.tx_mean):
                        ax.axhline(r.tx_mean, color=st["color"], ls=st["ls"], lw=1.4)
                        ax.annotate(f"ARQ {r.tx_mean:.1f} ({r.decode_rate:.0%})", (0.99, r.tx_mean),
                                    xycoords=("axes fraction", "data"), textcoords="offset points", xytext=(0, 3),
                                    fontsize=7, color=st["color"], ha="right", va="bottom")
                    else:
                        ax.text(0.99, 0.97, "ARQ: 0 % decoded", transform=ax.transAxes, fontsize=7,
                                color=st["color"], ha="right", va="top")
                    continue
                xs = g.max_hd.to_numpy(float) + (k - 1) * 0.08
                ys = g.tx_mean.to_numpy(float)
                ax.plot(xs, ys, color=st["color"], ls=st["ls"], lw=1.5)
                ax.errorbar(xs, ys, yerr=np.nan_to_num(g.tx_ci.to_numpy(float)), fmt="none", ecolor=st["color"],
                            elinewidth=0.8, capsize=2)
                for x, y, dr in zip(xs, ys, g.decode_rate):
                    yy = y if np.isfinite(y) else 2
                    ax.plot(x, yy, marker=st["marker"] if np.isfinite(y) else "x", ms=5.5, color=st["color"],
                            mfc=st["color"] if dr >= 1.0 else "white", mew=1.3, ls="none")
                    if dr < 1.0:
                        ax.annotate(f"{dr:.0%}", (x, yy), textcoords="offset points", xytext=(-24 if k == 0 else 5, 3 if k == 0 else -9),
                                    fontsize=6.5, color=st["color"])
            ax.set_xticks(hds)
            ax.set_xlim(0.6, 4.9)
            ax.set_ylim(bottom=0)
            ax.grid(True, color="#e6e6e6", lw=0.8)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            ax.tick_params(labelsize=8, colors=INK_MUTED, labelcolor=INK)
            if i == 0:
                n = int(cell["n_segments"].iloc[0]) if len(cell) else 0
                ax.set_title(f"payload {df} B  (N = {n})", color=INK, fontsize=10)
            if i == len(bers) - 1:
                ax.set_xlabel("max search depth HD", color=INK, fontsize=9)
            if j == 0:
                ax.set_ylabel(f"BER {ber:.0e}\npackets until decodable", color=INK, fontsize=9)
    _legend(fig, [a for a in ARMS_ORDER if a in arms_seen])
    fig.suptitle(f"Packets until decodable vs max search depth (mean of decoded generations; hollow + label = "
                 f"decode %, x = none decoded)\n{_settings(s, scope)}", color=INK, fontsize=9.5)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    _save(fig, out_dir, f"tx_vs_hd_{scope}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path("E:/projects/studienarbeit/logs/e2e_throughput/three_models_hd1-4"))
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    out = a.out or a.root / "plots_three_models"
    out.mkdir(parents=True, exist_ok=True)
    raw = load(a.root)
    s = summarize_all(raw)
    s.sort_values(["error_scope", "max_hd", "data_fields", "bit_error_rate", "arm"]).to_csv(
        out / "three_models_summary.csv", index=False)
    sil = raw[raw.silent_decode.astype(bool)][["error_scope", "hd_dir", "arm", "data_fields", "n_segments",
                                               "bit_error_rate", "trial_idx", "seed", "packets_to_decode",
                                               "n_corrupted_rx", "repaired_used", "wrong_used"]]
    sil.to_csv(out / "silent_decodes.csv", index=False)
    comp = s[np.isin(s.bit_error_rate, [1e-4, 1e-3, 3e-3]) & np.isin(s.max_hd, [-1, 2, 4])]
    comp[["error_scope", "max_hd", "arm", "data_fields", "bit_error_rate", "trials", "tx_mean", "decode_rate",
          "silent", "repaired_used_mean", "corrupted_rx_mean", "goodput"]].sort_values(
        ["error_scope", "data_fields", "bit_error_rate", "max_hd", "arm"]).to_csv(out / "three_models_compact.csv",
                                                                                   index=False)
    print(f"  {len(raw)} trials, {len(s)} cells, {len(sil)} silent decodes; tables in {out}")
    for scope in SCOPES:
        if (s.error_scope == scope).any():
            for metric in ("tx", "decode", "goodput"):
                _grid(s, scope, metric, out)
            _compact(s, scope, out)


if __name__ == "__main__":
    main()
