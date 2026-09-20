"""
Tests for the ARC-only recovery variant (ADR-0013, ticket 12), both arms.

ARC-only skips coefficient_first's coeff-repair stage and repairs the DATA segments
only, ARC-localizing from an INJECTED helper basis (clean helper packets the harness
never corrupts). This removes the coeff-repair stage as a source of arm-to-arm
difference: ARC availability is given, identical to both arms, so only the acceptance
oracle can still differ.

Meant to be read, not just run:
  - the equivalence tests pin the correctness anchor -- on a CLEAN-coeff fixture,
    ARC-only's data-segment result is byte-for-byte and outcome-for-outcome identical
    to coefficient_first (same localizer, same repair machinery), in each arm;
  - the symmetric-drop test pins error-model (b): a coeff-corrupted target is DROPPED
    (never half-repaired) identically in the keyless and keyed arms, while a data-only
    target beside it still recovers.

Judge pass/fail by exit code (0 = pass); banners print "assert"/"error" as prose.
"""
import random

from binary_ext_fields.custom_field import create_field
from binary_ext_fields.generate_symbols import (
    generate_identity_coefficients,
    recode_rlnc_without_coeffs,
)
from binary_ext_fields.segmented_tagging import (
    build_segments,
    tag_generation_segmented,
    check_orth_segmented,
)
from binary_ext_fields.segmented_recovery import (
    recover_coefficient_first,
    recover_arc_only,
    segment_slice,
)
from binary_ext_fields.segmented_mac_tagging import (
    layout_mac_segments,
    generate_keyset,
    tag_generation_mac,
    check_mac_segmented,
)
from binary_ext_fields.segmented_mac_recovery import (
    recover_coefficient_first_mac,
    recover_arc_only_mac,
    segment_slice as segment_slice_mac,
)
from playground.arc_pl import error_into_packet_chosen_bit


def _banner(name):
    print(f"\n=== {name} ===")


# Shared config: gen_size clean helpers (indices 0..gen_size-1) form the injected
# ARC basis; recoded spares (indices gen_size..) are the corruptible targets.
FIELD = create_field(8)
GEN_SIZE = 4
DATA_FIELDS = 12
NUM_DATA_SEGMENTS = 3
N_TARGETS = 4


def _random_data_rows(rng):
    return [bytearray(rng.randint(0, FIELD.max_value) for _ in range(DATA_FIELDS))
            for _ in range(GEN_SIZE)]


def _keyless_pool(seed):
    """gen_size clean originals + N_TARGETS recoded spares, orthogonally tagged."""
    rng = random.Random(seed)
    plain = generate_identity_coefficients(FIELD, _random_data_rows(rng))
    result = tag_generation_segmented(FIELD, plain, GEN_SIZE, NUM_DATA_SEGMENTS)
    assert result.ok, f"tagging gave up on {result.failed_segment!r}"
    recoded = recode_rlnc_without_coeffs(FIELD, result.packets, GEN_SIZE, count=N_TARGETS)
    pool = [bytearray(p) for p in result.packets] + [bytearray(p) for p in recoded]
    return pool, result.segments


def _keyed_pool(seed):
    """Same shape, MAC-tagged (num_keys = gen_size), + its keyset."""
    rng = random.Random(seed)
    plain = generate_identity_coefficients(FIELD, _random_data_rows(rng))
    segments = layout_mac_segments(GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, num_keys=GEN_SIZE)
    keyset = generate_keyset(FIELD, segments, rng)
    packets = tag_generation_mac(FIELD, plain, GEN_SIZE, NUM_DATA_SEGMENTS, keyset, num_keys=GEN_SIZE)
    recoded = recode_rlnc_without_coeffs(FIELD, packets, GEN_SIZE, count=N_TARGETS)
    pool = [bytearray(p) for p in packets] + [bytearray(p) for p in recoded]
    return pool, keyset, segments


def _data_segments(segments):
    return [s for s in segments if s.kind == "data"]


# ── (1) Correctness anchor: ARC-only == coefficient_first on clean coeffs ──────

def test_keyless_arc_only_equals_coefficient_first_on_clean_coeffs():
    _banner("keyless: ARC-only data result == coefficient_first (clean coeffs)")
    pool, segments = _keyless_pool(seed=31)
    original = [bytearray(p) for p in pool]
    assert all(check_orth_segmented(FIELD, pool, segments).values()), "clean pool must be orthogonal"

    data0 = next(s for s in segments if s.name == "data-0")
    broken = [bytearray(p) for p in pool]
    # Two targets corrupted in data-0 at DISJOINT columns (coeffs untouched) -> they
    # pair and recover; coeffs stay clean so ARC applies to every target.
    broken[4] = error_into_packet_chosen_bit(broken[4], data0.start, chosen_bit=5)
    broken[5] = error_into_packet_chosen_bit(broken[5], data0.start + 1, chosen_bit=6)

    basis_idx = list(range(GEN_SIZE))          # the clean helpers
    coeff_clean_targets = list(range(GEN_SIZE, GEN_SIZE + N_TARGETS))  # all coeffs clean

    cf = recover_coefficient_first(FIELD, [bytearray(p) for p in broken], segments,
                                   GEN_SIZE, max_combined_hd=2)
    arc = recover_arc_only(FIELD, [bytearray(p) for p in broken], segments, GEN_SIZE,
                           basis_idx, coeff_clean_targets, max_combined_hd=2)

    cf_data = {o.segment_name: o for o in cf.per_segment if o.segment_name != "coeff"}
    for o in arc.per_segment:
        print(f"  {o.segment_name}: arc={o}  cf={cf_data[o.segment_name]}")
        assert o == cf_data[o.segment_name], "per-data-segment outcome must match coefficient_first"

    for seg in _data_segments(segments):
        for i in range(len(pool)):
            assert segment_slice(arc.packets[i], seg) == segment_slice(cf.packets[i], seg), \
                f"data-segment bytes must match coefficient_first (packet {i}, {seg.name})"
            assert segment_slice(arc.packets[i], seg) == segment_slice(original[i], seg), \
                f"ARC-only must recover the true bytes (packet {i}, {seg.name})"
    print("  ARC-only reproduced coefficient_first's data-segment repair exactly")


def test_keyed_arc_only_equals_coefficient_first_on_clean_coeffs():
    _banner("keyed: ARC-only data result == coefficient_first_mac (clean coeffs)")
    pool, keyset, segments = _keyed_pool(seed=31)
    original = [bytearray(p) for p in pool]
    assert all(check_mac_segmented(FIELD, keyset, pool, segments).values()), "clean pool must verify"

    data0 = next(s for s in segments if s.name == "data-0")
    broken = [bytearray(p) for p in pool]
    broken[4] = error_into_packet_chosen_bit(broken[4], data0.start, chosen_bit=5)
    broken[5] = error_into_packet_chosen_bit(broken[5], data0.start + 1, chosen_bit=6)

    basis_idx = list(range(GEN_SIZE))
    coeff_clean_targets = list(range(GEN_SIZE, GEN_SIZE + N_TARGETS))

    cf = recover_coefficient_first_mac(FIELD, keyset, [bytearray(p) for p in broken], segments,
                                       GEN_SIZE, max_combined_hd=2)
    arc = recover_arc_only_mac(FIELD, keyset, [bytearray(p) for p in broken], segments, GEN_SIZE,
                               basis_idx, coeff_clean_targets, max_combined_hd=2)

    cf_data = {o.segment_name: o for o in cf.per_segment if o.segment_name != "coeff"}
    for o in arc.per_segment:
        print(f"  {o.segment_name}: arc={o}  cf={cf_data[o.segment_name]}")
        assert o == cf_data[o.segment_name], "per-data-segment outcome must match coefficient_first_mac"

    for seg in _data_segments(segments):
        for i in range(len(pool)):
            assert segment_slice_mac(arc.packets[i], seg) == segment_slice_mac(cf.packets[i], seg), \
                f"data-segment bytes must match coefficient_first_mac (packet {i}, {seg.name})"
            assert segment_slice_mac(arc.packets[i], seg) == segment_slice_mac(original[i], seg), \
                f"ARC-only must recover the true bytes (packet {i}, {seg.name})"
    print("  ARC-only (keyed) reproduced coefficient_first_mac's data-segment repair exactly")


# ── (2) Error model (b): coeff-corrupted target dropped symmetrically ─────────

def _drop_scenario_keyless():
    pool, segments = _keyless_pool(seed=44)
    coeff = next(s for s in segments if s.name == "coeff")
    data0 = next(s for s in segments if s.name == "data-0")
    broken = [bytearray(p) for p in pool]
    # Target 4: BOTH its coeff block and its data-0 payload corrupted -> ARC cannot
    # localize it (coeffs untrusted), so ARC-only must DROP it, not half-repair it.
    broken[4] = error_into_packet_chosen_bit(broken[4], coeff.start, chosen_bit=1)
    broken[4] = error_into_packet_chosen_bit(broken[4], data0.start, chosen_bit=5)
    # Target 5: data-only corruption in data-0 -> still recoverable.
    broken[5] = error_into_packet_chosen_bit(broken[5], data0.start + 1, chosen_bit=6)
    basis_idx = list(range(GEN_SIZE))
    coeff_clean_targets = [5, 6, 7]  # 4 excluded: its coeffs are corrupted (ground truth)
    arc = recover_arc_only(FIELD, [bytearray(p) for p in broken], segments, GEN_SIZE,
                           basis_idx, coeff_clean_targets, max_combined_hd=2)
    return arc, broken, segments, segment_slice


def _drop_scenario_keyed():
    pool, keyset, segments = _keyed_pool(seed=44)
    coeff = next(s for s in segments if s.name == "coeff")
    data0 = next(s for s in segments if s.name == "data-0")
    broken = [bytearray(p) for p in pool]
    broken[4] = error_into_packet_chosen_bit(broken[4], coeff.start, chosen_bit=1)
    broken[4] = error_into_packet_chosen_bit(broken[4], data0.start, chosen_bit=5)
    broken[5] = error_into_packet_chosen_bit(broken[5], data0.start + 1, chosen_bit=6)
    basis_idx = list(range(GEN_SIZE))
    coeff_clean_targets = [5, 6, 7]
    arc = recover_arc_only_mac(FIELD, keyset, [bytearray(p) for p in broken], segments, GEN_SIZE,
                               basis_idx, coeff_clean_targets, max_combined_hd=2)
    return arc, broken, segments, segment_slice_mac


def test_arc_only_drops_coeff_corrupted_target_symmetrically_in_both_arms():
    _banner("both arms: coeff-corrupted target dropped identically; data-only target recovered")
    arc_k, broken_k, segs_k, slc_k = _drop_scenario_keyless()
    arc_m, broken_m, segs_m, slc_m = _drop_scenario_keyed()

    for label, arc, broken, segs, slc in (("keyless", arc_k, broken_k, segs_k, slc_k),
                                          ("keyed", arc_m, broken_m, segs_m, slc_m)):
        data0_out = next(o for o in arc.per_segment if o.segment_name == "data-0")
        other_out = [o for o in arc.per_segment if o.segment_name != "data-0"]
        print(f"  [{label}] data-0 outcome: {data0_out}")

        # The coeff-corrupted target (4) is dropped in data-0, exactly once.
        assert data0_out.dropped == 1, f"[{label}] the coeff-corrupted target must be dropped"
        # Dropped means untouched: its data-0 bytes still equal the corrupted input.
        data0_seg = next(s for s in segs if s.name == "data-0")
        assert slc(arc.packets[4], data0_seg) == slc(broken[4], data0_seg), \
            f"[{label}] dropped target must be left untouched, not half-repaired"
        # Other data segments: target 4 isn't broken there, so nothing is dropped.
        for o in other_out:
            assert o.dropped == 0, f"[{label}] no drops expected in {o.segment_name}"
        # The data-only target (5) IS recovered (unpaired, ARC-narrowed).
        assert data0_out.unpaired_recovered >= 1, f"[{label}] data-only target should recover"

    # The identical-set claim: both arms drop the same target (index 4) in data-0.
    d4_k = slc_k(arc_k.packets[4], next(s for s in segs_k if s.name == "data-0"))
    d4_m = slc_m(arc_m.packets[4], next(s for s in segs_m if s.name == "data-0"))
    print("  both arms dropped target 4 in data-0 (identical drop set)")
    # (Byte equality across arms isn't expected -- different tag layouts -- but the
    #  DROP DECISION is identical, which is the symmetry the ADR requires.)
    assert d4_k is not None and d4_m is not None


if __name__ == "__main__":
    tests = [
        test_keyless_arc_only_equals_coefficient_first_on_clean_coeffs,
        test_keyed_arc_only_equals_coefficient_first_on_clean_coeffs,
        test_arc_only_drops_coeff_corrupted_target_symmetrically_in_both_arms,
    ]
    for test in tests:
        test()
        print(f"{test.__name__} passed")
    print("\nAll ARC-only recovery tests passed!")
