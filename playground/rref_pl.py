'''

algorithm:
for each column from left to right :
    Find pivot: Scan rows below current column for a non-zero entry 
    -> Skip if none.

    Scale pivot row: Divide row by pivot value to make it 1.

    Eliminate column: For every other row, subtract (its entry in pivot column) times pivot row to zero that column.

    Advance: Move to next column or row if pivots exhausted.

pseudo code:
for col in 0 to n-1:

    pivot_row = find_nonzero_row_from(col, col)

    if not pivot: continue

    swap row with pivot_row
    scale row inverse of element
    for each other row i:
        factor = A[i][col]
        row_i -= factor * row_col

        
What do we need?

inverse of an element  -> get_inverse ; check
adding rows to each other -> vector_add_into
finding pivot elements
multiplying a row with inverse of first non-zero element -> creates pivot elements

multiply pivot row with so that the next rwo is the result


Test Idea:

start from rref form for a Matrix

one function recodes in the choosen field
other function recodes with regular algebra

find rref from both matrices -> compare result

use regular rref from some library and test the same Matrix against that library, 

'''

from binary_ext_fields.log_utils import clear_logs
from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator as OTC_custom

from binary_ext_fields.custom_field import TableField, build_tables_gf2m, PRIMES_GF2M
from binary_ext_fields.generate_symbols import generate_symbols_random, check_orth


from utils.log_helpers import get_run_log_dir, get_field_subdir, save_generation_txt, print_generation
from utils.plot_utils import plot_acceptance_rates_comparison, get_playground_dir

import pathlib
from pathlib import Path

import statistics
import random
from typing import Any

from icecream import ic
from sympy import Matrix







def reference_rref_test():
    M = Matrix([[1, 2], [3, 4]])

    return M.rref()  # Returns (rref_matrix, pivot_columns)


if __name__ == "__main__":

    no_rref = [[1, 2], [3, 4]]
    no_rref_2 = [[1, 2, 3],  [1, 3, 4], [2, 2, 0]]
    
    print(no_rref)

    print("rref")

    field_int = 3
    prime = PRIMES_GF2M.get(field_int)
    add_table, mul_table = build_tables_gf2m(field_int, prime)

    # find pivot elements
    pivot_elements = []  # list with tuples (i -> which row, j -> column,  pivot element)
    rows_to_skip = set()

# when a row with pivot element has been found -> exclude that row from search
    for j in range(len(no_rref_2)):
        copy_matrix = 
        #inverse of element -> multiply whole vector
        #


        for i, row in enumerate(no_rref_2):
            if i in rows_to_skip: continue                
            if row[j] == 0: continue

            ic(j,i,row)
            pivot_elements.append((i,j, row[j])) 
            rows_to_skip.add(i)
            break
    ic(no_rref_2)
    ic(pivot_elements)

