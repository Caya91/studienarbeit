"""Incremental RLNC recovery+decode sweep -- the sequential companion to the
one-shot recovery_sim.py.

recovery_sim.py builds a *fixed* pool, pollutes it once, recovers once, and treats
"waiting" (not enough trusted packets for a basis) as a terminal dead-end. That is
not how RLNC works: the source keeps injecting fresh recoded combinations until the
receiver holds gen_size independent, clean-or-repaired packets, i.e. until decoding
is possible. This module models that.

Per trial we loop over *arrivals*: each round one fresh recoded packet is generated
(new random coefficient row), polluted at the BER, and appended to a growing pool.
Recovery runs on the accumulated pool each round; "waiting" just means loop again.
We stop when the accepted (self-check-passing = clean or repaired) packets reach
full rank -- decodable -- or when a packet-count cap is hit (undecoded within budget).

The headline metrics shift accordingly:
- decode_success_rate: fraction of trials that reached full rank before the cap.
- overhead = packets_received / gen_size: the classic RLNC coding-overhead curve
  (>=1; climbs with BER as more transmissions are needed to net gen_size good ones).
- silent_decode_rate: trials that reached full rank but decoded to the WRONG source
  (a silent-failure repair admitted into the basis). In the one-shot sim a silent
  failure loses one packet; here it corrupts the entire decoded generation -- the
  real safety story. Ground-truthed by actually re-decoding (calculate_rref +
  invert_pivot_rows) and comparing the decoded symbols against the known source.
- mul_ops: cumulative recovery + decode-attempt work to reach the stop condition,
  measured through a single CountingField shared across all rounds of the trial.

Decisions baked in (see the design discussion): 1 packet per round, keep every
received packet (no window), cap by total packets received.
"""

import csv
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from icecream import ic

# Recovery/sniffing modules icecream-dump on every call; silence for a big sweep.
ic.disable()

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import (
    generate_symbols_until_nonzero,
    recode_rlnc_without_coeffs,
    check_orth_packet,
)
from binary_ext_fields.pollution import pollute_generation, pollute_random
from binary_ext_fields.rref import calculate_rref, invert_pivot_rows
from playground.new_recovery import recover_generation_bitflip, _basis_full_rank
from playground.sniffing import sniff_pool
from utils.log_helpers import get_run_log_dir


# ── Sweep configuration ──────────────────────────────────────────────────────
FIELD_M = 8
GEN_SIZE = 10               # packets needed for a full-rank decodable basis
DATA_FIELDS = 10            # data symbols per packet (before the tag)
NUM_TRIALS = 1000

# Written as plain floats (recovery_sim.py's 10e-3 notation is misread as 1e-3 when
# it is actually 1e-2). Range spans the regime where the one-shot sim collapsed to
# "waiting" -- here that regime instead shows up as rising overhead / eventual timeout.
BIT_ERROR_RATES = [1e-5, 5e-5, 1e-4, 5e-4, 1e-3, 5e-3, 1e-2]
HAMMING_DISTANCE = 1
MODE = "per_column"         # the method under study (see recovery_sim.py for A/C)
VERIFY_COUNT = 4            # oracle breadth; see recover_generation_bitflip

# Arrival cap: give up after this many received packets without decoding, recorded
# as a timeout. Expressed as a multiple of gen_size so the overhead axis is bounded
# at MAX_PACKETS_FACTOR (a decoded trial has overhead in [1, MAX_PACKETS_FACTOR]).
MAX_PACKETS_FACTOR = 12

# Sniffing gates (ADR-0004). min_pool_size means the first arrivals are classified as
# neither broken nor trusted -- models receiver warm-up before any recovery can run.
MIN_TRUST_COUNT = 4
MIN_POOL_SIZE = 10

# Cross-verification gate for admission into the DECODE basis (distinct from the
# recovery oracle's verify_count). A packet may enter the basis only if it passes
# self-check AND is orthogonal to >= DECODE_VERIFY_COUNT other self-passing packets.
# 0 = self-check only (admits self-check false positives -> the silent-decode source).
# Raising it suppresses false positives geometrically (~field_size^-V) at the cost of
# needing more accumulated clean packets before anything is trusted (higher overhead,
# more timeouts at high BER). Swept by run_verify_sweep.
DECODE_VERIFY_COUNT = 0


@dataclass
class DecodeTrialResult:
    decoded: bool               # reached full rank before the cap
    correct: bool               # decoded AND == source (only meaningful if decoded)
    packets_to_decode: int      # arrivals until stop (== cap on timeout)
    overhead: float             # packets_to_decode / gen_size
    silent_decode: bool         # decoded but != source (basis held a wrong repair)
    mul_ops: int                # cumulative recovery + decode-attempt mul-ops
    add_ops: int
    rounds: int
    status: str                 # "decoded" | "silent_decode" | "timeout"
    wall_time_s: float          # wall-clock seconds spent on this trial's loop


def _accepted_packets(field, pool, decode_verify_count=DECODE_VERIFY_COUNT, min_pool_size=MIN_POOL_SIZE):
    """The receiver's usable set = what may enter the decode basis.

    decode_verify_count == 0: self-check only (clean survivors + oracle-accepted
        repairs). A still-broken packet fails self-check and is excluded; but a
        corrupted packet that self-passes by chance slips in unchecked -- the
        self-check false positive that poisons the whole decode (silent decode).

    decode_verify_count == V > 0: cross-verification gate. A packet is admitted only
        if it also cross-checks orthogonal to >= V other self-passing packets (exactly
        sniff_pool's trust rule with min_trust_count=V). A false positive's error is
        orthogonal to a clean packet only ~1/field_size of the time, so requiring V
        independent witnesses suppresses false positives geometrically. Runs through
        `field`, so the CountingField charges the extra cross-checks to the trial.
    """
    if decode_verify_count <= 0:
        return [p for p in pool if check_orth_packet(field, p)]
    _broken, trusted_idx = sniff_pool(field, pool, min_trust_count=decode_verify_count, min_pool_size=min_pool_size)
    return [pool[i] for i in trusted_idx]


def _try_decode(field, accepted, gen_size, source_suffix):
    """Attempt to decode the accepted set. Returns (decoded, correct).

    decoded: the accepted coefficient blocks reach full rank, so the receiver would
        stop and decode (it cannot tell right from wrong at this point).
    correct: the decoded systematic symbols equal the known source. A False here with
        decoded True is a silent decode failure -- a wrong repair sat in the basis.

    Runs through `field`, so a CountingField charges the decode attempt to the trial.
    """
    if len(accepted) < gen_size:
        return False, False
    try:
        # Cheap rank gate first (only reads diagonal pivots); the full RREF+invert
        # below assumes full rank, so don't pay for it until the gate passes.
        if not _basis_full_rank(field, accepted, gen_size):
            return False, False
        _, cleaned = calculate_rref([list(p) for p in accepted], field, gen_size)
        inverted = invert_pivot_rows(cleaned, field, gen_size)
    except (ValueError, IndexError):
        # zero pivot / not-yet-spanning basis -- underdetermined, treat as undecoded
        return False, False

    if len(inverted) < gen_size or any(inverted[i][i] != 1 for i in range(gen_size)):
        return False, False

    # Row i has coefficient block e_i after inversion, so its suffix is systematic
    # symbol i; the source (identity-coefficient generation) row i is the ground truth.
    for i in range(gen_size):
        if list(inverted[i][gen_size:]) != list(source_suffix[i]):
            return True, False
    return True, True


def run_incremental_trial(base_field, data_fields, gen_size, bit_error_rate,
                          hamming_distance=HAMMING_DISTANCE, mode=MODE,
                          verify_count=VERIFY_COUNT, max_packets_factor=MAX_PACKETS_FACTOR,
                          min_trust_count=MIN_TRUST_COUNT, min_pool_size=MIN_POOL_SIZE,
                          decode_verify_count=DECODE_VERIFY_COUNT) -> DecodeTrialResult:
    """One receiver's lifetime: keep pulling fresh recoded packets, polluting and
    accumulating them, recovering + attempting decode each round, until decodable or
    the packet cap is hit. One CountingField spans the whole trial so mul_ops is the
    cumulative work to reach the stop condition (an honest upper bound -- recovery
    re-scans the whole pool each round rather than incrementally)."""
    start = time.perf_counter()
    source = generate_symbols_until_nonzero(base_field, data_fields, gen_size, coefficients=True)
    source_suffix = [bytearray(p[gen_size:]) for p in source]

    cnt = CountingField(base_field)
    max_packets = max_packets_factor * gen_size

    pool: list[bytearray] = []
    packets_received = 0
    rounds = 0
    decoded = correct = False

    while packets_received < max_packets:
        # One fresh recoded arrival (new random coefficient row), polluted at the BER.
        new_clean = recode_rlnc_without_coeffs(base_field, source, gen_size, count=1)
        new_polluted = pollute_generation(base_field, [bytearray(new_clean)], bit_error_rate, pollute_random)[0]
        pool.append(bytearray(new_polluted))
        packets_received += 1
        rounds += 1

        # Recovery on the whole accumulated pool. "waiting" is non-terminal here.
        repaired, _status = recover_generation_bitflip(
            cnt, pool, gen_size, hamming_distance, mode=mode, verify_count=verify_count,
            min_trust_count=min_trust_count, min_pool_size=min_pool_size,
        )

        # if status == waiting -> no decodable basis yet, so skip
        if _status == "waiting":
            continue

        accepted = _accepted_packets(cnt, repaired, decode_verify_count, min_pool_size)
        decoded, correct = _try_decode(cnt, accepted, gen_size, source_suffix)
        if decoded:
            break  # receiver reaches full rank and stops -- it can't detect wrongness

    silent = decoded and not correct
    status = "decoded" if correct else ("silent_decode" if decoded else "timeout")
    wall_time_s = time.perf_counter() - start
    return DecodeTrialResult(
        decoded=decoded,
        correct=correct,
        packets_to_decode=packets_received,
        overhead=packets_received / gen_size,
        silent_decode=silent,
        mul_ops=cnt.mul_count,
        add_ops=cnt.add_count,
        rounds=rounds,
        status=status,
        wall_time_s=wall_time_s,
    )


def smoke_test(field_m=FIELD_M, gen_size=GEN_SIZE, data_fields=DATA_FIELDS,
               bit_error_rates=(1e-4, 1e-3, 5e-3), num_trials=20) -> None:
    """A few trials per BER, printed as a table -- quick sanity that the loop decodes
    at low BER, needs more overhead as BER rises, and times out at the top."""
    base_field = create_field(field_m)
    print(f"\nsmoke_test  gen_size={gen_size}  trials/BER={num_trials}  "
          f"cap={MAX_PACKETS_FACTOR}x gen_size")
    print(f"{'BER':>8} {'decode%':>8} {'silent%':>8} {'mean_ovh':>9} {'mean_mul':>10} {'mean_ms':>9}")
    for ber in bit_error_rates:
        rs = [run_incremental_trial(base_field, data_fields, gen_size, ber)
              for _ in range(num_trials)]
        dec = [r for r in rs if r.decoded]
        decode_rate = len(dec) / len(rs)
        silent_rate = sum(r.silent_decode for r in rs) / len(rs)
        mean_ovh = float(np.mean([r.overhead for r in dec])) if dec else float("nan")
        mean_mul = float(np.mean([r.mul_ops for r in rs]))
        mean_ms = float(np.mean([r.wall_time_s for r in rs])) * 1e3
        print(f"{ber:>8.0e} {decode_rate:>8.2f} {silent_rate:>8.2f} {mean_ovh:>9.2f} {mean_mul:>10.0f} {mean_ms:>9.2f}")


def run_sweep(field_m=FIELD_M, gen_size=GEN_SIZE, data_fields=DATA_FIELDS,
              num_trials=NUM_TRIALS, bit_error_rates=BIT_ERROR_RATES,
              mode=MODE, verify_count=VERIFY_COUNT) -> Path:
    run_dir = get_run_log_dir("recovery_decode_sim", trials=num_trials, gen=gen_size, m=field_m)
    base_field = create_field(field_m)

    raw_rows = []
    summary_rows = []

    for ber in bit_error_rates:
        print(f"=== BER={ber:g} ===")
        results = [run_incremental_trial(base_field, data_fields, gen_size, ber,
                                         mode=mode, verify_count=verify_count)
                   for _ in range(num_trials)]
        for trial_id, r in enumerate(results):
            raw_rows.append({"bit_error_rate": ber, "trial_id": trial_id, **asdict(r)})

        decoded = [r for r in results if r.decoded]
        # Overhead is only defined for trials that actually decoded (a timeout has no
        # decode point); report it over decoded trials plus the decode-success rate.
        summary_rows.append({
            "bit_error_rate": ber,
            "mode": mode,
            "verify_count": verify_count,
            "trials": num_trials,
            "decode_success_rate": len(decoded) / num_trials,
            "silent_decode_rate": sum(r.silent_decode for r in results) / num_trials,
            "timeout_rate": sum(r.status == "timeout" for r in results) / num_trials,
            "mean_overhead_decoded": float(np.mean([r.overhead for r in decoded])) if decoded else float("nan"),
            "mean_packets_to_decode": float(np.mean([r.packets_to_decode for r in decoded])) if decoded else float("nan"),
            "mul_ops_mean": float(np.mean([r.mul_ops for r in results])),
            "add_ops_mean": float(np.mean([r.add_ops for r in results])),
            "wall_time_s_mean": float(np.mean([r.wall_time_s for r in results])),
            "wall_time_s_total": float(np.sum([r.wall_time_s for r in results])),
        })

    _write_csv(run_dir / "raw_results.csv", raw_rows)
    _write_csv(run_dir / "summary.csv", summary_rows)

    _plot_vs_ber(summary_rows, "decode_success_rate", "Decode-success rate (trials decoded / total)",
                 run_dir / "decode_success_vs_ber.png", ylim=(-0.02, 1.02))
    _plot_vs_ber(summary_rows, "silent_decode_rate", "Silent-decode rate (decoded to wrong source)",
                 run_dir / "silent_decode_vs_ber.png", ylim=(-0.02, 1.02))
    _plot_vs_ber(summary_rows, "mean_overhead_decoded", "Mean overhead (packets received / gen_size)",
                 run_dir / "overhead_vs_ber.png", ylim=None, hline=1.0)
    _plot_vs_ber(summary_rows, "mul_ops_mean", "Mean cumulative mul-ops to stop",
                 run_dir / "mul_ops_vs_ber.png", ylim=None)
    _plot_vs_ber(summary_rows, "wall_time_s_mean", "Mean wall-clock time per trial (s)",
                 run_dir / "wall_time_vs_ber.png", ylim=None)

    print(f"\nDone. Results written to: {run_dir}")
    return run_dir


def run_verify_sweep(field_m=FIELD_M, gen_size=GEN_SIZE, data_fields=DATA_FIELDS,
                     num_trials=NUM_TRIALS, bit_error_rates=BIT_ERROR_RATES,
                     decode_verify_counts=(0, 1, 2, 3, 5), mode=MODE, verify_count=VERIFY_COUNT) -> Path:
    """The cross-verification tradeoff: sweep the decode-basis admission gate V over
    (BER x V). Answers "how many verifications are necessary" -- silent_decode_rate
    should fall geometrically with V while overhead / timeout_rate climb (V clean
    witnesses must accumulate before a packet is trusted). One line per V."""
    run_dir = get_run_log_dir("recovery_decode_verify_sweep", trials=num_trials, gen=gen_size, m=field_m)
    base_field = create_field(field_m)

    raw_rows = []
    summary_rows = []
    for v in decode_verify_counts:
        for ber in bit_error_rates:
            print(f"=== V={v}  BER={ber:g} ===")
            results = [run_incremental_trial(base_field, data_fields, gen_size, ber,
                                             mode=mode, verify_count=verify_count,
                                             decode_verify_count=v)
                       for _ in range(num_trials)]
            for trial_id, r in enumerate(results):
                raw_rows.append({"decode_verify_count": v, "bit_error_rate": ber,
                                 "trial_id": trial_id, **asdict(r)})
            decoded = [r for r in results if r.decoded]
            summary_rows.append({
                "decode_verify_count": v,
                "bit_error_rate": ber,
                "trials": num_trials,
                "decode_success_rate": len(decoded) / num_trials,
                "silent_decode_rate": sum(r.silent_decode for r in results) / num_trials,
                "timeout_rate": sum(r.status == "timeout" for r in results) / num_trials,
                "mean_overhead_decoded": float(np.mean([r.overhead for r in decoded])) if decoded else float("nan"),
                "mul_ops_mean": float(np.mean([r.mul_ops for r in results])),
                "wall_time_s_mean": float(np.mean([r.wall_time_s for r in results])),
            })

    _write_csv(run_dir / "raw_results.csv", raw_rows)
    _write_csv(run_dir / "summary.csv", summary_rows)

    _plot_vs_ber_multi(summary_rows, decode_verify_counts, "silent_decode_rate",
                       "Silent-decode rate (decoded to wrong source)",
                       run_dir / "silent_decode_vs_ber_by_V.png", ylim=(-0.02, 1.02))
    _plot_vs_ber_multi(summary_rows, decode_verify_counts, "decode_success_rate",
                       "Decode-success rate", run_dir / "decode_success_vs_ber_by_V.png", ylim=(-0.02, 1.02))
    _plot_vs_ber_multi(summary_rows, decode_verify_counts, "mean_overhead_decoded",
                       "Mean overhead (packets received / gen_size)",
                       run_dir / "overhead_vs_ber_by_V.png", ylim=None, hline=1.0)
    _plot_vs_ber_multi(summary_rows, decode_verify_counts, "timeout_rate",
                       "Timeout rate (undecoded within cap)",
                       run_dir / "timeout_vs_ber_by_V.png", ylim=(-0.02, 1.02))
    _plot_vs_ber_multi(summary_rows, decode_verify_counts, "mul_ops_mean",
                       "Mean cumulative mul-ops to stop",
                       run_dir / "mul_ops_vs_ber_by_V.png", ylim=None)
    _plot_vs_ber_multi(summary_rows, decode_verify_counts, "wall_time_s_mean",
                       "Mean wall-clock time per trial (s)",
                       run_dir / "wall_time_vs_ber_by_V.png", ylim=None)

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


def _plot_vs_ber(summary_rows, metric, ylabel, output_path, ylim=(-0.02, 1.02), hline=None) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    points = sorted((row["bit_error_rate"], row[metric]) for row in summary_rows)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    ax.plot(xs, ys, "-", marker="o", color="#2a6f97", linewidth=2, markersize=6)

    if hline is not None:
        ax.axhline(hline, color="grey", linestyle="-.", alpha=0.6, label=f"ideal = {hline:g}")
        ax.legend(fontsize=9)
    ax.set_xscale("log")
    ax.set_xlabel("Bit error rate", fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
    ax.set_title(f"{ylabel} vs bit error rate", fontsize=13, fontweight="bold")
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {output_path}")


def _plot_vs_ber_multi(summary_rows, series_values, metric, ylabel, output_path,
                       ylim=(-0.02, 1.02), hline=None) -> None:
    """One line per decode_verify_count V, metric vs BER."""
    fig, ax = plt.subplots(figsize=(9, 6))
    colors = plt.cm.viridis(np.linspace(0.1, 0.85, len(series_values)))
    for color, v in zip(colors, series_values):
        points = sorted((row["bit_error_rate"], row[metric])
                        for row in summary_rows if row["decode_verify_count"] == v)
        if not points:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ax.plot(xs, ys, "-", marker="o", color=color, linewidth=2, markersize=5, label=f"V={v}")

    if hline is not None:
        ax.axhline(hline, color="grey", linestyle="-.", alpha=0.6, label=f"ideal = {hline:g}")
    ax.set_xscale("log")
    ax.set_xlabel("Bit error rate", fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
    ax.set_title(f"{ylabel} vs BER, by decode-verify count V", fontsize=13, fontweight="bold")
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {output_path}")


if __name__ == "__main__":
    smoke_test()
    run_sweep()
    #run_verify_sweep()
