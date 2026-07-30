"""ADR-0007: sweep bit-flip + cross-check packet recovery over a
bit-error-rate x Hamming-distance grid, comparing three search strategies.

- mode "per_column" (B): flip up to d bits within each byte-column independently
  (recovers single-corrupted-column packets).
- mode "whole_packet" (A): flip up to d bits anywhere in the packet
  (the exhaustive upper bound; recovers multi-column corruption within budget).
- mode "arc_localized" (C): ARC-localize the corrupted columns first, then run the
  per-column flip over only those columns -- same single-column repair as B at far
  lower ops. Needs a full-rank trusted basis, else it returns "waiting" (tracked as
  waiting_rate so a C-vs-B recovery gap is attributable to gate-miss, not search).

All three modes run on the *same* polluted pool per trial (paired), so per-cell
differences are signal, not sampling noise. Recovery runs through a CountingField
so mul_ops/add_ops reflect only recovery work (C's total includes ARC localization).

See playground/new_recovery.py for the recoverer itself.
"""

import csv
from dataclasses import dataclass, asdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from icecream import ic

# The recovery/sniffing modules debug-log via icecream on every call; silence it
# so a multi-thousand-trial sweep isn't drowned in per-packet dumps.
ic.disable()


from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import (
    generate_symbols_until_nonzero,
    recode_rlnc_without_coeffs,
)
from binary_ext_fields.pollution import pollute_generation, pollute_random
from playground.new_recovery import recover_generation_bitflip
from utils.log_helpers import get_run_log_dir, print_generation


# ── Sweep configuration ──────────────────────────────────────────────────────
FIELD_M = 8                 # GF(2^m), fixed so the BER x d grid stays readable
GEN_SIZE = 10               # packets needed for a full-rank trusted basis
DATA_FIELDS = 10             # data symbols per packet (before the tag)
POOL_SIZE = 2 * GEN_SIZE    # recode into a pool > gen_size so a trusted basis survives pollution
NUM_TRIALS = 100

# Kept deliberately small: per-packet corruption probability is (1-BER)^(packet_bits),
# so above ~0.008 almost no packet survives clean, the trusted basis never forms, and
# the recoverer only ever returns "waiting". This range keeps the single-corrupted-column
# regime (the one mode "per_column" targets) dominant while still exercising multi-column
# cases at the top end. Verified empirically 2026-07-23.
BIT_ERROR_RATES = [10e-6, 10e-6 *5, 10e-5, 10e-5 *5, 10e-4, 10e-4 * 5, 10e-3]
HAMMING_DISTANCES = [1]
MODES = ["per_column"] #"arc_localized" , "whole_packet"

# Oracle safety/ops tradeoff axis: how many trusted packets the acceptance oracle
# checks a repair against. GEN_SIZE (=12) is the safety floor -- orthogonality to
# that many independent packets pins a repair uniquely. Below it, wrong repairs
# start passing (silent failures); above it only buys redundancy at extra ops.
# Values straddle the floor so the tradeoff curve shows both sides.
VERIFY_COUNTS = [4]
# Reference point for the vs-BER plots, which fix verify_count so the BER lines
# stay readable. The tradeoff *over* verify_count gets its own vs-verify_count plots.
REFERENCE_VERIFY_COUNT = 4       #GEN_SIZE

# Per-trial original/polluted/recovered generation dumps: useful for eyeballing a
# single trial, catastrophic for a multi-thousand-trial sweep. Off by default
# (repo rule: concise structured logs over large print dumps).
DEBUG_DUMP = False


@dataclass
class RecoveryTrialResult:
    polluted_count: int         # packets actually changed by pollution (ground truth)
    recovered_correct: int      # repaired AND == original
    silent_failures: int        # repaired to something != original  <- the safety number
    unrecovered: int            # left as polluted (incl. sniff misses)
    mul_ops: int                # CountingField, recovery only
    add_ops: int                # CountingField, recovery only
    status: str                 # recover_generation_bitflip verdict


def _score(original, polluted, recovered) -> tuple[int, int, int, int]:
    """Packet-by-packet outcome, counting only packets that were actually polluted.

    A polluted packet is: recovered_correct if the recoverer restored the
    original; silent_failure if the recoverer changed it to a *different* wrong
    value (an oracle-accepted wrong repair); unrecovered if left untouched
    (no accepted flip, or a sniff miss that was never attempted).
    """
    polluted_count = recovered_correct = silent_failures = unrecovered = 0
    for orig, poll, rec in zip(original, polluted, recovered):
        if poll == orig:
            continue  # this packet was not corrupted
        polluted_count += 1
        if rec == orig:
            recovered_correct += 1
        elif rec != poll:
            silent_failures += 1
        else:
            unrecovered += 1
    return polluted_count, recovered_correct, silent_failures, unrecovered


def run_paired_trial(base_field, data_fields, gen_size, pool_size, bit_error_rate, hamming_distance, modes=tuple(MODES), verify_counts=tuple(VERIFY_COUNTS)) -> dict:
    """One trial: build a clean pairwise-orthogonal pool, pollute it once, then run
    every (mode, verify_count) combination on that same polluted pool. Pairing
    across both axes on one pool keeps per-cell differences signal, not noise.
    Returns {(mode, verify_count): RecoveryTrialResult}.
    """
    source = generate_symbols_until_nonzero(base_field, data_fields, gen_size, coefficients=True)
    pool = recode_rlnc_without_coeffs(base_field, source, gen_size, count=pool_size)
    original = [bytearray(p) for p in pool]
    polluted = pollute_generation(base_field, pool, bit_error_rate, pollute_random)

    results = {}
    for mode in modes:
        for vc in verify_counts:
            # Fresh CountingField per run starts both counters at zero; wraps the
            # base field's tables so orthogonality results are identical.
            cnt_field = CountingField(base_field)
            recovered, status = recover_generation_bitflip(
                cnt_field, polluted, gen_size, hamming_distance, mode=mode, verify_count=vc
            )
            pc, rc, sf, ur = _score(original, polluted, recovered)
            results[(mode, vc)] = RecoveryTrialResult(
                polluted_count=pc,
                recovered_correct=rc,
                silent_failures=sf,
                unrecovered=ur,
                mul_ops=cnt_field.mul_count,
                add_ops=cnt_field.add_count,
                status=status,
            )
            if DEBUG_DUMP:
                print(f"====== {mode} verify_count={vc} ======")
                print("--- ORIGINAL ---");  print_generation(original)
                print("--- Polluted ---");  print_generation(polluted)
                print("--- Recovered ---"); print_generation(recovered)
    return results


def smoke_test(field_m: int = FIELD_M,
    gen_size: int = GEN_SIZE,
    data_fields: int = DATA_FIELDS,
    pool_size: int = POOL_SIZE,
    bit_error_rate: float = 0.001,
    hamming_distance: int = 1,
    modes: list[str] = MODES,
    verify_counts: list[int] = VERIFY_COUNTS,
) -> None:
    """One paired trial, printed as a table -- a quick sanity check that every
    (mode, verify_count) runs and the scores/ops look sane. No CSV or plots (use
    run_sweep for those)."""
    base_field = create_field(field_m)
    results = run_paired_trial(base_field, data_fields, gen_size, pool_size,
                               bit_error_rate, hamming_distance, modes, verify_counts)
    print(f"\nsmoke_test  BER={bit_error_rate}  d={hamming_distance}")
    print(f"{'mode':14} {'vc':>3} {'status':10} {'poll':>4} {'ok':>3} {'silent':>6} {'unrec':>5} {'mul':>8}")
    for (m, vc), r in results.items():
        print(f"{m:14} {vc:>3} {r.status:10} {r.polluted_count:>4} {r.recovered_correct:>3} "
              f"{r.silent_failures:>6} {r.unrecovered:>5} {r.mul_ops:>8}")


def run_sweep(
    field_m: int = FIELD_M,
    gen_size: int = GEN_SIZE,
    data_fields: int = DATA_FIELDS,
    pool_size: int = POOL_SIZE,
    num_trials: int = NUM_TRIALS,
    bit_error_rates: list[float] = BIT_ERROR_RATES,
    hamming_distances: list[int] = HAMMING_DISTANCES,
    modes: list[str] = MODES,
    verify_counts: list[int] = VERIFY_COUNTS,
    reference_verify_count: int = REFERENCE_VERIFY_COUNT,
) -> Path:
    run_dir = get_run_log_dir("recovery_sim", trials=num_trials, gen=gen_size, m=field_m)
    base_field = create_field(field_m)

    raw_rows = []
    summary_rows = []

    for ber in bit_error_rates:
        for d in hamming_distances:
            print(f"=== BER={ber}  d={d} ===")
            # Per (cell, mode, verify_count) running totals over trials.
            totals = {(m, vc): {"polluted": 0, "correct": 0, "silent": 0, "unrec": 0,
                                "waiting": 0, "mul": [], "add": []}
                      for m in modes for vc in verify_counts}

            for trial_id in range(num_trials):
                results = run_paired_trial(base_field, data_fields, gen_size, pool_size, ber, d, modes, verify_counts)
                for (m, vc), r in results.items():
                    raw_rows.append({
                        "bit_error_rate": ber,
                        "hamming_distance": d,
                        "mode": m,
                        "verify_count": vc,
                        "trial_id": trial_id,
                        **asdict(r),
                    })
                    t = totals[(m, vc)]
                    t["polluted"] += r.polluted_count
                    t["correct"] += r.recovered_correct
                    t["silent"] += r.silent_failures
                    t["unrec"] += r.unrecovered
                    # Diagnostic (Q3): a "waiting" trial recovered nothing because it
                    # never had a usable basis -- for mode C this is the full-rank gate
                    # miss. Counted per trial so a C-vs-B recovery gap is explainable.
                    if r.status == "waiting":
                        t["waiting"] += 1
                    t["mul"].append(r.mul_ops)
                    t["add"].append(r.add_ops)

            for m in modes:
                for vc in verify_counts:
                    t = totals[(m, vc)]
                    polluted = t["polluted"]
                    summary_rows.append({
                        "bit_error_rate": ber,
                        "hamming_distance": d,
                        "mode": m,
                        "verify_count": vc,
                        "polluted_total": polluted,
                        "recovery_rate": (t["correct"] / polluted) if polluted else 0.0,
                        "silent_failure_rate": (t["silent"] / polluted) if polluted else 0.0,
                        "unrecovered_rate": (t["unrec"] / polluted) if polluted else 0.0,
                        "waiting_rate": (t["waiting"] / num_trials) if num_trials else 0.0,
                        "mul_ops_mean": float(np.mean(t["mul"])),
                        "add_ops_mean": float(np.mean(t["add"])),
                    })

    _write_csv(run_dir / "raw_results.csv", raw_rows)
    _write_csv(run_dir / "summary.csv", summary_rows)

    # ── vs-BER plots: fix verify_count at the reference so BER lines stay readable ──
    _plot_metric_vs_ber(summary_rows, hamming_distances, modes, "recovery_rate",
                        "Recovery rate (correct / polluted)", run_dir / "recovery_rate_vs_ber.png",
                        verify_count=reference_verify_count)
    _plot_metric_vs_ber(summary_rows, hamming_distances, modes, "silent_failure_rate",
                        "Silent-failure rate (wrong repair / polluted)", run_dir / "silent_failure_rate_vs_ber.png",
                        verify_count=reference_verify_count)
    _plot_metric_vs_ber(summary_rows, hamming_distances, modes, "mul_ops_mean",
                        "Mean mul-ops per recovery", run_dir / "mul_ops_vs_ber.png",
                        verify_count=reference_verify_count, ylim=None)
    _plot_metric_vs_ber(summary_rows, hamming_distances, modes, "waiting_rate",
                        "Waiting rate (trials with no usable basis)", run_dir / "waiting_rate_vs_ber.png",
                        verify_count=reference_verify_count)

    # ── vs-verify_count plots: the oracle safety/ops tradeoff, at the top BER where ──
    # recovery is actually exercised. silent_failure_rate (safety cost) should climb
    # as verify_count drops below gen_size; mul_ops_mean (savings) should fall.
    #tradeoff_ber = max(bit_error_rates)
    d0 = hamming_distances[0]
    for tradeoff_ber in bit_error_rates:

        _plot_metric_vs_verify_count(summary_rows, tradeoff_ber, d0, modes, gen_size, "silent_failure_rate",
                                    "Silent-failure rate (wrong repair / polluted)",
                                    run_dir / f"silent_failure_rate_vs_verify_count_ber_{tradeoff_ber}.png")
        _plot_metric_vs_verify_count(summary_rows, tradeoff_ber, d0, modes, gen_size, "recovery_rate",
                                    "Recovery rate (correct / polluted)",
                                    run_dir / f"recovery_rate_vs_verify_count_ber_{tradeoff_ber}.png")
        _plot_metric_vs_verify_count(summary_rows, tradeoff_ber, d0, modes, gen_size, "mul_ops_mean",
                                    "Mean mul-ops per recovery",
                                    run_dir / f"mul_ops_vs_verify_count_ber_{tradeoff_ber}.png", ylim=None)

    print(f"\nDone. Results written to: {run_dir}")
    return run_dir


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written: {path}")


_MODE_STYLE = {"per_column": "-", "whole_packet": "--", "arc_localized": ":"}


def _plot_metric_vs_ber(summary_rows, hamming_distances, modes, metric, ylabel, output_path, verify_count, ylim=(-0.02, 1.02)) -> None:
    """Line plot: `metric` vs bit-error-rate, one line per (mode, d), at a fixed
    `verify_count` (so the oracle-breadth axis doesn't multiply the lines).
    Solid = per_column (B), dashed = whole_packet (A), dotted = arc_localized (C);
    colour = Hamming distance. `ylim=None` autoscales (for op-count plots, which
    aren't bounded to [0, 1] like the rate metrics).
    """
    fig, ax = plt.subplots(figsize=(9, 6))
    colors = plt.cm.viridis(np.linspace(0.15, 0.85, len(hamming_distances)))

    for color, d in zip(colors, hamming_distances):
        for m in modes:
            points = sorted(
                (row["bit_error_rate"], row[metric])
                for row in summary_rows
                if row["hamming_distance"] == d and row["mode"] == m and row["verify_count"] == verify_count
            )
            if not points:
                continue
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            ax.plot(xs, ys, _MODE_STYLE.get(m, "-"), marker="o", color=color, linewidth=2,
                    markersize=5, label=f"{m}, d={d}")

    ax.set_xscale("log")
    ax.set_xlabel("Bit error rate", fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
    ax.set_title(f"{ylabel} vs bit error rate (verify_count={verify_count})", fontsize=13, fontweight="bold")
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {output_path}")


def _plot_metric_vs_verify_count(summary_rows, ber, d, modes, gen_size, metric, ylabel, output_path, ylim=(-0.02, 1.02)) -> None:
    """The oracle safety/ops tradeoff: `metric` vs verify_count, one line per mode,
    at a fixed (BER, d). A vertical marker sits at gen_size -- the safety floor
    below which the acceptance oracle is underdetermined. `ylim=None` autoscales.
    """
    fig, ax = plt.subplots(figsize=(9, 6))
    colors = plt.cm.plasma(np.linspace(0.15, 0.8, len(modes)))

    for color, m in zip(colors, modes):
        points = sorted(
            (row["verify_count"], row[metric])
            for row in summary_rows
            if row["bit_error_rate"] == ber and row["hamming_distance"] == d and row["mode"] == m
        )
        if not points:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ax.plot(xs, ys, _MODE_STYLE.get(m, "-"), marker="o", color=color, linewidth=2,
                markersize=5, label=m)

    ax.set_xscale("log")
    ax.axvline(gen_size, color="grey", linestyle="-.", alpha=0.6, label=f"gen_size={gen_size} (safety floor)")
    ax.set_xlabel("verify_count (trusted packets checked by oracle)", fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
    ax.set_title(f"{ylabel} vs verify_count (BER={ber}, d={d})", fontsize=13, fontweight="bold")
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {output_path}")


if __name__ == "__main__":
    run_sweep()

    #smoke_test()
