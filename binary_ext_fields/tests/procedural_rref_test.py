from binary_ext_fields.custom_field import TableField, PRIMES_GF2M, build_tables_gf2m, create_field
from binary_ext_fields.rref import full_cleanup_rref, calculate_rref,calculate_only_partial_rref, invert_pivot_rows
from binary_ext_fields.rref import subtract_pivot_from_packet, stepwise_partial_rref, matrix_full_rank
from binary_ext_fields.generate_symbols import generate_symbols_random, generate_symbols_until_nonzero


from utils.log_helpers import get_run_log_dir, get_field_subdir, save_generation_txt, print_generation, to_int_matrx, to_byte_matrix

from icecream import ic
from sympy import Matrix

from sample_matrices import *

import copy


def add_packet_to_rref_simple(Matrix: list[list[int]]):
    
    field_int = 3
    field = create_field(field_int)
    next_partial = stepwise_partial_rref(matrix_partial_not_full_rank, bytearray([1, 1, 1, 1, 1, 1, 1, 1, 7, 1]), field)

    ic(next_partial)
    
    return True


def add_multiple_packets_procedural(Matrix: list[list[int]]):
        #full_rref_test(matrix_B_lower_rank)
    field_int = 3
    field = create_field(field_int)
    next_partial = stepwise_partial_rref(Matrix, bytearray([1, 1, 1, 1, 1, 1, 1, 1, 7, 1]), field)

    Matrix.append(next_partial)

    ic(Matrix)

    next_partial = stepwise_partial_rref(Matrix, bytearray([1, 1, 1, 1, 1, 1, 1, 1, 7, 7]), field)

    ic(next_partial)
    Matrix.append(next_partial)
    ic(Matrix)


    next_partial = stepwise_partial_rref(Matrix, bytearray([1, 1, 1, 1, 1, 1, 1, 1, 7, 7]), field)

    ic(Matrix)

def add_multiple_packets_procedural_bytearray_matrix(Matrix: list[list[int]]):
        #full_rref_test(matrix_B_lower_rank)
    field_int = 3
    field = create_field(field_int)

    byte_matrix = to_byte_matrix(Matrix)
    next_partial = stepwise_partial_rref(byte_matrix, bytearray([1, 1, 1, 1, 1, 1, 1, 1, 7, 1]), field)

    byte_matrix.append(next_partial)

    ic(byte_matrix)

    next_partial = stepwise_partial_rref(byte_matrix, bytearray([1, 1, 1, 1, 1, 1, 1, 1, 7, 7]), field)

    ic(next_partial)
    byte_matrix.append(next_partial)
    ic(byte_matrix)


    next_partial = stepwise_partial_rref(byte_matrix, bytearray([1, 1, 1, 1, 1, 1, 1, 1, 7, 7]), field)

    ic(byte_matrix)


def add_multiple_packets_matrix_shorter_than_gen_size(Matrix: list[list[int]]):

    field_int = 3
    field = create_field(field_int)
    gen_size = 10

    byte_matrix = to_byte_matrix(Matrix)
    
    partial_rref, cleaned_rref = calculate_rref(byte_matrix, field, gen_size)
    
    next_partial = stepwise_partial_rref(partial_rref, bytearray([1, 1, 1, 1, 1, 1, 1, 1, 7, 1]), field)

    partial_rref.append(next_partial)
    ic("STEP1", next_partial, partial_rref)

    next_partial = stepwise_partial_rref(partial_rref, bytearray([1, 1, 1, 1, 1, 1, 1, 1, 7, 7]), field)

    partial_rref.append(next_partial)
    ic("STEP2", next_partial, partial_rref)


    next_partial = stepwise_partial_rref(partial_rref, bytearray([1, 1, 1, 1, 1, 1, 1, 1, 7, 7]), field)
    
    partial_rref.append(next_partial)
    ic("STEP3", next_partial, partial_rref)

    cleaned_rref = full_cleanup_rref(partial_rref, field, gen_size)

    ic(cleaned_rref)


def add_multiple_packets_then_test_rank(Matrix: list[list[int]]):

    field_int = 3
    field = create_field(field_int)
    gen_size = 4
    data_fields = 6
    byte_matrix = to_byte_matrix(Matrix)
    
    partial_rref, cleaned_rref = calc(byte_matrix, field, gen_size)
    
    ic("STEP0",  partial_rref)

    next_packets = generate_symbols_random(0, field.max_value , data_fields, gen_size)
    ic(next_packets)
    next_partial = stepwise_partial_rref(partial_rref, next_packets[0], field, gen_size)

    partial_rref.append(next_partial)
    ic("STEP1", next_partial, partial_rref)
    ic(len(partial_rref))

    next_partial = stepwise_partial_rref(partial_rref, next_packets[1], field, gen_size)

    partial_rref.append(next_partial)
    ic("STEP2", next_partial, partial_rref)
    ic(len(partial_rref))


    next_partial = stepwise_partial_rref(partial_rref, next_packets[2], field, gen_size)
    
    partial_rref.append(next_partial)
    ic("STEP3", next_partial, partial_rref, len(partial_rref))
    ic(len(partial_rref))

    if matrix_full_rank(partial_rref, gen_size):
        ic("MATRIX IS FULL RANK, can fully decode now")
        cleaned_rref = full_cleanup_rref(partial_rref, field, gen_size)
        ic(cleaned_rref)


    else:
        ic("MATRIS IS NOT FULL RANK, WAIT WITH DECODE")
        ic(partial_rref)






def all_procedural_tests():
    add_multiple_packets_procedural(copy.deepcopy(matrix_partial_not_full_rank))

    
    add_multiple_packets_procedural_bytearray_matrix(copy.deepcopy(matrix_partial_not_full_rank))

    add_multiple_packets_matrix_shorter_than_gen_size(copy.deepcopy(matrix_B_short))



if __name__ == "__main__":

    #all_procedural_tests()

    #add_multiple_packets_then_test_rank(copy.deepcopy(matrix_B_short))
    add_multiple_packets_then_test_rank(copy.deepcopy(matrix_B_lower_rank))
    