"""Overnight verify_count safety sweep at HIGH BER (5e-3, 1e-2) -- the floor the
fast 1e-3 sweep couldn't reach. Question: does silent_decode_rate rise at small
verify_count when more poisoners land per generation?

Self-contained (sets LOG_FOLDER/PYTHONPATH), headless. Paired seeds: the SAME
pollution is replayed for every verify_count so metric diffs are purely the knob.
Bounded runtime: each (N,BER,vc) cell runs up to NUM_TRIALS but stops starting new
trials once CELL_BUDGET_S wall-time has elapsed (a slow high-BER cell degrades to
fewer trials rather than hanging the night). Results are written to summary.csv
AFTER EVERY CELL, so a partial night still leaves usable data.

    E:/projects/studienarbeit/.venv/Scripts/python.exe scripts/vc_overnight_sweep.py
"""
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

import random

from binary_ext_fields.generate_symbols import create_field
from simulation.scheme_comparison_sim import (
    run_recovery_trial, FIELD_M, GEN_SIZE, SEGMENTED_MAX_PACKETS_FACTOR,
)
from simulation.integrity_schemes import SCHEMES, AdmitConfig, SEGMENTED_DATA_FIELDS

# ── Knobs ─────────────────────────────────────────────────────────────────────
NS = (3, 5)
BERS = (5e-3, 1e-2)
VCS = (0, 1, 2, 4, None)
NUM_TRIALS = 400        # per cell, capped by the wall budget below
CELL_BUDGET_S = 900.0   # 15 min/cell -> worst case 2*2*5*15min = 5h; fast cells finish sooner

FIELDS = ["N", "ber", "verify_count", "trials_run", "decode_rate", "correct_rate",
          "silent_rate", "timeout_rate", "mean_overhead_decoded", "recovery_ops_mean",
          "detection_ops_mean", "wall_s"]


def main():
    run_dir = Path(os.environ["LOG_FOLDER"]) / "vc_overnight" / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    csv_path = run_dir / "summary.csv"
    with open(csv_path, "w", newline="") as f:
        csv.writer(f).writerow(FIELDS)
    print(f"writing -> {csv_path}", flush=True)
    print(f"grid: N={NS} BER={BERS} vc={VCS}  NUM_TRIALS<= {NUM_TRIALS}  "
          f"cell_budget={CELL_BUDGET_S:g}s\n", flush=True)

    bf = create_field(FIELD_M)
    for N in NS:
        sch = SCHEMES[f"segmented_uniform_hd_n{N}"]
        for ber in BERS:
            for vc in VCS:
                cfg = AdmitConfig(hamming_distance=2, verify_count=vc)
                res = []
                start = time.perf_counter()
                for t in range(NUM_TRIALS):
                    if t > 0 and time.perf_counter() - start >= CELL_BUDGET_S:
                        break
                    random.seed(t)  # paired across vc
                    try:
                        res.append(run_recovery_trial(bf, sch, SEGMENTED_DATA_FIELDS, GEN_SIZE, ber,
                                                      cfg, max_packets_factor=SEGMENTED_MAX_PACKETS_FACTOR))
                    except Exception as e:  # never let one bad trial kill the night
                        print(f"  !! trial {t} crashed (N={N} ber={ber:g} vc={vc}): {e}", flush=True)
                wall = time.perf_counter() - start
                n = len(res)
                if n == 0:
                    continue
                dec = [r for r in res if r.decoded]
                row = {
                    "N": N, "ber": ber, "verify_count": vc, "trials_run": n,
                    "decode_rate": round(len(dec) / n, 4),
                    "correct_rate": round(sum(r.correct for r in res) / n, 4),
                    "silent_rate": round(sum(r.silent_decode for r in res) / n, 4),
                    "timeout_rate": round(sum(r.status == "timeout" for r in res) / n, 4),
                    "mean_overhead_decoded": round(sum(r.overhead for r in dec) / len(dec), 3) if dec else "",
                    "recovery_ops_mean": round(sum(r.recovery_ops for r in res) / n),
                    "detection_ops_mean": round(sum(r.detection_ops for r in res) / n),
                    "wall_s": round(wall, 1),
                }
                with open(csv_path, "a", newline="") as f:
                    csv.DictWriter(f, FIELDS).writerow(row)
                print(f"  N={N} ber={ber:g} vc={str(vc):>4} n={n:>3} "
                      f"decode={row['decode_rate']:.2f} correct={row['correct_rate']:.2f} "
                      f"SILENT={row['silent_rate']:.3f} timeout={row['timeout_rate']:.2f} "
                      f"ovh={row['mean_overhead_decoded']} wall={row['wall_s']:.0f}s", flush=True)
        print("", flush=True)

    print(f"\nOVERNIGHT vc SWEEP COMPLETE -> {csv_path}", flush=True)


if __name__ == "__main__":
    main()
