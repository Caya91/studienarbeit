from icecream import ic
from collections.abc import Callable
from utils.log_helpers import log_packet
from random import choice

from binary_ext_fields.custom_field import TableField, create_field

from binary_ext_fields.generate_symbols import inner_product_bytes, check_orth, check_orth_packet
from binary_ext_fields.generate_symbols import generate_symbols_until_nonzero, recode_rlnc_without_coeffs
from binary_ext_fields.rref import calculate_rref, invert_pivot_rows
from binary_ext_fields.bitops import bit_flip_candidates
from utils.log_helpers import make_ic_logger, print_generation, print_packet
from playground.arc_pl import error_into_generation, error_into_packet, error_into_packet_chosen_bit
from playground.arc_pl import localize_errors
from playground.sniffing import sniff_pool
from itertools import combinations


def recover_packet_combined(field, p1:bytearray, p2:bytearray, recovery_columns: list[int]):
    # TODO: implement combined recovery from the base case of the single recovered packet
    # we take 2 packets -> XOR them, then recover this combined packet
    # then when that worked -> recover the old packets by xoring them to their original versions
    # the 2 recovery columns have to be different i think ...

    pass


def build_recovery_system(field: TableField, broken_packet: bytearray, candidate_columns: list[int], trusted_packets: list[bytearray]) -> list[list[int]]:
    '''
    Builds the augmented (M x K+1) matrix for the ADR-0002 linear solve.

    One row per trusted packet p_j: A[j][k] = p_j[candidate_columns[k]] (the
    linear coefficient of the unknown x_k in mul(p_j[c], x_c)), and the
    appended RHS b_j = inner_product(p_j, broken_packet-with-candidates-zeroed)
    -- the known-column contribution that the unknowns must sum to for
    orthogonality to hold (char-2 field, so no sign flip moving terms across =).
    '''
    zeroed = bytearray(broken_packet)
    for c in candidate_columns:
        zeroed[c] = 0

    matrix = []
    for p in trusted_packets:
        row = [p[c] for c in candidate_columns]
        b = inner_product_bytes(field, p, zeroed)
        row.append(b)
        matrix.append(row)

    return matrix


def solve_recovery_system(field: TableField, matrix: list[list[int]], K: int) -> list[int] | None:
    '''
    Runs calculate_rref + invert_pivot_rows (both from rref.py, unmodified)
    restricted to the K unknown columns of the augmented matrix.

    Returns the solved byte value per candidate column (in the same order as
    the columns of `matrix`), or None if the system is underdetermined --
    fewer independent trusted rows than K (ADR-0003: this is the signal to
    wait for more trusted packets, or fall back to bit-flip search).
    '''
    if len(matrix) < K:
        return None

    try:
        _, cleaned_rref = calculate_rref(matrix, field, K)
        solved_rref = invert_pivot_rows(cleaned_rref, field, K)
    except ValueError:
        # a zero pivot means the available trusted rows don't span the
        # K candidate columns yet -- underdetermined, not an error
        return None

    for i in range(K):
        if solved_rref[i][i] != 1:
            return None

    return [solved_rref[i][K] for i in range(K)]


def recover_packet_linear(field: TableField, broken_packet: bytearray, candidate_columns: set[int], trusted_packets: list[bytearray]) -> bytearray | None:
    '''
    ADR-0002: solve for the broken packet's true byte values at the ARC
    candidate columns via a linear system over trusted packets' cross-tags,
    instead of brute-force bit-flipping.

    Returns a repaired copy of broken_packet, or None if underdetermined
    (caller must still verify the result against the full acceptance oracle
    per ADR-0001 before accepting it -- this only proves internal consistency
    of the chosen candidate column set, not that it's the right one).
    '''
    columns = list(candidate_columns)
    K = len(columns)

    if K == 0:
        return bytearray(broken_packet)

    matrix = build_recovery_system(field, broken_packet, columns, trusted_packets)
    solved = solve_recovery_system(field, matrix, K)

    if solved is None:
        return None

    fixed = bytearray(broken_packet)
    for c, value in zip(columns, solved):
        fixed[c] = value

    return fixed


def is_orthogonal_to_trusted(field: TableField, candidate: bytearray, trusted_packets: list[bytearray]) -> bool:
    '''The bit-flip acceptance oracle (ADR-0007, "check with other packets").

    A repaired candidate is accepted iff it is self-orthogonal AND orthogonal to
    every trusted packet. This is the targeted, per-candidate cost -- exactly
    M+1 inner products -- rather than the full O(M^2) check_orth, so a
    CountingField measures only the work attributable to recovery.

    Orthogonality to a trusted set is necessary but not sufficient: with fewer
    than gen_size independent trusted packets a wrong repair can still pass,
    which is exactly the silent-failure regime the simulation measures.
    '''
    if not check_orth_packet(field, candidate):
        return False
    for t in trusted_packets:
        if inner_product_bytes(field, candidate, t) != 0:
            return False
    return True


def recover_packet_bitflip(field: TableField, packet: bytearray, recovery_column: int, hamming_distance: int, oracle: Callable[[bytearray], bool] | None = None):
    '''Flip up to `hamming_distance` bits within a single byte-column and accept
    the first flipped candidate that satisfies `oracle`.

    oracle: callable(candidate) -> bool. Defaults to self-orthogonality
    (check_orth_packet), preserving the original single-packet behavior. The
    cross-check recoverer (ADR-0007) passes an oracle that also tests
    orthogonality against the trusted set (is_orthogonal_to_trusted).

    Return: (candidate, True) on first accepted flip, else (original_packet, False).
    '''
    if oracle is None:
        oracle = lambda cand: check_orth_packet(field, cand)

    for flipped, mask, dist in bit_flip_candidates(packet[recovery_column], hamming_distance, field.bit_lenght):
        tmp = bytearray(packet)
        tmp[recovery_column] = flipped
        if oracle(tmp):
            return tmp, True

    return packet, False
    

def recover_generation(field: TableField, packet_pool: list[bytearray], min_trusted_packets: int, min_trust_count: int = 4, min_pool_size: int = 10, hamming_fallback: int = 1):
    #TODO: rename gen_size to something that makes more sense, min trust packages
    '''
    Orchestrates the single-packet recovery pipeline: sniffing -> ARC -> linear solve
    (CONTEXT.md glossary), replacing the old bit-flip-only orchestration.

    Returns (repaired_pool, status), where status is one of:
    - "waiting": not enough trusted packets yet for even an ARC basis (ADR-0003, no timeout -- caller retries later)
    - "recovered": every broken packet was fixed and verified
    - "partial": some broken packets could not be fixed (left as-is in repaired_pool)
    '''
    broken_idx, trusted_idx = sniff_pool(field, packet_pool, min_trust_count, min_pool_size)

    ic(broken_idx, trusted_idx)
    if len(trusted_idx) < min_trusted_packets:
        return packet_pool, "waiting"

    tmp = [bytearray(p) for p in packet_pool]
    trusted_basis = [tmp[i] for i in trusted_idx[0:min_trusted_packets]]
    trusted_packets = [tmp[i] for i in trusted_idx]

    unrecovered = []
    for row in broken_idx:
        broken_packet = tmp[row]
        candidate_columns = localize_errors(field, trusted_basis, broken_packet, min_trusted_packets)

        fixed = recover_packet_linear(field, broken_packet, candidate_columns, trusted_packets)

        if fixed is None:
            # ADR-0003 fallback: linear system underdetermined, try bit-flip search
            for column in candidate_columns:
                candidate, success = recover_packet_bitflip(field, broken_packet, column, hamming_fallback)
                if success:
                    fixed = candidate
                    break

        if fixed is None:
            unrecovered.append(row)
            continue

        # ADR-0001 acceptance oracle: full-generation orthogonality, not self-tag alone
        if check_orth(field, trusted_packets + [fixed]):
            tmp[row] = fixed
        else:
            unrecovered.append(row)

    # Final ground-truth check on the whole pool, not just per-packet bookkeeping --
    # if sniffing ever misses a broken packet, "recovered" must not be reported anyway
    # (ADR-0001: a silently wrong recovery is worse than none).
    status = "recovered" if (not unrecovered and check_orth(field, tmp)) else "partial"
    return tmp, status


def _flip_candidates_per_column(broken_packet: bytearray, hamming_distance: int, oracle: Callable[[bytearray], bool], field: TableField) -> bytearray | None:
    '''Mode B (ADR-0007): flip up to `hamming_distance` bits within each byte-column
    independently, column by column, and return the first candidate accepted by the
    oracle. Because the oracle is a whole-packet property, a single-column flip only
    passes when that column was the *only* corrupted one -- so this recovers
    single-corrupted-column packets. Columns are tried in index order (coefficient
    block included), so first-match may accept a wrong column before the right one
    (a measurable silent failure).
    '''
    for column in range(len(broken_packet)):
        candidate, success = recover_packet_bitflip(field, broken_packet, column, hamming_distance, oracle)
        if success:
            return candidate
    return None


def _flip_candidates_whole_packet(broken_packet: bytearray, hamming_distance: int, oracle: Callable[[bytearray], bool], field: TableField) -> bytearray | None:
    '''Mode A (ADR-0007): the exhaustive upper bound. Flip up to `hamming_distance`
    bits anywhere across the whole packet (all byte-columns at once) and return the
    first oracle-accepted candidate. Unlike mode B this can repair multi-column
    corruption, as long as the total number of flipped bits is within budget.
    Search size is C(len*bit_lenght, d), so keep `hamming_distance` small.
    '''
    n_bits = field.bit_lenght
    total_bits = len(broken_packet) * n_bits
    for dist in range(1, hamming_distance + 1):
        for positions in combinations(range(total_bits), dist):
            candidate = bytearray(broken_packet)
            for pos in positions:
                candidate[pos // n_bits] ^= (1 << (pos % n_bits))
            if oracle(candidate):
                return candidate
    return None


def recover_generation_bitflip(field: TableField, packet_pool: list[bytearray], min_trusted_packets: int, hamming_distance: int, mode: str = "per_column", min_trust_count: int = 4, min_pool_size: int = 10):
    '''ADR-0007: standalone bit-flip + cross-check recovery, with NO ARC column
    localization. Sniff the pool into broken/trusted, then for each broken packet
    flip bits and accept the first candidate orthogonal to the trusted set.

    mode="per_column" (B, the method under study): flip up to `hamming_distance`
        bits within each byte-column independently. Recovers single-corrupted-column
        packets.
    mode="whole_packet" (A, the exhaustive upper bound): flip up to
        `hamming_distance` bits across the whole packet. Recovers multi-column
        corruption within the bit budget.

    The oracle (is_orthogonal_to_trusted) is both the recovery test and the
    acceptance test -- first-match wins (ADR-0007 3b), so there is no separate
    second acceptance step.

    Returns (repaired_pool, status):
    - "waiting":   fewer than `min_trusted_packets` trusted packets (no basis yet)
    - "recovered": every broken packet was repaired to an oracle-accepted value
    - "partial":   at least one broken packet could not be repaired within budget
    '''
    broken_idx, trusted_idx = sniff_pool(field, packet_pool, min_trust_count, min_pool_size)

    if len(trusted_idx) < min_trusted_packets:
        return packet_pool, "waiting"

    tmp = [bytearray(p) for p in packet_pool]
    trusted_packets = [tmp[i] for i in trusted_idx]

    oracle = lambda cand: is_orthogonal_to_trusted(field, cand, trusted_packets)

    unrecovered = []
    for row in broken_idx:
        broken_packet = tmp[row]
        if mode == "per_column":
            fixed = _flip_candidates_per_column(broken_packet, hamming_distance, oracle, field)
        elif mode == "whole_packet":
            fixed = _flip_candidates_whole_packet(broken_packet, hamming_distance, oracle, field)
        else:
            raise ValueError(f"unknown recovery mode {mode!r} (expected 'per_column' or 'whole_packet')")

        if fixed is None:
            unrecovered.append(row)
        else:
            tmp[row] = fixed

    status = "recovered" if not unrecovered else "partial"
    return tmp, status


def test_full_recovery():
    field = create_field(5)
    generation = generate_symbols_until_nonzero(field, 3 , 3)

    print("generation Before introducing Error")
    print_generation(generation)


def base_recovery_test():

    field = create_field(5)
    generation = generate_symbols_until_nonzero(field, 3 , 3)

    print("generation Before introducing Error")
    print_generation(generation)


    print(check_orth(field, generation))

    error_column = 3
    error_packet = 0

    generation[error_packet] = error_into_packet(generation[error_packet], error_column)

    print("Generation After Introducing Error")
    print_generation(generation)

    print(check_orth(field, generation))

    print("===== Start packet recovery =====")
    print(f"Original polluted Packet: {error_packet} with the Error Column: {error_column}")

    recovered_packet, status= recover_packet_bitflip(field, generation[error_packet], error_column, 2)

    generation[error_packet] = recovered_packet

    print("==== Recovered Generation ==== ")
    print_generation(generation)


# Run the tests
if __name__ == "__main__":
    # Exercises the sniffing -> ARC -> linear solve pipeline end to end:
    # build a clean, pairwise-orthogonal recoded pool, break one packet, recover it.

    field = create_field(8)
    data_fields = 3
    gen_size = 3
    hamming_distance = 1

    generation = generate_symbols_until_nonzero(field, data_fields, gen_size)

    print("===== Generation Before Recoding =====")
    print_generation(generation)

    pool = recode_rlnc_without_coeffs(field, generation, gen_size, count=12)

    print("===== Recoded Pool (should already be pairwise orthogonal) =====")
    print_generation(pool)
    print(check_orth(field, pool))

    broken_row = 0
    error_column = gen_size  # first data column, past the coefficient block
    pool[broken_row] = error_into_packet(pool[broken_row], error_column, hamming_distance)

    print("===== Pool After Introducing Error =====")
    print_generation(pool)
    print(check_orth(field, pool))

    tmp, status = recover_generation(field, pool, gen_size)

    print(f"===== Generation After Recovery (status: {status}) =====")
    print_generation(tmp)

    print(check_orth(field, tmp))

    for pkt in tmp:
        print(check_orth_packet(field, pkt))

    #packet
    '''
    test_verify_tag()
    test_successful_repair()
    test_failed_repair()
    print("All tests finished successfully!")
    '''