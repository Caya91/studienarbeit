"""Pool multiple gensize_overhead runs into one higher-accuracy dataset.

Every run writes raw_results.csv (one row per trial). Accuracy comes from TRIAL COUNT,
so the right way to "get more data every time" is to keep the raw trials and recompute
the summary over the union -- NOT to average per-run means (which would weight a 1-trial
capped cell the same as a 40-trial one). This script does exactly that: concatenate the
raw rows from several run dirs, group by (scheme, gen_size, BER), and recompute
mean_overhead_decoded (+ std, rates) over ALL pooled trials, then redraw the plots.

Merge safety: a cell is only meaningful if every pooled trial used the same admit config
(hamming_distance, min_pool_size). New-format runs record both columns per row; if a cell
mixes configs the majority config wins and the rest are dropped with a warning. Legacy
runs (pre-config-column) are skipped by default -- pass --allow-legacy to force them in
(only safe when you know their config matches, e.g. gen>=10 where min_pool_size is 10
either way).

Usage:
    .venv/Scripts/python.exe scripts/gensize_overhead_aggregate.py \
        --runs logs/gensize_overhead_sweep/<runA> logs/gensize_overhead_sweep/<runB> \
        --out  logs/gensize_overhead_sweep/aggregate
    # or point at the parent and take every run:
    .venv/Scripts/python.exe scripts/gensize_overhead_aggregate.py \
        --glob "logs/gensize_overhead_sweep/2026*n5*" --out logs/gensize_overhead_sweep/aggregate_n5

Re-running with the SAME --out after a fresh sweep folds the new trials in (idempotent:
it recomputes from the raw union each time, so pointing at the same set twice is fine).
"""

import argparse
import csv
import glob as globmod
from collections import defaultdict
from pathlib import Path

from gensize_overhead_replot import replot  # same-dir import (scripts/ on sys.path)

CONFIG_COLS = ("hamming_distance", "min_pool_size")


def _load_raw(run_dir: Path, allow_legacy: bool):
    """Yield normalized trial rows from one run's raw_results.csv. Returns [] (with a
    warning) for a legacy run missing the config columns unless allow_legacy."""
    path = run_dir / "raw_results.csv"
    if not path.exists():
        print(f"  [skip] no raw_results.csv in {run_dir}")
        return []
    reader = csv.DictReader(path.open())
    legacy = not set(CONFIG_COLS).issubset(reader.fieldnames or [])
    if legacy and not allow_legacy:
        print(f"  [skip legacy] {run_dir.name} has no {CONFIG_COLS} columns "
              f"(pass --allow-legacy to force)")
        return []
    rows = []
    for r in reader:
        rows.append({
            "scheme_key": r["scheme_key"], "scheme": r["scheme"],
            "gen_size": int(r["gen_size"]), "data_fields": int(r["data_fields"]),
            "bit_error_rate": float(r["bit_error_rate"]),
            "hamming_distance": None if legacy else int(r["hamming_distance"]),
            "min_pool_size": None if legacy else int(r["min_pool_size"]),
            "overhead": float(r["overhead"]),
            "decoded": r["decoded"] == "True", "correct": r["correct"] == "True",
            "status": r["status"], "wall_time_s": float(r["wall_time_s"]),
            "_source": run_dir.name,
        })
    print(f"  [ok] {run_dir.name}: {len(rows)} trials"
          + ("  (LEGACY, forced)" if legacy else ""))
    return rows


def _config_filter(cell_rows):
    """Keep only rows matching the majority (hamming_distance, min_pool_size) config in a
    cell; None (legacy) configs are treated as compatible with the majority. Returns
    (kept_rows, dropped_count, chosen_config)."""
    counts = defaultdict(int)
    for r in cell_rows:
        cfg = (r["hamming_distance"], r["min_pool_size"])
        if cfg != (None, None):
            counts[cfg] += 1
    if not counts:
        return cell_rows, 0, (None, None)          # all legacy -- nothing to reconcile
    chosen = max(counts, key=counts.get)
    kept, dropped = [], 0
    for r in cell_rows:
        cfg = (r["hamming_distance"], r["min_pool_size"])
        if cfg == (None, None) or cfg == chosen:   # legacy rides along with the majority
            kept.append(r)
        else:
            dropped += 1
    return kept, dropped, chosen


def aggregate(run_dirs, out_dir: Path, allow_legacy: bool, seg_label: str) -> Path:
    all_rows = []
    for d in run_dirs:
        all_rows += _load_raw(Path(d), allow_legacy)
    if not all_rows:
        raise SystemExit("No usable trials found in the given runs.")

    cells = defaultdict(list)
    for r in all_rows:
        cells[(r["scheme_key"], r["scheme"], r["gen_size"], r["data_fields"],
               r["bit_error_rate"])].append(r)

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_out, summary_out = [], []
    for (scheme_key, scheme, gen_size, data_fields, ber), rows in sorted(cells.items()):
        rows, dropped, chosen = _config_filter(rows)
        if dropped:
            print(f"  [config mismatch] scheme={scheme} gen={gen_size} BER={ber:g}: "
                  f"dropped {dropped} trial(s) not matching config hd/min_pool={chosen}")
        for r in rows:
            raw_out.append(r)
        decoded = [r for r in rows if r["decoded"]]
        n = len(rows)
        mean_ovh = sum(r["overhead"] for r in decoded) / len(decoded) if decoded else float("nan")
        var = (sum((r["overhead"] - mean_ovh) ** 2 for r in decoded) / len(decoded)
               if decoded else float("nan"))
        summary_out.append({
            "scheme_key": scheme_key, "scheme": scheme,
            "gen_size": gen_size, "data_fields": data_fields, "bit_error_rate": ber,
            "hamming_distance": chosen[0], "min_pool_size": chosen[1],
            "trials_run": n, "n_runs": len({r["_source"] for r in rows}),
            "correct_rate": sum(r["correct"] for r in rows) / n,
            "decode_success_rate": len(decoded) / n,
            "timeout_rate": sum(r["status"] == "timeout" for r in rows) / n,
            "mean_overhead_decoded": mean_ovh,
            "std_overhead_decoded": var ** 0.5 if var == var else float("nan"),
            "wall_time_s_mean": sum(r["wall_time_s"] for r in rows) / n,
        })

    _write_csv(out_dir / "raw_results.csv", raw_out,
               fields=["scheme_key", "scheme", "gen_size", "data_fields", "bit_error_rate",
                       "hamming_distance", "min_pool_size", "overhead", "decoded", "correct",
                       "status", "wall_time_s", "_source"])
    _write_csv(out_dir / "summary.csv", summary_out, fields=list(summary_out[0].keys()))
    replot(out_dir, 0, 1e9, seg_label)   # full-range plots from the pooled summary
    print(f"\nAggregated {len(all_rows)} trials from {len(run_dirs)} run(s) -> {out_dir}")
    return out_dir


def _write_csv(path: Path, rows, fields) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Written: {path}  ({len(rows)} rows)")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Pool gensize_overhead runs into one dataset.")
    parser.add_argument("--runs", nargs="*", default=[], help="explicit run dirs to pool")
    parser.add_argument("--glob", default=None, help="glob of run dirs to pool (alternative to --runs)")
    parser.add_argument("--out", required=True, help="output aggregate dir (reuse to keep folding in)")
    parser.add_argument("--allow-legacy", action="store_true",
                        help="include runs missing config columns (only safe if config matches)")
    parser.add_argument("--seg-label", default="segmented (N=5)")
    args = parser.parse_args(argv)

    run_dirs = list(args.runs)
    if args.glob:
        run_dirs += sorted(globmod.glob(args.glob))
    if not run_dirs:
        raise SystemExit("Give --runs and/or --glob.")
    # Don't pool an --out that sits inside the glob back into itself.
    out = Path(args.out).resolve()
    run_dirs = [d for d in run_dirs if Path(d).resolve() != out]
    aggregate(run_dirs, Path(args.out), args.allow_legacy, args.seg_label)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
