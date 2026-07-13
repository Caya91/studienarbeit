"""KPI derivations from raw simulation.network_sim.TrialResult data.

See docs/adr/0005-tick-based-simulation-and-goodput-metric.md for why
goodput (not raw packet rate) is the primary throughput metric, and
CONTEXT.md's "Throughput simulation" section for the Tick / Goodput /
Source-Relay-Sink glossary.
"""

import statistics
from dataclasses import dataclass

from simulation.network_sim import TrialResult


@dataclass
class TrialKPIs:
    goodput: float | None       # payload symbols recovered per tick (None if full rank was never reached)
    ticks_to_full_rank: int | None
    redundancy: float | None    # packets sent through the network / gen_size (None if full rank was never reached)
    tag_overhead_ratio: float   # tag symbols / payload symbols, per packet


def derive_kpis(result: TrialResult, gen_size: int, data_fields: int) -> TrialKPIs:
    reached = result.ticks_to_full_rank is not None
    goodput = (result.payload_symbols / result.ticks_to_full_rank) if reached else None
    redundancy = (result.packets_sent / gen_size) if reached else None
    tag_overhead_ratio = gen_size / data_fields

    return TrialKPIs(
        goodput=goodput,
        ticks_to_full_rank=result.ticks_to_full_rank,
        redundancy=redundancy,
        tag_overhead_ratio=tag_overhead_ratio,
    )


@dataclass
class KPISummary:
    field_size: int
    gen_size: int
    num_trials: int
    reached_full_rank: int
    goodput_mean: float
    goodput_std: float
    ticks_mean: float
    ticks_std: float
    redundancy_mean: float
    redundancy_std: float
    tag_overhead_ratio: float


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = statistics.mean(values)
    std = statistics.stdev(values) / (len(values) ** 0.5) if len(values) > 1 else 0.0
    return mean, std


def summarize(trials: list[TrialKPIs], field_size: int, gen_size: int) -> KPISummary:
    reached = [t for t in trials if t.goodput is not None]

    goodput_mean, goodput_std = _mean_std([t.goodput for t in reached])
    ticks_mean, ticks_std = _mean_std([t.ticks_to_full_rank for t in reached])
    redundancy_mean, redundancy_std = _mean_std([t.redundancy for t in reached])

    return KPISummary(
        field_size=field_size,
        gen_size=gen_size,
        num_trials=len(trials),
        reached_full_rank=len(reached),
        goodput_mean=goodput_mean,
        goodput_std=goodput_std,
        ticks_mean=ticks_mean,
        ticks_std=ticks_std,
        redundancy_mean=redundancy_mean,
        redundancy_std=redundancy_std,
        tag_overhead_ratio=trials[0].tag_overhead_ratio if trials else 0.0,
    )
