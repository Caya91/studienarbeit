"""
Tests for the repair-span knob (ADR-0013, ticket 16), both arms.

`repair_span` decides which columns the ARC-narrowed bit-flip repair may touch:
  - "payload" (default): the data columns ARC localizes -- today's behaviour;
  - "segment": ALSO the salt/tag redundancy columns, so a corrupted salt (keyless)
    or tag (keyed) byte is searched and repaired instead of honest-failing.

Meant to be read, not just run:
  - the headline test pins the whole point: a PAYLOAD-CLEAN target whose salt/tag
    byte is flipped honest-FAILS at repair_span="payload" (nothing to search) and
    RECOVERS at repair_span="segment" (the redundancy byte is now in the search
    span), byte-for-byte back to the original -- in each arm;
  - the localizer test pins two invariants the knob rides on: "segment" is a strict
    superset of "payload" columns (so the pair cache, keyed on candidate_columns,
    can't reuse a payload-span result at segment span), and an unlocalizable packet
    stays None either way (so drop_unlocalized's symmetric drop is untouched).

Judge pass/fail by exit code (0 = pass); banners print "assert"/"error" as prose.
"""
import random

from binary_ext_fields.custom_field import create_field
from binary_ext_fields.generate_symbols import (
    generate_identity_coefficients,
    recode_rlnc_without_coeffs,
)
from binary_ext_fields.segmented_tagging import (
    tag_generation_segmented,
    check_orth_segmented,
)
from binary_ext_fields.segmented_recovery import (
    recover_arc_only,
    _make_arc_localizer,
    segment_slice,
)
from binary_ext_fields.segmented_mac_tagging import (
    layout_mac_segments,
    generate_keyset,
    tag_generation_mac,
    check_mac_segmented,
)
from binary_ext_fields.segmented_mac_recovery import (
    recover_arc_only_mac,
    _make_arc_localizer_mac,
    segment_slice as segment_slice_mac,
)
from playground.arc_pl import error_into_packet_chosen_bit


def _banner(name):
    print(f"\n=== {name} ===")


FIELD = create_field(8)
GEN_SIZE = 4
DATA_FIELDS = 12
NUM_DATA_SEGMENTS = 3
N_TARGETS = 4
BASIS = list(range(GEN_SIZE))                                   # clean helpers
ALL_COEFF_CLEAN = list(range(GEN_SIZE, GEN_SIZE + N_TARGETS))   # every target's coeffs clean


def _random_data_rows(rng):
    return [bytearray(rng.randint(0, FIELD.max_value) for _ in range(DATA_FIELDS))
            for _ in range(GEN_SIZE)]


def _keyless_pool(seed):
    rng = random.Random(seed)
    plain = generate_identity_coefficients(FIELD, _random_data_rows(rng))
    result = tag_generation_segmented(FIELD, plain, GEN_SIZE, NUM_DATA_SEGMENTS)
    assert result.ok, f"tagging gave up on {result.failed_segment!r}"
    recoded = recode_rlnc_without_coeffs(FIELD, result.packets, GEN_SIZE, count=N_TARGETS)
    pool = [bytearray(p) for p in result.packets] + [bytearray(p) for p in recoded]
    return pool, result.segments


def _keyed_pool(seed):
    rng = random.Random(seed)
    plain = generate_identity_coefficients(FIELD, _random_data_rows(rng))
    segments = layout_mac_segments(GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, num_keys=GEN_SIZE)
    keyset = generate_keyset(FIELD, segments, rng)
    packets = tag_generation_mac(FIELD, plain, GEN_SIZE, NUM_DATA_SEGMENTS, keyset, num_keys=GEN_SIZE)
    recoded = recode_rlnc_without_coeffs(FIELD, packets, GEN_SIZE, count=N_TARGETS)
    pool = [bytearray(p) for p in packets] + [bytearray(p) for p in recoded]
    return pool, keyset, segments


# ── (1) Headline: redundancy-byte flip -- fails at payload span, recovers at segment ──

def test_keyless_segment_span_repairs_salt_flip_that_payload_span_fails():
    _banner("keyless: salt-byte flip honest-fails at payload span, recovers at segment span")
    pool, segments = _keyless_pool(seed=31)
    original = [bytearray(p) for p in pool]
    assert all(check_orth_segmented(FIELD, pool, segments).values()), "clean pool must be orthogonal"

    data0 = next(s for s in segments if s.name == "data-0")
    tgt = GEN_SIZE  # first target; payload + coeffs stay clean, only its data-0 salt is flipped
    broken = [bytearray(p) for p in pool]
    broken[tgt] = error_into_packet_chosen_bit(broken[tgt], data0.salt_index, chosen_bit=3)
    assert segment_slice(broken[tgt], data0) != segment_slice(original[tgt], data0), "salt flip must land"

    # bitflip_only=True is the ADR-0013 comparison mode: it drops the two-stage path's
    # whole-segment fallback (which would repair the salt regardless), so the search span
    # is exactly repair_span -- the context in which this knob is meant to bite.
    def run(span):
        return recover_arc_only(FIELD, [bytearray(p) for p in broken], segments, GEN_SIZE,
                                BASIS, ALL_COEFF_CLEAN, max_combined_hd=2, bitflip_only=True,
                                repair_span=span)

    pay, seg = run("payload"), run("segment")
    pay_slice = segment_slice(pay.packets[tgt], data0)
    seg_slice = segment_slice(seg.packets[tgt], data0)
    print(f"  payload span: data-0 slice back to original? {pay_slice == segment_slice(original[tgt], data0)}")
    print(f"  segment span: data-0 slice back to original? {seg_slice == segment_slice(original[tgt], data0)}")

    assert pay_slice == segment_slice(broken[tgt], data0), \
        "payload span must NOT touch the salt -> target left as the corrupted input"
    assert seg_slice == segment_slice(original[tgt], data0), \
        "segment span must repair the salt byte back to the true bytes"
    print("  salt flip: unrepairable at payload span, repaired at segment span (keyless)")


def test_keyed_segment_span_repairs_tag_flip_that_payload_span_fails():
    _banner("keyed: tag-byte flip honest-fails at payload span, recovers at segment span")
    pool, keyset, segments = _keyed_pool(seed=31)
    original = [bytearray(p) for p in pool]
    assert all(check_mac_segmented(FIELD, keyset, pool, segments).values()), "clean pool must verify"

    data0 = next(s for s in segments if s.name == "data-0")
    tgt = GEN_SIZE
    broken = [bytearray(p) for p in pool]
    # keyed layout has no salt: the first redundancy column is the first MAC tag byte.
    first_tag_index = data0.start + data0.payload_length
    broken[tgt] = error_into_packet_chosen_bit(broken[tgt], first_tag_index, chosen_bit=3)
    assert segment_slice_mac(broken[tgt], data0) != segment_slice_mac(original[tgt], data0), "tag flip must land"

    def run(span):
        return recover_arc_only_mac(FIELD, keyset, [bytearray(p) for p in broken], segments, GEN_SIZE,
                                    BASIS, ALL_COEFF_CLEAN, max_combined_hd=2, repair_span=span)

    pay, seg = run("payload"), run("segment")
    pay_slice = segment_slice_mac(pay.packets[tgt], data0)
    seg_slice = segment_slice_mac(seg.packets[tgt], data0)
    print(f"  payload span: data-0 slice back to original? {pay_slice == segment_slice_mac(original[tgt], data0)}")
    print(f"  segment span: data-0 slice back to original? {seg_slice == segment_slice_mac(original[tgt], data0)}")

    assert pay_slice == segment_slice_mac(broken[tgt], data0), \
        "payload span must NOT touch the tag -> target left as the corrupted input"
    assert seg_slice == segment_slice_mac(original[tgt], data0), \
        "segment span must repair the tag byte back to the true bytes"
    print("  tag flip: unrepairable at payload span, repaired at segment span (keyed)")


# ── (2) Localizer invariants: superset (cache distinctness) + None-preservation (drop) ──

def test_segment_span_localizer_is_superset_and_preserves_none():
    _banner("localizer: segment span strictly widens payload columns; None stays None (drop kept)")
    pool, segments = _keyless_pool(seed=31)
    coeff = next(s for s in segments if s.kind == "coeff")
    data0 = next(s for s in segments if s.name == "data-0")

    # A localizable target: give it a payload error so ARC returns a non-empty payload set.
    broken = [bytearray(p) for p in pool]
    tgt = GEN_SIZE
    broken[tgt] = error_into_packet_chosen_bit(broken[tgt], data0.start + 2, chosen_bit=4)

    coeff_trusted = BASIS + ALL_COEFF_CLEAN
    loc_pay = _make_arc_localizer(FIELD, broken, coeff, data0, GEN_SIZE, coeff_trusted, BASIS,
                                  repair_span="payload")
    loc_seg = _make_arc_localizer(FIELD, broken, coeff, data0, GEN_SIZE, coeff_trusted, BASIS,
                                  repair_span="segment")

    cols_pay, cols_seg = loc_pay(tgt), loc_seg(tgt)
    redundancy = set(range(data0.payload_length, data0.total_length))
    print(f"  payload cols={cols_pay}  segment cols={cols_seg}  redundancy={sorted(redundancy)}")
    assert set(cols_pay) < set(cols_seg), "segment span must be a strict superset of payload span"
    assert redundancy <= set(cols_seg), "segment span must include every salt/tag column"
    assert redundancy.isdisjoint(cols_pay), "payload span must never include a salt/tag column"
    assert cols_pay != cols_seg, "distinct column sets -> distinct pair-cache keys (no cross-span reuse)"

    # An unlocalizable target (its coeffs untrusted) returns None under BOTH spans, so
    # drop_unlocalized still drops it symmetrically -- the knob doesn't leak into drop logic.
    untrusted_coeff = BASIS  # target GEN_SIZE is NOT in this set -> localizer's own-coeff gate returns None
    loc_pay_n = _make_arc_localizer(FIELD, broken, coeff, data0, GEN_SIZE, untrusted_coeff, BASIS,
                                    repair_span="payload")
    loc_seg_n = _make_arc_localizer(FIELD, broken, coeff, data0, GEN_SIZE, untrusted_coeff, BASIS,
                                    repair_span="segment")
    assert loc_pay_n(tgt) is None and loc_seg_n(tgt) is None, \
        "an unlocalizable packet stays None under both spans (drop symmetry preserved)"
    print("  segment span widens localizable columns and preserves None -> drop unaffected")


if __name__ == "__main__":
    test_keyless_segment_span_repairs_salt_flip_that_payload_span_fails()
    test_keyed_segment_span_repairs_tag_flip_that_payload_span_fails()
    test_segment_span_localizer_is_superset_and_preserves_none()
    print("\nAll repair-span tests passed!")
