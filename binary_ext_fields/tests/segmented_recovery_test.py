"""
Tests for segment pairing and recovery (ADR-0012, binary_ext_fields/segmented_recovery.py).

Meant to be read, not just run -- each test demonstrates one property of the
mechanism: who gets classified broken/trusted, how pairing groups them up, that
a genuinely disjoint two-packet corruption is repaired byte-for-byte back to
the original (not just "some" orthogonal value), that the coefficient block
-- the whole-packet scheme's documented blind spot -- is repaired exactly like
any data segment, that an odd one out correctly falls back to the ADR-0002
linear solve, and that the ONE thing this mechanism cannot do (two errors at
the exact same bit position) fails honestly instead of silently.
"""
import random

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import (
    generate_identity_coefficients,
    code_with_given_coefficients,
    recode_rlnc_without_coeffs,
)
from binary_ext_fields.segmented_tagging import (
    TaggedSegment,
    build_segments,
    tag_generation_segmented,
    check_orth_segmented,
)
from binary_ext_fields.segmented_recovery import (
    SegmentTrust,
    SegmentPair,
    classify_segment_trust,
    plan_pairing,
    recover_pair_by_combined_search,
    recover_uniform_hd,
    recover_coefficient_first,
    _make_arc_localizer,
)
from playground.arc_pl import error_into_packet_chosen_bit


def _random_data_rows(field, data_fields, gen_size):
    return [
        bytearray(random.randint(0, field.max_value) for _ in range(data_fields))
        for _ in range(gen_size)
    ]


def _build_tagged_pool(field, gen_size, data_fields, num_data_segments):
    plain_packets = generate_identity_coefficients(field, _random_data_rows(field, data_fields, gen_size))
    result = tag_generation_segmented(field, plain_packets, gen_size, num_data_segments)
    assert result.ok, f"segmented tagging gave up on segment {result.failed_segment!r}"
    return result


# Shared config for most tests: 4 packets, 3 equal data-segments of 4 bytes each
# (mirrors segmented_tagging_test.py's own convention, so payload lengths stay
# above the rank-deficiency floor build_segments documents).
FIELD = create_field(8)
GEN_SIZE = 4
DATA_FIELDS = 12
NUM_DATA_SEGMENTS = 3


def test_classify_segment_trust_marks_only_the_corrupted_packet_broken():
    '''A single corrupted packet fails its own self-check; everyone else, still
    pairwise cross-orthogonal, is trusted.'''
    random.seed(10)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    segment = next(s for s in result.segments if s.name == "data-1")

    packets = [bytearray(p) for p in result.packets]
    packets[2] = error_into_packet_chosen_bit(packets[2], segment.start, chosen_bit=1)

    trust = classify_segment_trust(FIELD, packets, segment)

    assert trust.broken == [2]
    assert trust.trusted == [0, 1, 3]


def test_plan_pairing_pairs_fifo_and_leaves_odd_one_out():
    '''Pure unit test of the pairing rule: ascending index, pairs of two, last
    leftover (if any) becomes the unpaired fallback case. No field/tagging
    needed -- this only exercises the FIFO grouping logic.'''
    even = SegmentTrust(segment_name="data-0", broken=[5, 1, 3, 0], trusted=[])
    plan = plan_pairing(even)
    assert plan.pairs == [
        SegmentPair("data-0", 0, 1),
        SegmentPair("data-0", 3, 5),
    ]
    assert plan.unpaired == []

    odd = SegmentTrust(segment_name="data-0", broken=[4, 0, 2], trusted=[])
    plan = plan_pairing(odd)
    assert [(p.packet_a, p.packet_b) for p in plan.pairs] == [(0, 2)]
    assert [(u.packet_index) for u in plan.unpaired] == [4]


def test_recover_pair_by_combined_search_fixes_two_disjoint_single_bit_errors():
    '''The core mechanism, exercised directly (not through the full pipeline):
    two packets broken at different columns of the same segment, each by one
    flipped bit. The combined search must recover BOTH exactly, byte-for-byte.'''
    random.seed(11)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    segment = next(s for s in result.segments if s.name == "data-0")
    original_a = bytearray(result.packets[0][segment.start:segment.start + segment.total_length])
    original_b = bytearray(result.packets[1][segment.start:segment.start + segment.total_length])

    broken_a = error_into_packet_chosen_bit(original_a, 0, chosen_bit=2)
    broken_b = error_into_packet_chosen_bit(original_b, 1, chosen_bit=6)
    trusted_slices = [result.packets[i][segment.start:segment.start + segment.total_length] for i in (2, 3)]

    columns = list(range(segment.payload_length))
    out = recover_pair_by_combined_search(FIELD, broken_a, broken_b, trusted_slices, columns, max_combined_hd=2)

    assert out.ok, "expected the disjoint two-error pair to be recoverable"
    assert out.fixed_a == original_a
    assert out.fixed_b == original_b


def test_recover_pair_by_combined_search_gives_up_within_budget_not_forever():
    '''A combined weight-2 correction needs max_combined_hd >= 2; capped at 1 it
    must report ok=False (an honest budget give-up), not loop or crash.'''
    random.seed(12)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    segment = next(s for s in result.segments if s.name == "data-0")
    original_a = bytearray(result.packets[0][segment.start:segment.start + segment.total_length])
    original_b = bytearray(result.packets[1][segment.start:segment.start + segment.total_length])

    broken_a = error_into_packet_chosen_bit(original_a, 0, chosen_bit=2)
    broken_b = error_into_packet_chosen_bit(original_b, 1, chosen_bit=6)
    trusted_slices = [result.packets[i][segment.start:segment.start + segment.total_length] for i in (2, 3)]

    columns = list(range(segment.payload_length))
    out = recover_pair_by_combined_search(FIELD, broken_a, broken_b, trusted_slices, columns, max_combined_hd=1)

    assert out.ok is False
    assert out.fixed_a is None and out.fixed_b is None


def test_recover_uniform_hd_repairs_two_broken_packets_in_a_data_segment():
    '''Full pipeline (Option 1): two packets broken in the same data segment at
    disjoint columns must both come back byte-for-byte identical to the
    original clean generation, and the whole pool must check out afterwards.'''
    random.seed(13)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    original = [bytearray(p) for p in result.packets]
    segment = next(s for s in result.segments if s.name == "data-1")

    broken = [bytearray(p) for p in result.packets]
    broken[0] = error_into_packet_chosen_bit(broken[0], segment.start, chosen_bit=2)
    broken[2] = error_into_packet_chosen_bit(broken[2], segment.start + 1, chosen_bit=5)
    assert check_orth_segmented(FIELD, broken, result.segments)["data-1"] is False

    report = recover_uniform_hd(FIELD, broken, result.segments, max_combined_hd=2)

    assert report.ok is True
    assert report.packets == original
    outcome = next(o for o in report.per_segment if o.segment_name == "data-1")
    assert outcome.pairs_recovered == 1
    assert outcome.pairs_failed == 0


def test_recover_uniform_hd_repairs_coefficient_segment_corruption():
    '''This is the gap ADR-0012 exists to close: the whole-packet scheme's ARC
    recovery can never repair the coefficient block (playground/new_recovery.py's
    documented "intrinsic blind spot"). Here, corrupting TWO packets' coeff
    segments must still recover exactly, via the exact same pairing/search
    mechanism used for any data segment -- no special-casing needed.'''
    random.seed(14)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    original = [bytearray(p) for p in result.packets]
    segment = next(s for s in result.segments if s.name == "coeff")

    broken = [bytearray(p) for p in result.packets]
    broken[1] = error_into_packet_chosen_bit(broken[1], segment.start, chosen_bit=1)
    broken[3] = error_into_packet_chosen_bit(broken[3], segment.start + 2, chosen_bit=4)

    report = recover_uniform_hd(FIELD, broken, result.segments, max_combined_hd=2)

    assert report.ok is True
    assert report.packets == original


def test_recover_uniform_hd_single_broken_packet_uses_unpaired_fallback():
    '''One broken packet has no pairing partner: plan_pairing must route it to
    the ADR-0002 linear solve, and (with enough trusted rows to fully determine
    the K=payload_length unknowns) recover it exactly.'''
    random.seed(15)
    field = create_field(8)
    gen_size = 6
    data_fields = 5  # one data-segment of length 5 == gen_size - 1, at build_segments' documented floor
    num_data_segments = 1

    result = _build_tagged_pool(field, gen_size, data_fields, num_data_segments)
    original = [bytearray(p) for p in result.packets]
    segment = next(s for s in result.segments if s.kind == "data")

    broken = [bytearray(p) for p in result.packets]
    broken[0] = error_into_packet_chosen_bit(broken[0], segment.start, chosen_bit=3)

    report = recover_uniform_hd(field, broken, result.segments, max_combined_hd=2)

    assert report.ok is True
    assert report.packets == original
    outcome = next(o for o in report.per_segment if o.segment_name == segment.name)
    assert outcome.unpaired_recovered == 1
    assert outcome.pairs_recovered == 0


def test_recover_uniform_hd_cannot_split_overlapping_errors():
    '''The documented, expected limitation (ADR-0012's deferred "IC-refinement
    Case 2"): if both paired packets are corrupted at the SAME bit position,
    the two flips cancel inside the XOR-combined row, so no split of the
    (now zero-weight, at that position) combined delta can separate them.
    This must fail honestly -- reported as a failed pair, ok=False -- not
    silently produce a wrong "fix".'''
    random.seed(16)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    segment = next(s for s in result.segments if s.name == "data-1")

    broken = [bytearray(p) for p in result.packets]
    broken[0] = error_into_packet_chosen_bit(broken[0], segment.start, chosen_bit=2)
    broken[2] = error_into_packet_chosen_bit(broken[2], segment.start, chosen_bit=2)  # identical column+bit

    report = recover_uniform_hd(FIELD, broken, result.segments, max_combined_hd=2)

    assert report.ok is False
    outcome = next(o for o in report.per_segment if o.segment_name == "data-1")
    assert outcome.pairs_failed == 1
    assert outcome.pairs_recovered == 0


def test_arc_localizer_narrows_to_the_true_corrupted_column_given_a_full_rank_basis():
    '''Isolated correctness check for _make_arc_localizer's glue code (building
    the [coefficients | data-segment payload] synthetic packets and converting
    localize_errors' offsets back to segment-local columns), independent of
    whether a real segmented generation can supply the gen_size-sized trusted
    basis this needs (see the next test: within a single closed generation, it
    generally cannot -- see that test's docstring for why).

    Hand-built scenario, mirroring playground/arc_pl.py's own ARC tests: a
    gen_size trusted basis with identity coefficients, and a 5th packet coded
    with different (recoded) coefficients and one corrupted data byte.
    '''
    random.seed(17)
    field = create_field(8)
    gen_size = 4
    data_len = 6

    coeff_segment = TaggedSegment(name="coeff", kind="coeff", start=0, payload_length=gen_size, gen_size=gen_size)
    data_segment = TaggedSegment(
        name="data-0", kind="data", start=coeff_segment.total_length, payload_length=data_len, gen_size=gen_size,
    )

    def synthetic_packet(coeffs, data):
        # segment_slice only ever reads the payload prefix of each block, so the
        # salt+tag bytes after it are never inspected here -- zero-fill is enough.
        return bytearray(coeffs) + bytearray(1 + gen_size) + bytearray(data) + bytearray(1 + gen_size)

    identity_rows = [[1 if i == j else 0 for j in range(gen_size)] for i in range(gen_size)]
    source_data = [bytearray(random.randint(0, field.max_value) for _ in range(data_len)) for _ in range(gen_size)]
    packets = [synthetic_packet(identity_rows[i], source_data[i]) for i in range(gen_size)]

    recode_coeffs = bytearray(random.randint(1, field.max_value) for _ in range(gen_size))
    true_data = code_with_given_coefficients(source_data, recode_coeffs, field)
    broken_data = bytearray(true_data)
    broken_data[2] ^= 0x04
    packets.append(synthetic_packet(recode_coeffs, broken_data))

    localizer = _make_arc_localizer(
        field, packets, coeff_segment, data_segment, gen_size,
        coeff_trusted_idx=[0, 1, 2, 3, 4],  # coefficients are clean on every packet, including the broken one
        data_trusted_idx=[0, 1, 2, 3],
    )

    assert localizer(4) == [2]


def test_recover_coefficient_first_falls_back_when_pool_has_no_recoding_headroom_yet():
    '''ADR-0012 Option 2, full pipeline, but fed a bare gen_size generation (no
    recoded packets accumulated yet -- e.g. right at the start of reception).
    localize_errors needs gen_size TRUSTED packets as a decoding basis PLUS a
    separate broken packet to check against them (playground/arc_pl.py), so a
    pool of exactly gen_size packets never has a spare one to spend on the
    basis. _make_arc_localizer correctly detects this and falls back to None
    rather than guessing, so Option 2 still recovers correctly here via the
    same combined-search fallback Option 1 uses -- the ARC-narrowing step
    just doesn't get to run yet. See
    test_recover_coefficient_first_narrows_via_arc_once_recoded_packets_have_accumulated
    for the realistic case (a receiver almost always has more than gen_size
    packets on hand by the time recovery runs, per the real send-until-decoded
    network/sim behaviour), where narrowing does engage.'''
    random.seed(18)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    original = [bytearray(p) for p in result.packets]
    coeff_segment = next(s for s in result.segments if s.name == "coeff")
    data_segment = next(s for s in result.segments if s.name == "data-0")

    broken = [bytearray(p) for p in result.packets]
    broken[0] = error_into_packet_chosen_bit(broken[0], coeff_segment.start, chosen_bit=1)
    broken[2] = error_into_packet_chosen_bit(broken[2], coeff_segment.start + 2, chosen_bit=3)
    broken[1] = error_into_packet_chosen_bit(broken[1], data_segment.start, chosen_bit=5)
    broken[3] = error_into_packet_chosen_bit(broken[3], data_segment.start + 1, chosen_bit=6)

    report = recover_coefficient_first(FIELD, broken, result.segments, GEN_SIZE, max_combined_hd=2)

    assert report.ok is True
    assert report.packets == original
    coeff_outcome = next(o for o in report.per_segment if o.segment_name == "coeff")
    assert coeff_outcome.pairs_recovered == 1


def test_recover_coefficient_first_narrows_via_arc_once_recoded_packets_have_accumulated():
    '''The realistic case: in both the real network and the sim, a generation
    is sent as recoded packets until it decodes, so a receiver normally has
    more than gen_size packets on hand by the time recovery runs. Recoding
    (recode_rlnc_without_coeffs) linearly combines whole rows, and every
    segment's tag pool is itself a self+cross-orthogonal set, so the same
    bilinear argument the module docstring makes for pairing shows a linear
    combination of the pool stays self+cross-orthogonal per segment too --
    recoded packets are exactly as decodable/localizable as originals, no
    special-casing needed. With that headroom, ARC narrowing must actually
    engage and pin each broken packet down to its true, single corrupted
    column -- not just fall back to a full-payload search.'''
    random.seed(19)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    recoded = recode_rlnc_without_coeffs(FIELD, result.packets, GEN_SIZE, count=5)
    pool = [bytearray(p) for p in result.packets] + [bytearray(p) for p in recoded]
    original = [bytearray(p) for p in pool]
    assert all(check_orth_segmented(FIELD, pool, result.segments).values()), (
        "recoded packets must stay orthogonal in every segment before any corruption"
    )

    coeff_segment = next(s for s in result.segments if s.name == "coeff")
    data_segment = next(s for s in result.segments if s.name == "data-0")

    broken = [bytearray(p) for p in pool]
    broken[0] = error_into_packet_chosen_bit(broken[0], coeff_segment.start, chosen_bit=1)
    broken[1] = error_into_packet_chosen_bit(broken[1], coeff_segment.start + 2, chosen_bit=3)
    broken[2] = error_into_packet_chosen_bit(broken[2], data_segment.start, chosen_bit=5)
    broken[3] = error_into_packet_chosen_bit(broken[3], data_segment.start + 1, chosen_bit=6)

    # Confirm ARC narrowing actually fires (not the no-localization fallback)
    # before checking end-to-end recovery: repair coeffs, then ask the same
    # localizer recover_coefficient_first would build for the exact columns.
    coeff_fixed_probe = [bytearray(p) for p in broken]
    coeff_fixed_probe[0][coeff_segment.start:coeff_segment.start + coeff_segment.total_length] = \
        original[0][coeff_segment.start:coeff_segment.start + coeff_segment.total_length]
    coeff_fixed_probe[1][coeff_segment.start:coeff_segment.start + coeff_segment.total_length] = \
        original[1][coeff_segment.start:coeff_segment.start + coeff_segment.total_length]
    coeff_trust = classify_segment_trust(FIELD, coeff_fixed_probe, coeff_segment)
    data_trust = classify_segment_trust(FIELD, coeff_fixed_probe, data_segment)
    localizer = _make_arc_localizer(
        FIELD, coeff_fixed_probe, coeff_segment, data_segment, GEN_SIZE, coeff_trust.trusted, data_trust.trusted,
    )
    assert localizer(2) == [0], "ARC should pin packet 2's error to exactly its true corrupted column"
    assert localizer(3) == [1], "ARC should pin packet 3's error to exactly its true corrupted column"

    report = recover_coefficient_first(FIELD, broken, result.segments, GEN_SIZE, max_combined_hd=2)

    assert report.ok is True
    assert report.packets == original


# ── Per-pair search persistence (ticket 01, ADR-0012's deferred cost) ────────
#
# The cache is an exact memo of a pure function: a hit must return a result
# identical to recomputing, but WITHOUT re-spending the search's field ops. A
# CountingField makes "was it actually re-searched?" observable -- zero new muls
# on a hit, nonzero on a genuine miss.

def _failed_pair_inputs(seed):
    """A recoverable-only-at-hd>=2 pair; searched at max_combined_hd=1 it is an
    honest budget give-up (ok=False) that still spends field ops filtering
    candidates -- the exact stale-but-unchanged pair the sim re-hits every round."""
    random.seed(seed)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    segment = next(s for s in result.segments if s.name == "data-0")
    sl = lambda i: bytearray(result.packets[i][segment.start:segment.start + segment.total_length])
    broken_a = error_into_packet_chosen_bit(sl(0), 0, chosen_bit=2)
    broken_b = error_into_packet_chosen_bit(sl(1), 1, chosen_bit=6)
    trusted = [sl(2), sl(3)]
    columns = list(range(segment.payload_length))
    return broken_a, broken_b, trusted, columns


def test_pair_cache_skips_the_search_on_an_unchanged_failed_pair():
    '''Second call with the same inputs and the same cache returns the identical
    give-up result and spends ZERO additional field multiplications -- the pair
    is not re-searched.'''
    broken_a, broken_b, trusted, columns = _failed_pair_inputs(20)
    cnt = CountingField(FIELD)
    cache = {}

    first = recover_pair_by_combined_search(cnt, broken_a, broken_b, trusted, columns,
                                            max_combined_hd=1, candidates_budget=10_000, pair_cache=cache)
    assert first.ok is False
    muls_after_first = cnt.mul_count
    assert muls_after_first > 0, "the first search must actually do field work"
    assert len(cache) == 1

    second = recover_pair_by_combined_search(cnt, broken_a, broken_b, trusted, columns,
                                             max_combined_hd=1, candidates_budget=10_000, pair_cache=cache)
    assert second == first
    assert cnt.mul_count == muls_after_first, "a cache hit must not re-spend any field ops"


def test_pair_cache_reuses_a_successful_repair_without_researching():
    '''A recoverable disjoint pair is searched once; the cached hit returns the
    same byte-for-byte fix with no further field ops.'''
    random.seed(21)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    segment = next(s for s in result.segments if s.name == "data-0")
    original_a = bytearray(result.packets[0][segment.start:segment.start + segment.total_length])
    original_b = bytearray(result.packets[1][segment.start:segment.start + segment.total_length])
    broken_a = error_into_packet_chosen_bit(original_a, 0, chosen_bit=2)
    broken_b = error_into_packet_chosen_bit(original_b, 1, chosen_bit=6)
    trusted = [result.packets[i][segment.start:segment.start + segment.total_length] for i in (2, 3)]
    columns = list(range(segment.payload_length))

    cnt = CountingField(FIELD)
    cache = {}
    first = recover_pair_by_combined_search(cnt, broken_a, broken_b, trusted, columns,
                                            max_combined_hd=2, pair_cache=cache)
    assert first.ok and first.fixed_a == original_a and first.fixed_b == original_b
    muls_after_first = cnt.mul_count

    second = recover_pair_by_combined_search(cnt, broken_a, broken_b, trusted, columns,
                                             max_combined_hd=2, pair_cache=cache)
    assert second == first
    assert cnt.mul_count == muls_after_first, "a cache hit must not re-spend any field ops"


def test_pair_cache_miss_when_the_trusted_set_changes():
    '''Changing the trusted set changes the key -- the pair is genuinely
    re-searched (new field ops, a second cache entry), never a stale hit.'''
    broken_a, broken_b, trusted, columns = _failed_pair_inputs(22)
    cnt = CountingField(FIELD)
    cache = {}

    recover_pair_by_combined_search(cnt, broken_a, broken_b, trusted, columns,
                                    max_combined_hd=1, pair_cache=cache)
    muls_after_first = cnt.mul_count

    recover_pair_by_combined_search(cnt, broken_a, broken_b, trusted[:1], columns,
                                    max_combined_hd=1, pair_cache=cache)
    assert cnt.mul_count > muls_after_first, "a changed trusted set must force a fresh search"
    assert len(cache) == 2


def test_pair_cache_does_not_change_recovery_output():
    '''End-to-end: recover_uniform_hd with a cache produces exactly the same
    repaired packets and per-segment outcome as without one -- the cache is a
    pure speed-up, never a behaviour change.'''
    random.seed(23)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    segment = next(s for s in result.segments if s.name == "data-1")

    def broken_pool():
        pool = [bytearray(p) for p in result.packets]
        pool[0] = error_into_packet_chosen_bit(pool[0], segment.start, chosen_bit=2)
        pool[2] = error_into_packet_chosen_bit(pool[2], segment.start + 1, chosen_bit=5)
        return pool

    uncached = recover_uniform_hd(FIELD, broken_pool(), result.segments, max_combined_hd=2)
    cached = recover_uniform_hd(FIELD, broken_pool(), result.segments, max_combined_hd=2, pair_cache={})

    assert cached.ok == uncached.ok
    assert cached.packets == uncached.packets
    assert cached.per_segment == uncached.per_segment


if __name__ == "__main__":
    tests = [
        test_classify_segment_trust_marks_only_the_corrupted_packet_broken,
        test_plan_pairing_pairs_fifo_and_leaves_odd_one_out,
        test_recover_pair_by_combined_search_fixes_two_disjoint_single_bit_errors,
        test_recover_pair_by_combined_search_gives_up_within_budget_not_forever,
        test_recover_uniform_hd_repairs_two_broken_packets_in_a_data_segment,
        test_recover_uniform_hd_repairs_coefficient_segment_corruption,
        test_recover_uniform_hd_single_broken_packet_uses_unpaired_fallback,
        test_recover_uniform_hd_cannot_split_overlapping_errors,
        test_arc_localizer_narrows_to_the_true_corrupted_column_given_a_full_rank_basis,
        test_recover_coefficient_first_falls_back_when_pool_has_no_recoding_headroom_yet,
        test_recover_coefficient_first_narrows_via_arc_once_recoded_packets_have_accumulated,
        test_pair_cache_skips_the_search_on_an_unchanged_failed_pair,
        test_pair_cache_reuses_a_successful_repair_without_researching,
        test_pair_cache_miss_when_the_trusted_set_changes,
        test_pair_cache_does_not_change_recovery_output,
    ]
    for test in tests:
        test()
        print(f"{test.__name__} passed")
    print("All segmented recovery tests passed!")
