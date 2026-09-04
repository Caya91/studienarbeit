"""Segmented-scheme forgery attack: keyless orthogonal vs keyed homomorphic-MAC
(ticket 06 -- the security half of the segmented comparison).

Threat model (mirrors intelligent_attack_sim.py's malicious relay, extended to the
segmented arms): a white-box on-path relay forwards honest recoded packets while
keeping copies, then at a strike point injects ONE forged packet. The forged packet
is a COPY of a genuine valid packet with exactly ONE segment replaced -- the
coefficient segment. It leaves the other N-1 segments genuine, so they still verify
for free. The forged coeff-segment carries a coefficient row INDEPENDENT of the
already-accepted rows (so it pivots into the decode basis) while the packet's data
segments are the victim's genuine data -- inconsistent with the new coefficients, so
once the packet is admitted the decoded generation is WRONG (ADR-0008's definition of
a successful attack: admitted AND wrong, graded against ground truth).

Why the coefficient segment is the poison target (ticket 06 decision 3): a packet is
admitted only if EVERY segment trusts it, but the attacker does not have to forge all
N -- forging one segment that makes the packet an independent-but-inconsistent basis
row is enough, and the coeff-segment is the one whose payload IS the coefficient row,
so replacing it is what buys the independent pivot. Forge-work is therefore the cost
of breaking ONE segment, independent of N (N is a recovery knob, not a security knob);
the per-segment dial that actually sets forge difficulty is V = tags/segment = gen_size.

Two schemes x (for the MAC) two key settings:
  - orthogonal (keyless): the relay solves the coeff-segment's self+cross
    orthogonality system (pollute_intelligent, scoped to one segment) -- always
    possible, at a measurable field-op cost W. Same in both key settings (no key
    exists to leak).
  - MAC, setting b (key SECRET): the relay cannot compute a valid coeff-segment tag,
    so its forgery is rejected -> silent-accept ~ 0. The MAC wins this setting.
  - MAC, setting c (key COMPROMISED): the relay computes valid tags for free ->
    forgery admitted -> silent-accept ~ 1. The MAC gives zero protection.

The headline is the SHAPE: MAC security is a cliff (great while the key is secret,
gone the moment it isn't); the orthogonal work-floor W is flat and never depends on a
secret. In setting b the MAC is genuinely harder to forge -- reported honestly.

Self-contained by design (ticket 06 decision 4): the attack loop lives here top to
bottom rather than being threaded through the generic recovery driver. It reuses only
verified leaf primitives -- tagging, recoding, the pollute_intelligent linear solve,
_try_decode -- never the recovery/admit machinery of integrity_schemes.py.
"""

import csv
import random
from dataclasses import dataclass, asdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import (
    generate_identity_coefficients,
    recode_rlnc_without_coeffs,
    check_orth_packet,
)
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.pollution import pollute_intelligent, _independent_coeff_row
from binary_ext_fields.segmented_tagging import tag_generation_segmented, layout_segments
from binary_ext_fields.segmented_mac_tagging import (
    layout_mac_segments, generate_keyset, tag_generation_mac, mac_tag_vector, mac_verify_segment,
)
from simulation.integrity_schemes import _strip_to_code
from simulation.recovery_decode_sim import _try_decode
from utils.log_helpers import get_run_log_dir


# ── Sweep configuration ──────────────────────────────────────────────────────
FIELD_M = 8
GEN_SIZE = 6
DATA_FIELDS = 24              # splits into every N's data-segments >= rank floor (gen_size-1)
NUM_TRIALS = 60

THRESHOLD = 2                 # per-segment trust gate V (ADR-0004 absolute-count rule)
MIN_POOL_SIZE = GEN_SIZE      # receiver warm-up before any packet is trusted
MAX_PACKETS_FACTOR = 6        # arrival cap = factor * gen_size, else "no decode"

N_VALUES = (2, 3, 5)          # segments per packet = 1 coeff + (N-1) data
# Strike after this many honest forwards: early enough that the forged independent
# coeff row still occupies a real pivot (before the honest set spans on its own),
# late enough that `threshold` copies are already saved to forge agreement with.
STRIKE_S = THRESHOLD


# ── Arm labels ────────────────────────────────────────────────────────────────
# (scheme, key_setting): key_setting is "n/a" for the keyless orthogonal arm; "secret"
# (b) and "compromised" (c) for the MAC. Orthogonal is run once and shown in both
# settings' panels as the flat reference.
ARMS = [
    ("orthogonal", "n/a"),
    ("mac", "secret"),
    ("mac", "compromised"),
]


@dataclass
class AttackTrialResult:
    scheme: str
    key_setting: str
    n: int
    decoded: bool                 # accepted set reached full rank
    correct: bool                 # decoded == source
    silent_accept: bool           # admitted a forgery AND decoded wrong (the safety number)
    forged_admitted: bool         # the forged packet cleared every segment's gate at decode time
    attacker_mul: int             # field muls on the forging path (attacker work)
    attacker_add: int
    packets_received: int
    rounds: int
    status: str                   # "silent_accept" | "clean_decode" | "no_decode"


# ── Building a valid segmented generation (either arm) ────────────────────────

def _build_orthogonal_generation(field, gen_size, data_fields, num_data_segments, rng):
    """A valid orthogonal-tagged generation + its TaggedSegment layout + the source
    data rows (ground truth for grading)."""
    data_rows = [bytearray(rng.randint(0, field.max_value) for _ in range(data_fields))
                 for _ in range(gen_size)]
    plain = generate_identity_coefficients(field, data_rows)
    result = tag_generation_segmented(field, plain, gen_size, num_data_segments)
    assert result.ok, "tagging must succeed for the chosen (gen_size, data_fields, N)"
    return result.packets, result.segments, data_rows


def _build_mac_generation(field, gen_size, data_fields, num_data_segments, num_keys, rng):
    """A valid MAC-tagged generation + its MacSegment layout + keyset + source rows."""
    data_rows = [bytearray(rng.randint(0, field.max_value) for _ in range(data_fields))
                 for _ in range(gen_size)]
    plain = generate_identity_coefficients(field, data_rows)
    segments = layout_mac_segments(gen_size, data_fields, num_data_segments, num_keys)
    keyset = generate_keyset(field, segments, rng)
    packets = tag_generation_mac(field, plain, gen_size, num_data_segments, keyset, num_keys)
    return packets, segments, keyset, data_rows


# ── Admission oracles (the receiver's real accept rule, per arm) ──────────────

def _seg_slice(packet, segment):
    return packet[segment.start: segment.start + segment.total_length]


def _orth_segment_trusted(field, slices, threshold):
    """Indices of one segment's slices that self-check AND are cross-orthogonal to at
    least `threshold` other self-checking slices -- the ADR-0004 absolute-count trust
    rule, applied per segment."""
    self_pass = [i for i, s in enumerate(slices) if check_orth_packet(field, s)]
    trusted = []
    for i in self_pass:
        agree = sum(1 for j in self_pass
                    if j != i and inner_product_bytes(field, slices[i], slices[j]) == 0)
        if agree >= threshold:
            trusted.append(i)
    return set(trusted)


def _admit_orthogonal(field, pool, segments, threshold, min_pool_size):
    """A packet is admitted iff it is trusted in EVERY segment (intersection). Warm-up
    gate: nothing is admitted until the pool has min_pool_size packets."""
    if len(pool) < min_pool_size:
        return []
    admitted = set(range(len(pool)))
    for segment in segments:
        slices = [_seg_slice(p, segment) for p in pool]
        admitted &= _orth_segment_trusted(field, slices, threshold)
    return sorted(admitted)


def _admit_mac(field, pool, segments, keyset, min_pool_size):
    """A packet is admitted iff EVERY segment's MAC verifies (self-sufficient -- no
    cross-check). Same warm-up gate."""
    if len(pool) < min_pool_size:
        return []
    admitted = []
    for i, packet in enumerate(pool):
        if all(mac_verify_segment(field, keyset[s], _seg_slice(packet, seg), seg)
               for s, seg in enumerate(segments)):
            admitted.append(i)
    return admitted


# ── Forging one coefficient segment of a copied valid packet ──────────────────

def _forge_coeff_segment_orthogonal(cnt_atk, saved, coeff_segment, gen_size, threshold,
                                    accepted_coeff_rows, rng):
    """Solve the coeff-segment's self+cross orthogonality system for a forged slice:
    an INDEPENDENT coefficient row + salt as the payload, tag bytes solved so the slice
    self-verifies and cross-verifies against `threshold` saved coeff-slices. This is
    pollute_intelligent scoped to one segment: prefix = [coeff row (gen_size) | 1 salt
    byte], tag_start = gen_size + 1, gen_size tag unknowns -- exactly the coeff-segment
    layout. Charged through cnt_atk (attacker work). Returns (forged_slice | None)."""
    saved_coeff_slices = [_seg_slice(p, coeff_segment) for p in saved]
    if len(saved_coeff_slices) < threshold:
        return None
    forged_slice, _n = pollute_intelligent(
        cnt_atk, saved_coeff_slices, gen_size, data_length=1, threshold=threshold,
        avoid_coeff_rows=accepted_coeff_rows, rng=rng,
    )
    return forged_slice  # length = gen_size + 1 + gen_size = coeff_segment.total_length


def _forge_coeff_segment_mac(cnt_atk, coeff_segment, coeff_keys, gen_size,
                             accepted_coeff_rows, key_known, rng):
    """Forge a MAC coeff-segment: an independent coefficient row payload + tag bytes.
    key_known (setting c): compute the real homomorphic MAC over the forged row (valid
    tag, will verify). Not known (setting b): emit a bogus random tag (will NOT verify
    -- the whole point). Charged through cnt_atk. Returns the forged slice
    ([coeff row | num_keys tags], length coeff_segment.total_length)."""
    coeff_row = _independent_coeff_row(cnt_atk, gen_size, accepted_coeff_rows, rng)
    if key_known:
        tags = mac_tag_vector(cnt_atk, coeff_keys, coeff_row)          # real, verifying tag
    else:
        tags = [rng.randint(0, cnt_atk.max_value) for _ in range(coeff_segment.num_keys)]  # bogus
    return bytearray(coeff_row) + bytearray(tags)


def _splice_segment(victim, segment, forged_slice):
    """A copy of `victim` with `segment`'s bytes replaced by forged_slice (the other
    N-1 segments stay genuine)."""
    forged = bytearray(victim)
    forged[segment.start: segment.start + segment.total_length] = forged_slice
    assert len(forged) == len(victim), "forged slice must match the segment width"
    return forged


# ── One attack lifetime (either arm / key setting) ────────────────────────────

def run_attack_trial(base_field, scheme, key_setting, n, gen_size=GEN_SIZE,
                     data_fields=DATA_FIELDS, threshold=THRESHOLD, strike_s=STRIKE_S,
                     min_pool_size=MIN_POOL_SIZE, max_packets_factor=MAX_PACKETS_FACTOR,
                     rng=None) -> AttackTrialResult:
    """Forward honest recoded packets (the relay saves copies), inject ONE forged
    packet after `strike_s` forwards, and grade the decode against ground truth. The
    forged packet is a copy of the latest saved honest packet with its coeff-segment
    replaced by a forgery (independent coeff row + valid-or-bogus tag)."""
    rng = rng or random
    num_data_segments = n - 1
    key_known = (key_setting == "compromised")
    cnt_atk = CountingField(base_field)   # attacker forging work -- the reported metric
    cnt_recv = CountingField(base_field)  # receiver verify work (not a headline here)
    max_packets = max_packets_factor * gen_size

    if scheme == "orthogonal":
        gen_packets, segments, data_rows = _build_orthogonal_generation(
            base_field, gen_size, data_fields, num_data_segments, rng)
        keyset = None
    else:
        num_keys = gen_size
        gen_packets, segments, keyset, data_rows = _build_mac_generation(
            base_field, gen_size, data_fields, num_data_segments, num_keys, rng)
    coeff_segment = next(s for s in segments if s.kind == "coeff")
    source_suffix = data_rows  # identity-coefficient generation: systematic symbol i = data row i

    def admit(pool):
        if scheme == "orthogonal":
            return _admit_orthogonal(cnt_recv, pool, segments, threshold, min_pool_size)
        return _admit_mac(cnt_recv, pool, segments, keyset, min_pool_size)

    pool, saved = [], []
    forged_id = None
    forwarded = injected = rounds = 0
    decoded = correct = False
    admitted_idx = []

    while len(pool) < max_packets:
        rounds += 1
        can_strike = injected == 0 and forwarded >= strike_s and len(saved) >= threshold
        if can_strike:
            victim = saved[-1]                     # a genuine, fully-valid packet
            accepted = admit(pool)
            accepted_coeff_rows = [pool[i][coeff_segment.start:coeff_segment.start + gen_size]
                                   for i in accepted]
            if scheme == "orthogonal":
                forged_slice = _forge_coeff_segment_orthogonal(
                    cnt_atk, saved, coeff_segment, gen_size, threshold, accepted_coeff_rows, rng)
            else:
                forged_slice = _forge_coeff_segment_mac(
                    cnt_atk, coeff_segment, keyset[0], gen_size, accepted_coeff_rows, key_known, rng)
            if forged_slice is not None:
                forged = _splice_segment(victim, coeff_segment, forged_slice)
                pool.append(forged)
                forged_id = id(forged)
                injected += 1
                continue
        # FORWARD an honest recoded arrival; the relay records a copy.
        clean = bytearray(recode_rlnc_without_coeffs(base_field, gen_packets, gen_size, count=1))
        pool.append(clean)
        saved.append(clean)
        forwarded += 1

        admitted_idx = admit(pool)
        stripped = [_strip_to_code(pool[i], segments) for i in admitted_idx]
        decoded, correct = _try_decode(cnt_recv, stripped, gen_size, source_suffix)
        if decoded:
            break

    forged_admitted = forged_id is not None and any(id(pool[i]) == forged_id for i in admitted_idx)
    silent = decoded and not correct
    status = "silent_accept" if silent else ("clean_decode" if decoded else "no_decode")
    return AttackTrialResult(
        scheme=scheme, key_setting=key_setting, n=n,
        decoded=decoded, correct=correct, silent_accept=silent, forged_admitted=forged_admitted,
        attacker_mul=cnt_atk.mul_count, attacker_add=cnt_atk.add_count,
        packets_received=len(pool), rounds=rounds, status=status,
    )


# ── Sweeps + reporting ────────────────────────────────────────────────────────

def smoke_test(field_m=FIELD_M, gen_size=GEN_SIZE, data_fields=DATA_FIELDS,
               n_values=N_VALUES, num_trials=30) -> None:
    """A few trials per (arm, N): confirm the SHAPE -- orthogonal is forgeable at a
    flat work floor (silent > 0), MAC-secret rejects the forgery (silent ~ 0),
    MAC-compromised admits it (silent ~ 1), and forge-work is ~flat in N."""
    base_field = create_field(field_m)
    print(f"\nsmoke_test  m={field_m} gen={gen_size} data={data_fields} thr={THRESHOLD} "
          f"trials={num_trials}")
    print(f"{'scheme':>11} {'keysetting':>12} {'N':>2}  {'silent%':>8} {'forgedOK%':>10} "
          f"{'decode%':>8} {'atkMul':>9}")
    for n in n_values:
        for scheme, setting in ARMS:
            rs = [run_attack_trial(base_field, scheme, setting, n, gen_size, data_fields)
                  for _ in range(num_trials)]
            silent = np.mean([r.silent_accept for r in rs])
            fok = np.mean([r.forged_admitted for r in rs])
            dec = np.mean([r.decoded for r in rs])
            mul = np.mean([r.attacker_mul for r in rs])
            print(f"{scheme:>11} {setting:>12} {n:>2}  {silent:>8.2f} {fok:>10.2f} "
                  f"{dec:>8.2f} {mul:>9.0f}")


def run_attack_sweep(field_m=FIELD_M, gen_size=GEN_SIZE, data_fields=DATA_FIELDS,
                     n_values=N_VALUES, num_trials=NUM_TRIALS, threshold=THRESHOLD) -> Path:
    """Sweep N for every arm. Headline outputs: silent-accept vs N (the MAC cliff vs
    the orthogonal flat floor) and attacker forge-work vs N (flat -- N is not a
    security knob)."""
    run_dir = get_run_log_dir("segmented_attack_sim", trials=num_trials, gen=gen_size, m=field_m)
    base_field = create_field(field_m)

    raw_rows, summary_rows = [], []
    for n in n_values:
        for scheme, setting in ARMS:
            print(f"=== scheme={scheme} key={setting} N={n} ===")
            results = [run_attack_trial(base_field, scheme, setting, n, gen_size, data_fields,
                                        threshold=threshold) for _ in range(num_trials)]
            for trial_id, r in enumerate(results):
                raw_rows.append({"trial_id": trial_id, **asdict(r)})
            admitted = [r for r in results if r.forged_admitted]
            summary_rows.append({
                "scheme": scheme, "key_setting": setting, "n": n, "threshold": threshold,
                "trials": num_trials,
                "silent_accept_rate": np.mean([r.silent_accept for r in results]),
                "forged_admitted_rate": np.mean([r.forged_admitted for r in results]),
                "decode_rate": np.mean([r.decoded for r in results]),
                # attacker work per ADMITTED forgery (the "how much work to land one" number).
                # For MAC-secret no forgery is admitted -> NaN (it can't buy an accept at any
                # finite field-op cost; the real cost is the q^-V tag collision, not solving).
                "attacker_mul_per_admit": (np.mean([r.attacker_mul for r in admitted])
                                           if admitted else float("nan")),
                "attacker_mul_mean": np.mean([r.attacker_mul for r in results]),
            })

    _write_csv(run_dir / "raw_results.csv", raw_rows)
    _write_csv(run_dir / "summary.csv", summary_rows)

    _plot_vs_n(summary_rows, "silent_accept_rate",
               "Silent-accept rate (forgery admitted AND decode wrong)",
               run_dir / "silent_accept_vs_n.png", ylim=(-0.02, 1.02))
    _plot_vs_n(summary_rows, "attacker_mul_mean",
               "Attacker field-muls to forge one coeff-segment",
               run_dir / "attacker_work_vs_n.png", ylim=None)

    _print_shape_summary(summary_rows)
    print(f"\nDone. Results written to: {run_dir}")
    return run_dir


_ARM_STYLE = {
    ("orthogonal", "n/a"): ("#588157", "o", "orthogonal (keyless)"),
    ("mac", "secret"): ("#8338ec", "s", "MAC, key secret (b)"),
    ("mac", "compromised"): ("#fb8500", "^", "MAC, key compromised (c)"),
}


def _plot_vs_n(summary_rows, metric, ylabel, output_path, ylim=(-0.02, 1.02)) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    for (scheme, setting), (color, marker, label) in _ARM_STYLE.items():
        pts = sorted((row["n"], row[metric]) for row in summary_rows
                     if row["scheme"] == scheme and row["key_setting"] == setting)
        if not pts:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        ax.plot(xs, ys, "-", marker=marker, color=color, linewidth=2, markersize=8, label=label)
    ax.set_xlabel("N (segments per packet = 1 coeff + N-1 data)", fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
    ax.set_title(f"{ylabel}\nvs segments per packet", fontsize=13, fontweight="bold")
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=11)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {output_path}")


def _print_shape_summary(summary_rows) -> None:
    def rate(scheme, setting):
        vals = [r["silent_accept_rate"] for r in summary_rows
                if r["scheme"] == scheme and r["key_setting"] == setting]
        return np.mean(vals) if vals else float("nan")
    print("\n-- Shape (mean silent-accept over N) -------------------------")
    print(f"  orthogonal (keyless)     : {rate('orthogonal', 'n/a'):.2f}  (flat work floor, no key to leak)")
    print(f"  MAC, key secret (b)      : {rate('mac', 'secret'):.2f}  (forgery rejected -- MAC wins)")
    print(f"  MAC, key compromised (c) : {rate('mac', 'compromised'):.2f}  (valid tags for free -- MAC collapses)")
    print("  MAC security is a cliff (secret->leaked); orthogonal is a flat work floor.")


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written: {path}")


if __name__ == "__main__":
    smoke_test()
    # run_attack_sweep()
