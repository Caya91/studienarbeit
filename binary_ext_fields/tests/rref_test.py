import galois
#from galois import PolyLike
import numpy as np
from binary_ext_fields.custom_field import TableField, PRIMES_GF2M, build_tables_gf2m

from icecream import ic


'''
def galois_rref(packets, field_order: int, data_len: int):
    """Reference RREF using galois lib."""
    GF = galois.GF(2**field_order)
    
    # Extract full matrix (data + tags as field elems)
    n = gen_size
    matrix = np.array([[field_int_from_bytes(...) for ...]])  # Shape: n x total_len
    GF_matrix = GF(matrix)
    
    # RREF on full augmented matrix
    rref_GF = GF_matrix.row_reduce()
    
    # Convert back to packets
    rref_packets = [...]
    return rref_packets

'''

if __name__ == "__main__":

    m = 4
    prime = PRIMES_GF2M.get(m)
    ic(prime)
    GF = galois.GF(2**4, irreducible_poly = prime)
    ic(GF)

        # Tiny 2x3 example matrix over your GF(16)
    A = GF([
        [1, 2, 5],
        [3, 0, 7]
    ])  # 2 rows, 3 cols (augmented style)
    ic("Original:\n", A)

    rref_A, pivots = A.row_reduce()  # Returns (rref_matrix, pivot_cols)!
    ic("RREF:\n", rref_A)
    ic("Pivots:", pivots)  # [0,1] → full rank
    ic("Rank:", len(pivots))  # 2 (number of pivots)

    A = GF([
    [1, 2, 5, 9, 11],
    [3, 0, 7, 12, 1],
    [2, 4, 3, 8, 13]
    ])

    ic("Original (3x5):\n", A)

    # Row reduce on FIRST ncols=2 cols (returns single matrix!)
    rref_A = A.row_reduce(ncols=2)
    ic("RREF (ncols=2):\n", rref_A)

    # Manual rank: count non-zero rows in left block
    left_block = rref_A[:, :2]
    rank = np.count_nonzero(np.any(left_block != 0, axis=1))
    ic("Rank:", rank)  # 2
    ic("Pivots:", np.argmax(left_block != 0, axis=1))  # Rough pivot cols

        # Row reduce on FIRST ncols=3 cols (returns single matrix!)
    rref_A = A.row_reduce(ncols=3)
    ic("RREF (ncols=3):\n", rref_A)

    # Manual rank: count non-zero rows in left block
    left_block = rref_A[:, :2]
    rank = np.count_nonzero(np.any(left_block != 0, axis=1))
    ic("Rank:", rank)  # 2
    ic("Pivots:", np.argmax(left_block != 0, axis=1))  # Rough pivot cols

    '''

        # Convert binary int to galois poly format (coefficients list, MSB first)
        coeffs = [(prime >> i) & 1 for i in range(m, -1, -1)]  # [1,0,0,0,1,1,0,1,1]
        field =  galois.GF(2**m, irreducible_poly=coeffs)

        ic(field)
    '''

    '''
    # Compare
    my_rref = packets_to_rref(packets, field, n)
    ref_rref = galois_rref(packets, m=8, gen_size=n, data_len=...)
    assert np.array_equal(my_rref_tags, ref_rref_tags)  # Tags match!
    '''