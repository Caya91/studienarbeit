import random
from enum import Enum

from icecream import ic
from collections.abc import Callable
from binary_ext_fields.custom_field import (TableField, create_field)
from binary_ext_fields.generate_symbols import generate_symbols_until_nonzero
from utils.log_helpers import print_generation

class Pollution(Enum):
    ALL = 0
    DATA = 1
    TAG = 2
    SMART = 3

# TODO: min_int is usually 0, so could be left out of all operations
# TODO: max_int could be derived from used field, 
# TODO: implement coefficient pollution

def pollute_full_packet(packet:bytearray, min_int:int, max_int:int) -> bytearray:
    length = len(packet)
    # nicht das Original verändern
    poll_pack = bytearray(random.randint(min_int, max_int) for _ in range(length))
    return poll_pack


def pollute_data_packet(data_length:int, packet:bytearray ,min_int:int, max_int:int) -> bytearray:
    # soll nicht das Original verändern!
    # wichtig: hier eine Kopie machen, da sonst auch das Original geändert wird
    poll_pack = packet.copy()

    # bytearray expects an Integer from 0- 255 as an assignment
    poll_pack[0] = 5   # this is placeholder just to test if it works
    for i,e in enumerate(packet):
            if i >= data_length:
                continue
            poll_pack[i] = random.randint(min_int, max_int)

    return poll_pack


def pollute_tags_packet(data_length:int, packet:bytearray, min_int:int, max_int:int) -> bytearray:
    poll_pack = packet.copy()
    for i,e in enumerate(packet):
        if i < data_length:
            continue
        poll_pack[i] = random.randint(min_int, max_int)
    #ic(poll_pack, packet)
    return poll_pack


# ── Intelligent (detection-evading) pollution — targeted forgery (ADR-0008) ──
# A white-box on-path relay forges a packet that passes the current acceptance
# oracle (self-check + `threshold` cross-agreements, ADR-0004) while carrying
# data inconsistent with its coefficients, so once admitted it poisons the decode.
#
# The whole forgery is one small linear system over GF(2^m) in the gen_size tag
# bytes x_0..x_{g-1}:
#   cross j:  <p, t_j> = 0  ==>  sum_k t_j[tag_k]*x_k = <prefix_p, prefix_{t_j}>
#   self:     <p, p>   = 0  ==>  sum_k x_k = XOR(prefix_p bytes)
# The self equation is linear because in characteristic 2, sum_c p[c]^2 =
# (sum_c p[c])^2, so <p,p>=0 iff the XOR of all bytes is 0. Solving through
# `field.mul`/`field.add` lets a CountingField charge the attacker's work.


def _gf_prefix_dot(field, x: bytearray, y: bytearray, upto: int) -> int:
    """<x, y> over columns [0, upto) only. Charged through field.mul/add."""
    acc = 0
    for i in range(upto):
        acc = field.add(acc, field.mul(x[i], y[i]))
    return acc


def _gf_xor_sum(field, x: bytearray, upto: int) -> int:
    """XOR-fold of columns [0, upto). Uses field.add (= XOR in GF(2^m))."""
    acc = 0
    for i in range(upto):
        acc = field.add(acc, x[i])
    return acc


def _gf_row_reduce(field, rows: list[list[int]]) -> list[tuple[int, list[int]]]:
    """RREF of `rows` over GF(2^m). Returns [(pivot_col, normalized_row), ...].
    Charged through field.mul/add so it counts toward attacker work."""
    M = [list(r) for r in rows]
    n = len(M[0]) if M else 0
    pivots: list[tuple[int, list[int]]] = []
    r = 0
    for c in range(n):
        piv = next((rr for rr in range(r, len(M)) if M[rr][c] != 0), None)
        if piv is None:
            continue
        M[r], M[piv] = M[piv], M[r]
        inv = field.get_mul_inverse(M[r][c])
        M[r] = [field.mul(v, inv) for v in M[r]]
        for rr in range(len(M)):
            if rr != r and M[rr][c] != 0:
                f = M[rr][c]
                M[rr] = [field.add(M[rr][k], field.mul(f, M[r][k])) for k in range(n)]
        pivots.append((c, M[r]))
        r += 1
        if r == len(M):
            break
    return pivots


def _gf_solve(field, A: list[list[int]], b: list[int]) -> list[int] | None:
    """Solve A x = b over GF(2^m); free variables set to 0. Returns x or None if
    inconsistent. Charged through field.mul/add."""
    rows = len(A)
    cols = len(A[0]) if rows else 0
    M = [list(A[r]) + [b[r]] for r in range(rows)]
    pivot_cols: list[int] = []
    r = 0
    for c in range(cols):
        piv = next((rr for rr in range(r, rows) if M[rr][c] != 0), None)
        if piv is None:
            continue
        M[r], M[piv] = M[piv], M[r]
        inv = field.get_mul_inverse(M[r][c])
        M[r] = [field.mul(v, inv) for v in M[r]]
        for rr in range(rows):
            if rr != r and M[rr][c] != 0:
                f = M[rr][c]
                M[rr] = [field.add(M[rr][k], field.mul(f, M[r][k])) for k in range(cols + 1)]
        pivot_cols.append(c)
        r += 1
        if r == rows:
            break
    # inconsistent: a 0 = nonzero row
    for rr in range(rows):
        if all(M[rr][k] == 0 for k in range(cols)) and M[rr][cols] != 0:
            return None
    x = [0] * cols
    for i, c in enumerate(pivot_cols):
        x[c] = M[i][cols]
    return x


def _independent_coeff_row(field, gen_size: int, avoid_coeff_rows, rng, tries: int = 16):
    """A nonzero coefficient row not in the row-span of `avoid_coeff_rows`, so the
    forged packet becomes an independent pivot in the decode basis (deterministic
    poison). Falls back to a random nonzero row if the avoid set already spans the
    space (e.g. a late strike) -- then the forged packet cannot get a fresh pivot."""
    avoid = [list(r[:gen_size]) for r in (avoid_coeff_rows or [])]
    basis = _gf_row_reduce(field, avoid) if avoid else []
    for _ in range(tries):
        cand = [rng.randint(0, field.max_value) for _ in range(gen_size)]
        if not any(cand):
            continue
        residual = list(cand)
        for pc, prow in basis:
            if residual[pc] != 0:
                f = residual[pc]
                residual = [field.add(residual[k], field.mul(f, prow[k])) for k in range(gen_size)]
        if any(residual):  # not in span -> independent
            return bytearray(cand)
    return bytearray(rng.randint(0, field.max_value) for _ in range(gen_size))


def pollute_intelligent(field, trusted_packets, gen_size, data_length, threshold,
                        avoid_coeff_rows=None, rng=None):
    """Forge a packet that passes the current acceptance oracle (self-check +
    `threshold` cross-agreements) yet carries data inconsistent with its
    coefficients, so admitting it corrupts the decode (ADR-0008).

    White-box: `trusted_packets` are packets the attacker forwarded and knows in
    full; it forges agreement with `threshold` of them. `avoid_coeff_rows` are the
    coefficient blocks the receiver has already accepted -- the forged coefficient
    row is chosen independent of them so the packet pivots into the basis.

    Pass a CountingField as `field` to charge the attacker's forging work.

    Returns (forged_packet, n_constraints). forged_packet is None if the linear
    solve is inconsistent (caller may retry with a fresh prefix). Packet layout is
    [gen_size coefficients | data_length data | gen_size tags].
    """
    rng = rng or random
    assert len(trusted_packets) >= threshold, "need >= threshold seen packets to forge"
    tag_start = gen_size + data_length
    targets = rng.sample(list(trusted_packets), threshold)

    # prefix = independent coefficients + wrong (random) data
    coeff_row = _independent_coeff_row(field, gen_size, avoid_coeff_rows, rng)
    data = bytearray(rng.randint(0, field.max_value) for _ in range(data_length))
    prefix = bytearray(coeff_row) + data

    # linear system A x = b over the gen_size tag unknowns
    A: list[list[int]] = []
    b: list[int] = []
    for t in targets:
        A.append([t[tag_start + k] for k in range(gen_size)])
        b.append(_gf_prefix_dot(field, prefix, t, tag_start))
    A.append([1] * gen_size)                       # self-orthogonality (XOR) row
    b.append(_gf_xor_sum(field, prefix, tag_start))

    n_constraints = threshold + 1
    x = _gf_solve(field, A, b)
    if x is None:
        return None, n_constraints
    return prefix + bytearray(x), n_constraints


def pollute_random(field, packet, bit_error_rate) -> bytearray:
    # Only flip the field.bit_lenght low bits (m for GF(2^m)); flipping higher
    # bits would push a symbol above field.max_value, out of the field. This also
    # keeps pollution in the same bit space the recoverer searches (bit_flip_candidates
    # / whole_packet both use field.bit_lenght).
    polluted_packet = bytearray(packet)

    for i in range(len(polluted_packet)):
        byte = polluted_packet[i]
        for bit_pos in range(field.bit_lenght):
            if random.random() < bit_error_rate:
                byte ^= (1 << bit_pos)
        polluted_packet[i] = byte

    return polluted_packet


def pollute_generation(field, generation, bit_error_rate, polluter: Callable,):
# TODO: make all pollution functions take the same Callable, so using them in for loop will be easy

#TODO: test the bit error Rate, by checking the number of broken bytes, when compared to the original, should be amount of symbols * error_rate

    polluted_generation = []
    for packet in generation:
        polluted_generation.append(polluter(field, packet, bit_error_rate))
        
        #apply pollution

    return polluted_generation


def bit_error_rate_generation(generation1, generation2, bits_per_element = 8):
    assert len(generation1) == len(generation2)
    #TODO:  should we return the whole data, like bit count and other things too?

    byte_count = len(generation1) * len(generation1[0])
    bit_count = byte_count * bits_per_element
    byte_errors = 0
    bit_errors = 0
    for packet1,packet2 in zip(generation1, generation2):        
        for byte1, byte2 in zip(packet1,packet2):
            if byte1 == byte2:
               continue
            else:
                byte_errors += 1
            #ic(format(byte1,'08b' ), format(byte2,'08b'))


            for bit1, bit2 in zip(format(byte1,'08b' ), format(byte2,'08b')):
                #ic(bit1, bit2)
                if bit1 == bit2:
                   continue
                else:
                    bit_errors += 1


    bit_error_rate = bit_errors / bit_count
    byte_error_rate = byte_errors / byte_count

    return bit_errors, byte_errors , bit_error_rate, byte_error_rate

def test_pollution():
    field = create_field(4)
    gen_size = 3
    data_fields = 4 

    generation = generate_symbols_until_nonzero(field, data_fields, gen_size, True)


    bit_error_rate = 0.01

    polluted_generation = pollute_generation(field, generation, bit_error_rate, pollute_random) 

    print_generation(generation)
    print_generation(polluted_generation)









if __name__ == "__main__":
    field = create_field(4)
    gen_size = 3
    data_fields = 4 

    generation = generate_symbols_until_nonzero(field, data_fields, gen_size, True)


    bit_error_rate = 0.01

    polluted_generation = pollute_generation(field, generation, bit_error_rate, pollute_random) 

    print_generation(generation)
    print_generation(polluted_generation)

    


    print("Pollution")
    print(byte_error_rate_generation(generation, polluted_generation))
    print(bit_error_rate_generation(generation, polluted_generation))
