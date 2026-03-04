from binary_ext_fields.log_utils import clear_logs
from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator as OTC_custom

from binary_ext_fields.custom_field import TableField, build_tables_gf2m, PRIMES_GF2M
from binary_ext_fields.generate_symbols import generate_symbols_random, check_orth


from utils.plot_utils import plot_acceptance_rates_comparison, get_playground_dir

from typing import Any

from icecream import ic

# TODO:  test rref for all different field sizes


def _find_pivot(Matrix: list[list[int]], column= 0 )-> tuple[int,int, int]:

    for i, row in enumerate(Matrix):
        if i < column: continue
        if row[column] > 0:
            return i, column , row[column]
        
    return -1, -1, -1


def _subtract_pivot_from_matrix(pivot_row: int, pivot_column:int, pivot_value: int, Matrix: list[list[int]], field:TableField)-> list[list[int]]:
    if pivot_row == -1: # if the was no pivot element found, just return the Matrix as is
        # TODO: decide if there should be an error or warning, or what to do when this happens
        # usually should mean, that matrix wasnt of full rank -> linear dependant
        return Matrix
    
    Matrix_copy = Matrix.copy()

    pivot_full_row = Matrix_copy[pivot_row].copy()


    if pivot_row != pivot_column:
        # swapping the elements so pivot element is at the position [pivot_column, pivot_column]
        Matrix_copy[pivot_column], Matrix_copy[pivot_row] =  Matrix_copy[pivot_row], Matrix_copy[pivot_column] 
    
    # TODO: check if i should add the pivot row to rows that have a zero element, 
    # or should i put zero element rows down for later use?

    for i, row in enumerate(Matrix_copy):
        if i <= pivot_row: continue

        target = row[pivot_column]
        new_row = []
        
        if target != 0:
            scalar = field.get_mul_to_target(pivot_value, target)
            new_row = field.vector_multiply_add_into(row, pivot_full_row, scalar)
            Matrix_copy[i] = new_row

    return Matrix_copy


def invert_pivot_rows(cleaned_matrix:list[list[int]], field: TableField):
    
    final_rref = []
    for i, row in enumerate(cleaned_matrix):
        pivot_element = row[i]
        assert pivot_element != 0  # if pivot element == 0   this should break
        if pivot_element != 1:
            inverse = field.get_mul_inverse(pivot_element)
            new_row = row.copy()
            field.vector_multiply_into(new_row, inverse)
            final_rref.append(new_row)

    return final_rref

# TODO: decide where this function goes,  this should guaruantee, that all matrices are bytearrays, for consistency before working with it
def to_byte_matrix(M):
    '''converts a matrix of ints to a bytearray for consistency'''
    return [bytearray(row) for row in M]

def _cleanup_rref(partial_rref: list[list[int]], column: int, field:TableField) -> list[list[int]]:
    '''clean the partial rref from the bottom up
    SHOULDNT MUTATE ORIGINAL
    '''
    #ic(column)
    cleanup_row = partial_rref[column].copy() # take row corresponding to the column
    pivot_element = cleanup_row[column] # save base element
    rref_copy = partial_rref.copy()

    for i, row in enumerate(rref_copy):
        if row[column] == 0 or i == column: continue  # skip the self row and if the element is already 0

        #ic(field)
        #ic(pivot_element,row[column])
        scalar = field.get_mul_to_target(pivot_element,row[column])
        #ic(row,cleanup_row,scalar)
        new_row = field.vector_multiply_add_into(row,cleanup_row,scalar)
        rref_copy[i] = new_row

    #ic(rref_copy)
    return rref_copy
        


def calculate_rref(Matrix:list[list[int]], field:TableField) -> list[list[int]]:

    pivot_tuple = _find_pivot(Matrix)
    partial_rref = _subtract_pivot_from_matrix(*pivot_tuple,Matrix,field)

    for i in range(1,len(Matrix)): # skip first element of the loop
        pivot_tuple = _find_pivot(partial_rref,i)
        partial_rref = _subtract_pivot_from_matrix(*pivot_tuple, partial_rref, field)


    #rank check:
    for i, row in enumerate(partial_rref):
        assert row[i] != 0 ,   "pivot element is zero: matrix not full rank"
    
    cleaned_rref = full_cleanup_rref(partial_rref, field)

    return partial_rref , cleaned_rref


def full_cleanup_rref(partial_rref: list[list[int]], field:TableField) -> list[list[int]]:
    '''cleans up the whole partial rref
    uses _cleanup_rref()
    '''
    #ic(len(partial_rref) -1, partial_rref)

    #rank check again .... just to be sure
    for i, row in enumerate(partial_rref):
        assert row[i] != 0 ,   "pivot element is zero: matrix not full rank"


    cleanup_rref = _cleanup_rref(partial_rref,len(partial_rref) -1, field)
    #ic(partial_rref)
    for i in range(len(partial_rref) -1 , -1, -1):  # starting from last packet until packet [0]
        #ic(i)
        cleanup_rref = _cleanup_rref(cleanup_rref, i, field)
        #ic(cleanup_rref)
    
    return cleanup_rref




if __name__ == "__main__":

    print("rref")
