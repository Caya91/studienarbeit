from binary_ext_fields.log_utils import clear_logs
from utils.log_helpers import get_run_log_dir, get_field_subdir, save_generation_txt, print_generation, to_int_matrx

from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator as OTC_custom

from binary_ext_fields.custom_field import TableField, create_field
from binary_ext_fields.generate_symbols import generate_symbols_random, check_orth


from utils.plot_utils import plot_acceptance_rates_comparison, get_playground_dir

from typing import Any

from icecream import ic

# TODO:  test rref for all different field sizes
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
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 7]

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

def _find_pivot(Matrix: list[list[int]], column= 0, gen_size = None )-> tuple[int,int, int]:
    """
    Use in for loop, while incrementing :column
    
    :param Matrix: generation
    :type Matrix: list[list[int]]
    :param column: index of the column
    :param gen_size: how many packets are in the generation
    
    :return: Description
    :rtype: tuple[int, int, int]
    """

    if gen_size == None:
        gen_size = len(Matrix)

    if column >= gen_size:
        return -1, -1, -1 
    
    if column >= len(Matrix[0]):   # if we try to access the column a column out of range
        # TODO: add a proper check when and how go over the gen size of a generation
        return -1, -1, -1 

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


def subtract_pivot_from_packet( pivot_tuples: list[tuple], Matrix: list[list[int]], packet:bytearray, field:TableField)-> list[list[int]]:
    '''
    this function takes the generated list of pivot elements and subtracts a new incoming packet, to see if it can be added to the partial rref
    '''

    # pivto tuples: list of : (pivot_row: int, pivot_column:int, pivot_value: int)
    for i, tpl in enumerate(pivot_tuples):
        pivot_row, pivot_column, pivot_value = tpl
        ic(pivot_row, pivot_column, pivot_value , tpl)

        if pivot_row == -1: continue # if the was no pivot element found, just return the Matrix as is


        pivot_full_row = Matrix[pivot_row].copy()

        if pivot_row != pivot_column:
            # swapping the elements so pivot element is at the position [pivot_column, pivot_column]
            Matrix[pivot_column], Matrix[pivot_row] =  Matrix[pivot_row], Matrix[pivot_column] 
        

        target = packet[pivot_column]

        if target != 0:
            scalar = field.get_mul_to_target(pivot_value, target)
            packet = field.vector_multiply_add_into(packet, pivot_full_row, scalar)


    return packet


def invert_pivot_rows(cleaned_matrix:list[list[int]], field: TableField, gen_size:int):
    ''' its assumed that the matrix is of full rank until the row: Matrix[generation size]
    THis will MUTATE the original matrix, if that results in Problem, that can be changed
    '''
    
    final_rref = []
    for i, row in enumerate(cleaned_matrix):
        if i >= gen_size: 
            final_rref.append(row.copy())
            continue
             # when the pivot rows are handled we can break the loop

        pivot_element = row[i]
        assert pivot_element != 0  # if pivot element == 0   this should break
        if pivot_element != 1:
            inverse = field.get_mul_inverse(pivot_element)
            new_row = row.copy()
            field.vector_multiply_into(new_row, inverse)
            final_rref.append(new_row)
        else:
            new_row = row.copy()
            final_rref.append(new_row)           

    if len(final_rref) == 0: # falls keien reihe invertiert wird, ist die liste leer, dann returnen wir das Original
        return cleaned_matrix.copy()

    #TODO: add a warning or error when incoming and outgoing dont ahve the same length

    return final_rref


def _cleanup_rref(partial_rref: list[list[int]], column: int, field:TableField) -> list[list[int]]:
    '''clean the partial rref from the bottom up
    SHOULDNT MUTATE ORIGINAL
    '''
    #ic(column)
    #ic(partial_rref)
    cleanup_row = partial_rref[column].copy() # take row corresponding to the column
    pivot_element = cleanup_row[column] # save base element
    rref_copy = partial_rref.copy()

    if pivot_element == 0: # if the element is zero, there is no we just skip this function call and return the original 
        return partial_rref

    for i, row in enumerate(rref_copy):
        if row[column] == 0 or i == column: continue  # skip the self row and if the element is already 0

        #ic(field)
        #ic(pivot_element,row[column], cleanup_row)
        scalar = field.get_mul_to_target(pivot_element,row[column])
        #ic(row,cleanup_row,scalar)
        new_row = field.vector_multiply_add_into(row,cleanup_row,scalar)
        rref_copy[i] = new_row

    #ic(rref_copy)
    return rref_copy


def _partial_rref(Matrix:list[list[int]], field:TableField) -> list[list[int]]:
    pivot_tuple = _find_pivot(Matrix)
    partial_rref = _subtract_pivot_from_matrix(*pivot_tuple,Matrix,field)

    for i in range(1,len(Matrix)): # skip first element of the loop
        pivot_tuple = _find_pivot(partial_rref,i)
        partial_rref = _subtract_pivot_from_matrix(*pivot_tuple, partial_rref, field)

    return partial_rref


def matrix_full_rank(Matrix:list[list[int]], gen_size:int):
    ''' return True if enough packets arrived and Matrix is of full rank
    -> then we can start sending out packets
    '''
    if len(Matrix) < gen_size: return False # Generation is not full rank, if we havent received eough packets y


    for i, row in enumerate(Matrix):
        ic(i,row)
        if i >= gen_size: return True # when we reach a the packet nr that is higher than gen_size, matrix has full rank  
        if row[i] !=0: continue # as long as the pivot elements are non-zero   The Matrix could be of full rank
        return False # when we reach this point Matrix is not of full rank: 1.an element row[i] == 0 and it was not a packet later than gen_size (packets) 



def stepwise_partial_rref(Matrix:list[bytearray], packet:bytearray, field:TableField) -> list[list[int]]:
    '''
    this should be use by Nodes whenever they receive a new packet, after there is already a partial rref present
    '''
    # TODO: add a check if matrix or gen size is the smaller/larger value here and decide on that if we add it to the rref

    pivot_tuples = []
    for i in range(len(Matrix)):    #Somehow the gensize has to come here with the heck, so we dont take too many pivot elements 
        pivot_tuple = _find_pivot(Matrix, i)
        pivot_tuples.append(pivot_tuple)
    
    packet = subtract_pivot_from_packet(pivot_tuples,Matrix, packet, field)

    if packet.count(0) != 0:
        return packet

    return None


def calculate_rref(Matrix:list[list[int]], field:TableField, gen_size:int) -> list[list[int]]:
    ''' returns 2 lists, the partial rref AND the cleaned rref '''
    pivot_tuple = _find_pivot(Matrix)
    partial_rref = _subtract_pivot_from_matrix(*pivot_tuple,Matrix,field)
    for i in range(1,gen_size): # skip first element of the loop
        pivot_tuple = _find_pivot(partial_rref,i)
        partial_rref = _subtract_pivot_from_matrix(*pivot_tuple, partial_rref, field)


    #rank check:
    # for i in range(gen_size):
    #     ic(f"RANK CHECK ROW/Column{i} , Gen_size{gen_size}")
    #     assert partial_rref[i][i] != 0 ,   "pivot element is zero: matrix not full rank"
    



    cleaned_rref = full_cleanup_rref(partial_rref, field, gen_size)

    return partial_rref , cleaned_rref


def full_cleanup_rref(partial_rref: list[list[int]], field:TableField, gen_size:int) -> list[list[int]]:
    '''cleans up the whole partial rref, should be used as soon as the partial rref has full rank
    uses _cleanup_rref()
    '''
    #ic(len(partial_rref) -1, partial_rref)

    #rank check again .... just to be sure # TODO: maybe make a function for this check
    #for i in range(gen_size):
    #    assert partial_rref[i][i] != 0 ,   "pivot element is zero: matrix not full rank"

    if len(partial_rref) < gen_size:
        gen_size = len(partial_rref)

    ic("cleanup aufruf:", partial_rref, gen_size -1 )
    cleanup_rref = _cleanup_rref(partial_rref,gen_size -1, field)
    ic(gen_size -1)
    #ic(partial_rref)

    # here cleanup for the first rows
    for i in range(gen_size -1 , -1, -1):  # starting from last packet until packet [0]
        ic(i)
        cleanup_rref = _cleanup_rref(cleanup_rref, i, field)
        ic(cleanup_rref)
    
    return cleanup_rref





if __name__ == "__main__":
    print("rref")
    
    field = create_field(3)
    gen_size = 10
    rref, stuff = calculate_rref(matrix_B,field , gen_size)

    rref_int = to_int_matrx(rref)
    print_generation(rref_int)
    

    rref_1, stuff1 = calculate_rref(matrix_C, field, gen_size)
    rref_1_int = to_int_matrx(stuff1)
    print("RREF 1")
    print_generation(rref_1_int)

    rref_2, stuff2 = calculate_rref(matrix_D, field, gen_size)
    rref_2_int = to_int_matrx(stuff2)
    inverted_rref2 = invert_pivot_rows(rref_2_int,field, gen_size)
    print("RREF 2")
    print_generation(rref_2_int)
    print("RREF 2 Inverted")    
    print_generation(inverted_rref2)

    
    filler, rref_faulty = calculate_rref(matrix_bitflip, field, gen_size)
    rref_faulty_int = to_int_matrx(rref_faulty)
    inverted_faulty = invert_pivot_rows(rref_faulty_int,field, gen_size)
    print("RREF 3")
    print_generation(rref_faulty_int)
    print("RREF 3 Inverted")    
    print_generation(inverted_faulty)