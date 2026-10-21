r"""Same-run wall-clock ratios for ADR-0015 task 1 (secondary metric).

The main sweep (scripts/e2e_throughput_runs.sh) runs one arm after the other on a machine shared with
other jobs, so its per-trial wall times are not comparable ACROSS arms. This bench runs the four arms
INTERLEAVED in ONE process (arm order rotated per trial; same seed per trial for every arm), so every
ratio arm / keyless is measured under the same load. Logical metrics (packets, ops) stay primary.

Settings = the main sweep (gen 4, 50 B data segments, payload-only errors, acr_only, HD 2, budget 20000,
cap 64 packets). Default cells: df 100 / 300 / 1000 x BER 1e-4, 1e-3; 30 trials each.
Output: <out>/wallclock_raw.csv, <out>/wallclock_summary.csv (mean wall per generation + ratio to keyless).

CLI (PowerShell):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/e2e_wallclock_bench.py --out E:/projects/studienarbeit/logs/e2e_throughput/wallclock
"""
import argparse
import csv
import random
import sys
import zlib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
from icecream import ic

from binary_ext_fields.custom_field import create_field
from scripts.pareto_sweep import ARMS, make_scheme
from simulation.integrity_schemes import AdmitConfig
from simulation.scheme_comparison_sim import run_recovery_trial

ic.disable()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=_ROOT / "logs" / "e2e_throughput" / "wallclock")
    ap.add_argument("--configs", default="100:3,300:7,1000:21")
    ap.add_argument("--bers", default="1e-4,1e-3")
    ap.add_argument("--trials", type=int, default=30)
    a = ap.parse_args(argv)
    field = create_field(8)
    cfg = AdmitConfig(hamming_distance=2, pair_budget=20000, repair_span="payload", min_pool_size=4)
    a.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for pair in a.configs.split(","):
        df, n = (int(x) for x in pair.split(":"))
        for ber in (float(b) for b in a.bers.split(",")):
            for t in range(a.trials):
                seed = zlib.crc32(f"wallclock|{df}|{n}|{ber!r}|{t}".encode())
                order = ARMS[t % len(ARMS):] + ARMS[:t % len(ARMS)]
                for arm in order:
                    random.seed(seed)
                    np.random.seed(seed % 2**32)
                    tr = {}
                    r = run_recovery_trial(field, make_scheme(arm, n, df, "acr_only"), df, 4, ber, cfg,
                                           max_packets_factor=16, error_scope="data_payload", trace=tr)
                    rows.append({"arm": arm, "data_fields": df, "n_segments": n, "bit_error_rate": ber, "trial": t,
                                 "seed": seed, "status": r.status, "packets": r.packets_to_decode,
                                 "wall_time_s": r.wall_time_s, "repaired_used": tr["repaired_used"]})
            print(f"df={df} ber={ber:g} done", flush=True)
    raw = pd.DataFrame(rows)
    raw.to_csv(a.out / "wallclock_raw.csv", index=False)
    g = raw.groupby(["data_fields", "bit_error_rate", "arm"]).agg(
        trials=("wall_time_s", "size"), decoded=("status", lambda s: int((s == "decoded").sum())),
        wall_ms_mean=("wall_time_s", lambda x: 1e3 * x.mean()), packets_mean=("packets", "mean")).reset_index()
    kl = g[g["arm"] == "keyless"].set_index(["data_fields", "bit_error_rate"])["wall_ms_mean"]
    g["ratio_to_keyless"] = [w / kl.loc[(d, b)] for d, b, w in zip(g["data_fields"], g["bit_error_rate"], g["wall_ms_mean"])]
    g.to_csv(a.out / "wallclock_summary.csv", index=False)
    print(g.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
