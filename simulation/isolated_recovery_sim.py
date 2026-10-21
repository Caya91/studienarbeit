r"""
Isolated recovery comparison harness (ADR-0013, ticket 13).

Compares the RLNC recovery *mechanism* between the two arms -- keyless (orthogonal
self/cross tag) and keyed (homomorphic MAC) -- with everything but the acceptance
oracle held identical. This is deliberately NOT end-to-end: sniffing/trust
classification is idealized out (injected from ground truth), so a measured gap can
only come from the oracle, never from detection quality or the ADR-0002 exact solve
(both arms run bit-flip search only, tickets 10-12).

What is held identical (ADR-0013):
- Pool: G = gen_size ground-truth-CLEAN helper packets (fixed, never corrupted,
  never scored) -- the ARC basis for both arms and the keyless acceptance witnesses
  -- plus T corruptible target packets, scored on. Helpers are the identity-coeff
  originals (full-rank ARC basis); targets are recoded spares.
- Paired ground truth (common random numbers): one seed fixes the source payload,
  the coefficient vectors, and the helper/target split for BOTH arms. The error
  pattern on the information columns [coeff | payload] is applied IDENTICALLY to both
  arms (asserted); the tag/redundancy region is seed-matched per-arm (different
  layouts: keyless salt+orth tags vs keyed MAC tags), not byte-identical. In the
  data-only config both arms face exactly the same corruption end to end.
- Injected trust: recovery is handed the helper set directly (SegmentTrust from
  ground truth); classify_segment_trust(_mac) is never run here.

CRC-32 arms (ADR-0014, `arms=`): crc_acr / crc_blind -- one CRC-32 per segment instead of
salt + tags, same pairing/combined-search repair, ACR-localized or blind columns, ARC-only
configs only. Default arms stay keyless + keyed.

Three configs, each in both arms:
  coefficient_first  -- whole-packet BER, coeff repaired (full recovery incl. coeffs).
  ARC-only (a)       -- data-only BER, coeffs clean, ARC always applies (ticket 12).
  ARC-only (b)       -- whole-packet BER, coeff-corrupted targets dropped symmetrically.

Metrics over the T targets: recovery rate, silent-decode rate, recovery field-ops
(total GF ops of the recovery call), and a per-target head-to-head (win/loss/tie on
identical corruption). Silent-decode is a MEASURED output (it may rise at small W);
it is never a pass/fail limit. The one wiring self-check: data-only at a large W must
give ~0 silent decodes (a strong oracle rejects wrong fixes) -- if it does not, the
injection/oracle wiring is wrong.

Run the readable smoke (PowerShell, project .venv):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="$env:TEMP\st_logs"; .\.venv\Scripts\python.exe simulation\isolated_recovery_sim.py --smoke

W sweep (ticket 14) -> logs/isolated_recovery/<run>/raw_trials.csv (long: run in background):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; .\.venv\Scripts\python.exe simulation\isolated_recovery_sim.py --sweep --workers 6
Replot without re-running: scripts/isolated_recovery_plots_from_csv.py (pools every run dir).

FROZEN CSV SCHEMA (raw_trials.csv, CSV_SCHEMA_VERSION = 5; `CSV_COLUMNS` enforces it)
One row per (config, arm, repair_span, W, bit_error_rate, max_combined_hd, candidates_budget,
seed) -- max_combined_hd/candidates_budget are sweep dimensions since v3 (ticket 19). A "trial" is one
seed's full T-target pool. Pooling across seeds = sum counts, then divide (never
average per-seed rates when T could differ).
  schema_version     int   = CSV_SCHEMA_VERSION
  config             str   coefficient_first | arc_only_a | arc_only_b
                           | coefficient_first_info | arc_only_b_info (payload-only variants, added
                           2026-09-23; value extension only, columns unchanged -> still v1)
                           | acr_only_data_tags (2026-09-29: ACR-only with data payload + data
                           salt/tag flips; value extension only)
  error_model        str   whole_packet | data_only | info_only | data_segment (fixed by config)
  arm                str   keyless | keyed | crc_acr | crc_blind (v5, ADR-0014: CRC-32 per segment,
                           ACR-localized or blind columns; ARC-only configs only)
  repair_span        str   payload | segment (ticket 16, matched across arms)
  W                  int   recovery-acceptance width (-1 for CRC arms: fixed oracle, run once per cell)
  bit_error_rate     float
  seed               int   pool + injection seed; injection is independent of W and
                           repair_span, so rows differing only in those are paired too
  gen_size           int   = G (helpers)
  T                  int   targets scored (= n_targets)
  data_fields        int
  num_data_segments  int
  field_bits         int   GF(2^m)
  max_combined_hd    int
  candidates_budget  int   (-1 = unlimited)
  keyed_early_exit   int   (v3) 1 = keyed verify stops at first bad tag (ticket 18, fair ops); 0 = old
  n_info_corrupted   int   targets with >=1 [coeff|payload] flip (paired, same both arms)
  n_coeff_corrupted  int   targets with a corrupted coeff payload (= ARC-only drop set)
  n_arm_corrupted    int   targets with ANY byte changed in this arm (incl. tag/salt)
  recovered          int   accepted at W AND info columns == ground truth
  silent             int   accepted at W AND info columns != ground truth (wrong-accept)
  failed             int   not accepted at W (honest fail)
  recovery_rate      float recovered / T
  silent_decode_rate float silent / T
  failed_rate        float failed / T
  recovery_ops       int   total GF ops (mul+add) of this arm's recovery call -- since v4 REPAIR ONLY:
                           the entry's post-repair whole-pool check (report.ok) is excluded (ticket 20)
  recovery_mul       int   (v2) GF multiplications of the recovery call
  recovery_add       int   (v2) GF additions of the recovery call
  recovery_time_s    float (v2) wall-clock seconds of the recovery call (perf_counter, scoring
                           excluded). Machine- and load-dependent (parallel workers share the CPU):
                           compare arms WITHIN a run, prefer ops as the deterministic cost metric.
  final_check_ops    int   (v4) ops of the post-repair whole-pool check, costed separately: keyless
                           check_orth_segmented (all packet pairs, O(M^2)), keyed check_mac_segmented (O(M))
  final_check_time_s float (v4) wall-clock of that check
  h2h_keyless_only   int   per-target head-to-head on 'recovered', keyless vs keyed (same on both arm
  h2h_keyed_only     int   rows); -1 when the two did not run together (e.g. CRC rows)
  h2h_both           int
  h2h_neither        int
  target_outcomes    str   (v5) per-target outcome letters in target order, R/S/F = recovered/silent/
                           failed -- pair any two arms offline on the same seed/cell
  recovery_crc_bytes int   (v5) CRC arms: bytes fed through CRC-32 by the recovery call (0 otherwise);
                           recovery_ops of a CRC arm = field ops of ACR localization only
  final_check_crc_bytes int (v5) CRC arms: bytes of the post-repair whole-pool CRC check
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field as dc_field

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import (
    generate_identity_coefficients,
    recode_rlnc_without_coeffs,
)
from binary_ext_fields.segmented_tagging import tag_generation_segmented, check_orth_segmented
from binary_ext_fields.segmented_recovery import (
    SegmentTrust,
    recover_coefficient_first,
    recover_arc_only,
    segment_slice as kl_slice,
)
from binary_ext_fields.segmented_mac_tagging import (
    layout_mac_segments,
    generate_keyset,
    tag_generation_mac,
    mac_verify_segment,
    check_mac_segmented,
)
from binary_ext_fields.segmented_mac_recovery import (
    recover_coefficient_first_mac,
    recover_arc_only_mac,
    segment_slice as kd_slice,
)
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.generate_symbols import check_orth_packet
from simulation.segmented_crc import (
    Crc32Instrument,
    layout_crc_segments,
    tag_packets_crc,
    crc_verify_segment,
    check_crc_segmented,
    recover_arc_only_crc,
    segment_slice as crc_slice,
)


# ── Pool building: paired, common random numbers ──────────────────────────────

@dataclass
class PairedPools:
    field: CountingField
    gen_size: int
    kl_clean: list[bytearray]        # keyless pool, pre-corruption
    kl_segments: list                # TaggedSegment[]
    kd_clean: list[bytearray]        # keyed pool, pre-corruption
    kd_segments: list                # MacSegment[]
    keyset: list                     # keyed keyset (per segment)
    helper_idx: list[int]
    target_idx: list[int]
    crc_clean: list[bytearray] = dc_field(default_factory=list)   # CRC-32 pool (ADR-0014), pre-corruption
    crc_segments: list = dc_field(default_factory=list)           # CrcSegment[]


def build_paired_pools(field: CountingField, gen_size: int, data_fields: int,
                       num_data_segments: int, T: int, seed: int) -> PairedPools:
    """G = gen_size clean identity-coeff helpers + T recoded targets, tagged both ways
    from ONE shared logical generation. The recode coefficient matrix is drawn from
    the same global-RNG seed for both arms, so target i carries the same logical
    [coeff | data] in both -- the paired invariant the caller then asserts."""
    rng_data = random.Random(seed)
    data_rows = [bytearray(rng_data.randint(0, field.max_value) for _ in range(data_fields))
                 for _ in range(gen_size)]
    plain = generate_identity_coefficients(field, data_rows)

    # Keyless helpers (salt draws use the global RNG -> seed it for determinism).
    random.seed(seed * 3 + 1)
    kl_res = tag_generation_segmented(field, plain, gen_size, num_data_segments)
    assert kl_res.ok, f"keyless tagging gave up on segment {kl_res.failed_segment!r}"
    random.seed(seed * 3 + 2)
    kl_targets = recode_rlnc_without_coeffs(field, kl_res.packets, gen_size, count=T)

    # Keyed helpers (no salt; keyset from an INDEPENDENT rng so it can't perturb the
    # shared recode stream).
    rng_keys = random.Random(seed * 3 + 3)
    kd_segments = layout_mac_segments(gen_size, data_fields, num_data_segments, num_keys=gen_size)
    keyset = generate_keyset(field, kd_segments, rng_keys)
    kd_helpers = tag_generation_mac(field, plain, gen_size, num_data_segments, keyset, num_keys=gen_size)
    random.seed(seed * 3 + 2)  # SAME seed as the keyless recode -> identical coeff matrix
    kd_targets = recode_rlnc_without_coeffs(field, kd_helpers, gen_size, count=T)

    kl_pool = [bytearray(p) for p in kl_res.packets] + [bytearray(p) for p in kl_targets]
    kd_pool = [bytearray(p) for p in kd_helpers] + [bytearray(p) for p in kd_targets]
    # CRC-32 arm (ADR-0014): the keyless pool's [coeff | data] columns re-framed with one CRC
    # per segment. The source CRCs every coded packet itself (single hop), and no RNG is
    # drawn here, so adding this arm leaves the keyless/keyed pools byte-identical.
    crc_segments = layout_crc_segments(kl_res.segments)
    crc_pool = tag_packets_crc(Crc32Instrument(), kl_pool, kl_res.segments, crc_segments)
    return PairedPools(
        field=field, gen_size=gen_size,
        kl_clean=kl_pool, kl_segments=kl_res.segments,
        kd_clean=kd_pool, kd_segments=kd_segments, keyset=keyset,
        helper_idx=list(range(gen_size)),
        target_idx=list(range(gen_size, gen_size + T)),
        crc_clean=crc_pool, crc_segments=crc_segments,
    )


def info_columns(packet: bytearray, segments) -> bytearray:
    """The [coeff | payload] information bytes of one packet -- every segment's payload,
    tag/salt columns excluded. Logically identical across arms for the same packet."""
    out = bytearray()
    for seg in segments:
        out += packet[seg.start:seg.start + seg.payload_length]
    return out


def assert_paired_info_columns(pools: PairedPools) -> None:
    """The paired invariant: every packet's information columns are byte-identical
    across the two arms (clean, pre-corruption)."""
    for i in range(len(pools.kl_clean)):
        assert info_columns(pools.kl_clean[i], pools.kl_segments) == \
               info_columns(pools.kd_clean[i], pools.kd_segments), \
            f"paired invariant broken: packet {i} info columns differ across arms"
        if pools.crc_clean:
            assert info_columns(pools.kl_clean[i], pools.kl_segments) == \
                   info_columns(pools.crc_clean[i], pools.crc_segments), \
                f"paired invariant broken: packet {i} info columns differ keyless vs CRC"


# ── Paired error injection ────────────────────────────────────────────────────

@dataclass
class InjectedErrors:
    kl: list[bytearray]                 # keyless corrupted pool
    kd: list[bytearray]                 # keyed corrupted pool
    per_target: dict[int, list]         # target -> [(segment_name, col, bit), ...] (info-column flips)
    crc: list[bytearray] | None = None  # CRC-32 corrupted pool (ADR-0014); None = hand-built kl/kd-only injection


def inject_paired(pools: PairedPools, ber: float, model: str, seed: int) -> InjectedErrors:
    """Corrupt ONLY the targets; helpers are never touched.

    model="data_only": flip only DATA-segment payload columns; no coeff payload, no
    tag/salt -> both arms get byte-identical corruption end to end.
    model="whole_packet": flip all payload columns (coeff + data) identically across
    arms, PLUS the tag/salt region per-arm (seed-matched, different layouts).
    model="info_only": the whole_packet info-column flips (same RNG stream -> the SAME
    [coeff|payload] corruption as whole_packet for a given seed) but NO tag/salt flips,
    so both arms face byte-identical corruption end to end.
    model="data_segment" (2026-09-29): data_only's payload flips (same RNG stream -> the
    SAME payload corruption as data_only for a given seed) PLUS the DATA segments' own
    salt/tag region per-arm (seed-matched); the coeff segment is never touched.

    Info-column flips are drawn from one shared RNG and applied to both arms in
    lock-step, so the [coeff|payload] corruption is identical by construction."""
    bits = pools.field.bit_lenght
    kl = [bytearray(p) for p in pools.kl_clean]
    kd = [bytearray(p) for p in pools.kd_clean]
    crc = [bytearray(p) for p in pools.crc_clean]
    crc_segments = pools.crc_segments or [None] * len(pools.kl_segments)
    info_rng = random.Random(seed)
    kl_red_rng = random.Random(seed + 1)
    kd_red_rng = random.Random(seed + 2)
    crc_red_rng = random.Random(seed + 3)
    per_target: dict[int, list] = {}

    for t in pools.target_idx:
        descs = []
        # Information columns -- identical flips in every arm.
        for sl, sd, sc in zip(pools.kl_segments, pools.kd_segments, crc_segments):
            if model in ("data_only", "data_segment") and sl.kind != "data":
                continue
            for col in range(sl.payload_length):
                for bit in range(bits):
                    if info_rng.random() < ber:
                        kl[t][sl.start + col] ^= (1 << bit)
                        kd[t][sd.start + col] ^= (1 << bit)
                        if sc is not None:
                            crc[t][sc.start + col] ^= (1 << bit)
                        descs.append((sl.name, col, bit))
        # Redundancy region -- per-arm, seed-matched (whole-packet: every segment;
        # data_segment: data segments only).
        if model in ("whole_packet", "data_segment"):
            for sl in pools.kl_segments:
                if model == "data_segment" and sl.kind != "data":
                    continue
                for b in range(sl.payload_length, sl.total_length):
                    for bit in range(bits):
                        if kl_red_rng.random() < ber:
                            kl[t][sl.start + b] ^= (1 << bit)
            for sd in pools.kd_segments:
                if model == "data_segment" and sd.kind != "data":
                    continue
                for b in range(sd.payload_length, sd.total_length):
                    for bit in range(bits):
                        if kd_red_rng.random() < ber:
                            kd[t][sd.start + b] ^= (1 << bit)
            for sc in pools.crc_segments:   # CRC bytes: own seed-matched stream (ADR-0014)
                if model == "data_segment" and sc.kind != "data":
                    continue
                for b in range(sc.payload_length, sc.total_length):
                    for bit in range(bits):
                        if crc_red_rng.random() < ber:
                            crc[t][sc.start + b] ^= (1 << bit)
        per_target[t] = descs
    return InjectedErrors(kl=kl, kd=kd, per_target=per_target, crc=crc if pools.crc_clean else None)


def assert_identical_info_corruption(pools: PairedPools, inj: InjectedErrors) -> None:
    """Guard: the corrupted information columns are byte-identical across arms (this is
    the corruption recovery actually fixes, so the head-to-head is exact and paired)."""
    for i in range(len(inj.kl)):
        assert info_columns(inj.kl[i], pools.kl_segments) == info_columns(inj.kd[i], pools.kd_segments), \
            f"info-column corruption differs across arms at packet {i}"
        if inj.crc is not None:
            assert info_columns(inj.kl[i], pools.kl_segments) == info_columns(inj.crc[i], pools.crc_segments), \
                f"info-column corruption differs keyless vs CRC at packet {i}"


# ── Injected trust (ground truth, no sniffing) ────────────────────────────────

def injected_trust_map(clean_pool, corrupt_pool, segments, helper_idx, target_idx):
    """Per-segment SegmentTrust from ground truth: broken = targets whose segment slice
    changed; trusted = everyone else (helpers + clean targets). Helpers occupy the
    lowest indices and are never broken, so a sorted trusted list puts them first --
    the keyless acceptance oracle's first-W witnesses are therefore the W helpers."""
    m = {}
    for seg in segments:
        broken = [t for t in target_idx
                  if corrupt_pool[t][seg.start:seg.start + seg.total_length]
                  != clean_pool[t][seg.start:seg.start + seg.total_length]]
        broken_set = set(broken)
        trusted = [i for i in range(len(clean_pool)) if i not in broken_set]
        m[seg.name] = SegmentTrust(seg.name, broken=sorted(broken), trusted=sorted(trusted))
    return m


def coeff_clean_targets(clean_pool, corrupt_pool, segments, target_idx) -> list[int]:
    """Targets whose coefficient PAYLOAD (the coefficients themselves) is byte-clean --
    i.e. ARC can still use them, so they are localizable and NOT dropped.

    Only the payload columns are compared, never the coeff segment's tag/salt region:
    ARC re-derives expected data from the coefficients, so a corrupted coeff *tag*
    (which differs per-arm under whole-packet BER) does not make the coefficients
    unusable. Comparing only the payload keeps this set paired-identical across the two
    arms (the coeff payload is part of the identical [coeff|payload] corruption), which
    is what makes the ARC-only drop symmetric."""
    coeff = next(s for s in segments if s.kind == "coeff")
    return [t for t in target_idx
            if corrupt_pool[t][coeff.start:coeff.start + coeff.payload_length]
            == clean_pool[t][coeff.start:coeff.start + coeff.payload_length]]


# ── Per-target scoring ────────────────────────────────────────────────────────

RECOVERED, SILENT, FAILED = "recovered", "silent", "failed"


def _accepted_keyless(field, packet, segments, helper_slices_by_seg, W) -> bool:
    for seg in segments:
        sl = kl_slice(packet, seg)
        if not check_orth_packet(field, sl):
            return False
        for w in helper_slices_by_seg[seg.name][:W]:
            if inner_product_bytes(field, sl, w) != 0:
                return False
    return True


def _accepted_keyed(field, packet, segments, keyset, seg_index, W) -> bool:
    for seg in segments:
        if not mac_verify_segment(field, keyset[seg_index[seg.name]], kd_slice(packet, seg), seg, W=W):
            return False
    return True


def _score_target(correct: bool, accepted: bool) -> str:
    if accepted and correct:
        return RECOVERED
    if accepted and not correct:
        return SILENT
    return FAILED


def score_keyless(pools, recovered_pool, W):
    helper_slices_by_seg = {seg.name: [kl_slice(recovered_pool[h], seg) for h in pools.helper_idx]
                            for seg in pools.kl_segments}
    outcomes = {}
    for t in pools.target_idx:
        correct = info_columns(recovered_pool[t], pools.kl_segments) == info_columns(pools.kl_clean[t], pools.kl_segments)
        accepted = _accepted_keyless(pools.field, recovered_pool[t], pools.kl_segments, helper_slices_by_seg, W)
        outcomes[t] = _score_target(correct, accepted)
    return outcomes


def score_keyed(pools, recovered_pool, W):
    seg_index = {seg.name: s for s, seg in enumerate(pools.kd_segments)}
    outcomes = {}
    for t in pools.target_idx:
        correct = info_columns(recovered_pool[t], pools.kd_segments) == info_columns(pools.kd_clean[t], pools.kd_segments)
        accepted = _accepted_keyed(pools.field, recovered_pool[t], pools.kd_segments, pools.keyset, seg_index, W)
        outcomes[t] = _score_target(correct, accepted)
    return outcomes


def score_crc(pools, recovered_pool):
    """CRC arms (ADR-0014): accepted iff every segment passes its CRC-32. No W (fixed oracle)."""
    instrument = Crc32Instrument()  # scoring is not part of the arm's measured cost
    outcomes = {}
    for t in pools.target_idx:
        correct = info_columns(recovered_pool[t], pools.crc_segments) == info_columns(pools.crc_clean[t], pools.crc_segments)
        accepted = all(crc_verify_segment(instrument, crc_slice(recovered_pool[t], seg), seg)
                       for seg in pools.crc_segments)
        outcomes[t] = _score_target(correct, accepted)
    return outcomes


# ── Running one (config x arm) ────────────────────────────────────────────────

@dataclass
class ArmResult:
    outcomes: dict[int, str]
    ops: int
    recovered: int
    silent: int
    failed: int
    mul: int = 0          # GF multiplications of the recovery call (ops = mul + add)
    add: int = 0          # GF additions
    time_s: float = 0.0   # wall-clock of the recovery call (perf_counter); scoring excluded
    final_check_ops: int = 0        # ticket 20: the post-repair whole-pool check, costed separately
    final_check_time_s: float = 0.0  # (keyless all-pairs orthogonality, keyed per-packet MAC)
    crc_bytes: int = 0               # ADR-0014 CRC arms: bytes fed through CRC-32 by the recovery call
    final_check_crc_bytes: int = 0   # ... and by the post-repair whole-pool CRC check


def _tally(outcomes) -> tuple[int, int, int]:
    rec = sum(1 for v in outcomes.values() if v == RECOVERED)
    sil = sum(1 for v in outcomes.values() if v == SILENT)
    fail = sum(1 for v in outcomes.values() if v == FAILED)
    return rec, sil, fail


CONFIGS = ("coefficient_first", "arc_only_a", "arc_only_b")
# Payload-only variants of the two whole-packet configs: identical [coeff|payload] flips,
# no salt/tag corruption -> the only cross-arm difference left is the oracle.
INFO_CONFIGS = ("coefficient_first_info", "arc_only_b_info")
# ACR-only configs for the 2026-09-29 scaling study (no coeff repair, coeffs never hit):
# payload-only data errors (arc_only_a) vs data payload + data salt/tag errors.
ACR_CONFIGS = ("arc_only_a", "acr_only_data_tags")
_CONFIG_MODEL = {"coefficient_first": "whole_packet", "arc_only_a": "data_only", "arc_only_b": "whole_packet",
                 "coefficient_first_info": "info_only", "arc_only_b_info": "info_only",
                 "acr_only_data_tags": "data_segment"}
_CONFIG_METHOD = {"coefficient_first": "coefficient_first", "arc_only_a": "arc_only", "arc_only_b": "arc_only",
                  "coefficient_first_info": "coefficient_first", "arc_only_b_info": "arc_only",
                  "acr_only_data_tags": "arc_only"}
_CONFIG_LABEL = {
    "coefficient_first": "coefficient_first (whole-packet BER)",
    "arc_only_a": "ARC-only (data-only BER)",
    "arc_only_b": "ARC-only (whole-packet BER, symmetric drop)",
    "coefficient_first_info": "coefficient_first (payload-only BER, no salt/tag hits)",
    "arc_only_b_info": "ARC-only (payload-only BER, symmetric drop)",
    "acr_only_data_tags": "ACR-only (data payload + data salt/tag BER)",
}


W_ARMS = ("keyless", "keyed")         # recovery-acceptance width W applies
CRC_ARMS = ("crc_acr", "crc_blind")   # ADR-0014: fixed CRC-32 oracle, no W
ARMS = W_ARMS + CRC_ARMS
_CRC_LOCALIZATION = {"crc_acr": "acr", "crc_blind": "blind"}


@dataclass
class ConfigResult:
    config: str
    inj: InjectedErrors
    keyless: ArmResult | None   # None = arm not run (see run_config `arms`)
    keyed: ArmResult | None
    kl_packets: list[bytearray] = dc_field(default_factory=list)   # keyless pool after recovery
    kd_packets: list[bytearray] = dc_field(default_factory=list)   # keyed pool after recovery
    kl_report: object = None   # SegmentedRecoveryReport (per-segment pairs/unpaired/dropped counts)
    kd_report: object = None
    crc: dict = dc_field(default_factory=dict)           # CRC arm name -> ArmResult (ADR-0014)
    crc_packets: dict = dc_field(default_factory=dict)   # CRC arm name -> pool after recovery

    def arm_results(self) -> dict:
        """Every arm that ran, name -> ArmResult, in ARMS order."""
        every = {"keyless": self.keyless, "keyed": self.keyed, **self.crc}
        return {a: every[a] for a in ARMS if every.get(a) is not None}


def _final_check_cost(field, check) -> tuple[int, float]:
    """Ops/time of the post-repair whole-pool check, in its own window (ticket 20). It is
    not part of repair and the harness scoring never uses it, so it is reported beside,
    not inside, recovery_ops/recovery_time_s."""
    field.reset()
    t0 = time.perf_counter()
    check()
    return field.mul_count + field.add_count, time.perf_counter() - t0


def run_config(pools: PairedPools, config: str, ber: float, W: int | None, seed: int,
               max_combined_hd: int = 2, candidates_budget: int | None = 20000,
               repair_span: str = "payload", inj: InjectedErrors | None = None,
               keyed_early_exit: bool = True, arms=W_ARMS) -> ConfigResult:
    """Inject the config's error model (paired), then run the chosen arms with injected
    trust and score the T targets. All arms see identical [coeff|payload] corruption.

    repair_span (ADR-0013 ticket 16, matched across arms): "payload" = repair the
    ARC-narrowed data columns only (default); "segment" = also search the salt/tag
    redundancy columns, so a corrupted salt/tag byte is repairable at a measured
    silent-decode cost.

    inj: a hand-built injection (tests / edge cases) instead of drawing one at `ber`;
    the paired-info-column guard is still enforced on it.

    keyed_early_exit (ticket 18): keyed MAC verification stops at the first mismatching
    tag, matching the keyless oracle's self-check short-circuit, so ops/time are compared
    fairly. Outcomes are identical either way; False reproduces the pre-ticket-18 ops.

    arms (ADR-0014): subset of ARMS; default = keyless + keyed (unchanged behaviour). The
    CRC arms ignore W (pass W=None when only CRC arms run) and support the ARC-only
    configs only (no coefficient repair)."""
    unknown = set(arms) - set(ARMS)
    assert not unknown, f"unknown arms {sorted(unknown)}; choose from {ARMS}"
    assert W is not None or not set(arms) & set(W_ARMS), "keyless/keyed arms need an int W"
    model = _CONFIG_MODEL[config]
    if inj is None:
        inj = inject_paired(pools, ber, model, seed=seed * 131 + 7)
    assert_identical_info_corruption(pools, inj)
    res = ConfigResult(config=config, inj=inj, keyless=None, keyed=None)

    # ---- keyless (bit-flip only: the ADR-0002 exact solve is bypassed so both arms
    #      run the identical search and the only surviving difference is the oracle) ----
    if "keyless" in arms:
        kl_trust = injected_trust_map(pools.kl_clean, inj.kl, pools.kl_segments, pools.helper_idx, pools.target_idx)
        pools.field.reset()
        t0 = time.perf_counter()
        if _CONFIG_METHOD[config] == "coefficient_first":
            rep_kl = recover_coefficient_first(pools.field, inj.kl, pools.kl_segments, pools.gen_size,
                                               max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                                               W=W, injected_trust_by_segment=kl_trust, bitflip_only=True,
                                               repair_span=repair_span, final_check=False)
        else:
            ccl = coeff_clean_targets(pools.kl_clean, inj.kl, pools.kl_segments, pools.target_idx)
            rep_kl = recover_arc_only(pools.field, inj.kl, pools.kl_segments, pools.gen_size,
                                      basis_idx=pools.helper_idx, coeff_clean_target_idx=ccl,
                                      max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                                      W=W, injected_trust_by_segment=kl_trust, bitflip_only=True,
                                      repair_span=repair_span, final_check=False)
        kl_time = time.perf_counter() - t0
        kl_mul, kl_add = pools.field.mul_count, pools.field.add_count
        kl_fc_ops, kl_fc_time = _final_check_cost(pools.field, lambda: check_orth_segmented(
            pools.field, rep_kl.packets, pools.kl_segments))
        kl_out = score_keyless(pools, rep_kl.packets, W)
        res.keyless = ArmResult(kl_out, kl_mul + kl_add, *_tally(kl_out), mul=kl_mul, add=kl_add, time_s=kl_time,
                                final_check_ops=kl_fc_ops, final_check_time_s=kl_fc_time)
        res.kl_packets, res.kl_report = rep_kl.packets, rep_kl

    # ---- keyed ----
    if "keyed" in arms:
        kd_trust = injected_trust_map(pools.kd_clean, inj.kd, pools.kd_segments, pools.helper_idx, pools.target_idx)
        pools.field.reset()
        t0 = time.perf_counter()
        if _CONFIG_METHOD[config] == "coefficient_first":
            rep_kd = recover_coefficient_first_mac(pools.field, pools.keyset, inj.kd, pools.kd_segments, pools.gen_size,
                                                   max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                                                   W=W, injected_trust_by_segment=kd_trust, repair_span=repair_span,
                                                   early_exit=keyed_early_exit, final_check=False)
        else:
            ccl = coeff_clean_targets(pools.kd_clean, inj.kd, pools.kd_segments, pools.target_idx)
            rep_kd = recover_arc_only_mac(pools.field, pools.keyset, inj.kd, pools.kd_segments, pools.gen_size,
                                          basis_idx=pools.helper_idx, coeff_clean_target_idx=ccl,
                                          max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                                          W=W, injected_trust_by_segment=kd_trust, repair_span=repair_span,
                                          early_exit=keyed_early_exit, final_check=False)
        kd_time = time.perf_counter() - t0
        kd_mul, kd_add = pools.field.mul_count, pools.field.add_count
        kd_fc_ops, kd_fc_time = _final_check_cost(pools.field, lambda: check_mac_segmented(
            pools.field, pools.keyset, rep_kd.packets, pools.kd_segments))
        kd_out = score_keyed(pools, rep_kd.packets, W)
        res.keyed = ArmResult(kd_out, kd_mul + kd_add, *_tally(kd_out), mul=kd_mul, add=kd_add, time_s=kd_time,
                              final_check_ops=kd_fc_ops, final_check_time_s=kd_fc_time)
        res.kd_packets, res.kd_report = rep_kd.packets, rep_kd

    # ---- CRC-32 (ADR-0014): same ARC-only pipeline, oracle = per-segment CRC ----
    crc_arms = [a for a in CRC_ARMS if a in arms]
    if crc_arms:
        assert _CONFIG_METHOD[config] == "arc_only", f"CRC arms support ARC-only configs only, not {config!r}"
        assert inj.crc is not None, "CRC arms need an injection that includes the CRC pool"
        assert pools.field.bit_lenght == 8, "CRC arms assume byte symbols (GF(2^8))"
        crc_trust = injected_trust_map(pools.crc_clean, inj.crc, pools.crc_segments, pools.helper_idx, pools.target_idx)
        ccl = coeff_clean_targets(pools.crc_clean, inj.crc, pools.crc_segments, pools.target_idx)
    for arm in crc_arms:
        instrument = Crc32Instrument()
        pools.field.reset()  # crc_acr: localize_errors' field ops land here
        t0 = time.perf_counter()
        rep = recover_arc_only_crc(pools.field, instrument, inj.crc, pools.crc_segments, pools.gen_size,
                                   basis_idx=pools.helper_idx, coeff_clean_target_idx=ccl,
                                   localization=_CRC_LOCALIZATION[arm], max_combined_hd=max_combined_hd,
                                   candidates_budget=candidates_budget, injected_trust_by_segment=crc_trust,
                                   repair_span=repair_span, final_check=False)
        elapsed = time.perf_counter() - t0
        mul, add = pools.field.mul_count, pools.field.add_count
        fc_instrument = Crc32Instrument()
        t0 = time.perf_counter()
        check_crc_segmented(fc_instrument, rep.packets, pools.crc_segments)
        fc_time = time.perf_counter() - t0
        out = score_crc(pools, rep.packets)
        res.crc[arm] = ArmResult(out, mul + add, *_tally(out), mul=mul, add=add, time_s=elapsed,
                                 final_check_time_s=fc_time, crc_bytes=instrument.crc_ops,
                                 final_check_crc_bytes=fc_instrument.crc_ops)
        res.crc_packets[arm] = rep.packets
    return res


def head_to_head(kl_out, kd_out) -> dict[str, int]:
    """Per-target win/loss/tie on 'recovered'."""
    tally = {"keyless_only": 0, "keyed_only": 0, "both": 0, "neither": 0}
    for t in kl_out:
        k = kl_out[t] == RECOVERED
        d = kd_out[t] == RECOVERED
        if k and d:
            tally["both"] += 1
        elif k and not d:
            tally["keyless_only"] += 1
        elif d and not k:
            tally["keyed_only"] += 1
        else:
            tally["neither"] += 1
    return tally


# ── Readable smoke (ticket 15 format) ─────────────────────────────────────────

def _fmt_errs(descs) -> str:
    if not descs:
        return "info: none"
    by_seg = {}
    for name, col, _bit in descs:
        by_seg.setdefault(name, set()).add(col)
    parts = [f"{name}[{','.join(str(c) for c in sorted(cols))}]" for name, cols in by_seg.items()]
    return f"{'; '.join(parts)}  {len(descs)}b"


# ASCII marks -- the Windows console (cp1252) can't encode check/cross glyphs, and
# ADR-0013 wants the smoke output to be diff-able across re-runs.
_MARK = {RECOVERED: "recovered [OK]", SILENT: "SILENT [x] wrong-accept", FAILED: "failed  [-]"}


def print_smoke(pools: PairedPools, results: list[ConfigResult], W: int, seed: int, ber: float,
                repair_span: str = "payload") -> None:
    G, T = len(pools.helper_idx), len(pools.target_idx)
    print("\nLegend:  [OK] recovered   [x] SILENT (wrong-accept, oracle passed but bytes wrong)   [-] honest fail")
    print(f"Fixed:   seed={seed}  W={W}  G={G}  T={T}  BER={ber}  repair_span={repair_span}"
          f"  (helpers 0..{G-1} clean, never scored{'; CRC arms have no W' if any(r.crc for r in results) else ''})")

    overall = {"keyless_only": 0, "keyed_only": 0, "both": 0, "neither": 0}
    for res in results:
        arms = res.arm_results()
        width = max(7, *(len(a) for a in arms))
        label = "arm pair" if tuple(arms) == W_ARMS else f"arms {', '.join(arms)}"
        print(f"\n=== config: {_CONFIG_LABEL[res.config]}  |  {label}, W={W}, seed={seed}, G={G}, T={T} ===")
        if _CONFIG_MODEL[res.config] == "whole_packet":
            print("  (whole-packet BER: 'injected errs' lists the paired [coeff|payload] flips only;"
                  " tag/salt bytes are also corrupted per-arm, seed-matched)")
        print(f" {'t#':>3} | {'injected errs':<26} | " + " | ".join(f"{a.upper():<26}" for a in arms))
        for t in pools.target_idx:
            print(f" {t:>3} | {_fmt_errs(res.inj.per_target[t]):<26} | "
                  + " | ".join(f"{_MARK[ar.outcomes[t]]:<26}" for ar in arms.values()))
        for i, (arm, ar) in enumerate(arms.items()):
            lead = " summary  " if i == 0 else "          "
            extra = f"  crc_bytes {ar.crc_bytes:.3g}" if arm in CRC_ARMS else ""
            # no wall-clock here: the smoke must stay byte-identical across re-runs (ADR-0013)
            print(f"{lead}{arm:<{width}}: rec {ar.recovered}/{T}  silent {ar.silent}  fail {ar.failed}  "
                  f"ops {ar.ops:.3g}{extra}")
        if res.keyless is not None and res.keyed is not None:
            h2h = head_to_head(res.keyless.outcomes, res.keyed.outcomes)
            print(f" head-to-head    keyless-only-win {h2h['keyless_only']}  keyed-only-win {h2h['keyed_only']}  "
                  f"both {h2h['both']}  neither {h2h['neither']}")
            for k in overall:
                overall[k] += h2h[k]
        if res.keyless is not None:
            for arm, ar in res.crc.items():
                h2h = head_to_head(res.keyless.outcomes, ar.outcomes)
                print(f" head-to-head    keyless-only-win {h2h['keyless_only']}  {arm}-only-win {h2h['keyed_only']}  "
                      f"both {h2h['both']}  neither {h2h['neither']}")

    if any(r.keyless is not None and r.keyed is not None for r in results):
        print(f"\n overall head-to-head  keyless-only-win {overall['keyless_only']}  keyed-only-win {overall['keyed_only']}  "
              f"both {overall['both']}  neither {overall['neither']}")


def run_smoke(seed: int = 7, gen_size: int = 6, T: int = 8, W: int = 2, ber: float = 0.006,
              data_fields: int = 18, num_data_segments: int = 3,
              repair_span: str = "payload", arms=W_ARMS) -> list[ConfigResult]:
    field = CountingField(create_field(8))
    pools = build_paired_pools(field, gen_size, data_fields, num_data_segments, T, seed)
    assert_paired_info_columns(pools)
    # CRC arms run the ARC-only configs only (ADR-0014)
    configs = CONFIGS if not set(arms) & set(CRC_ARMS) else tuple(c for c in CONFIGS if _CONFIG_METHOD[c] == "arc_only")
    results = [run_config(pools, cfg, ber, W, seed, repair_span=repair_span, arms=arms) for cfg in configs]
    print_smoke(pools, results, W, seed, ber, repair_span)
    return results


# ── W sweep (ticket 14) ───────────────────────────────────────────────────────

CSV_SCHEMA_VERSION = 5  # v2: + recovery_mul/add/time_s; v3: + keyed_early_exit; v4 (2026-09-25): repair-only
#                        recovery_* (final pool check excluded) + final_check_ops/_time_s; v5 (2026-10-13,
#                        ADR-0014): CRC arms + target_outcomes + recovery_crc_bytes/final_check_crc_bytes
CSV_COLUMNS = (
    "schema_version", "config", "error_model", "arm", "repair_span", "W", "bit_error_rate", "seed",
    "gen_size", "T", "data_fields", "num_data_segments", "field_bits", "max_combined_hd",
    "candidates_budget", "keyed_early_exit", "n_info_corrupted", "n_coeff_corrupted", "n_arm_corrupted",
    "recovered", "silent", "failed", "recovery_rate", "silent_decode_rate", "failed_rate",
    "recovery_ops", "recovery_mul", "recovery_add", "recovery_time_s",
    "final_check_ops", "final_check_time_s",
    "h2h_keyless_only", "h2h_keyed_only", "h2h_both", "h2h_neither",
    "target_outcomes", "recovery_crc_bytes", "final_check_crc_bytes",
)

SWEEP_W = (1, 2, 3)
SWEEP_BERS = (1e-3, 2e-3, 4e-3, 6e-3, 1e-2)
SWEEP_SPANS = ("payload", "segment")
SWEEP_SEEDS = 30
_OUTCOME_LETTER = {RECOVERED: "R", SILENT: "S", FAILED: "F"}


def _n_changed(clean_pool, corrupt_pool, idx) -> int:
    return sum(1 for t in idx if corrupt_pool[t] != clean_pool[t])


def result_rows(pools: PairedPools, res: ConfigResult, *, W: int | None, ber: float, seed: int, repair_span: str,
                data_fields: int, num_data_segments: int, max_combined_hd: int,
                candidates_budget: int | None, keyed_early_exit: bool = True) -> list[dict]:
    """One frozen-schema row per arm that ran in this run_config result. CRC rows carry
    W = -1 (no acceptance width). h2h_* = keyless vs keyed when both ran, else -1; the
    per-target `target_outcomes` string (R/S/F in target order) allows any paired
    comparison offline."""
    T = len(pools.target_idx)
    both = res.keyless is not None and res.keyed is not None
    h2h = head_to_head(res.keyless.outcomes, res.keyed.outcomes) if both else \
        {"keyless_only": -1, "keyed_only": -1, "both": -1, "neither": -1}
    n_info = sum(1 for t in pools.target_idx if res.inj.per_target[t])
    n_coeff = T - len(coeff_clean_targets(pools.kl_clean, res.inj.kl, pools.kl_segments, pools.target_idx))
    common = {
        "schema_version": CSV_SCHEMA_VERSION, "config": res.config, "error_model": _CONFIG_MODEL[res.config],
        "repair_span": repair_span, "bit_error_rate": ber, "seed": seed,
        "gen_size": pools.gen_size, "T": T, "data_fields": data_fields,
        "num_data_segments": num_data_segments, "field_bits": pools.field.bit_lenght,
        "max_combined_hd": max_combined_hd,
        "candidates_budget": -1 if candidates_budget is None else candidates_budget,
        "keyed_early_exit": int(keyed_early_exit),
        "n_info_corrupted": n_info, "n_coeff_corrupted": n_coeff,
        "h2h_keyless_only": h2h["keyless_only"], "h2h_keyed_only": h2h["keyed_only"],
        "h2h_both": h2h["both"], "h2h_neither": h2h["neither"],
    }
    pools_by_arm = {"keyless": (pools.kl_clean, res.inj.kl), "keyed": (pools.kd_clean, res.inj.kd),
                    **{a: (pools.crc_clean, res.inj.crc) for a in CRC_ARMS}}
    rows = []
    for arm, ar in res.arm_results().items():
        clean, corrupt = pools_by_arm[arm]
        row = dict(common, arm=arm, W=-1 if arm in CRC_ARMS else W,
                   n_arm_corrupted=_n_changed(clean, corrupt, pools.target_idx),
                   recovered=ar.recovered, silent=ar.silent, failed=ar.failed,
                   recovery_rate=ar.recovered / T, silent_decode_rate=ar.silent / T,
                   failed_rate=ar.failed / T, recovery_ops=ar.ops,
                   recovery_mul=ar.mul, recovery_add=ar.add, recovery_time_s=ar.time_s,
                   final_check_ops=ar.final_check_ops, final_check_time_s=ar.final_check_time_s,
                   target_outcomes="".join(_OUTCOME_LETTER[ar.outcomes[t]] for t in pools.target_idx),
                   recovery_crc_bytes=ar.crc_bytes, final_check_crc_bytes=ar.final_check_crc_bytes)
        assert set(row) == set(CSV_COLUMNS), f"row drifted from frozen schema: {set(row) ^ set(CSV_COLUMNS)}"
        rows.append(row)
    return rows


def sweep_seed(seed: int, *, gen_size: int, T: int, data_fields: int, num_data_segments: int,
               field_bits: int, Ws, bers, spans, configs, hds, budgets,
               keyed_early_exit: bool = True, arms=W_ARMS) -> list[dict]:
    """Every (BER, config, span, HD, budget, W) cell for ONE seed -- the unit of parallel
    work. One pool per seed; the injection is drawn from (seed, BER) only, so all
    W/span/HD/budget variants of a cell -- and every arm -- see the same corruption (paired).
    CRC arms (ADR-0014) have no W: they run once per (BER, config, span, HD, budget) cell."""
    from icecream import ic
    ic.disable()  # playground/arc_pl.py debug prints would flood every worker's stderr
    field = CountingField(create_field(field_bits))
    pools = build_paired_pools(field, gen_size, data_fields, num_data_segments, T, seed)
    assert_paired_info_columns(pools)
    w_arms = tuple(a for a in W_ARMS if a in arms)
    crc_arms = tuple(a for a in CRC_ARMS if a in arms)
    rows = []
    for ber in bers:
        for config in configs:
            for span in spans:
                for hd in hds:
                    for budget in budgets:
                        cell = dict(ber=ber, seed=seed, repair_span=span, data_fields=data_fields,
                                    num_data_segments=num_data_segments, max_combined_hd=hd,
                                    candidates_budget=budget, keyed_early_exit=keyed_early_exit)
                        for W in (Ws if w_arms else ()):
                            res = run_config(pools, config, ber, W, seed, max_combined_hd=hd,
                                             candidates_budget=budget, repair_span=span,
                                             keyed_early_exit=keyed_early_exit, arms=w_arms)
                            rows += result_rows(pools, res, W=W, **cell)
                        if crc_arms:
                            res = run_config(pools, config, ber, None, seed, max_combined_hd=hd,
                                             candidates_budget=budget, repair_span=span, arms=crc_arms)
                            rows += result_rows(pools, res, W=None, **cell)
    return rows


def write_rows(path, rows: list[dict], append: bool = False) -> None:
    """Write (or append, without header) frozen-schema rows."""
    import csv
    with open(path, "a" if append else "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="raise")
        if not append:
            w.writeheader()
        w.writerows(rows)


def run_sweep(seeds=range(SWEEP_SEEDS), gen_size: int = 6, T: int | None = None, data_fields: int = 18,
              num_data_segments: int = 3, field_bits: int = 8, Ws=SWEEP_W, bers=SWEEP_BERS,
              spans=SWEEP_SPANS, configs=CONFIGS, max_combined_hd: int = 2,
              candidates_budget: int | None = 20000, workers: int = 1, out_dir=None,
              hds=None, budgets=None, keyed_early_exit: bool = True, arms=W_ARMS):
    """W x BER x config x arm x repair_span (x HD x budget) sweep -> raw_trials.csv.
    arms (ADR-0014): subset of ARMS, default keyless + keyed; CRC arms need ARC-only configs.
    hds/budgets (ticket 19) default to the single (max_combined_hd, candidates_budget);
    a budget of None = unlimited. Seeds run in parallel (`workers` processes); rows are
    appended as each seed lands, then rewritten seed-sorted at the end. Returns run dir."""
    from functools import partial
    from pathlib import Path
    T = gen_size if T is None else T  # ADR-0013 default T = gen_size
    assert all(0 <= w <= gen_size for w in Ws), f"W must be in 0..gen_size={gen_size}, got {tuple(Ws)}"
    if out_dir is None:
        from utils.log_helpers import get_run_log_dir
        out_dir = get_run_log_dir("isolated_recovery", gen=gen_size, T=T, seeds=len(list(seeds)))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "raw_trials.csv"
    job = partial(sweep_seed, gen_size=gen_size, T=T, data_fields=data_fields,
                  num_data_segments=num_data_segments, field_bits=field_bits, Ws=tuple(Ws),
                  bers=tuple(bers), spans=tuple(spans), configs=tuple(configs),
                  hds=tuple(hds or (max_combined_hd,)),
                  budgets=tuple(budgets or (candidates_budget,)), keyed_early_exit=keyed_early_exit,
                  arms=tuple(arms))
    seeds = list(seeds)
    by_seed: dict[int, list[dict]] = {}

    # Append each seed as it lands (linear cost; the file is replot-able part-way, rows in
    # completion order), then one final seed-sorted rewrite -> deterministic file.
    write_rows(csv_path, [])

    def _land(seed, rows):
        by_seed[seed] = rows
        write_rows(csv_path, rows, append=True)
        print(f"  seed {seed} done ({len(by_seed)}/{len(seeds)}) -> {csv_path}", flush=True)

    if workers <= 1:
        for s in seeds:
            _land(s, job(s))
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(job, s): s for s in seeds}
            for f in as_completed(futs):
                _land(futs[f], f.result())
    write_rows(csv_path, [r for s in sorted(by_seed) for r in by_seed[s]])
    return out_dir


def main(argv=None) -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Isolated recovery comparison (ADR-0013).")
    parser.add_argument("--smoke", action="store_true", help="run the readable per-target smoke report")
    parser.add_argument("--sweep", action="store_true", help="W x BER x config x arm x span sweep -> raw_trials.csv")
    parser.add_argument("--seeds", type=int, default=SWEEP_SEEDS, help="sweep: N seeds starting at --seed-start")
    parser.add_argument("--seed-start", type=int, default=0,
                        help="sweep: first seed (use a fresh range to extend a pooled run without duplicates)")
    parser.add_argument("--Ws", default=",".join(str(w) for w in SWEEP_W),
                        help="sweep: comma list of W values, e.g. 1,2,3,4,5,6 (W <= gen_size)")
    parser.add_argument("--spans", default=",".join(SWEEP_SPANS), help="sweep: comma list of repair spans (payload,segment)")
    parser.add_argument("--hds", default="2", help="sweep: comma list of max_combined_hd values, e.g. 1,2,3,4,5")
    parser.add_argument("--budgets", default="20000",
                        help="sweep: comma list of candidates_budget values, 'none' = unlimited, e.g. 20000,none")
    parser.add_argument("--no-keyed-early-exit", action="store_true",
                        help="sweep: old keyed verify (all W tags per candidate) -- reproduces pre-ticket-18 ops")
    parser.add_argument("--configs", default=",".join(CONFIGS),
                        help="sweep: comma list of configs, e.g. coefficient_first_info,arc_only_b_info")
    parser.add_argument("--data-fields", type=int, default=18,
                        help="sweep: data bytes (needs >= num_data_segments*(gen_size-1) for keyless tagging)")
    parser.add_argument("--num-data-segments", type=int, default=3,
                        help="sweep: data segments (N_total - 1)")
    parser.add_argument("--bers", default=",".join(repr(b) for b in SWEEP_BERS),
                        help="sweep: comma list of bit error rates")
    parser.add_argument("--workers", type=int, default=1, help="sweep: parallel processes (one seed each)")
    parser.add_argument("--out", default=None, help="sweep: output dir (default logs/isolated_recovery/<run>)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--gen-size", type=int, default=6)
    parser.add_argument("--targets", type=int, default=8, help="T target packets")
    parser.add_argument("-W", type=int, default=2, help="recovery-acceptance width")
    parser.add_argument("--ber", type=float, default=0.006)
    parser.add_argument("--repair-span", choices=("payload", "segment"), default="payload",
                        help="which columns the repair may touch: payload only, or +salt/tag redundancy")
    parser.add_argument("--arms", default=",".join(W_ARMS),
                        help=f"comma list of arms from {','.join(ARMS)} (CRC arms: ADR-0014, ARC-only configs)")
    args = parser.parse_args(argv)
    arms = tuple(a.strip() for a in args.arms.split(","))

    if args.smoke:
        run_smoke(seed=args.seed, gen_size=args.gen_size, T=args.targets, W=args.W, ber=args.ber,
                  data_fields=args.data_fields, num_data_segments=args.num_data_segments,
                  repair_span=args.repair_span, arms=arms)
    elif args.sweep:
        # sweep uses its own frozen grid (SWEEP_*), T = gen_size per ADR-0013
        d = run_sweep(seeds=range(args.seed_start, args.seed_start + args.seeds), gen_size=args.gen_size,
                      data_fields=args.data_fields, workers=args.workers, out_dir=args.out,
                      num_data_segments=args.num_data_segments,
                      bers=tuple(float(b) for b in args.bers.split(",")),
                      configs=tuple(c.strip() for c in args.configs.split(",")),
                      Ws=tuple(int(w) for w in args.Ws.split(",")),
                      hds=tuple(int(h) for h in args.hds.split(",")),
                      budgets=tuple(None if b.strip().lower() == "none" else int(b) for b in args.budgets.split(",")),
                      keyed_early_exit=not args.no_keyed_early_exit,
                      spans=tuple(x.strip() for x in args.spans.split(",")), arms=arms)
        print(f"sweep done -> {d}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
