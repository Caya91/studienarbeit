"""Baseline comparison driver (ADR-0009): orthogonal tag vs CRC vs HMAC.

Two experiments, both scheme-agnostic (the per-scheme parts live in
`integrity_schemes.py`); the validated `recovery_decode_sim` / `intelligent_attack_sim`
are imported and left untouched:

1. Random-error recovery (all three schemes). Single-hop send-until-decodable at a
   sweep of BERs. Headline: transmission overhead (packets_to_decode / gen_size) --
   the orthogonal tag repairs and so needs fewer transmissions, CRC/HMAC drop and
   retransmit. Also decode-success, silent-decode, and each scheme's NATIVE op count
   (field muls / CRC byte-ops / HMAC block-ops -- reported per scheme, never summed).

2. Attack (orthogonal vs HMAC only; CRC is not a security baseline). End-to-end HMAC
   with a source<->receiver key the relay lacks structurally blocks the targeted
   forgery (silent-accept == 0); the orthogonal arm is the existing attack sim.

Computation is reported in native units + the tag-overhead figure; wall-clock is
deliberately not produced here (see docs/comparison_methodology_notes.md).
"""

import csv
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
)
from simulation.intelligent_attack_sim import run_attack_trial
from utils.log_helpers import get_run_log_dir


# ── Sweep configuration ──────────────────────────────────────────────────────
FIELD_M = 8
GEN_SIZE = 10
DATA_FIELDS = 10
NUM_TRIALS = 100
BIT_ERROR_RATES = [1e-5, 5e-5, 1e-4, 5e-4, 1e-3, 5e-3, 1e-2]
MAX_PACKETS_FACTOR = 12
SCHEME_NAMES = ("orthogonal", "crc", "hmac")

SCHEME_COLORS = {"orthogonal": "#2a6f97", "crc": "#e07a5f", "hmac": "#3d405b"}
SCHEME_OP_UNIT = {"orthogonal": "field muls", "crc": "CRC byte-ops", "hmac": "HMAC block-ops"}


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

    silent = decoded and not correct
    status = "decoded" if correct else ("silent_decode" if decoded else "timeout")
    return SchemeTrialResult(
        scheme=scheme.name, decoded=decoded, correct=correct, silent_decode=silent,
        packets_to_decode=received, overhead=received / gen_size,
        scheme_ops=scheme.primary_ops(instrument), decode_ops=cnt_decode.mul_count,
        status=status,
    )


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
        scheme = SCHEMES[name]
        tag_bits = scheme.tag_overhead_bits(gen_size, field_m)
        for ber in bit_error_rates:
            print(f"=== scheme={name} BER={ber:g} ===")
            results = [run_recovery_trial(base_field, scheme, data_fields, gen_size, ber, cfg)
                       for _ in range(num_trials)]
            for trial_id, r in enumerate(results):
                raw_rows.append({"scheme": name, "bit_error_rate": ber, "trial_id": trial_id, **asdict(r)})

            decoded = [r for r in results if r.decoded]
            summary_rows.append({
                "scheme": name,
                "bit_error_rate": ber,
                "trials": num_trials,
                "tag_overhead_bits": tag_bits,
                "decode_success_rate": len(decoded) / num_trials,
                "silent_decode_rate": sum(r.silent_decode for r in results) / num_trials,
                "timeout_rate": sum(r.status == "timeout" for r in results) / num_trials,
                "mean_overhead_decoded": float(np.mean([r.overhead for r in decoded])) if decoded else float("nan"),
                "scheme_op_unit": SCHEME_OP_UNIT[name],
                "scheme_ops_mean": float(np.mean([r.scheme_ops for r in results])),
                "decode_ops_mean": float(np.mean([r.decode_ops for r in results])),
            })

    _write_csv(run_dir / "raw_results.csv", raw_rows)
    _write_csv(run_dir / "summary.csv", summary_rows)

    _plot_by_scheme(summary_rows, scheme_names, "decode_success_rate",
                    "Decode-success rate", run_dir / "decode_success_vs_ber.png", ylim=(-0.02, 1.02))
    _plot_by_scheme(summary_rows, scheme_names, "silent_decode_rate",
                    "Silent-decode rate", run_dir / "silent_decode_vs_ber.png", ylim=(-0.02, 1.02))
    _plot_by_scheme(summary_rows, scheme_names, "mean_overhead_decoded",
                    "Mean transmission overhead (packets / gen_size)",
                    run_dir / "overhead_vs_ber.png", ylim=None, hline=1.0)

    _print_op_table(summary_rows, scheme_names, bit_error_rates)
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
    print(f"{'scheme':>11} {'BER':>8} {'decode%':>8} {'silent%':>8} {'mean_ovh':>9} "
          f"{'scheme_ops':>11} {'unit':>14}")
    for name in SCHEME_NAMES:
        scheme = SCHEMES[name]
        for ber in bit_error_rates:
            rs = [run_recovery_trial(base_field, scheme, data_fields, gen_size, ber, cfg)
                  for _ in range(num_trials)]
            dec = [r for r in rs if r.decoded]
            drate = len(dec) / len(rs)
            srate = sum(r.silent_decode for r in rs) / len(rs)
            ovh = float(np.mean([r.overhead for r in dec])) if dec else float("nan")
            ops = float(np.mean([r.scheme_ops for r in rs]))
            print(f"{name:>11} {ber:>8.0e} {drate:>8.2f} {srate:>8.2f} {ovh:>9.2f} "
                  f"{ops:>11.0f} {SCHEME_OP_UNIT[name]:>14}")


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
          ", ".join(f"{name}={SCHEMES[name].tag_overhead_bits(GEN_SIZE, FIELD_M)}" for name in scheme_names))


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


if __name__ == "__main__":
    smoke_test()
    # run_recovery_sweep()
    # run_attack_comparison()
