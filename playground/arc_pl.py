"""
k packets are necessary for decoing the matrix

UPDATE: we will use a matrix of however many packets -> will make the rref and the first rows
until full rank, then will cleanup the remaining packets to zero.

the zero rows should be 0 in the data, otherwise: potential error search location

the potential error column and the hmac tag together will give error locations

ideas:

first start with identity matrix I + 1 packet
leave out the last packet 
-> calculate rref 
-> use coefficients from last packet
-> guess the symbol

How to note where and potential error columns are
and how to use that for repairing?

plan: make 2 functions, 1  where i take a deterministic packet out
and 1 where i take random packets out and check them



"""

from binary_ext_fields.custom_field import TableField, create_field
from binary_ext_fields.generate_symbols import generate_symbols_until_nonzero, recode, recode_rlnc, recode_rlnc_without_coeffs
from binary_ext_fields.rref import *

from utils.log_helpers import make_ic_logger


from icecream import ic
import random

start_matrix =[
    [1,0,0],
    [0,1,0],
    [0,0,1],
    [1,1,1]
]

long_matrix =[
    [1,0,0],
    [0,1,0],
    [0,0,1],
    [1,1,1],
    [2,2,2],
    [3,3,3]
]



if __name__ == "__main__":

    print("arc_check")

    field_int = 3
    data_fields = 2
    gen_size= 3


    field = create_field(field_int)

    dir = get_playground_dir("simple_arc_check.txt")
    ic.configureOutput(outputFunction = make_ic_logger(dir))

    generation = generate_symbols_until_nonzero(field,data_fields, gen_size, coefficients=True )
    ic(generation)


    recoded_packets = recode_rlnc_without_coeffs(field, generation, gen_size, count=7)
    ic(recoded_packets)

    partial_rref, cleaned_rref = calculate_rref(recoded_packets, field, gen_size)
    ic(partial_rref, cleaned_rref)
    
    inverted_rref = invert_pivot_rows(cleaned_rref, field, gen_size)
    ic(inverted_rref)




    dir = get_playground_dir("second_arc_check.txt")
    ic.configureOutput(outputFunction = make_ic_logger(dir))

    generation = generate_symbols_until_nonzero(field,data_fields, gen_size, coefficients=True )
    ic(generation)


    recoded_packets = recode_rlnc_without_coeffs(field, generation, gen_size, count=7)
    ic(recoded_packets)

    partial_rref, cleaned_rref = calculate_rref(recoded_packets, field, gen_size)
    ic(partial_rref, cleaned_rref)
    
    inverted_rref = invert_pivot_rows(cleaned_rref, field, gen_size)
    ic(inverted_rref)
    ic("compare original generation with inverted rref", generation, inverted_rref)

