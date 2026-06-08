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
import dataclasses
from binary_ext_fields.custom_field import TableField, create_field
from binary_ext_fields.generate_symbols import generate_symbols_until_nonzero, recode, recode_rlnc, recode_rlnc_without_coeffs, code_with_given_coefficients
from binary_ext_fields.rref import *

from utils.log_helpers import make_ic_logger, print_generation, print_packet


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


def test1():
    '''
    generates nonzero tag error packets
    recodes them
    then makes an rref and finds the original symbols
    '''
    print("arc_check")

    field_int = 3
    data_fields = 2
    gen_size= 3


    field = create_field(field_int)

    dir = get_playground_dir("simple_arc_check.txt")
    ic.configureOutput(outputFunction = make_ic_logger(dir))

    generation = generate_symbols_until_nonzero(field,data_fields, gen_size, coefficients=True )
    print("============= Generation ====================")
    print_generation(generation)


    recoded_packets = recode_rlnc_without_coeffs(field, generation, gen_size, count=7)
    print("============= Recoded Packets ====================")
    print_generation(recoded_packets)

    partial_rref, cleaned_rref = calculate_rref(recoded_packets, field, gen_size)
    print("============= Partial RREF ====================")
    print_generation(partial_rref)
    print("============= Cleaned RREF ====================")
    print_generation(cleaned_rref)
    
    inverted_rref = invert_pivot_rows(cleaned_rref, field, gen_size)
    print("============= Inverted RREF ====================")
    print_generation(inverted_rref)




if __name__ == "__main__":

    print("arc_check")

    field_int = 3
    data_fields = 2
    gen_size= 3


    field = create_field(field_int)

    dir = get_playground_dir("simple_arc_check.txt")
    ic.configureOutput(outputFunction = make_ic_logger(dir))

    generation = generate_symbols_until_nonzero(field,data_fields, gen_size, coefficients=True )
    print("============= Generation ====================")
    print_generation(generation)


    recoded_packets = recode_rlnc_without_coeffs(field, generation, gen_size, count=7)
    print("============= Recoded Packets ====================")
    print_generation(recoded_packets)


    # Take a bucket of packets bigger than the original symbols used
    # gen_size + 1  for arc check

    take = gen_size + 1

    chosen_packets = recoded_packets[0:take]
    print("============= Chosen Packets ====================")
    print_generation(chosen_packets)

    '''
    TODO: PLAN
    - wir machen die rref auf den ersten Paketen
    - trennen Koeffizienten und Daten auf
    - dann nehmen wir die Koeffizienten vom letzen Paket und berechnen wie das Paket aussehen müsste
    - gibt es einen Mismatch -> dann ist der Mismatch, die falsche Spalte
    
    '''
    partial_rref, cleaned_rref = calculate_rref(chosen_packets, field, gen_size)
    print("============= Finished Matrix Packets ====================")
    print_generation(chosen_packets)
    inverted_rref = invert_pivot_rows(cleaned_rref, field, gen_size)

    coefficients = []
    estimated_symbols = []

    for i in range(0, gen_size):
        coefficients.append(inverted_rref[i][0:gen_size])
        estimated_symbols.append(inverted_rref[i][gen_size::])

    print("============= Estimated Symbols, and Coefficients ====================")
    print_generation(coefficients)
    print_generation(estimated_symbols)
    # Step 2: Take the k+1 packet as control packet

    control_coefficients = chosen_packets[gen_size][0:gen_size]
    control_packet = chosen_packets[gen_size][gen_size::]

    print("============= Control Packet ====================")

    print_packet(control_coefficients)
    
    # Introduce an Error
    error_packet = bytearray([0,0,1,0,0])
    control_packet = bytearray(x ^ y for x,y in zip(control_packet, error_packet) )
    
    
    print_packet(control_packet)


    # Step 3: Recalculate with the gioven Coefficients

    calculated_packet = code_with_given_coefficients(estimated_symbols, control_coefficients, field)

    print("============= Calculated Packet ====================")

    print_packet(calculated_packet)


    # Step 4: find the error and mark the Column as faulty

    error_positions = set()

    for i, (e,r) in enumerate(zip(control_packet,calculated_packet)):
        if e != r:
            error_positions.add(i)

    print(error_positions)
    
    # ARC Check works with the correct columns !
    # TODO: make an actual funciton out of it, that takes in random size generation and makes the arc check for it
    # it should return the error columns as a set/list
    # TODO: think: how can this be implemented with the hmac to have error zones that we try to repair






'''

    partial_rref, cleaned_rref = calculate_rref(recoded_packets, field, gen_size)
    print("============= Partial RREF ====================")
    print_generation(partial_rref)
    print("============= Cleaned RREF ====================")
    print_generation(cleaned_rref)
    
    inverted_rref = invert_pivot_rows(cleaned_rref, field, gen_size)
    print("============= Inverted RREF ====================")
    print_generation(inverted_rref)


'''












'''

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

'''