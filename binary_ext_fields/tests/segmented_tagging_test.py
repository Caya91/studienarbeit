"""
Smoke tests for segmented orthogonal tagging (ADR-0012).

These are meant to be read, not just run: each test demonstrates one property
of the mechanism -- that segments tag/verify independently of each other, that
corruption in one segment never leaks into another, and that the ADR-0010
salt give-up path still surfaces cleanly per segment.
"""
import random

from binary_ext_fields.custom_field import create_field
from binary_ext_fields.generate_symbols import generate_identity_coefficients
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


def test_build_segments_rejects_uneven_split():
    '''ADR-0012 defers uneven splits -- must fail loudly, not silently drop/pad bytes.'''
    try:
        build_segments(gen_size=3, data_len=5, num_data_segments=2)
        assert False, "expected ValueError for a data_len that does not split evenly"
    except ValueError:
        pass


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


if __name__ == "__main__":
    test_build_segments_lays_out_coeff_and_data_segments()
    print("test_build_segments_lays_out_coeff_and_data_segments passed")

    test_build_segments_rejects_uneven_split()
    print("test_build_segments_rejects_uneven_split passed")

    test_freshly_tagged_pool_is_orthogonal_in_every_segment()
    print("test_freshly_tagged_pool_is_orthogonal_in_every_segment passed")

    test_corrupting_the_coeff_segment_breaks_only_that_segment()
    print("test_corrupting_the_coeff_segment_breaks_only_that_segment passed")

    test_corrupting_one_data_segment_breaks_only_that_segment()
    print("test_corrupting_one_data_segment_breaks_only_that_segment passed")

    test_salt_give_up_surfaces_ok_false_instead_of_looping_forever()
    print("test_salt_give_up_surfaces_ok_false_instead_of_looping_forever passed")

    print("All segmented tagging tests passed!")
