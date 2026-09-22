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
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field as dc_field

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import (
    generate_identity_coefficients,
    recode_rlnc_without_coeffs,
)
from binary_ext_fields.segmented_tagging import tag_generation_segmented
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
)
from binary_ext_fields.segmented_mac_recovery import (
    recover_coefficient_first_mac,
    recover_arc_only_mac,
    segment_slice as kd_slice,
)
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.generate_symbols import check_orth_packet


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
    return PairedPools(
        field=field, gen_size=gen_size,
        kl_clean=kl_pool, kl_segments=kl_res.segments,
        kd_clean=kd_pool, kd_segments=kd_segments, keyset=keyset,
        helper_idx=list(range(gen_size)),
        target_idx=list(range(gen_size, gen_size + T)),
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


# ── Paired error injection ────────────────────────────────────────────────────

@dataclass
class InjectedErrors:
    kl: list[bytearray]                 # keyless corrupted pool
    kd: list[bytearray]                 # keyed corrupted pool
    per_target: dict[int, list]         # target -> [(segment_name, col, bit), ...] (info-column flips)


def inject_paired(pools: PairedPools, ber: float, model: str, seed: int) -> InjectedErrors:
    """Corrupt ONLY the targets; helpers are never touched.

    model="data_only": flip only DATA-segment payload columns; no coeff payload, no
    tag/salt -> both arms get byte-identical corruption end to end.
    model="whole_packet": flip all payload columns (coeff + data) identically across
    arms, PLUS the tag/salt region per-arm (seed-matched, different layouts).

    Info-column flips are drawn from one shared RNG and applied to both arms in
    lock-step, so the [coeff|payload] corruption is identical by construction."""
    bits = pools.field.bit_lenght
    kl = [bytearray(p) for p in pools.kl_clean]
    kd = [bytearray(p) for p in pools.kd_clean]
    info_rng = random.Random(seed)
    kl_red_rng = random.Random(seed + 1)
    kd_red_rng = random.Random(seed + 2)
    per_target: dict[int, list] = {}

    for t in pools.target_idx:
        descs = []
        # Information columns -- identical flips both arms.
        for sl, sd in zip(pools.kl_segments, pools.kd_segments):
            if model == "data_only" and sl.kind != "data":
                continue
            for col in range(sl.payload_length):
                for bit in range(bits):
                    if info_rng.random() < ber:
                        kl[t][sl.start + col] ^= (1 << bit)
                        kd[t][sd.start + col] ^= (1 << bit)
                        descs.append((sl.name, col, bit))
        # Redundancy region -- per-arm, seed-matched (whole-packet only).
        if model == "whole_packet":
            for sl in pools.kl_segments:
                for b in range(sl.payload_length, sl.total_length):
                    for bit in range(bits):
                        if kl_red_rng.random() < ber:
                            kl[t][sl.start + b] ^= (1 << bit)
            for sd in pools.kd_segments:
                for b in range(sd.payload_length, sd.total_length):
                    for bit in range(bits):
                        if kd_red_rng.random() < ber:
                            kd[t][sd.start + b] ^= (1 << bit)
        per_target[t] = descs
    return InjectedErrors(kl=kl, kd=kd, per_target=per_target)


def assert_identical_info_corruption(pools: PairedPools, inj: InjectedErrors) -> None:
    """Guard: the corrupted information columns are byte-identical across arms (this is
    the corruption recovery actually fixes, so the head-to-head is exact and paired)."""
    for i in range(len(inj.kl)):
        assert info_columns(inj.kl[i], pools.kl_segments) == info_columns(inj.kd[i], pools.kd_segments), \
            f"info-column corruption differs across arms at packet {i}"


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


# ── Running one (config x arm) ────────────────────────────────────────────────

@dataclass
class ArmResult:
    outcomes: dict[int, str]
    ops: int
    recovered: int
    silent: int
    failed: int


def _tally(outcomes) -> tuple[int, int, int]:
    rec = sum(1 for v in outcomes.values() if v == RECOVERED)
    sil = sum(1 for v in outcomes.values() if v == SILENT)
    fail = sum(1 for v in outcomes.values() if v == FAILED)
    return rec, sil, fail


CONFIGS = ("coefficient_first", "arc_only_a", "arc_only_b")
_CONFIG_MODEL = {"coefficient_first": "whole_packet", "arc_only_a": "data_only", "arc_only_b": "whole_packet"}
_CONFIG_LABEL = {
    "coefficient_first": "coefficient_first (whole-packet BER)",
    "arc_only_a": "ARC-only (data-only BER)",
    "arc_only_b": "ARC-only (whole-packet BER, symmetric drop)",
}


@dataclass
class ConfigResult:
    config: str
    inj: InjectedErrors
    keyless: ArmResult
    keyed: ArmResult
    kl_packets: list[bytearray] = dc_field(default_factory=list)   # keyless pool after recovery
    kd_packets: list[bytearray] = dc_field(default_factory=list)   # keyed pool after recovery


def run_config(pools: PairedPools, config: str, ber: float, W: int, seed: int,
               max_combined_hd: int = 2, candidates_budget: int | None = 20000,
               repair_span: str = "payload") -> ConfigResult:
    """Inject the config's error model (paired), then run BOTH arms with injected trust
    and score the T targets. The two arms see identical [coeff|payload] corruption.

    repair_span (ADR-0013 ticket 16, matched across arms): "payload" = repair the
    ARC-narrowed data columns only (default); "segment" = also search the salt/tag
    redundancy columns, so a corrupted salt/tag byte is repairable at a measured
    silent-decode cost."""
    model = _CONFIG_MODEL[config]
    inj = inject_paired(pools, ber, model, seed=seed * 131 + 7)
    assert_identical_info_corruption(pools, inj)

    kl_trust = injected_trust_map(pools.kl_clean, inj.kl, pools.kl_segments, pools.helper_idx, pools.target_idx)
    kd_trust = injected_trust_map(pools.kd_clean, inj.kd, pools.kd_segments, pools.helper_idx, pools.target_idx)

    # ---- keyless (bit-flip only: the ADR-0002 exact solve is bypassed so both arms
    #      run the identical search and the only surviving difference is the oracle) ----
    pools.field.reset()
    if config == "coefficient_first":
        rep_kl = recover_coefficient_first(pools.field, inj.kl, pools.kl_segments, pools.gen_size,
                                           max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                                           W=W, injected_trust_by_segment=kl_trust, bitflip_only=True,
                                           repair_span=repair_span)
    else:
        ccl = coeff_clean_targets(pools.kl_clean, inj.kl, pools.kl_segments, pools.target_idx)
        rep_kl = recover_arc_only(pools.field, inj.kl, pools.kl_segments, pools.gen_size,
                                  basis_idx=pools.helper_idx, coeff_clean_target_idx=ccl,
                                  max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                                  W=W, injected_trust_by_segment=kl_trust, bitflip_only=True,
                                  repair_span=repair_span)
    kl_ops = pools.field.mul_count + pools.field.add_count
    kl_out = score_keyless(pools, rep_kl.packets, W)

    # ---- keyed ----
    pools.field.reset()
    if config == "coefficient_first":
        rep_kd = recover_coefficient_first_mac(pools.field, pools.keyset, inj.kd, pools.kd_segments, pools.gen_size,
                                               max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                                               W=W, injected_trust_by_segment=kd_trust, repair_span=repair_span)
    else:
        ccl = coeff_clean_targets(pools.kd_clean, inj.kd, pools.kd_segments, pools.target_idx)
        rep_kd = recover_arc_only_mac(pools.field, pools.keyset, inj.kd, pools.kd_segments, pools.gen_size,
                                      basis_idx=pools.helper_idx, coeff_clean_target_idx=ccl,
                                      max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                                      W=W, injected_trust_by_segment=kd_trust, repair_span=repair_span)
    kd_ops = pools.field.mul_count + pools.field.add_count
    kd_out = score_keyed(pools, rep_kd.packets, W)

    return ConfigResult(
        config=config, inj=inj,
        keyless=ArmResult(kl_out, kl_ops, *_tally(kl_out)),
        keyed=ArmResult(kd_out, kd_ops, *_tally(kd_out)),
        kl_packets=rep_kl.packets, kd_packets=rep_kd.packets,
    )


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
          f"  (helpers 0..{G-1} clean, never scored)")

    overall = {"keyless_only": 0, "keyed_only": 0, "both": 0, "neither": 0}
    for res in results:
        print(f"\n=== config: {_CONFIG_LABEL[res.config]}  |  arm pair, W={W}, seed={seed}, G={G}, T={T} ===")
        if _CONFIG_MODEL[res.config] == "whole_packet":
            print("  (whole-packet BER: 'injected errs' lists the paired [coeff|payload] flips only;"
                  " tag/salt bytes are also corrupted per-arm, seed-matched)")
        print(f" {'t#':>3} | {'injected errs':<26} | {'KEYLESS':<26} | {'KEYED':<26}")
        for t in pools.target_idx:
            print(f" {t:>3} | {_fmt_errs(res.inj.per_target[t]):<26} | "
                  f"{_MARK[res.keyless.outcomes[t]]:<26} | {_MARK[res.keyed.outcomes[t]]:<26}")
        kl, kd = res.keyless, res.keyed
        print(f" summary  keyless: rec {kl.recovered}/{T}  silent {kl.silent}  fail {kl.failed}  ops {kl.ops:.3g}")
        print(f"          keyed  : rec {kd.recovered}/{T}  silent {kd.silent}  fail {kd.failed}  ops {kd.ops:.3g}")
        h2h = head_to_head(kl.outcomes, kd.outcomes)
        print(f" head-to-head    keyless-only-win {h2h['keyless_only']}  keyed-only-win {h2h['keyed_only']}  "
              f"both {h2h['both']}  neither {h2h['neither']}")
        for k in overall:
            overall[k] += h2h[k]

    print(f"\n overall head-to-head  keyless-only-win {overall['keyless_only']}  keyed-only-win {overall['keyed_only']}  "
          f"both {overall['both']}  neither {overall['neither']}")


def run_smoke(seed: int = 7, gen_size: int = 6, T: int = 8, W: int = 2, ber: float = 0.006,
              data_fields: int = 18, num_data_segments: int = 3,
              repair_span: str = "payload") -> list[ConfigResult]:
    field = CountingField(create_field(8))
    pools = build_paired_pools(field, gen_size, data_fields, num_data_segments, T, seed)
    assert_paired_info_columns(pools)
    results = [run_config(pools, cfg, ber, W, seed, repair_span=repair_span) for cfg in CONFIGS]
    print_smoke(pools, results, W, seed, ber, repair_span)
    return results


def main(argv=None) -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Isolated recovery comparison (ADR-0013).")
    parser.add_argument("--smoke", action="store_true", help="run the readable per-target smoke report")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--gen-size", type=int, default=6)
    parser.add_argument("--targets", type=int, default=8, help="T target packets")
    parser.add_argument("-W", type=int, default=2, help="recovery-acceptance width")
    parser.add_argument("--ber", type=float, default=0.006)
    parser.add_argument("--repair-span", choices=("payload", "segment"), default="payload",
                        help="which columns the repair may touch: payload only, or +salt/tag redundancy")
    args = parser.parse_args(argv)

    if args.smoke:
        run_smoke(seed=args.seed, gen_size=args.gen_size, T=args.targets, W=args.W, ber=args.ber,
                  repair_span=args.repair_span)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
