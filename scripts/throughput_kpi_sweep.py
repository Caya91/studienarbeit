"""Sweeps field size x generation size and measures clean-channel throughput
KPIs for the orthogonal-tag RLNC algorithm.

See docs/adr/0005-tick-based-simulation-and-goodput-metric.md and
docs/adr/0006-relay-topology-and-forwarding-policy.md for the design behind
this sweep.
"""

import csv
from pathlib import Path

from binary_ext_fields.custom_field import create_field

from simulation.network_sim import run_trial
from simulation.kpi_metrics import derive_kpis, summarize, KPISummary

from utils.log_helpers import get_run_log_dir
from utils.plot_utils import plot_kpi_vs_field_size

FIELDS = list(range(5, 9))
GEN_SIZES = [8, 16, 32]
DATA_FIELDS = 50
NUM_TRIALS = 100


def run_sweep(
    fields: list[int] = FIELDS,
    gen_sizes: list[int] = GEN_SIZES,
    data_fields: int = DATA_FIELDS,
    num_trials: int = NUM_TRIALS,
) -> Path:
    run_dir = get_run_log_dir("throughput_kpi_sweep", trials=num_trials, data_fields=data_fields)

    raw_rows = []
    summaries: list[KPISummary] = []

    for m in fields:
        field = create_field(m)
        field_size = field.max_value + 1

        for gen_size in gen_sizes:
            print(f"=== field=GF(2^{m}) ({field_size})  gen_size={gen_size} ===")
            trial_kpis = []

            for trial_id in range(num_trials):
                result = run_trial(field, data_fields, gen_size)
                kpis = derive_kpis(result, gen_size, data_fields)
                trial_kpis.append(kpis)

                raw_rows.append({
                    "field_size": field_size,
                    "gen_size": gen_size,
                    "trial_id": trial_id,
                    "ticks_to_full_rank": kpis.ticks_to_full_rank,
                    "goodput": kpis.goodput,
                    "redundancy": kpis.redundancy,
                    "tag_overhead_ratio": kpis.tag_overhead_ratio,
                })

            summaries.append(summarize(trial_kpis, field_size, gen_size))

    _write_raw_csv(run_dir / "raw_results.csv", raw_rows)
    _write_summary_csv(run_dir / "summary.csv", summaries)
    _plot_summaries(summaries, gen_sizes, run_dir)

    return run_dir


def _write_raw_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Raw results written to: {path}")


def _write_summary_csv(path: Path, summaries: list[KPISummary]) -> None:
    if not summaries:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(vars(summaries[0]).keys()))
        writer.writeheader()
        for s in summaries:
            writer.writerow(vars(s))
    print(f"Summary written to: {path}")


def _plot_summaries(summaries: list[KPISummary], gen_sizes: list[int], run_dir: Path) -> None:
    plot_kpi_vs_field_size(
        summaries, gen_sizes, "goodput_mean", "goodput_std",
        "Goodput (payload symbols / tick)", run_dir / "goodput_vs_field.png",
    )
    plot_kpi_vs_field_size(
        summaries, gen_sizes, "ticks_mean", "ticks_std",
        "Time to full rank (ticks)", run_dir / "time_to_full_rank_vs_field.png",
    )
    plot_kpi_vs_field_size(
        summaries, gen_sizes, "redundancy_mean", "redundancy_std",
        "Redundancy (packets sent / gen_size)", run_dir / "redundancy_vs_field.png",
    )
    plot_kpi_vs_field_size(
        summaries, gen_sizes, "tag_overhead_ratio", None,
        "Tag overhead ratio (tag symbols / payload symbols)", run_dir / "tag_overhead_ratio_vs_field.png",
    )


if __name__ == "__main__":
    result_dir = run_sweep()
    print(f"\nDone. Results written to: {result_dir}")
