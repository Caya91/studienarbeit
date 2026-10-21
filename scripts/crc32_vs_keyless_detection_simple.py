r"""Detection only (no repair), CRC-32 vs keyless HMAC (self-check + all 4 witnesses), 100 B packets (user 2026-10-20).

Same trials as the recovery run `logs/crc32_vs_keyless/simple_100B/run_seeds20000`: per seed the same pool
(build_paired_pools: gen 4, 100 B data in 2 x 50 B segments, 4 clean helpers + 4 targets) and the same payload bit
flips (inject_paired "data_only", seed*131+7 -- exactly what run_config draws). Every received target packet is
checked ONCE with the same functions the recovery uses to accept a candidate:
  CRC-32        every segment's zlib CRC-32 matches        (isolated_recovery_sim.score_crc logic)
  keyless HMAC  every segment self-orthogonal AND orthogonal to all 4 witnesses (_accepted_keyless, W=4)
Counts: corrupted packets, corrupted packets NOT detected (passed the check), clean packets flagged (false alarms).
Time: wall-clock of one packet check (all segments), mean over all checked target packets.
Output: logs/crc32_vs_keyless/simple_100B/detection/{detection_counts.csv, raw.csv} + plots/detection_*.png|pdf.

CLI: $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/crc32_vs_keyless_detection_simple.py --workers 8
"""
import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path("E:/projects/studienarbeit/logs/crc32_vs_keyless/simple_100B")
GEN, DF, NDS, T, W = 4, 100, 2, 4, 4
BERS = (1e-5, 1e-3)


def _seed_job(seed, bers):
    from icecream import ic
    ic.disable()
    from binary_ext_fields.custom_field import CountingField, create_field
    from simulation.isolated_recovery_sim import (
        _accepted_keyless, build_paired_pools, info_columns, inject_paired, kl_slice,
    )
    from simulation.segmented_crc import Crc32Instrument, crc_verify_segment, segment_slice as crc_slice
    field = CountingField(create_field(8))
    pools = build_paired_pools(field, GEN, DF, NDS, T, seed)
    helpers = {seg.name: [kl_slice(pools.kl_clean[h], seg) for h in pools.helper_idx] for seg in pools.kl_segments}
    inst = Crc32Instrument()
    rows = []
    for ber in bers:
        inj = inject_paired(pools, ber, "data_only", seed=seed * 131 + 7)
        for t in pools.target_idx:
            corrupted = info_columns(inj.kl[t], pools.kl_segments) != info_columns(pools.kl_clean[t], pools.kl_segments)
            t0 = time.perf_counter()
            kl_ok = _accepted_keyless(field, inj.kl[t], pools.kl_segments, helpers, W)
            kl_t = time.perf_counter() - t0
            t0 = time.perf_counter()
            crc_ok = all(crc_verify_segment(inst, crc_slice(inj.crc[t], seg), seg) for seg in pools.crc_segments)
            crc_t = time.perf_counter() - t0
            rows.append((seed, ber, t, int(corrupted), int(not kl_ok), int(not crc_ok), kl_t, crc_t))
    return rows


def run(seeds, workers):
    job = partial(_seed_job, bers=BERS)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        out = [r for rows in ex.map(job, seeds, chunksize=50) for r in rows]
    return pd.DataFrame(out, columns=["seed", "ber", "target", "corrupted", "keyless_flagged", "crc_flagged",
                                      "keyless_check_s", "crc_check_s"])


def counts(raw):
    rows = []
    for ber, g in raw.groupby("ber"):
        c = g[g.corrupted == 1]
        k = g[g.corrupted == 0]
        for arm, label in (("crc", "CRC-32"), ("keyless", "keyless HMAC")):
            rows.append(dict(ber=ber, scheme=label, packets=len(g), corrupted=len(c),
                             undetected=int((c[f"{arm}_flagged"] == 0).sum()),
                             false_alarms=int((k[f"{arm}_flagged"] == 1).sum()),
                             check_us=1e6 * g[f"{arm}_check_s"].mean()))
    return pd.DataFrame(rows)


def _bars(cnt, col, ylabel, title, out, name, fmt):
    from scripts.scaling_plots_from_csv import GRID, INK, INK_MUTED
    colors = {"CRC-32": "#4a3aa7", "keyless HMAC": "#588157"}
    bers = sorted(cnt.ber.unique())
    x = np.arange(len(bers))
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    for i, (scheme, color) in enumerate(colors.items()):
        vals = [float(cnt[(cnt.ber == b) & (cnt.scheme == scheme)][col].iloc[0]) for b in bers]
        bars = ax.bar(x + (i - 0.5) * 0.38, vals, 0.36, color=color, label=scheme)
        ax.bar_label(bars, labels=[fmt(v) for v in vals], padding=2, fontsize=9, color=INK)
    ax.set_xticks(x, [{1e-5: "$10^{-5}$", 1e-3: "$10^{-3}$"}.get(b, f"{b:g}") for b in bers])
    ax.set_xlabel("bit error rate", color=INK, fontsize=10)
    ax.set_ylabel(ylabel, color=INK, fontsize=10)
    ax.set_title(title, color=INK, fontsize=12)
    top = float(cnt[col].max())
    ax.set_ylim(0, top * 1.18 if top > 0 else 1)
    if col == "undetected":
        from matplotlib.ticker import MaxNLocator
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=INK_MUTED, labelcolor=INK, labelsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    h, l = ax.get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, frameon=False, fontsize=9, labelcolor=INK)
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(out / f"{name}.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out / name}.png")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--replot", action="store_true", help="only re-plot from detection/raw.csv")
    a = ap.parse_args(argv)
    det = ROOT / "detection"
    det.mkdir(parents=True, exist_ok=True)
    if a.replot:
        raw = pd.read_csv(det / "raw.csv")
    else:
        raw = run(range(a.seeds), a.workers)
        raw.to_csv(det / "raw.csv", index=False)
    cnt = counts(raw)
    cnt.to_csv(det / "detection_counts.csv", index=False)
    print(cnt.to_string(index=False))
    _bars(cnt, "undetected", "undetected corrupted packets", "Undetected errors", ROOT / "plots",
          "detection_undetected", lambda v: f"{int(v)}")
    _bars(cnt, "check_us", "time per packet check (µs)", "Detection time", ROOT / "plots",
          "detection_time", lambda v: f"{v:.1f}")


if __name__ == "__main__":
    main()
