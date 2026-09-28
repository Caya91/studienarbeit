"""Pareto sweep for the keyless segmented scheme: segment count N x payload df x BER.

Question: where are the Pareto points of keyless HMAC (SegmentedScheme) between
  * bit-efficiency  = info bits delivered / wire bits sent  (tags + salt + coeff header
                      + retransmissions all counted -- the packet-count overhead of
                      ticket 03 hides the tag bits that grow with N), and
  * receiver compute = scheme_ops + decode_ops per generation (deterministic field muls),
with silent_decode = 0 as a hard filter. Analysis/plots: scripts/pareto_from_csv.py.

Grid (matched segment lengths across payloads): for each df, N is chosen so the data-
segment length L = df/(N-1) hits {48, 24, 16, 12}, plus N_max at the rank floor
(L >= gen_size-1, see build_segments). gen=10, m=8 ->
  df=48:  N {2,3,4,5,6}    df=96:  N {3,5,7,9,11}    df=192: N {5,9,13,17,22}
So "df" and "L" are separable in the analysis: same L, bigger df = more data per tag.

Fixed (settled elsewhere, see docs/segmented_n_sweep_findings.md + memory):
  strategy coefficient_first, hamming_distance 2, verify_count 4, ic_refinement on,
  max_packets_factor 8 (= ticket 03). pair_budget = None (full HD-2 enumeration) so a
  long segment is never budget-truncated -- at 100k an L=48 segment (472 bit columns,
  111,628 HD-2 candidates) would be, confounding the N comparison.

Recovery is NOT a separate sim: admit() runs the full combined recovery, and every
raw row carries pairs_recovered/failed, unpaired_*, detection_ops, recovery_ops.
The `arm` column (keyless | keyed) lets later keyed runs at chosen Pareto points pool
into the same analysis without schema changes.

Scheduling: trials run in a process pool (default 6 workers). Cells are ordered
cheap-first; a cell stops getting new trials once its summed trial wall time reaches
--cell-budget-s (every cell gets >= 1 trial), at most --max-inflight-per-cell trials of
one cell run at once, and each trial stops pulling packets after --trial-deadline-s
(status "wall_limit"). raw_trials.csv is appended + flushed after EVERY trial, and
--resume <run_dir> skips trials already in it -- an interrupted run loses at most the
in-flight trials. Wall times are contended (N workers share the CPU); ops are not.

Run (PowerShell, from the worktree; memory how_to_run_sims):
  $env:LOG_FOLDER="./logs"; $env:PYTHONPATH="."
  & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/pareto_sweep.py --stage smoke
  & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/pareto_sweep.py --stage full `
      --out-root E:/projects/studienarbeit/logs/pareto_sweep
"""

import argparse
import csv
import json
import os
import random
import sys
import time
import zlib
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

import numpy as np

from binary_ext_fields.custom_field import create_field
from simulation.integrity_schemes import AdmitConfig, SegmentedMacScheme, SegmentedScheme
from simulation.scheme_comparison_sim import SEGMENTED_MAX_PACKETS_FACTOR, run_recovery_trial

SCHEMA_VERSION = 1
GEN_SIZE = 10
FIELD_M = 8
STRATEGY = "coefficient_first"
HAMMING_DISTANCE = 2
SEGMENT_LENGTHS = (48, 24, 16, 12)   # target data-segment length L; N_max added per df

STAGES = {
    "smoke": dict(dfs=[48], n_by_df={48: [3, 5]}, bers=[1e-4, 1e-3], trials=2,
                  cell_budget_s=120.0, trial_deadline_s=300.0),
    "full":  dict(dfs=[48, 96, 192], n_by_df=None, bers=[1e-4, 5e-4, 1e-3], trials=30,
                  cell_budget_s=1800.0, trial_deadline_s=1800.0),
}

RAW_FIELDS = [
    "schema_version", "arm", "scheme", "strategy", "gen_size", "field_m", "data_fields",
    "n_segments", "seg_len_min", "seg_len_max", "wire_symbols", "hamming_distance",
    "pair_budget", "verify_count", "min_pool_size", "max_packets_factor", "trial_deadline_s",
    "bit_error_rate", "trial_idx", "seed",
    "status", "decoded", "correct", "silent_decode", "packets_to_decode", "overhead",
    "scheme_ops", "decode_ops", "detection_ops", "recovery_ops",
    "pairs_recovered", "pairs_failed", "unpaired_recovered", "unpaired_failed",
    "wall_time_s", "time_per_packet_s", "info_bits_delivered", "wire_bits_sent",
]


def n_values_for(df: int, gen_size: int) -> list[int]:
    """N (total segments incl. coeff) hitting each target L, plus N_max at the rank floor."""
    n_max = df // (gen_size - 1) + 1
    ns = {df // L + 1 for L in SEGMENT_LENGTHS if df // L + 1 >= 2} | {n_max}
    return sorted(n for n in ns if 2 <= n <= n_max)


def make_scheme(arm: str, n_segments: int, df: int):
    cls = SegmentedScheme if arm == "keyless" else SegmentedMacScheme
    prefix = "segmented" if arm == "keyless" else "mac"
    return cls(num_data_segments=n_segments - 1, data_fields=df, strategy=STRATEGY,
               name=f"{prefix}_{STRATEGY}_n{n_segments}_df{df}")


@dataclass(frozen=True)
class Cell:
    arm: str
    df: int
    n: int
    ber: float

    @property
    def key(self):
        return (self.arm, self.df, self.n, self.ber)


@dataclass(frozen=True)
class Task:
    cell: Cell
    trial_idx: int
    seed: int
    gen_size: int
    field_m: int
    cfg: dict
    max_packets_factor: int
    trial_deadline_s: float | None
    wire_symbols: int
    seg_len_min: int
    seg_len_max: int


def _seed(cell: Cell, trial_idx: int, gen_size: int, field_m: int) -> int:
    return zlib.crc32(f"{cell.arm}|{gen_size}|{field_m}|{cell.df}|{cell.n}|{cell.ber!r}|{trial_idx}".encode())


_FIELDS = {}


def run_task(task: Task) -> dict:
    """Worker entry (top-level so it pickles under Windows spawn)."""
    random.seed(task.seed)
    np.random.seed(task.seed % 2**32)
    field = _FIELDS.setdefault(task.field_m, create_field(task.field_m))
    cell = task.cell
    scheme = make_scheme(cell.arm, cell.n, cell.df)
    cfg = AdmitConfig(**task.cfg)
    res = run_recovery_trial(field, scheme, cell.df, task.gen_size, cell.ber, cfg,
                             max_packets_factor=task.max_packets_factor,
                             deadline_s=task.trial_deadline_s)
    r = asdict(res)
    info_bits = task.gen_size * cell.df * task.field_m if res.correct else 0
    wire_bits = res.packets_to_decode * task.wire_symbols * task.field_m
    return {
        "schema_version": SCHEMA_VERSION, "arm": cell.arm, "scheme": scheme.name,
        "strategy": STRATEGY, "gen_size": task.gen_size, "field_m": task.field_m,
        "data_fields": cell.df, "n_segments": cell.n, "seg_len_min": task.seg_len_min,
        "seg_len_max": task.seg_len_max, "wire_symbols": task.wire_symbols,
        "hamming_distance": cfg.hamming_distance, "pair_budget": cfg.pair_budget,
        "verify_count": cfg.verify_count, "min_pool_size": cfg.min_pool_size,
        "max_packets_factor": task.max_packets_factor, "trial_deadline_s": task.trial_deadline_s,
        "bit_error_rate": cell.ber, "trial_idx": task.trial_idx, "seed": task.seed,
        **{k: r[k] for k in RAW_FIELDS if k in r},
        "info_bits_delivered": info_bits, "wire_bits_sent": wire_bits,
    }


def _layout(arm: str, n: int, df: int, gen_size: int, field) -> tuple[int, int, int]:
    """(wire_symbols, seg_len_min, seg_len_max) measured from a real tagged source, so
    the bit accounting is whatever the scheme actually puts on the wire (salt included)."""
    from binary_ext_fields.segmented_tagging import build_segments
    packets, _ = make_scheme(arm, n, df).make_source(field, df, gen_size)
    data_lens = [s.length for s in build_segments(gen_size, df, n - 1) if s.kind != "coeff"]
    return len(packets[0]), min(data_lens), max(data_lens)


def _est_cost(cell: Cell, wire_symbols: int, seg_len_max: int) -> float:
    """Ordering heuristic only: expected flips per packet x per-segment search width."""
    return cell.ber * wire_symbols * (seg_len_max + GEN_SIZE + 1)


def _load_done(raw_path: Path) -> dict:
    """{(cell_key, trial_idx): wall_time_s} for rows already in raw_trials.csv."""
    done = {}
    if not raw_path.exists():
        return done
    with raw_path.open(newline="") as f:
        for row in csv.DictReader(f):
            cell = Cell(row["arm"], int(row["data_fields"]), int(row["n_segments"]),
                        float(row["bit_error_rate"]))
            done[(cell.key, int(row["trial_idx"]))] = float(row["wall_time_s"])
    return done


def run_sweep(arm, dfs, n_by_df, bers, trials, cell_budget_s, trial_deadline_s, workers,
              max_inflight_per_cell, pair_budget, out_root: Path, resume: Path | None) -> Path:
    field = create_field(FIELD_M)
    cfg = dict(hamming_distance=HAMMING_DISTANCE, pair_budget=pair_budget)
    cfg_obj = AdmitConfig(**cfg)

    run_dir = resume or out_root / f"{datetime.now():%Y%m%d_%H%M%S}_{arm}_gen{GEN_SIZE}_m{FIELD_M}_t{trials}"
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_path = run_dir / "raw_trials.csv"
    done = _load_done(raw_path)

    cells, layout = [], {}
    for df in dfs:
        for n in (n_by_df or {}).get(df) or n_values_for(df, GEN_SIZE):
            layout[(df, n)] = _layout(arm, n, df, GEN_SIZE, field)
            cells += [Cell(arm, df, n, ber) for ber in bers]
    cells.sort(key=lambda c: _est_cost(c, layout[(c.df, c.n)][0], layout[(c.df, c.n)][2]))

    (run_dir / "run_config.json").write_text(json.dumps({
        "schema_version": SCHEMA_VERSION, "arm": arm, "gen_size": GEN_SIZE, "field_m": FIELD_M,
        "strategy": STRATEGY, "admit_config": asdict(cfg_obj),
        "max_packets_factor": SEGMENTED_MAX_PACKETS_FACTOR, "trials": trials,
        "cell_budget_s": cell_budget_s, "trial_deadline_s": trial_deadline_s, "workers": workers,
        "max_inflight_per_cell": max_inflight_per_cell, "bers": bers,
        "configs": [{"df": df, "n": n, "wire_symbols": w, "seg_len_min": lo, "seg_len_max": hi}
                    for (df, n), (w, lo, hi) in sorted(layout.items())],
        "started": datetime.now().isoformat(timespec="seconds"),
    }, indent=2))

    spent = {c.key: 0.0 for c in cells}
    count = {c.key: 0 for c in cells}
    queue = []
    for c in cells:
        for t in range(trials):
            if (c.key, t) in done:
                spent[c.key] += done[(c.key, t)]
                count[c.key] += 1
            else:
                w, lo, hi = layout[(c.df, c.n)]
                queue.append(Task(c, t, _seed(c, t, GEN_SIZE, FIELD_M), GEN_SIZE, FIELD_M, cfg,
                                  SEGMENTED_MAX_PACKETS_FACTOR, trial_deadline_s, w, lo, hi))

    print(f"run_dir: {run_dir}")
    print(f"{len(cells)} cells, {len(queue)} trials queued ({len(done)} resumed), "
          f"workers={workers}, cell budget {cell_budget_s:g}s, trial deadline {trial_deadline_s}s")

    def eligible(task: Task) -> bool:
        k = task.cell.key
        return count[k] + inflight[k] == 0 or (spent[k] < cell_budget_s
                                               and inflight[k] < max_inflight_per_cell)

    inflight = {c.key: 0 for c in cells}
    skipped = 0
    new_file = not raw_path.exists()
    t0 = time.perf_counter()
    with raw_path.open("a", newline="") as f, ProcessPoolExecutor(max_workers=workers) as ex:
        writer = csv.DictWriter(f, fieldnames=RAW_FIELDS)
        if new_file:
            writer.writeheader()
            f.flush()
        futs = {}
        while queue or futs:
            # Drop trials of cells whose budget is spent and that have nothing in flight.
            kept = []
            for task in queue:
                k = task.cell.key
                if count[k] > 0 and spent[k] >= cell_budget_s and inflight[k] == 0:
                    skipped += 1
                else:
                    kept.append(task)
            queue = kept
            while len(futs) < workers:
                task = next((t for t in queue if eligible(t)), None)
                if task is None:
                    break
                queue.remove(task)
                inflight[task.cell.key] += 1
                futs[ex.submit(run_task, task)] = task
            if not futs:
                break
            finished, _ = wait(futs, return_when=FIRST_COMPLETED)
            for fut in finished:
                task = futs.pop(fut)
                k = task.cell.key
                inflight[k] -= 1
                row = fut.result()
                writer.writerow(row)
                f.flush()
                spent[k] += row["wall_time_s"]
                count[k] += 1
                eff = row["info_bits_delivered"] / row["wire_bits_sent"] if row["wire_bits_sent"] else 0.0
                print(f"[{time.perf_counter() - t0:7.0f}s] df={task.cell.df:<3} N={task.cell.n:<2} "
                      f"ber={task.cell.ber:.0e} t{task.trial_idx:<2} {row['status']:<13} "
                      f"ov={row['overhead']:.2f} eff={eff:.3f} ops={row['scheme_ops'] + row['decode_ops']:.3g} "
                      f"wall={row['wall_time_s']:.1f}s  cell {count[k]}/{trials} {spent[k]:.0f}s",
                      flush=True)

    print(f"done in {time.perf_counter() - t0:.0f}s; {skipped} trials skipped by cell budget")
    capped = [c for c in cells if count[c.key] < trials]
    for c in capped:
        print(f"  capped: df={c.df} N={c.n} ber={c.ber:.0e} -> {count[c.key]}/{trials} trials")
    return run_dir


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Keyless segmented Pareto sweep: N x df x BER.")
    p.add_argument("--stage", choices=list(STAGES), default="smoke")
    p.add_argument("--arm", choices=["keyless", "keyed"], default="keyless")
    p.add_argument("--configs", type=str, default=None,
                   help='override grid, e.g. "48:3,96:5" (df:N pairs; for keyed runs at Pareto points)')
    p.add_argument("--bers", type=str, default=None, help="comma list, overrides stage")
    p.add_argument("--trials", type=int, default=None)
    p.add_argument("--cell-budget-s", type=float, default=None)
    p.add_argument("--trial-deadline-s", type=float, default=None)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--max-inflight-per-cell", type=int, default=2)
    p.add_argument("--pair-budget", type=str, default="none", help='int or "none" (full HD-2 search)')
    p.add_argument("--out-root", type=Path, default=_ROOT / "logs" / "pareto_sweep")
    p.add_argument("--resume", type=Path, default=None, help="existing run dir to continue")
    a = p.parse_args(argv)

    st = dict(STAGES[a.stage])
    n_by_df = st["n_by_df"]
    dfs = st["dfs"]
    if a.configs:
        n_by_df = {}
        for pair in a.configs.split(","):
            df, n = (int(x) for x in pair.split(":"))
            n_by_df.setdefault(df, []).append(n)
        dfs = sorted(n_by_df)
    bers = [float(x) for x in a.bers.split(",")] if a.bers else st["bers"]
    run_sweep(arm=a.arm, dfs=dfs, n_by_df=n_by_df, bers=bers,
              trials=a.trials or st["trials"],
              cell_budget_s=a.cell_budget_s if a.cell_budget_s is not None else st["cell_budget_s"],
              trial_deadline_s=a.trial_deadline_s if a.trial_deadline_s is not None else st["trial_deadline_s"],
              workers=a.workers, max_inflight_per_cell=a.max_inflight_per_cell,
              pair_budget=None if a.pair_budget.lower() == "none" else int(a.pair_budget),
              out_root=a.out_root, resume=a.resume)


if __name__ == "__main__":
    main()
