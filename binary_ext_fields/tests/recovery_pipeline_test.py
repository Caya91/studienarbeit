"""
End-to-end checks for the sniffing -> ARC -> linear solve recovery pipeline
(ADR-0001..0004, CONTEXT.md glossary "Combined recovery": deferred until this
single-packet base case works).
"""
from icecream import ic
from binary_ext_fields.custom_field import create_field
from binary_ext_fields.generate_symbols import check_orth, check_orth_packet, recode_rlnc_without_coeffs, generate_symbols_until_nonzero
from playground.arc_pl import error_into_packet_chosen_bit
from playground.new_recovery import recover_generation, recover_packet_linear


def _build_pool(field, gen_size, data_fields, count):
    generation = generate_symbols_until_nonzero(field, data_fields, gen_size)
    return recode_rlnc_without_coeffs(field, generation, gen_size, count=count)


def test_single_packet_recovery():
    '''Enough trusted packets available: recover_generation must fully repair the pool.'''
    field = create_field(8)
    gen_size = 3
    data_fields = 3

    pool = _build_pool(field, gen_size, data_fields, count=12)
    assert check_orth(field, pool), "pool must be clean/orthogonal before corruption"

    broken_row = 0
    error_column = gen_size  # first data column, past the coefficient block
    pool[broken_row] = error_into_packet_chosen_bit(pool[broken_row], error_column, chosen_bit=0)

    tmp, status = recover_generation(field, pool, gen_size)

    assert status == "recovered", f"expected recovered, got {status}"
    assert check_orth(field, tmp)
    for pkt in tmp:
        assert check_orth_packet(field, pkt)


def test_too_few_trusted_packets_waits():
    '''Pool below min_pool_size: recovery must defer (ADR-0003), not guess.'''
    field = create_field(8)
    gen_size = 3
    data_fields = 3

    pool = _build_pool(field, gen_size, data_fields, count=5)  # < default min_pool_size (10)

    tmp, status = recover_generation(field, pool, gen_size)

    assert status == "waiting"
    assert tmp == pool


def test_wrong_candidate_column_is_not_silently_accepted():
    '''
    A wrong single candidate column is always "solvable" (1 unknown, 1+ equations
    -- ADR-0001's same false-positive mechanism as self-tag-only checking), so
    recover_packet_linear alone is not proof of correctness. The orchestrator's
    acceptance-oracle step (check_orth against the trusted set) must be the
    thing that actually rejects it.
    '''
    field = create_field(8)
    gen_size = 3
    data_fields = 3

    pool = _build_pool(field, gen_size, data_fields, count=12)

    true_error_column = gen_size
    wrong_column = gen_size + 1
    broken_packet = error_into_packet_chosen_bit(pool[0], true_error_column, chosen_bit=0)
    trusted_packets = pool[1:]

    fixed_with_wrong_column = recover_packet_linear(field, broken_packet, {wrong_column}, trusted_packets)

    assert fixed_with_wrong_column is not None, "a single unknown column is always solvable"
    assert not check_orth(field, trusted_packets + [fixed_with_wrong_column]), (
        "a wrong candidate column must fail the full acceptance oracle"
    )


if __name__ == "__main__":
    test_single_packet_recovery()
    print("test_single_packet_recovery passed")

    test_too_few_trusted_packets_waits()
    print("test_too_few_trusted_packets_waits passed")

    test_wrong_candidate_column_is_not_silently_accepted()
    print("test_wrong_candidate_column_is_not_silently_accepted passed")

    print("All recovery pipeline tests passed!")
