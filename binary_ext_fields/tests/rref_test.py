'''
       
Test Idea:

start from rref form for a Matrix

one function recodes in the choosen field
other function recodes with regular algebra

find rref from both matrices -> compare result

use regular rref from some library and test the same Matrix against that library, 

'''


import galois
#from galois import PolyLike
import numpy as np
from binary_ext_fields.custom_field import TableField, PRIMES_GF2M, build_tables_gf2m, create_field
from binary_ext_fields.rref import full_cleanup_rref, to_byte_matrix,calculate_rref, invert_pivot_rows

from utils.log_helpers import get_run_log_dir, get_field_subdir, save_generation_txt, print_generation, to_int_matrx

from icecream import ic
from sympy import Matrix



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


matrix_A = [
    [1, 4, 7, 2, 5, 3, 6, 1, 2, 7],
    [3, 6, 2, 7, 1, 4, 5, 2, 3, 6],
    [5, 1, 4, 3, 6, 2, 7, 3, 4, 1],
    [7, 3, 6, 1, 2, 5, 4, 4, 5, 2],
    [2, 5, 1, 4, 3, 6, 1, 5, 6, 3],
    [4, 7, 3, 6, 7, 1, 2, 6, 7, 4],
    [6, 2, 5, 5, 4, 7, 3, 7, 1, 5],
    [1, 4, 7, 2, 5, 3, 6, 1, 2, 7],
    [3, 6, 2, 7, 1, 4, 5, 2, 3, 6],
    [5, 1, 4, 3, 6, 2, 7, 3, 4, 1],
    ]

matrix_B = [
    [7, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 7, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 7, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 7, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 7, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 7, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 7, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 7, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 7, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7],
]

matrix_partial_one = [
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [0, 0, 1, 1, 1, 1, 1, 1, 1, 1],
    [0, 0, 0, 1, 1, 1, 1, 1, 1, 1],
    [0, 0, 0, 0, 1, 1, 1, 1, 1, 1],
    [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
    [0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
    [0, 0, 0, 0, 0, 0, 0, 1, 1, 1],
    [0, 0, 0, 0, 0, 0, 0, 0, 1, 1],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
]


matrix_partial_two = [
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [0, 2, 1, 1, 1, 1, 1, 1, 1, 1],
    [0, 0, 3, 1, 1, 1, 1, 1, 1, 1],
    [0, 0, 0, 4, 1, 1, 1, 1, 1, 1],
    [0, 0, 0, 0, 5, 1, 1, 1, 1, 1],
    [0, 0, 0, 0, 0, 6, 1, 1, 1, 1],
    [0, 0, 0, 0, 0, 0, 7, 1, 1, 1],
    [0, 0, 0, 0, 0, 0, 0, 2, 1, 1],
    [0, 0, 0, 0, 0, 0, 0, 0, 3, 1],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 4],
]

matrix_C = [
    [7, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 7, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 7, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 7, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 7, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 7, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 7, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 7, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 7, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7]

]


matrix_D = [
    [7, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 7, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 7, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 7, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 7, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 7, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 7, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 7, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 7, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7]

]


matrix_bitflip = [
    [7, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 7, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 1, 7, 1, 1, 1, 1, 1, 1, 1, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 1, 1, 7, 1, 1, 1, 1, 1, 1, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 1, 1, 1, 7, 1, 1, 1, 1, 1, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 1, 1, 1, 1, 7, 1, 1, 1, 1, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 1, 1, 1, 1, 1, 7, 1, 1, 1, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 1, 1, 1, 1, 1, 1, 7, 1, 1, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 1, 1, 1, 1, 1, 1, 1, 7, 1, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7, 1, 0 ,2, 3, 5, 4,2 ,1],
    [1, 1, 1, 1, 1, 1, 1, 1, 2, 7, 1, 0 ,2, 3, 5, 4,2 ,1]

]


def cleanup_test_1():
    
    cleaned_rref = full_cleanup_rref(matrix_partial_one)
    print_generation(cleaned_rref)

    cleaned_rref = full_cleanup_rref(matrix_partial_two)
    print_generation(cleaned_rref)
    ic(cleaned_rref)
    return True


def assertion_fail_test(Matrix):
    field_int = 3
    prime = PRIMES_GF2M.get(field_int)
    add_table, mul_table = build_tables_gf2m(field_int, prime)
    
    #using global variable for now
    rref_field = TableField(add_table,mul_table,prime)

    gen_size = len(Matrix) 
    matrix_A = to_byte_matrix(Matrix)      # TODO: how to check and throw error when a matrix isnt full rank?

    print("Test should fail with assertion error after this statement")

    try:
        calculate_rref(matrix_A, rref_field, gen_size)
    except AssertionError as e:
        # assertion was triggered as expected
        assert "pivot" in str(e) or "rank" in str(e)
        return True # Test passed
    else:
        # if we get here, the assertion did NOT trigger, which is a test failure
        raise AssertionError("Expected AssertionError for rank-deficient matrix")
    return False

def full_rref_test(Matrix: list[list[int]]):
    
    field_int = 3
    prime = PRIMES_GF2M.get(field_int)
    add_table, mul_table = build_tables_gf2m(field_int, prime)
    
    #using global variable for now
    rref_field = TableField(add_table,mul_table,prime)

    matrix_B = to_byte_matrix(Matrix)
    # TODO: tests müssen wahrscheinlich hier nochmal angepasst werden
    rref_2, cleaned_rref_2 = calculate_rref(matrix_B, rref_field, len(matrix_B))
    final_rref = invert_pivot_rows(cleaned_rref_2, rref_field, len(matrix_B))
    ic(rref_2, cleaned_rref_2, final_rref)
    
    return True



def reference_rref_test():
    M = Matrix([[1, 2], [3, 4]])

    return M.rref()  # Returns (rref_matrix, pivot_columns)


def galois_stuff():
    '''dont know if this test will be relevant any, check again later'''
    
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


def test_different_matrices(field:TableField):

    field = create_field(3)
    gen_size = 10
    rref, stuff = calculate_rref(matrix_B,field , gen_size)

    rref_int = to_int_matrx(rref)
    print_generation(rref_int)
    

    rref_1, stuff1 = calculate_rref(matrix_C, field, gen_size)
    rref_1_int = to_int_matrx(stuff1)
    print_generation(rref_1_int)

    rref_2, stuff2 = calculate_rref(matrix_D, field, gen_size)
    rref_2_int = to_int_matrx(stuff2)
    inverted_rref2 = invert_pivot_rows(rref_2_int,field, gen_size)
    print_generation(rref_2_int)
    print_generation(inverted_rref2)

    
    filler, rref_faulty = calculate_rref(matrix_bitflip, field, gen_size)
    rref_faulty_int = to_int_matrx(rref_faulty)
    inverted_faulty = invert_pivot_rows(rref_faulty_int,field, gen_size)
    print_generation(rref_faulty_int)
    print_generation(inverted_faulty)

    return True

if __name__ == "__main__":

    test_1 = assertion_fail_test(matrix_A)

    test_2 = full_rref_test(matrix_B)

    field = create_field(3)
    test_4 = test_different_matrices(field)

    ic(test_1, test_2, test_4)




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