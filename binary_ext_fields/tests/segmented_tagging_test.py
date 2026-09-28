"""
Smoke tests for segmented orthogonal tagging (ADR-0012).

These are meant to be read, not just run: each test demonstrates one property
of the mechanism -- that segments tag/verify independently of each other, that
corruption in one segment never leaks into another, and that the ADR-0010
salt give-up path still surfaces cleanly per segment.
"""
import random

from binary_ext_fields.custom_field import create_field
from binary_ext_fields.generate_symbols import generate_identity_coefficients, generate_symbols_until_nonzero
from binary_ext_fields.orthogonal_tag_creator import has_unit_tag_column
from binary_ext_fields.segmented_tagging import (
    build_segments,
    tag_generation_segmented,
    check_orth_segmented,
)
from playground.arc_pl import error_into_packet_chosen_bit


def _random_data_rows(field, data_fields, gen_size):
    '''Plain [data] rows, no trailing reserved tag columns -- unlike generate_symbols_random,
    which reserves them for the N=1 whole-packet scheme this module does not use.'''
    return [
        bytearray(random.randint(0, field.max_value) for _ in range(data_fields))
        for _ in range(gen_size)
    ]


def _build_tagged_pool(field, gen_size, data_fields, num_data_segments):
    plain_packets = generate_identity_coefficients(field, _random_data_rows(field, data_fields, gen_size))
    result = tag_generation_segmented(field, plain_packets, gen_size, num_data_segments)
    assert result.ok, f"segmented tagging gave up on segment {result.failed_segment!r}"
    return result


def test_build_segments_lays_out_coeff_and_data_segments():
    '''One coeff-segment of length gen_size, then num_data_segments equal-length data-segments.'''
    segments = build_segments(gen_size=3, data_len=6, num_data_segments=3)

    assert [(s.name, s.start, s.length) for s in segments] == [
        ("coeff", 0, 3),
        ("data-0", 3, 2),
        ("data-1", 5, 2),
        ("data-2", 7, 2),
    ]


def test_build_segments_round_robins_the_remainder():
    '''ADR-0012 (resolved 2026-08-11): an uneven split round-robins the remainder,
    +1 byte to each of the first (data_len % num_data_segments) segments, instead
    of raising or dumping it all on the last segment.'''
    segments = build_segments(gen_size=3, data_len=5, num_data_segments=2)

    assert [(s.name, s.start, s.length) for s in segments] == [
        ("coeff", 0, 3),
        ("data-0", 3, 3),  # gets the +1 remainder byte
        ("data-1", 6, 2),
    ]


def test_freshly_tagged_pool_is_orthogonal_in_every_segment():
    '''Baseline: a freshly tagged generation must pass self/cross orthogonality in EVERY segment.'''
    field = create_field(8)
    gen_size = 4
    data_fields = 12  # each data-segment (4 bytes) stays >= gen_size - 1, see build_segments' note
    num_data_segments = 3  # -> segments: coeff, data-0, data-1, data-2

    result = _build_tagged_pool(field, gen_size, data_fields, num_data_segments)

    assert len(result.segments) == 1 + num_data_segments
    orth = check_orth_segmented(field, result.packets, result.segments)
    assert all(orth.values()), orth

    total_expected_length = sum(s.total_length for s in result.segments)
    for packet in result.packets:
        assert len(packet) == total_expected_length


def test_corrupting_the_coeff_segment_breaks_only_that_segment():
    '''
    The gap ADR-0012 closes: today's whole-packet scheme trusts the coefficient
    block unconditionally. Here, a bit-flip inside packet 0's coeff-segment must
    fail the coeff-segment's own orthogonality check, while every data-segment --
    untouched -- stays orthogonal.
    '''
    field = create_field(8)
    gen_size = 4
    data_fields = 12
    num_data_segments = 3

    result = _build_tagged_pool(field, gen_size, data_fields, num_data_segments)
    coeff_segment = next(s for s in result.segments if s.name == "coeff")

    corrupt_column = coeff_segment.start  # first byte of packet 0's coeff payload
    result.packets[0] = error_into_packet_chosen_bit(result.packets[0], corrupt_column, chosen_bit=0)

    orth = check_orth_segmented(field, result.packets, result.segments)

    assert orth["coeff"] is False
    for s in result.segments:
        if s.kind == "data":
            assert orth[s.name] is True, f"{s.name} must stay orthogonal, only coeff was corrupted"


def test_corrupting_one_data_segment_breaks_only_that_segment():
    '''
    Segments are independent of each other too, not just coeff-vs-data: corrupting
    data-segment 1 must leave the coeff-segment and data-segment 0 orthogonal.
    '''
    field = create_field(8)
    gen_size = 4
    data_fields = 12
    num_data_segments = 3

    result = _build_tagged_pool(field, gen_size, data_fields, num_data_segments)
    target_segment = next(s for s in result.segments if s.name == "data-1")

    corrupt_column = target_segment.start
    result.packets[2] = error_into_packet_chosen_bit(result.packets[2], corrupt_column, chosen_bit=3)

    orth = check_orth_segmented(field, result.packets, result.segments)

    assert orth["data-1"] is False
    assert orth["coeff"] is True
    assert orth["data-0"] is True
    assert orth["data-2"] is True


def test_salt_give_up_surfaces_ok_false_instead_of_looping_forever():
    '''
    ADR-0010's documented give-up path, per segment: with max_salt_draws=0 the salt
    loop never even tries a draw, so tagging must report failure on the first
    segment (coeff, tagged first) instead of raising or returning a degenerate result.
    '''
    field = create_field(4)
    gen_size = 3
    data_fields = 4
    num_data_segments = 2

    plain_packets = generate_identity_coefficients(field, _random_data_rows(field, data_fields, gen_size))
    result = tag_generation_segmented(field, plain_packets, gen_size, num_data_segments, max_salt_draws=0)

    assert result.ok is False
    assert result.packets is None
    assert result.failed_segment == "coeff"


def test_rank_deficient_segment_exhausts_salt_budget_no_matter_how_generous():
    '''
    build_segments' own docstring warning, made concrete: a data-segment shorter
    than gen_size - 1 is rank-deficient by construction, so at least one packet's
    self-tag MUST be zero -- no salt draw can fix it. Unlike the max_salt_draws=0
    case above (which never tries), this proves give-up still holds with a large,
    realistic budget, because the failure is structural, not bad luck.
    '''
    field = create_field(4)
    gen_size = 4
    data_fields = 4
    num_data_segments = 4  # data-segment length 1 -> payload_length+1=2 < gen_size=4

    plain_packets = generate_identity_coefficients(field, _random_data_rows(field, data_fields, gen_size))
    result = tag_generation_segmented(field, plain_packets, gen_size, num_data_segments, max_salt_draws=200)

    assert result.ok is False
    assert result.packets is None
    assert result.failed_segment == "data-0"  # coeff-segment (length=gen_size) is not rank-deficient


def test_last_self_tag_is_never_one_in_any_segment():
    '''
    Salt rule extension (silent-decode diagnosis 2026-09-24, extends ADR-0010).
    generate_all_tags is lower-triangular -- packet k only fills tags 0..k -- so a
    segment's LAST tag column equals c * (coefficient g-1) for every recoded packet,
    c = the last packet's self-tag. With c == 1, flipping the same bit in coeff[g-1]
    and tag[g-1] passes the self-check AND every cross-check, so a harmless tag[g-1]
    error gets "repaired" into a wrong coefficient (silent decode). The salt loop must
    therefore reject c == 1 exactly like it rejects c == 0 -- and, generally, any tag column
    equal to e_k (self-tag 1, zero below): in the coeff-segment a row whose salt is 0 yields
    exactly that (~gen_size/q of generations; found by the repair-seam regression test).
    '''
    field = create_field(8)
    gen_size, data_fields, num_data_segments = 4, 8, 1
    random.seed(0)
    for _ in range(1500):
        result = _build_tagged_pool(field, gen_size, data_fields, num_data_segments)
        for segment in result.segments:
            last_self_tag = result.packets[-1][segment.salt_index + gen_size]
            assert last_self_tag not in (0, 1), (segment.name, last_self_tag)
            rows = [p[segment.start:segment.salt_index + 1 + gen_size] for p in result.packets]
            assert not has_unit_tag_column(rows, gen_size), segment.name  # e.g. coeff row with salt 0


def test_whole_packet_generator_also_rejects_last_self_tag_one():
    '''Same rule for the N=1 whole-packet scheme (OrthogonalScheme's source generator):
    same lower-triangular generator, same coeff[g-1]/tag[g-1] blind pair when c == 1.
    The last packet's self-tag is its final byte.'''
    field = create_field(8)
    random.seed(0)
    for _ in range(1500):
        tagged = generate_symbols_until_nonzero(field, 8, 4, coefficients=True)
        assert tagged[-1][-1] not in (0, 1)
        assert not has_unit_tag_column(tagged, 4)


if __name__ == "__main__":
    test_build_segments_lays_out_coeff_and_data_segments()
    print("test_build_segments_lays_out_coeff_and_data_segments passed")

    test_build_segments_round_robins_the_remainder()
    print("test_build_segments_round_robins_the_remainder passed")

    test_freshly_tagged_pool_is_orthogonal_in_every_segment()
    print("test_freshly_tagged_pool_is_orthogonal_in_every_segment passed")

    test_corrupting_the_coeff_segment_breaks_only_that_segment()
    print("test_corrupting_the_coeff_segment_breaks_only_that_segment passed")

    test_corrupting_one_data_segment_breaks_only_that_segment()
    print("test_corrupting_one_data_segment_breaks_only_that_segment passed")

    test_salt_give_up_surfaces_ok_false_instead_of_looping_forever()
    print("test_salt_give_up_surfaces_ok_false_instead_of_looping_forever passed")

    test_rank_deficient_segment_exhausts_salt_budget_no_matter_how_generous()
    print("test_rank_deficient_segment_exhausts_salt_budget_no_matter_how_generous passed")

    print("All segmented tagging tests passed!")

    test_last_self_tag_is_never_one_in_any_segment()
    print("test_last_self_tag_is_never_one_in_any_segment passed")

    test_whole_packet_generator_also_rejects_last_self_tag_one()
    print("test_whole_packet_generator_also_rejects_last_self_tag_one passed")
