"""ADR-0007: sweep bit-flip + cross-check packet recovery over a
bit-error-rate x Hamming-distance grid, comparing two search strategies.

- mode "per_column" (B): flip up to d bits within each byte-column independently
  (the method under study; recovers single-corrupted-column packets).
- mode "whole_packet" (A): flip up to d bits anywhere in the packet
  (the exhaustive upper bound; recovers multi-column corruption within budget).

Both modes run on the *same* polluted pool per trial (paired), so per-cell
differences are signal, not sampling noise. Recovery runs through a CountingField
so mul_ops/add_ops reflect only recovery work.

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
GEN_SIZE = 12               # packets needed for a full-rank trusted basis
DATA_FIELDS = 5             # data symbols per packet (before the tag)
POOL_SIZE = 3 * GEN_SIZE    # recode into a pool > gen_size so a trusted basis survives pollution
NUM_TRIALS = 100

# Kept deliberately small: per-packet corruption probability is (1-BER)^(packet_bits),
# so above ~0.008 almost no packet survives clean, the trusted basis never forms, and
# the recoverer only ever returns "waiting". This range keeps the single-corrupted-column
# regime (the one mode "per_column" targets) dominant while still exercising multi-column
# cases at the top end. Verified empirically 2026-07-23.
BIT_ERROR_RATES = [10e-6, 10e-6 *5, 10e-5, 10e-5 *5, 10e-4, 10e-4 * 5, 10e-3]
HAMMING_DISTANCES = [1]
MODES = ["per_column"] # "whole_packet"


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


def run_paired_trial(base_field, data_fields, gen_size, pool_size, bit_error_rate, hamming_distance, modes=tuple(MODES)) -> dict:
    """One trial: build a clean pairwise-orthogonal pool, pollute it once, then
    run every mode on that same polluted pool. Returns {mode: RecoveryTrialResult}.
    """
    source = generate_symbols_until_nonzero(base_field, data_fields, gen_size, coefficients=True)
    pool = recode_rlnc_without_coeffs(base_field, source, gen_size, count=pool_size)
    original = [bytearray(p) for p in pool]
    polluted = pollute_generation(base_field, pool, bit_error_rate, pollute_random)

    results = {}
    for mode in modes:
        # Fresh CountingField per mode starts both counters at zero; wraps the
        # base field's tables so orthogonality results are identical.
        cnt_field = CountingField(base_field)
        recovered, status = recover_generation_bitflip(
            cnt_field, polluted, gen_size, hamming_distance, mode=mode
        )
        pc, rc, sf, ur = _score(original, polluted, recovered)
        results[mode] = RecoveryTrialResult(
            polluted_count=pc,
            recovered_correct=rc,
            silent_failures=sf,
            unrecovered=ur,
            mul_ops=cnt_field.mul_count,
            add_ops=cnt_field.add_count,
            status=status,
        )
        print("====== ORIGINAL ======")
        print_generation(original)
        print("====== Polluted ======")
        print_generation(polluted)
        print("====== Recovered ======")
        print_generation(recovered)
    return results


#TODO: remove if not longer necessary
def smoke_test(field_m: int = FIELD_M,
    gen_size: int = GEN_SIZE,
    data_fields: int = DATA_FIELDS,
    pool_size: int = POOL_SIZE,
    num_trials: int = NUM_TRIALS,
    bit_error_rate: float = 0.0001,
    hamming_distances: list[int] = [1],
    modes: list[str] = MODES,
) -> Path:
    run_dir = get_run_log_dir("smoke_test", trials=num_trials, gen=gen_size, m=field_m)
    base_field = create_field(field_m)

    raw_rows = []
    summary_rows = []
    trial_id = 1

    totals = {m: {"polluted": 0, "correct": 0, "silent": 0, "unrec": 0,
                          "mul": [], "add": []} for m in modes}

    results = run_paired_trial(base_field, data_fields, gen_size, pool_size, bit_error_rate, hamming_distances[0], modes)


    for m, r in results.items():
                    raw_rows.append({
                        "bit_error_rate": bit_error_rate,
                        "hamming_distance": hamming_distances[0],
                        "mode": m,
                        "trial_id": trial_id,
                        **asdict(r),
                    })
                    t = totals[m]
                    t["polluted"] += r.polluted_count
                    t["correct"] += r.recovered_correct
                    t["silent"] += r.silent_failures
                    t["unrec"] += r.unrecovered
                    t["mul"].append(r.mul_ops)
                    t["add"].append(r.add_ops)

    _write_csv(run_dir / "raw_results.csv", raw_rows)
    _write_csv(run_dir / "summary.csv", summary_rows)
    _plot_metric_vs_ber(summary_rows, hamming_distances, modes, "recovery_rate",
                        "Recovery rate (correct / polluted)", run_dir / "recovery_rate_vs_ber.png")
    _plot_metric_vs_ber(summary_rows, hamming_distances, modes, "silent_failure_rate",
                        "Silent-failure rate (wrong repair / polluted)", run_dir / "silent_failure_rate_vs_ber.png")


def run_sweep(
    field_m: int = FIELD_M,
    gen_size: int = GEN_SIZE,
    data_fields: int = DATA_FIELDS,
    pool_size: int = POOL_SIZE,
    num_trials: int = NUM_TRIALS,
    bit_error_rates: list[float] = BIT_ERROR_RATES,
    hamming_distances: list[int] = HAMMING_DISTANCES,
    modes: list[str] = MODES,
) -> Path:
    run_dir = get_run_log_dir("recovery_sim", trials=num_trials, gen=gen_size, m=field_m)
    base_field = create_field(field_m)

    raw_rows = []
    summary_rows = []

    for ber in bit_error_rates:
        for d in hamming_distances:
            print(f"=== BER={ber}  d={d} ===")
            # Per (cell, mode) running totals over trials.
            totals = {m: {"polluted": 0, "correct": 0, "silent": 0, "unrec": 0,
                          "mul": [], "add": []} for m in modes}

            for trial_id in range(num_trials):
                results = run_paired_trial(base_field, data_fields, gen_size, pool_size, ber, d, modes)
                for m, r in results.items():
                    raw_rows.append({
                        "bit_error_rate": ber,
                        "hamming_distance": d,
                        "mode": m,
                        "trial_id": trial_id,
                        **asdict(r),
                    })
                    t = totals[m]
                    t["polluted"] += r.polluted_count
                    t["correct"] += r.recovered_correct
                    t["silent"] += r.silent_failures
                    t["unrec"] += r.unrecovered
                    t["mul"].append(r.mul_ops)
                    t["add"].append(r.add_ops)

            for m in modes:
                t = totals[m]
                polluted = t["polluted"]
                summary_rows.append({
                    "bit_error_rate": ber,
                    "hamming_distance": d,
                    "mode": m,
                    "polluted_total": polluted,
                    "recovery_rate": (t["correct"] / polluted) if polluted else 0.0,
                    "silent_failure_rate": (t["silent"] / polluted) if polluted else 0.0,
                    "unrecovered_rate": (t["unrec"] / polluted) if polluted else 0.0,
                    "mul_ops_mean": float(np.mean(t["mul"])),
                    "add_ops_mean": float(np.mean(t["add"])),
                })

    _write_csv(run_dir / "raw_results.csv", raw_rows)
    _write_csv(run_dir / "summary.csv", summary_rows)
    _plot_metric_vs_ber(summary_rows, hamming_distances, modes, "recovery_rate",
                        "Recovery rate (correct / polluted)", run_dir / "recovery_rate_vs_ber.png")
    _plot_metric_vs_ber(summary_rows, hamming_distances, modes, "silent_failure_rate",
                        "Silent-failure rate (wrong repair / polluted)", run_dir / "silent_failure_rate_vs_ber.png")

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


def _plot_metric_vs_ber(summary_rows, hamming_distances, modes, metric, ylabel, output_path) -> None:
    """Line plot: `metric` vs bit-error-rate, one line per (mode, d).
    Solid = per_column (B), dashed = whole_packet (A); colour = Hamming distance.
    """
    fig, ax = plt.subplots(figsize=(9, 6))
    colors = plt.cm.viridis(np.linspace(0.15, 0.85, len(hamming_distances)))
    style = {"per_column": "-", "whole_packet": "--"}

    for color, d in zip(colors, hamming_distances):
        for m in modes:
            points = sorted(
                (row["bit_error_rate"], row[metric])
                for row in summary_rows
                if row["hamming_distance"] == d and row["mode"] == m
            )
            if not points:
                continue
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            ax.plot(xs, ys, style.get(m, "-"), marker="o", color=color, linewidth=2,
                    markersize=5, label=f"{m}, d={d}")

    ax.set_xlabel("Bit error rate", fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
    ax.set_title(f"{ylabel} vs bit error rate", fontsize=13, fontweight="bold")
    ax.set_ylim(-0.02, 1.02)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {output_path}")


if __name__ == "__main__":
    #run_sweep()

    smoke_test()
