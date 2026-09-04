"""Diagnostic: is the keyless HMAC's extra overhead the trust oracle, not weaker repair?

Hypothesis (2026-09-01): under uniform_hd both keyed (MAC) and keyless (orthogonal) repair
the SAME segments with the SAME reach, so keyless's higher overhead-vs-gen_size can't be a
repair deficit. It should instead be the keyless TRUST oracle being conservative -- it only
admits a self-passing packet if it also agrees with `verify_count` core witnesses, and it
warms up until each segment has `min_trust_count` trusted packets. The keyed MAC verifies
each packet conclusively with no cross-check and no warm-up.

Test: run keyless with the cross-check + warm-up DISABLED (verify_count=0, min_trust_count=1
-- self-check only) alongside the real strict keyless and the keyed baseline, at BER 1e-3.
If the oracle is the cause, keyless-loose collapses toward the keyed line. (Loose is a
DIAGNOSTIC only: verify_count=0 removes the forgery resistance that is the whole point of
the cross-check -- never a production config.)

Run: LOG_FOLDER=./logs PYTHONPATH=. .venv/Scripts/python.exe scripts/gensize_keyless_trust_diagnostic.py
"""

import csv
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

from binary_ext_fields.custom_field import create_field
from simulation.integrity_schemes import AdmitConfig, SegmentedScheme, SegmentedMacScheme
from simulation.scheme_comparison_sim import run_recovery_trial, _run_capped_cell
from utils.log_helpers import get_run_log_dir

FIELD_M = 8
N = 5
STRATEGY = "uniform_hd"
BER = 1e-3
GEN_SIZES = [7, 11, 16, 20]
NUM_TRIALS = 20
CELL_BUDGET_S = 500.0
MAX_PACKETS_FACTOR = 20

ARMS = {
    "keyed":          {"color": "#3d405b", "label": "keyed HMAC (MAC oracle)"},
    "keyless_strict": {"color": "#588157", "label": "keyless strict (vc=4, mtc=4)"},
    "keyless_loose":  {"color": "#e07a5f", "label": "keyless loose (vc=0, mtc=1)"},
}


def _make(arm, gen_size, data_fields):
    """(scheme, cfg) for one arm. min_pool_size = min(10, gen) for all three, so the ONLY
    difference between the two keyless arms is verify_count/min_trust_count."""
    mp = min(10, gen_size)
    nds = N - 1
    if arm == "keyed":
        s = SegmentedMacScheme(num_data_segments=nds, data_fields=data_fields,
                               strategy=STRATEGY, name=f"mac_{STRATEGY}_n{N}")
        return s, AdmitConfig(hamming_distance=2, min_pool_size=mp)
    s = SegmentedScheme(num_data_segments=nds, data_fields=data_fields,
                        strategy=STRATEGY, name=f"segmented_{STRATEGY}_n{N}")
    if arm == "keyless_strict":
        return s, AdmitConfig(hamming_distance=2, min_pool_size=mp, verify_count=4, min_trust_count=4)
    return s, AdmitConfig(hamming_distance=2, min_pool_size=mp, verify_count=0, min_trust_count=1)


def main() -> None:
    run_dir = get_run_log_dir("gensize_keyless_trust_diagnostic", trials=NUM_TRIALS, n=N)
    base_field = create_field(FIELD_M)
    rows = []
    for gen_size in GEN_SIZES:
        data_fields = (N - 1) * gen_size
        for arm in ARMS:
            scheme, cfg = _make(arm, gen_size, data_fields)
            print(f"=== arm={arm} gen={gen_size} df={data_fields} BER={BER:g} ===", flush=True)
            results = _run_capped_cell(
                lambda: run_recovery_trial(base_field, scheme, data_fields, gen_size, BER, cfg,
                                           max_packets_factor=MAX_PACKETS_FACTOR),
                NUM_TRIALS, CELL_BUDGET_S)
            decoded = [r for r in results if r.decoded]
            ovh = float(np.mean([r.overhead for r in decoded])) if decoded else float("nan")
            std = float(np.std([r.overhead for r in decoded])) if decoded else float("nan")
            rows.append({"arm": arm, "gen_size": gen_size, "data_fields": data_fields,
                         "bit_error_rate": BER, "trials_run": len(results),
                         "mean_overhead_decoded": ovh, "std_overhead_decoded": std})
            print(f"    overhead={ovh:.3f}  n={len(results)}", flush=True)

    with (run_dir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"Written: {run_dir/'summary.csv'}")

    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    for arm, meta in ARMS.items():
        pts = sorted((r["gen_size"], r["mean_overhead_decoded"]) for r in rows
                     if r["arm"] == arm and not np.isnan(r["mean_overhead_decoded"]))
        if pts:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], "-", marker="o",
                    color=meta["color"], linewidth=2, markersize=6, label=meta["label"])
    ax.axhline(1.0, color="grey", linestyle="-.", alpha=0.6, label="ideal = 1")
    ax.set_xlabel("Generation size", fontsize=12, fontweight="bold")
    ax.set_ylabel("Mean overhead (packets sent / gen_size)", fontsize=12, fontweight="bold")
    ax.set_title(f"Keyless trust-oracle diagnostic @ BER={BER:g} (N={N}, {STRATEGY})",
                 fontsize=12, fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=9)
    plt.tight_layout()
    out = run_dir / "keyless_trust_diagnostic.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {out}\nDone -> {run_dir}")


if __name__ == "__main__":
    main()
