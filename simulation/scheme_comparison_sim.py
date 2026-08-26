"""Baseline comparison driver (ADR-0009, ADR-0011): orthogonal tag vs HMAC.

Two experiments, scheme-agnostic where possible (the per-scheme parts for
orthogonal/HMAC live in `integrity_schemes.py`); the validated
`recovery_decode_sim` / `intelligent_attack_sim` are imported and left untouched:

1. Random-error recovery (orthogonal + HMAC). Single-hop send-until-decodable at a
   sweep of BERs. Headline: transmission overhead (packets_to_decode / gen_size) --
   the orthogonal tag repairs so needs fewer transmissions than a detect-and-drop
   scheme; HMAC drops and retransmits. Also decode-success, silent-decode, and each
   scheme's NATIVE op count (field muls / HMAC block-ops -- reported per scheme,
   never summed).

2. Attack (orthogonal vs HMAC). End-to-end HMAC with a source<->receiver key the
   relay lacks structurally blocks the targeted forgery (silent-accept == 0); the
   orthogonal arm is the existing attack sim.

The CRC arm is no longer here: ADR-0011 refocused it as a standalone single-packet
Hamming-distance recovery study (`simulation/crc_recovery_sim.py`); its earlier
Fly-PRAC dependent-group form (and this driver's `run_fly_prac_trial`) was retired.
The homomorphic-MAC benchmark and the three-way CRC/HMAC/orthogonal comparison on
this harness are the deferred phases 2 and 3 (ADR-0011).

Computation is reported in native units + the tag-overhead figure; wall-clock is
deliberately not produced here (see docs/comparison_methodology_notes.md).
"""

import csv
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from icecream import ic

ic.disable()

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import recode_rlnc_without_coeffs
from binary_ext_fields.pollution import pollute_generation, pollute_random
from simulation.recovery_decode_sim import _try_decode
from simulation.integrity_schemes import (
    SCHEMES, AdmitConfig, HmacScheme, forge_hmac,
    SEGMENTED_DATA_FIELDS, SEGMENTED_N_VALUES, SEGMENTED_STRATEGIES, MAC_STRATEGIES,
)
from simulation.intelligent_attack_sim import run_attack_trial
from utils.log_helpers import get_run_log_dir


# ── Sweep configuration ──────────────────────────────────────────────────────
FIELD_M = 8
GEN_SIZE = 10
DATA_FIELDS = 10
NUM_TRIALS = 100
BIT_ERROR_RATES = [1e-5, 5e-5, 1e-4, 5e-4, 1e-3] # 5e-3, 1e-2
MAX_PACKETS_FACTOR = 12
# Recovery comparison (ADR-0011 phase 3): the orthogonal self-tag against the CRC
# baseline in both its localized (fair-fight) and whole-packet (bare floor) forms.
# HMAC stays registered in SCHEMES for the attack comparison but is off this axis.
SCHEME_NAMES = ("orthogonal", "crc_localized", "crc_whole")

SCHEME_COLORS = {"orthogonal": "#2a6f97", "hmac": "#3d405b",
                 "crc_localized": "#e07a5f", "crc_whole": "#f2a65a"}
SCHEME_OP_UNIT = {"orthogonal": "field muls", "hmac": "HMAC block-ops",
                  "crc_localized": "CRC checks", "crc_whole": "CRC checks"}
# Segmented scheme (ADR-0012) native op unit -- same primitive as orthogonal (field
# muls), one entry per registered N/strategy combination so _print_op_table can
# look any of them up by name.
SCHEME_OP_UNIT.update({
    f"segmented_{strategy}_n{n}": "field muls"
    for n in SEGMENTED_N_VALUES for strategy in SEGMENTED_STRATEGIES
})
# Homomorphic-MAC benchmark arm -- same native primitive (field muls), one entry per
# registered N/strategy so _print_op_table can look any of them up by name.
SCHEME_OP_UNIT.update({
    f"mac_{strategy}_n{n}": "field muls"
    for n in SEGMENTED_N_VALUES for strategy in MAC_STRATEGIES
})
# HD-parity sweep: same bit-flip repair reach (HD 1/2/3) for both schemes, so the
# comparison is fair. Colour = scheme, linestyle = Hamming distance.
HD_LINESTYLE = {1: "-", 2: "--", 3: ":"}
HD_SCHEME_NAMES = ("orthogonal", "crc_localized", "crc_whole")   # fair pairing + the no-localization floor
HAMMING_DISTANCES = (1, 2, 3)


@dataclass
class SchemeTrialResult:
    scheme: str
    decoded: bool
    correct: bool
    silent_decode: bool
    packets_to_decode: int
    overhead: float          # transmissions: packets_to_decode / gen_size
    scheme_ops: int          # native primary op count -- UNIT DIFFERS PER SCHEME
    decode_ops: int          # common RLNC decode muls (separate field, not scheme work)
    status: str              # "decoded" | "silent_decode" | "timeout"
    wall_time_s: float       # wall-clock spent in this trial's loop (pure-Python fair bridge)
    time_per_packet_s: float # wall_time_s / packets_to_decode -- the completion-time metric
    pairs_recovered: int = 0 # segmented scheme only (ADR-0012); 0 for every other scheme
    pairs_failed: int = 0    # segmented scheme's IC-refinement gap (measure-only, ADR-0012
                              # "Resolved"): same-bit-position overlapping errors this
                              # mechanism cannot split. 0 for every other scheme.
    unpaired_recovered: int = 0  # segmented odd-one-out broken segment repaired via the
                                  # unpaired linear-solve/bit-flip fallback; 0 for others.
    unpaired_failed: int = 0     # unpaired broken segment neither stage could fix; 0 for others.
    detection_ops: int = 0   # segmented: field muls in orthogonality/self-check (finding
                              # corruption) -- the cost any tag scheme pays. 0 for others.
    recovery_ops: int = 0    # segmented: field muls in the combined/bit-flip search (fixing
                              # corruption) -- the fair recovery-cost axis. 0 for others.


def run_recovery_trial(base_field, scheme, data_fields, gen_size, bit_error_rate,
                       cfg: AdmitConfig, max_packets_factor=MAX_PACKETS_FACTOR) -> SchemeTrialResult:
    """One receiver lifetime for a given scheme: keep pulling fresh recoded packets,
    tag -> pollute -> admit -> try decode, until decodable or the arrival cap. The
    scheme's native op counter charges tagging/verification/repair; a separate
    CountingField charges the (scheme-common) RLNC decode."""
    source, source_suffix = scheme.make_source(base_field, data_fields, gen_size)
    instrument = scheme.new_instrument(base_field)
    cnt_decode = CountingField(base_field)
    max_packets = max_packets_factor * gen_size

    pool: list[bytearray] = []
    received = 0
    decoded = correct = False

    start = time.perf_counter()
    while received < max_packets:
        clean = recode_rlnc_without_coeffs(base_field, source, gen_size, count=1)
        wire = scheme.attach(instrument, bytearray(clean))
        polluted = pollute_generation(base_field, [wire], bit_error_rate, pollute_random)[0]
        pool.append(bytearray(polluted))
        received += 1

        accepted = scheme.admit(instrument, pool, gen_size, cfg)
        if accepted is None:          # orthogonal "waiting" -- no basis yet
            continue
        decoded, correct = _try_decode(cnt_decode, accepted, gen_size, source_suffix)
        if decoded:
            break
    wall_time_s = time.perf_counter() - start

    silent = decoded and not correct
    status = "decoded" if correct else ("silent_decode" if decoded else "timeout")
    op_counts = scheme.op_counts(instrument)  # per-scheme dict; only segmented has pairs_*
    return SchemeTrialResult(
        scheme=scheme.name, decoded=decoded, correct=correct, silent_decode=silent,
        packets_to_decode=received, overhead=received / gen_size,
        scheme_ops=scheme.primary_ops(instrument), decode_ops=cnt_decode.mul_count,
        pairs_recovered=op_counts.get("pairs_recovered", 0), pairs_failed=op_counts.get("pairs_failed", 0),
        unpaired_recovered=op_counts.get("unpaired_recovered", 0), unpaired_failed=op_counts.get("unpaired_failed", 0),
        detection_ops=op_counts.get("detection_mul", 0), recovery_ops=op_counts.get("recovery_mul", 0),
        status=status,
        wall_time_s=wall_time_s,
        time_per_packet_s=wall_time_s / received if received else float("nan"),
    )


def _run_trial(name: str, base_field, data_fields, gen_size, bit_error_rate,
              cfg: AdmitConfig) -> SchemeTrialResult:
    """Every scheme goes through the generic IntegrityScheme path (ADR-0011)."""
    return run_recovery_trial(base_field, SCHEMES[name], data_fields, gen_size, bit_error_rate, cfg)


def _tag_overhead_bits_for(name: str, gen_size, field_m) -> int:
    return SCHEMES[name].tag_overhead_bits(gen_size, field_m)


def _run_capped_cell(trial_fn, num_trials, time_budget_s):
    """Run up to `num_trials` calls of `trial_fn()`, stopping BEFORE starting a new
    trial once `time_budget_s` of wall time has elapsed in this cell. Returns the list
    of trial results; its length reflects the cap (fewer than num_trials on a capped
    cell). Always runs at least one trial -- a slow cell degrades to fewer trials, not
    an empty (divide-by-zero) one. `time_budget_s=None` disables the cap.

    The check is between trials, not mid-trial: a single trial already in flight always
    finishes, so the actual wall time can overshoot the budget by up to one trial."""
    results = []
    start = time.perf_counter()
    for i in range(num_trials):
        if i > 0 and time_budget_s is not None and time.perf_counter() - start >= time_budget_s:
            break
        results.append(trial_fn())
    return results


def run_recovery_sweep(field_m=FIELD_M, gen_size=GEN_SIZE, data_fields=DATA_FIELDS,
                       num_trials=NUM_TRIALS, bit_error_rates=BIT_ERROR_RATES,
                       scheme_names=SCHEME_NAMES) -> Path:
    """Sweep BER x scheme. Comparable metrics (decode-success, silent-decode,
    transmission overhead) are co-plotted; native op counts go to the CSV/console
    only (incommensurable units -- ADR-0009)."""
    run_dir = get_run_log_dir("scheme_comparison_sim", trials=num_trials, gen=gen_size, m=field_m)
    base_field = create_field(field_m)
    cfg = AdmitConfig()

    raw_rows, summary_rows = [], []
    for name in scheme_names:
        tag_bits = _tag_overhead_bits_for(name, gen_size, field_m)
        for ber in bit_error_rates:
            print(f"=== scheme={name} BER={ber:g} ===")
            results = [_run_trial(name, base_field, data_fields, gen_size, ber, cfg)
                       for _ in range(num_trials)]
            for trial_id, r in enumerate(results):
                raw_rows.append({"scheme": name, "bit_error_rate": ber, "trial_id": trial_id, **asdict(r)})

            decoded = [r for r in results if r.decoded]
            summary_rows.append({
                "scheme": name,
                "bit_error_rate": ber,
                "trials": num_trials,
                "tag_overhead_bits": tag_bits,
                "correct_rate": sum(r.correct for r in results) / num_trials,   # recovered to the RIGHT source
                "decode_success_rate": len(decoded) / num_trials,                # reached full rank (silent incl.)
                "silent_decode_rate": sum(r.silent_decode for r in results) / num_trials,
                "timeout_rate": sum(r.status == "timeout" for r in results) / num_trials,
                "mean_overhead_decoded": float(np.mean([r.overhead for r in decoded])) if decoded else float("nan"),
                "time_per_packet_s_mean": float(np.mean([r.time_per_packet_s for r in results])),
                "wall_time_s_mean": float(np.mean([r.wall_time_s for r in results])),
                "scheme_op_unit": SCHEME_OP_UNIT[name],
                "scheme_ops_mean": float(np.mean([r.scheme_ops for r in results])),
                "decode_ops_mean": float(np.mean([r.decode_ops for r in results])),
            })

    _write_csv(run_dir / "raw_results.csv", raw_rows)
    _write_csv(run_dir / "summary.csv", summary_rows)

    _plot_by_scheme(summary_rows, scheme_names, "correct_rate",
                    "Recovery rate (decoded to correct source)", run_dir / "recovery_rate_vs_ber.png", ylim=(-0.02, 1.02))
    _plot_by_scheme(summary_rows, scheme_names, "decode_success_rate",
                    "Decode-success rate (reached full rank, silent incl.)",
                    run_dir / "decode_success_vs_ber.png", ylim=(-0.02, 1.02))
    _plot_by_scheme(summary_rows, scheme_names, "silent_decode_rate",
                    "Silent-decode rate", run_dir / "silent_decode_vs_ber.png", ylim=(-0.02, 1.02))
    _plot_by_scheme(summary_rows, scheme_names, "mean_overhead_decoded",
                    "Mean transmission overhead (packets / gen_size)",
                    run_dir / "overhead_vs_ber.png", ylim=None, hline=1.0)
    _plot_by_scheme(summary_rows, scheme_names, "time_per_packet_s_mean",
                    "Mean completion time per received packet (s)",
                    run_dir / "time_per_packet_vs_ber.png", ylim=None)

    _print_op_table(summary_rows, scheme_names, bit_error_rates)
    print(f"\nDone. Results written to: {run_dir}")
    return run_dir


# ── HD-parity sweep: HD 1/2/3 x BER x scheme, fair repair reach ───────────────
def run_hd_sweep(field_m=FIELD_M, gen_size=GEN_SIZE, data_fields=DATA_FIELDS,
                 num_trials=NUM_TRIALS, bit_error_rates=BIT_ERROR_RATES,
                 hamming_distances=HAMMING_DISTANCES, scheme_names=HD_SCHEME_NAMES) -> Path:
    """The fair comparison: give both schemes the SAME bit-flip repair reach (HD in
    {1,2,3}) and sweep it against BER. cfg.hamming_distance now drives both arms --
    the orthogonal per-column oracle AND the CRC candidate search (integrity_schemes)
    -- so a HD-k line means both repair up to k bit-flips. One line per (scheme, HD):
    colour = scheme, linestyle = HD."""
    run_dir = get_run_log_dir("scheme_comparison_hd_sweep", trials=num_trials, gen=gen_size, m=field_m)
    base_field = create_field(field_m)

    raw_rows, summary_rows = [], []
    for name in scheme_names:
        tag_bits = _tag_overhead_bits_for(name, gen_size, field_m)
        for hd in hamming_distances:
            cfg = AdmitConfig(hamming_distance=hd)
            for ber in bit_error_rates:
                print(f"=== scheme={name} HD={hd} BER={ber:g} ===")
                results = [_run_trial(name, base_field, data_fields, gen_size, ber, cfg)
                           for _ in range(num_trials)]
                for trial_id, r in enumerate(results):
                    raw_rows.append({"scheme": name, "hamming_distance": hd,
                                     "bit_error_rate": ber, "trial_id": trial_id, **asdict(r)})
                decoded = [r for r in results if r.decoded]
                summary_rows.append({
                    "scheme": name,
                    "hamming_distance": hd,
                    "bit_error_rate": ber,
                    "trials": num_trials,
                    "tag_overhead_bits": tag_bits,
                    "correct_rate": sum(r.correct for r in results) / num_trials,
                    "decode_success_rate": len(decoded) / num_trials,
                    "silent_decode_rate": sum(r.silent_decode for r in results) / num_trials,
                    "timeout_rate": sum(r.status == "timeout" for r in results) / num_trials,
                    "mean_overhead_decoded": float(np.mean([r.overhead for r in decoded])) if decoded else float("nan"),
                    "time_per_packet_s_mean": float(np.mean([r.time_per_packet_s for r in results])),
                    "wall_time_s_mean": float(np.mean([r.wall_time_s for r in results])),
                    "scheme_ops_mean": float(np.mean([r.scheme_ops for r in results])),
                })

    _write_csv(run_dir / "raw_results.csv", raw_rows)
    _write_csv(run_dir / "summary.csv", summary_rows)

    _plot_by_scheme_hd(summary_rows, scheme_names, hamming_distances, "correct_rate",
                       "Recovery rate (decoded to correct source)",
                       run_dir / "recovery_rate_vs_ber_by_hd.png", ylim=(-0.02, 1.02))
    _plot_by_scheme_hd(summary_rows, scheme_names, hamming_distances, "silent_decode_rate",
                       "Silent-decode rate", run_dir / "silent_decode_vs_ber_by_hd.png", ylim=(-0.02, 1.02))
    _plot_by_scheme_hd(summary_rows, scheme_names, hamming_distances, "time_per_packet_s_mean",
                       "Mean completion time per received packet (s)",
                       run_dir / "time_per_packet_vs_ber_by_hd.png", ylim=None)
    _plot_by_scheme_hd(summary_rows, scheme_names, hamming_distances, "mean_overhead_decoded",
                       "Mean transmission overhead (packets / gen_size)",
                       run_dir / "overhead_vs_ber_by_hd.png", ylim=None, hline=1.0)
    print(f"\nDone. Results written to: {run_dir}")
    return run_dir


# ── Segmented scheme sweep: N x BER (ADR-0012 "Resolved" 2026-08-11) ──────────
# N is this scheme's headline knob (coeff-segment repair + pairing tradeoff), so it
# gets its own 2D sweep against BER rather than a fixed value. data_fields is fixed
# at SEGMENTED_DATA_FIELDS (48), applied to EVERY scheme here including the N=1
# orthogonal baseline, so the comparison stays fair -- see ADR-0012 for why 48
# (build_segments' rank-deficiency floor rules out this file's usual DATA_FIELDS=10
# for N>=3). One line per (N, strategy): colour = strategy, linestyle = N. The N=1
# baseline is plain OrthogonalScheme (no segmentation, registered in SCHEMES already).
#
# COST: the segmented arm's repair search is heavier than the other two, and high-BER
# cells are the slow ones. Ticket 01 memoised the per-pair search (no recompute when a
# pair is unchanged) and ticket 02 adds a per-cell wall-time budget below, so a hot cell
# now degrades to fewer trials rather than blocking. The defaults here are still smaller
# than NUM_TRIALS/BIT_ERROR_RATES for a feasible exploratory run, not the "right" final
# numbers -- tune num_trials/bit_error_rates for a headline run.
SEGMENTED_NUM_TRIALS = 20
SEGMENTED_BIT_ERROR_RATES = (1e-4, 5e-4, 1e-3, 5e-3)  # 1e-2 available but noise-dominated + very slow at data_fields=48
SEGMENTED_MAX_PACKETS_FACTOR = 8
# Per-cell wall-time budget (ticket 02): even with ticket 01's per-pair memo, the
# highest-BER cells can still be slow. A cell runs up to SEGMENTED_NUM_TRIALS trials
# but stops adding new ones once this many seconds have elapsed, so one hot cell can't
# hang the whole sweep. 120s at 20 trials ~= a slow high-BER cell gets a handful of
# trials rather than blocking; lower it for a quick exploratory run. None disables it.
SEGMENTED_CELL_TIME_BUDGET_S = 120.0

SEGMENTED_N_LINESTYLE = {1: "-", 2: "--", 3: "-.", 5: ":"}
SEGMENTED_STRATEGY_COLORS = {"orthogonal": SCHEME_COLORS["orthogonal"],
                             "uniform_hd": "#588157", "coefficient_first": "#bc4749",
                             # keyed homomorphic-MAC benchmark arm (its own strategy labels)
                             "mac_uniform_hd": "#8338ec", "mac_coefficient_first": "#fb8500"}

# CRC baseline arms folded into the segmented sweep so CRC overhead + recovery sit on
# the SAME axes as the segmented scheme (the user's compare-CRC-to-segmented ask). Both
# flow through run_recovery_trial unchanged -- like orthogonal they are non-segmented
# (N=1) reference arms, not (N, strategy) grid points, so the plotter draws them as
# flat lines keyed by scheme name (see _flat_reference_schemes / _plot_by_n_strategy).
SEGMENTED_CRC_SCHEMES = ("crc_localized", "crc_whole")
# Colour + legend label for every flat (N=1) reference arm the segmented plots draw.
FLAT_ARM_COLOR = {"orthogonal": SEGMENTED_STRATEGY_COLORS["orthogonal"],
                  "crc_localized": SCHEME_COLORS["crc_localized"],
                  "crc_whole": SCHEME_COLORS["crc_whole"]}
FLAT_ARM_LABEL = {"orthogonal": "orthogonal (N=1)",
                  "crc_localized": "CRC (localized)", "crc_whole": "CRC (whole-packet)"}
FLAT_ARM_MARKER = {"orthogonal": "o", "crc_localized": "^", "crc_whole": "D"}


def _segmented_sweep_schemes(n_values=SEGMENTED_N_VALUES, strategies=SEGMENTED_STRATEGIES,
                             mac_strategies=MAC_STRATEGIES, crc_schemes=SEGMENTED_CRC_SCHEMES):
    """(scheme_name, n, strategy_label) for the N=1 orthogonal baseline, the CRC
    baseline arms, plus every (N, strategy) combination in the segmented sweep -- the
    keyless orthogonal arm AND the keyed homomorphic-MAC benchmark arm (strategy label
    prefixed 'mac_'). CRC arms are non-segmented references: N=1, strategy == scheme
    name, so the (N, strategy) plot loop skips them and they draw as flat lines."""
    rows = [("orthogonal", 1, "orthogonal")]
    rows += [(name, 1, name) for name in crc_schemes]
    for n in n_values:
        for strategy in strategies:
            rows.append((f"segmented_{strategy}_n{n}", n, strategy))
        for strategy in mac_strategies:
            rows.append((f"mac_{strategy}_n{n}", n, f"mac_{strategy}"))
    return rows


def run_segmented_n_sweep(field_m=FIELD_M, gen_size=GEN_SIZE, data_fields=SEGMENTED_DATA_FIELDS,
                          num_trials=SEGMENTED_NUM_TRIALS, bit_error_rates=SEGMENTED_BIT_ERROR_RATES,
                          n_values=SEGMENTED_N_VALUES, strategies=SEGMENTED_STRATEGIES,
                          mac_strategies=MAC_STRATEGIES, crc_schemes=SEGMENTED_CRC_SCHEMES,
                          max_packets_factor=SEGMENTED_MAX_PACKETS_FACTOR,
                          cell_time_budget_s=SEGMENTED_CELL_TIME_BUDGET_S) -> Path:
    """N x BER sweep for the segmented scheme (ADR-0012), against the N=1 orthogonal
    baseline at the same data_fields, alongside the keyed homomorphic-MAC benchmark arm
    (mac_strategies). Reuses run_recovery_trial unchanged -- every arm is just another
    IntegrityScheme, so the driver doesn't know or care they differ.

    Per-cell runtime cap (ticket 02): each (scheme, BER) cell runs up to num_trials trials
    but stops adding new ones once cell_time_budget_s of wall time has elapsed, so a slow
    high-BER cell degrades to fewer trials instead of hanging the whole sweep. The summary's
    `trials_run` column reflects the ACTUAL count and `capped` flags cells that hit the
    limit; all rates use trials_run as the denominator. Pass cell_time_budget_s=None to
    disable the cap."""
    run_dir = get_run_log_dir("scheme_comparison_segmented_n_sweep", trials=num_trials, gen=gen_size, m=field_m)
    base_field = create_field(field_m)
    cfg = AdmitConfig(hamming_distance=2) # if this is less than 2, combined reovery wont work at all
    sweep_schemes = _segmented_sweep_schemes(n_values, strategies, mac_strategies, crc_schemes)
    # strategy labels to draw one line each (orthogonal baseline is drawn separately)
    plot_strategies = list(strategies) + [f"mac_{s}" for s in mac_strategies]

    raw_rows, summary_rows = [], []
    for name, n, strategy in sweep_schemes:
        tag_bits = _tag_overhead_bits_for(name, gen_size, field_m)
        for ber in bit_error_rates:
            print(f"=== scheme={name} N={n} strategy={strategy} BER={ber:g} ===")
            results = _run_capped_cell(
                lambda: run_recovery_trial(base_field, SCHEMES[name], data_fields, gen_size, ber, cfg,
                                           max_packets_factor=max_packets_factor),
                num_trials, cell_time_budget_s)
            trials_run = len(results)
            capped = trials_run < num_trials
            if capped:
                print(f"    [capped] cell hit {cell_time_budget_s:g}s budget after "
                      f"{trials_run}/{num_trials} trials")
            for trial_id, r in enumerate(results):
                raw_rows.append({"scheme": name, "n": n, "strategy": strategy,
                                 "bit_error_rate": ber, "trial_id": trial_id, **asdict(r)})

            decoded = [r for r in results if r.decoded]
            total_pairs = sum(r.pairs_recovered + r.pairs_failed for r in results)
            summary_rows.append({
                "scheme": name, "n": n, "strategy": strategy,
                "bit_error_rate": ber,
                "trials": num_trials,
                "trials_run": trials_run,
                "capped": capped,
                "tag_overhead_bits": tag_bits,
                "correct_rate": sum(r.correct for r in results) / trials_run,
                "decode_success_rate": len(decoded) / trials_run,
                "silent_decode_rate": sum(r.silent_decode for r in results) / trials_run,
                "timeout_rate": sum(r.status == "timeout" for r in results) / trials_run,
                "mean_overhead_decoded": float(np.mean([r.overhead for r in decoded])) if decoded else float("nan"),
                "time_per_packet_s_mean": float(np.mean([r.time_per_packet_s for r in results])),
                "wall_time_s_mean": float(np.mean([r.wall_time_s for r in results])),
                "scheme_ops_mean": float(np.mean([r.scheme_ops for r in results])),
                # scheme_ops split by phase (segmented_recovery._count_phase): detection =
                # orthogonality/self-checks (finding corruption, paid by any tag scheme);
                # recovery = the combined/bit-flip search (fixing it) -- the fair
                # recovery-cost axis for the N comparison. Sum to scheme_ops for uniform_hd;
                # coefficient_first's ARC localization is the unattributed remainder.
                "detection_ops_mean": float(np.mean([r.detection_ops for r in results])),
                "recovery_ops_mean": float(np.mean([r.recovery_ops for r in results])),
                "unpaired_recovered_mean": float(np.mean([r.unpaired_recovered for r in results])),
                "unpaired_failed_mean": float(np.mean([r.unpaired_failed for r in results])),
                # ADR-0012 "Resolved": IC-refinement is measure-only -- this IS that
                # measurement. NaN (not 0) when no pair was ever attempted this cell,
                # so it's visibly distinct from "attempted and always succeeded".
                "ic_refinement_failure_rate": (
                    sum(r.pairs_failed for r in results) / total_pairs if total_pairs else float("nan")
                ),
            })

    _write_csv(run_dir / "raw_results.csv", raw_rows)
    _write_csv(run_dir / "summary.csv", summary_rows)

    _plot_by_n_strategy(summary_rows, n_values, plot_strategies, "correct_rate",
                        "Recovery rate (decoded to correct source)",
                        run_dir / "recovery_rate_vs_ber_by_n.png", ylim=(-0.02, 1.02))
    _plot_by_n_strategy(summary_rows, n_values, plot_strategies, "mean_overhead_decoded",
                        "Mean transmission overhead (packets / gen_size)",
                        run_dir / "overhead_vs_ber_by_n.png", ylim=None, hline=1.0)
    _plot_by_n_strategy(summary_rows, n_values, plot_strategies, "ic_refinement_failure_rate",
                        "IC-refinement failure rate (overlapping-error pairs, measure-only)",
                        run_dir / "ic_refinement_failure_vs_ber_by_n.png", ylim=(-0.02, 1.02))
    _plot_by_n_strategy(summary_rows, n_values, plot_strategies, "time_per_packet_s_mean",
                        "Mean completion time per received packet (s)",
                        run_dir / "time_per_packet_vs_ber_by_n.png", ylim=None)
    # Silent-decode (false-repair) rate -- one of the four headline metrics. Expected
    # ~0 for MAC (q^-V collision) and for orthogonal cross-verify; a non-zero line is a
    # scheme silently accepting a corrupted decode, the worst failure mode.
    _plot_by_n_strategy(summary_rows, n_values, plot_strategies, "silent_decode_rate",
                        "Silent-decode rate (accepted a corrupted decode)",
                        run_dir / "silent_decode_vs_ber_by_n.png", ylim=(-0.02, 1.02))
    # Wall-clock completion time per trial -- the pure-Python wall figure alongside the
    # per-packet metric. Incommensurable with C/SHA-NI implementations (see
    # comparison_methodology_notes), so it is a secondary, same-substrate comparison only.
    _plot_by_n_strategy(summary_rows, n_values, plot_strategies, "wall_time_s_mean",
                        "Mean wall-clock time per trial (s)",
                        run_dir / "wall_time_vs_ber_by_n.png", ylim=None)
    # The recovery-cost curve the detection/recovery split is for: search muls only,
    # excluding the detection baseline every tag scheme pays, so N arms compare fairly.
    _plot_by_n_strategy(summary_rows, n_values, plot_strategies, "recovery_ops_mean",
                        "Mean recovery field-muls (combined/bit-flip search only)",
                        run_dir / "recovery_ops_vs_ber_by_n.png", ylim=None, draw_flat_arms=False)
    _plot_by_n_strategy(summary_rows, n_values, plot_strategies, "detection_ops_mean",
                        "Mean detection field-muls (orthogonality/self-checks)",
                        run_dir / "detection_ops_vs_ber_by_n.png", ylim=None, draw_flat_arms=False)

    _print_op_table(summary_rows, [name for name, _, _ in sweep_schemes], bit_error_rates)
    print(f"\nDone. Results written to: {run_dir}")
    return run_dir


# ── Attack comparison: orthogonal (existing sim) vs end-to-end HMAC ───────────
@dataclass
class HmacAttackResult:
    decoded: bool
    correct: bool
    silent_accept: bool
    forged_accepted: bool
    n_injected: int
    packets_received: int
    status: str


def run_hmac_attack_trial(base_field, data_fields, gen_size, strike_s, cfg: AdmitConfig,
                          threshold, n_inject=1, max_packets_factor=6, rng=None) -> HmacAttackResult:
    """The malicious relay forwards source-signed packets, then injects forged ones it
    cannot sign (no key). HMAC admit recomputes and rejects them, so silent-accept is
    structurally impossible -- the counterpoint to the orthogonal attack sim."""
    import random as _random
    rng = rng or _random
    scheme = HmacScheme()
    source, source_suffix = scheme.make_source(base_field, data_fields, gen_size)
    instrument = scheme.new_instrument(base_field)   # holds the key the relay lacks
    cnt_decode = CountingField(base_field)
    max_packets = max_packets_factor * gen_size

    pool: list[bytearray] = []
    saved: list[bytearray] = []
    forged_codes: set[bytes] = set()
    forwarded = injected = 0
    decoded = correct = False
    accepted: list[bytearray] = []

    while len(pool) < max_packets:
        if injected < n_inject and forwarded >= strike_s and len(saved) >= threshold:
            forged = forge_hmac(saved, gen_size, data_fields, base_field.max_value, rng)
            forged_codes.add(bytes(forged[:gen_size + data_fields]))
            pool.append(forged)
            injected += 1
        else:
            clean = bytearray(recode_rlnc_without_coeffs(base_field, source, gen_size, count=1))
            wire = scheme.attach(instrument, clean)
            pool.append(wire)
            saved.append(wire)
            forwarded += 1

        accepted = scheme.admit(instrument, pool, gen_size, cfg)
        decoded, correct = _try_decode(cnt_decode, accepted, gen_size, source_suffix)
        if decoded:
            break

    forged_accepted = any(bytes(p) in forged_codes for p in accepted)
    silent = decoded and not correct
    status = "silent_accept" if silent else ("clean_decode" if decoded else "no_decode")
    return HmacAttackResult(decoded, correct, silent, forged_accepted, injected, len(pool), status)


def run_attack_comparison(field_m=FIELD_M, gen_size=12, data_fields=8, num_trials=100,
                          strike_points=(0, 2, 3, 4, 6, 8, 10, 12), threshold=2) -> Path:
    """Silent-accept rate vs strike point for the orthogonal oracle (existing attack
    sim) and end-to-end HMAC side by side. Expected: orthogonal admits silent
    forgeries once S>=threshold; HMAC stays flat at 0."""
    run_dir = get_run_log_dir("scheme_attack_comparison", trials=num_trials, gen=gen_size, m=field_m)
    base_field = create_field(field_m)
    cfg = AdmitConfig()

    summary_rows = []
    for s in strike_points:
        print(f"=== strike_S={s} ===")
        orth = [run_attack_trial(base_field, data_fields, gen_size, s, threshold=threshold)
                for _ in range(num_trials)]
        hmac_rs = [run_hmac_attack_trial(base_field, data_fields, gen_size, s, cfg, threshold)
                   for _ in range(num_trials)]
        summary_rows.append({
            "strike_s": s,
            "threshold": threshold,
            "trials": num_trials,
            "orth_silent_accept_rate": sum(r.silent_accept for r in orth) / num_trials,
            "orth_forged_accepted_rate": sum(r.forged_accepted for r in orth) / num_trials,
            "hmac_silent_accept_rate": sum(r.silent_accept for r in hmac_rs) / num_trials,
            "hmac_forged_accepted_rate": sum(r.forged_accepted for r in hmac_rs) / num_trials,
        })

    _write_csv(run_dir / "attack_summary.csv", summary_rows)
    _plot_attack_comparison(summary_rows, run_dir / "silent_accept_vs_strike.png")
    print(f"\nDone. Results written to: {run_dir}")
    return run_dir


# ── smoke tests ───────────────────────────────────────────────────────────────
def smoke_test(field_m=FIELD_M, gen_size=GEN_SIZE, data_fields=DATA_FIELDS,
               bit_error_rates=(1e-4, 1e-3, 5e-3), num_trials=20) -> None:
    base_field = create_field(field_m)
    cfg = AdmitConfig()
    print(f"\nsmoke_test  gen_size={gen_size}  trials/cell={num_trials}")
    print(f"{'scheme':>13} {'BER':>8} {'decode%':>8} {'silent%':>8} {'mean_ovh':>9} "
          f"{'tpp_ms':>9} {'scheme_ops':>11} {'unit':>14}")
    for name in SCHEME_NAMES:
        for ber in bit_error_rates:
            rs = [_run_trial(name, base_field, data_fields, gen_size, ber, cfg)
                  for _ in range(num_trials)]
            dec = [r for r in rs if r.decoded]
            drate = len(dec) / len(rs)
            srate = sum(r.silent_decode for r in rs) / len(rs)
            ovh = float(np.mean([r.overhead for r in dec])) if dec else float("nan")
            tpp_ms = float(np.mean([r.time_per_packet_s for r in rs])) * 1e3
            ops = float(np.mean([r.scheme_ops for r in rs]))
            print(f"{name:>13} {ber:>8.0e} {drate:>8.2f} {srate:>8.2f} {ovh:>9.2f} "
                  f"{tpp_ms:>9.3f} {ops:>11.0f} {SCHEME_OP_UNIT[name]:>14}")


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written: {path}")


def _print_op_table(summary_rows, scheme_names, bit_error_rates) -> None:
    """Native op counts are incommensurable across schemes, so they get a table, not
    a shared-axis plot (ADR-0009)."""
    print("\nNative op counts (mean per trial) -- units differ per scheme, do NOT compare across rows:")
    print(f"{'scheme':>11} {'unit':>15} " + " ".join(f"{b:>10.0e}" for b in bit_error_rates))
    for name in scheme_names:
        by_ber = {row["bit_error_rate"]: row["scheme_ops_mean"]
                  for row in summary_rows if row["scheme"] == name}
        cells = " ".join(f"{by_ber.get(b, float('nan')):>10.0f}" for b in bit_error_rates)
        print(f"{name:>11} {SCHEME_OP_UNIT[name]:>15} {cells}")
    print(f"\nStatic tag overhead (bits/packet): " +
          ", ".join(f"{name}={_tag_overhead_bits_for(name, GEN_SIZE, FIELD_M)}" for name in scheme_names))


def _plot_by_scheme(summary_rows, scheme_names, metric, ylabel, output_path,
                    ylim=(-0.02, 1.02), hline=None) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    for name in scheme_names:
        points = sorted((row["bit_error_rate"], row[metric])
                        for row in summary_rows if row["scheme"] == name)
        if not points:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ax.plot(xs, ys, "-", marker="o", color=SCHEME_COLORS.get(name), linewidth=2,
                markersize=6, label=name)
    if hline is not None:
        ax.axhline(hline, color="grey", linestyle="-.", alpha=0.6, label=f"ideal = {hline:g}")
    ax.set_xscale("log")
    ax.set_xlabel("Bit error rate", fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
    ax.set_title(f"{ylabel} vs BER, by scheme", fontsize=13, fontweight="bold")
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=10)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {output_path}")


def _plot_by_scheme_hd(summary_rows, scheme_names, hds, metric, ylabel, output_path,
                       ylim=(-0.02, 1.02), hline=None) -> None:
    """One line per (scheme, HD): colour = scheme, linestyle = Hamming distance."""
    fig, ax = plt.subplots(figsize=(9, 6))
    for name in scheme_names:
        for hd in hds:
            points = sorted((row["bit_error_rate"], row[metric]) for row in summary_rows
                            if row["scheme"] == name and row["hamming_distance"] == hd)
            if not points:
                continue
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            ax.plot(xs, ys, HD_LINESTYLE.get(hd, "-"), marker="o", color=SCHEME_COLORS.get(name),
                    linewidth=2, markersize=5, label=f"{name} HD{hd}")
    if hline is not None:
        ax.axhline(hline, color="grey", linestyle="-.", alpha=0.6, label=f"ideal = {hline:g}")
    ax.set_xscale("log")
    ax.set_xlabel("Bit error rate", fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
    ax.set_title(f"{ylabel} vs BER, by scheme x HD", fontsize=13, fontweight="bold")
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=8, ncol=len(scheme_names))
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {output_path}")


def _plot_by_n_strategy(summary_rows, n_values, strategies, metric, ylabel, output_path,
                        ylim=(-0.02, 1.02), hline=None, draw_flat_arms=True) -> None:
    """One line per (N, strategy), plus the N=1 orthogonal baseline: colour =
    strategy (orthogonal counts as its own "strategy" here), linestyle = N.
    NaN points (e.g. ic_refinement_failure_rate with zero pairs attempted) are
    dropped from that line rather than plotted as a gap.

    draw_flat_arms=False suppresses the orthogonal/CRC reference lines -- used for the
    detection/recovery-op plots, where those arms have no phase-split instrumentation
    and would otherwise draw a misleading flat line at 0 (not "zero cost", just
    un-bucketed)."""
    fig, ax = plt.subplots(figsize=(9, 6))

    # Flat (non-segmented, N=1) reference arms -- orthogonal + the CRC baselines -- each
    # drawn as its own solid line keyed by scheme, so CRC recovery/overhead sits on the
    # same axes as the segmented (N, strategy) lines below. Draw in registration order.
    flat_schemes = [s for s in ("orthogonal",) + tuple(SEGMENTED_CRC_SCHEMES)
                    if draw_flat_arms and any(row["scheme"] == s and row["n"] == 1 for row in summary_rows)]
    for scheme in flat_schemes:
        points = sorted((row["bit_error_rate"], row[metric]) for row in summary_rows
                        if row["scheme"] == scheme and not np.isnan(row[metric]))
        if not points:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ax.plot(xs, ys, "-", marker=FLAT_ARM_MARKER.get(scheme, "o"),
                color=FLAT_ARM_COLOR.get(scheme), linewidth=2, markersize=6,
                markerfacecolor="none" if scheme != "orthogonal" else FLAT_ARM_COLOR.get(scheme),
                markeredgewidth=1.6, label=FLAT_ARM_LABEL.get(scheme, scheme))

    for strategy in strategies:
        for n in n_values:
            points = sorted((row["bit_error_rate"], row[metric]) for row in summary_rows
                            if row["n"] == n and row["strategy"] == strategy and not np.isnan(row[metric]))
            if not points:
                continue
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            ax.plot(xs, ys, SEGMENTED_N_LINESTYLE.get(n, "-"), marker="s",
                    color=SEGMENTED_STRATEGY_COLORS.get(strategy), linewidth=2, markersize=5,
                    label=f"{strategy} N={n}")

    if hline is not None:
        ax.axhline(hline, color="grey", linestyle="-.", alpha=0.6, label=f"ideal = {hline:g}")
    ax.set_xscale("log")
    ax.set_xlabel("Bit error rate", fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
    ax.set_title(f"{ylabel} vs BER, by N x strategy", fontsize=13, fontweight="bold")
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    # Only draw a legend when something was actually plotted: the ic-refinement plot
    # for a sweep where no pair was ever attempted has all-NaN lines and no baseline,
    # and an unconditional legend() there just warns "No artists with labels".
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=8, ncol=2)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved: {output_path}")


def _plot_attack_comparison(summary_rows, output_path) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    points = sorted((row["strike_s"], row["orth_silent_accept_rate"],
                     row["hmac_silent_accept_rate"]) for row in summary_rows)
    xs = [p[0] for p in points]
    ax.plot(xs, [p[1] for p in points], "-", marker="o", color=SCHEME_COLORS["orthogonal"],
            linewidth=2, markersize=6, label="orthogonal")
    ax.plot(xs, [p[2] for p in points], "-", marker="s", color=SCHEME_COLORS["hmac"],
            linewidth=2, markersize=6, label="hmac (end-to-end)")
    ax.set_xlabel("Strike point S", fontsize=12, fontweight="bold")
    ax.set_ylabel("Silent-accept rate", fontsize=12, fontweight="bold")
    ax.set_title("Silent-accept rate vs strike point: orthogonal vs HMAC", fontsize=13, fontweight="bold")
    ax.set_ylim(-0.02, 1.02)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=10)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {output_path}")


def main(argv=None) -> None:
    """First-class entrypoints (ticket 02). Each sweep is a named run so a user/agent can
    launch it without editing source:

        python -m simulation.scheme_comparison_sim segmented   # N x BER segmented sweep
        python -m simulation.scheme_comparison_sim smoke       # quick smoke table
        python -m simulation.scheme_comparison_sim hd          # HD-parity recovery sweep
        python -m simulation.scheme_comparison_sim recovery    # random-error recovery sweep
        python -m simulation.scheme_comparison_sim attack      # orthogonal vs HMAC attack

    (no arg -> the default smoke + hd_sweep, preserving prior behaviour). See
    docs/running_sims.md for the required LOG_FOLDER/PYTHONPATH env + venv."""
    import argparse
    parser = argparse.ArgumentParser(description="Scheme comparison driver (ADR-0009/0011/0012).")
    parser.add_argument("sweep", nargs="?", default=None,
                        choices=["smoke", "hd", "recovery", "attack", "segmented"],
                        help="which experiment to run (default: smoke + hd)")
    parser.add_argument("--cell-time-budget-s", type=float, default=SEGMENTED_CELL_TIME_BUDGET_S,
                        help="segmented sweep only: per-cell wall-time cap in seconds "
                             "(0 or negative -> one trial/cell; use a large value to effectively disable)")
    args = parser.parse_args(argv)

    if args.sweep is None:
        smoke_test()
        run_hd_sweep()
    elif args.sweep == "smoke":
        smoke_test()
    elif args.sweep == "hd":
        run_hd_sweep()
    elif args.sweep == "recovery":
        run_recovery_sweep()
    elif args.sweep == "attack":
        run_attack_comparison()
    elif args.sweep == "segmented":
        run_segmented_n_sweep(cell_time_budget_s=args.cell_time_budget_s)


if __name__ == "__main__":
    main()
    # run_segmented_n_sweep()  # ADR-0012; slow at high BER, see its module comment
