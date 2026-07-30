"""Intelligent-pollution attack sweep -- a white-box on-path relay forges packets
that are silently accepted and poison the decode (ADR-0008).

Threat model (the "malicious relay"): the attacker sits on the receiver's inbound
link. For a while it honestly *forwards* recoded packets while keeping copies
(forward-and-record) -- so the receiver's trust pool is built out of exactly the
packets the attacker holds. After forwarding `strike_S` packets it *strikes*:
each round it injects a forged packet built by `pollute_intelligent`, which
(a) passes the self-check for free, (b) is cross-orthogonal to `threshold` of the
saved packets so it clears the current absolute-count trust gate (ADR-0004), and
(c) carries a coefficient row independent of the accepted set with inconsistent
data, so once it enters the decode basis the decoded generation is wrong.

Because the whole scheme's clean packets are mutually orthogonal, a forger that
agrees with just `threshold` (=2..4) packets is indistinguishable from a clean
packet under the absolute-count rule -- the honest majority provides no defense.
And a single independent silent poison corrupts the entire decode: "one is enough".

What we measure (grade by re-decoding against the known source, reusing
recovery_decode_sim's _accepted_packets / _try_decode):
- silent_accept_rate: trials where a forged packet was admitted AND the decode came
  out wrong -- the safety-critical number.
- forged_accepted_rate: trials where a forged packet cleared the trust gate at all.
- attacker work: field-ops on the FORGING path only (separate CountingField), per
  accepted forged packet -- the symmetric-to-defender cost from ADR-0007.
- earliest strike: smallest strike_S that still yields a silent accept.

Deferred (see ADR-0008): the self-vouching flood, the disagreement-aware ratio
trust rule, a seen-may-miss-pool overlap model, and an active (dropping) relay.
"""

import csv
import random
from dataclasses import dataclass, asdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from icecream import ic

ic.disable()

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import (
    generate_symbols_until_nonzero,
    recode_rlnc_without_coeffs,
)
from binary_ext_fields.pollution import pollute_intelligent
from simulation.recovery_decode_sim import _accepted_packets, _try_decode
from utils.log_helpers import get_run_log_dir


# ── Sweep configuration ──────────────────────────────────────────────────────
FIELD_M = 8
GEN_SIZE = 12                 # independent packets needed for a decodable basis
DATA_FIELDS = 8               # data symbols per packet (before the tag block)
NUM_TRIALS = 100

THRESHOLD = 2                 # trust gate V (= sniff min_trust_count on the decode gate)
MIN_POOL_SIZE = 6             # receiver warm-up before any packet is trusted (ADR-0004)
N_INJECT = 1                  # forged packets the relay tries to slip in per trial
MAX_PACKETS_FACTOR = 6        # arrival cap = factor * gen_size (else: no-decode)

STRIKE_POINTS = [0, 1, 2, 3, 4, 6, 8, 10, 12]   # honest packets forwarded before striking


@dataclass
class AttackTrialResult:
    decoded: bool                 # receiver reached full rank and decoded
    correct: bool                 # decoded == source
    silent_accept: bool           # decoded to the WRONG source (a forged packet poisoned it)
    forged_accepted: bool         # >=1 forged packet cleared the trust gate at decode time
    n_injected: int               # forged packets actually appended to the pool
    attacker_attempts: int        # calls to pollute_intelligent (incl. inconsistent solves)
    attacker_mul: int             # field muls on the forging path (attacker work)
    attacker_add: int
    packets_received: int         # total arrivals when the trial stopped
    rounds: int
    status: str                   # "silent_accept" | "clean_decode" | "no_decode"


def _coeff_prefixes(field, gen_size, packets):
    return [bytearray(p[:gen_size]) for p in packets]


def run_attack_trial(base_field, data_fields, gen_size, strike_s,
                     threshold=THRESHOLD, n_inject=N_INJECT,
                     min_pool_size=MIN_POOL_SIZE, max_packets_factor=MAX_PACKETS_FACTOR,
                     rng=None) -> AttackTrialResult:
    """One receiver lifetime under a forward-and-record relay that strikes after
    `strike_s` honest forwards. Honest packets keep arriving after the strike, so
    the forged packet is only a fraction of the pool. Stops at first decode or the
    arrival cap."""
    rng = rng or random
    source = generate_symbols_until_nonzero(base_field, data_fields, gen_size, coefficients=True)
    source_suffix = [bytearray(p[gen_size:]) for p in source]

    cnt_recv = CountingField(base_field)   # receiver pipeline work (unused as a headline here)
    cnt_atk = CountingField(base_field)    # attacker forging work -- the metric we report
    max_packets = max_packets_factor * gen_size

    pool: list[bytearray] = []
    saved: list[bytearray] = []            # attacker's forwarded-and-recorded copies
    forged_ids: set[int] = set()           # id() of forged packets, to spot them in `accepted`

    forwarded = injected = attempts = rounds = 0
    decoded = correct = False
    accepted = []

    while len(pool) < max_packets:
        rounds += 1
        if injected < n_inject and forwarded >= strike_s and len(saved) >= threshold:
            # STRIKE: forge one packet orthogonal to `threshold` saved packets, with a
            # coefficient row independent of everything forwarded so far (=> a pivot).
            attempts += 1
            forged, _ncon = pollute_intelligent(
                cnt_atk, saved, gen_size, data_fields, threshold,
                avoid_coeff_rows=_coeff_prefixes(base_field, gen_size, saved), rng=rng,
            )
            if forged is not None:
                pool.append(forged)
                forged_ids.add(id(forged))
                injected += 1
        else:
            # FORWARD: honest recoded arrival; the relay keeps a copy.
            clean = bytearray(recode_rlnc_without_coeffs(base_field, source, gen_size, count=1))
            pool.append(clean)
            saved.append(clean)
            forwarded += 1

        accepted = _accepted_packets(cnt_recv, pool, decode_verify_count=threshold,
                                     min_pool_size=min_pool_size)
        decoded, correct = _try_decode(cnt_recv, accepted, gen_size, source_suffix)
        if decoded:
            break

    forged_accepted = any(id(p) in forged_ids for p in accepted)
    silent = decoded and not correct
    status = "silent_accept" if silent else ("clean_decode" if decoded else "no_decode")
    return AttackTrialResult(
        decoded=decoded,
        correct=correct,
        silent_accept=silent,
        forged_accepted=forged_accepted,
        n_injected=injected,
        attacker_attempts=attempts,
        attacker_mul=cnt_atk.mul_count,
        attacker_add=cnt_atk.add_count,
        packets_received=len(pool),
        rounds=rounds,
        status=status,
    )


def smoke_test(field_m=FIELD_M, gen_size=GEN_SIZE, data_fields=DATA_FIELDS,
               strike_points=(0, 2, 3, 6, 12), num_trials=40, threshold=THRESHOLD) -> None:
    """A few trials per strike point -- quick check that a well-timed strike lands a
    silent accept and a late one misses (honest set already full-rank)."""
    base_field = create_field(field_m)
    print(f"\nsmoke_test  m={field_m} gen={gen_size} data={data_fields} thr={threshold} "
          f"trials={num_trials} cap={MAX_PACKETS_FACTOR}x")
    print(f"{'strikeS':>8} {'silent%':>8} {'forgedOK%':>10} {'decode%':>8} "
          f"{'atkMul':>8} {'atkTries':>9}")
    for s in strike_points:
        rs = [run_attack_trial(base_field, data_fields, gen_size, s, threshold=threshold)
              for _ in range(num_trials)]
        silent = sum(r.silent_accept for r in rs) / len(rs)
        fok = sum(r.forged_accepted for r in rs) / len(rs)
        dec = sum(r.decoded for r in rs) / len(rs)
        mul = float(np.mean([r.attacker_mul for r in rs]))
        tries = float(np.mean([r.attacker_attempts for r in rs]))
        print(f"{s:>8} {silent:>8.2f} {fok:>10.2f} {dec:>8.2f} {mul:>8.0f} {tries:>9.1f}")


def run_strike_sweep(field_m=FIELD_M, gen_size=GEN_SIZE, data_fields=DATA_FIELDS,
                     num_trials=NUM_TRIALS, strike_points=STRIKE_POINTS,
                     threshold=THRESHOLD) -> Path:
    """Sweep the strike point S. Headline: silent-accept rate and attacker work vs S,
    plus the earliest S that still yields a silent accept."""
    run_dir = get_run_log_dir("intelligent_attack_sim", trials=num_trials, gen=gen_size, m=field_m)
    base_field = create_field(field_m)

    raw_rows, summary_rows = [], []
    for s in strike_points:
        print(f"=== strike_S={s} ===")
        results = [run_attack_trial(base_field, data_fields, gen_size, s, threshold=threshold)
                   for _ in range(num_trials)]
        for trial_id, r in enumerate(results):
            raw_rows.append({"strike_s": s, "trial_id": trial_id, **asdict(r)})

        accepted_forged = [r for r in results if r.forged_accepted]
        summary_rows.append({
            "strike_s": s,
            "threshold": threshold,
            "trials": num_trials,
            "silent_accept_rate": sum(r.silent_accept for r in results) / num_trials,
            "forged_accepted_rate": len(accepted_forged) / num_trials,
            "decode_rate": sum(r.decoded for r in results) / num_trials,
            # attacker work per accepted forged packet (the "how much work" number)
            "attacker_mul_mean": float(np.mean([r.attacker_mul for r in accepted_forged]))
                if accepted_forged else float("nan"),
            "attacker_attempts_mean": float(np.mean([r.attacker_attempts for r in results])),
            "mean_packets": float(np.mean([r.packets_received for r in results])),
        })

    _write_csv(run_dir / "raw_results.csv", raw_rows)
    _write_csv(run_dir / "summary.csv", summary_rows)

    landed = [row["strike_s"] for row in summary_rows if row["silent_accept_rate"] > 0]
    earliest = min(landed) if landed else None
    print(f"\nEarliest strike with a silent accept: "
          f"{earliest if earliest is not None else 'none in sweep'}")

    _plot_vs_strike(summary_rows, "silent_accept_rate",
                    "Silent-accept rate (forged admitted AND wrong decode)",
                    run_dir / "silent_accept_vs_strike.png", ylim=(-0.02, 1.02))
    _plot_vs_strike(summary_rows, "forged_accepted_rate",
                    "Forged-accepted rate (cleared the trust gate)",
                    run_dir / "forged_accepted_vs_strike.png", ylim=(-0.02, 1.02))
    _plot_vs_strike(summary_rows, "attacker_mul_mean",
                    "Attacker field-muls per accepted forged packet",
                    run_dir / "attacker_work_vs_strike.png", ylim=None)

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


def _plot_vs_strike(summary_rows, metric, ylabel, output_path, ylim=(-0.02, 1.02)) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    points = sorted((row["strike_s"], row[metric]) for row in summary_rows)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    ax.plot(xs, ys, "-", marker="o", color="#b5179e", linewidth=2, markersize=6)
    ax.set_xlabel("Strike point S (honest packets forwarded before striking)",
                  fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
    ax.set_title(f"{ylabel}\nvs strike point", fontsize=13, fontweight="bold")
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {output_path}")


if __name__ == "__main__":
    smoke_test()
    # run_strike_sweep()
