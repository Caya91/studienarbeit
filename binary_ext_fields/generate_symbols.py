import pyerasure
import pyerasure.finite_field
import random
import os
from pathlib import Path
from icecream import ic
from binary_ext_fields.operations import inner_product_bytes, print_ints
from binary_ext_fields.custom_field import TableField, create_field
from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator as OTC


from utils.log_helpers import get_playground_dir, get_run_log_dir


import pathlib
from typing import Iterable, Any

logs_dir = pathlib.Path("logs")
logs_dir.mkdir(exist_ok=True)  

_env_log = os.getenv("LOG_FOLDER")
LOG_PATH = pathlib.Path(_env_log) if _env_log else pathlib.Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_PATH / "orth_failures.log"
bad_packets: set[tuple[int, ...]] = set()


verbose = False


def generate_symbols_random(min_int:int, max_int:int, data_fields:int, gen_size:int,
                            rng=random.randint) -> list:
    assert data_fields > 0
    assert gen_size > 0

    symbols = []

    for packet in range(gen_size):
        symbol = bytearray([rng(min_int, max_int) for _ in range(data_fields)] + [0 for _ in range(gen_size)])
        symbols.append(symbol)

    #ic(len(symbols),symbols)
    '''
    for symbol in symbols:
        print_ints(symbol)
    '''
    return symbols


def generate_symbols_until_nonzero(field:TableField,data_fields:int, gen_size:int, coefficients: bool = False) -> list:
    '''This function generates Symbols until all the self tags are non-zero
    
    coefficients = True -> generate with coefficient matrix
    '''
    
    assert data_fields > 0
    assert gen_size > 0
        
    min_int = 0
    max_int = field.max_value
    symbols = []

    accepts = False
    no_tag_error = False

    otc = OTC(field)

    while not (accepts and no_tag_error):
        symbols = generate_symbols_random(min_int, max_int, data_fields, gen_size)
        symbols_with_coeffs = generate_identity_coefficients(field, symbols)
        ic(symbols_with_coeffs)
        tagged_symbols = otc.generate_all_tags(symbols_with_coeffs)
        accepts = check_orth(field, tagged_symbols)
        no_tag_error = check_no_tag_error(tagged_symbols)

    return tagged_symbols


def generate_with_zero_tag_error(field:TableField,data_fields:int, gen_size:int) -> list:
    '''This function generates Symbols until all the self tags are non-zero
    
    coefficients = True -> generate with coefficient matrix
    '''
    
    assert data_fields > 0
    assert gen_size > 0
        
    min_int = 0
    max_int = field.max_value
    symbols = []

    accepts = False
    no_tag_error = True

    otc = OTC(field)

    while not (accepts and not no_tag_error):
        symbols = generate_symbols_random(min_int, max_int, data_fields, gen_size)
        symbols_with_coeffs = generate_identity_coefficients(field, symbols)
        ic(symbols_with_coeffs)
        tagged_symbols = otc.generate_all_tags(symbols_with_coeffs)
        accepts = check_orth(field, tagged_symbols)
        no_tag_error = check_no_tag_error(tagged_symbols)

    return tagged_symbols


def generate_symbols_with_swap(field:TableField,data_fields:int, gen_size:int) -> list:
    '''This function generates Symbols until all the self tags are non-zero
    '''
    
    assert data_fields > 0
    assert gen_size > 0
        
    min_int = 0
    max_int = field.max_value
    symbols = []

    accepts = False

    otc = OTC(field)

    while not accepts:
        symbols = generate_symbols_random(min_int, max_int, data_fields, gen_size)
        tagged_symbols = otc.generate_all_tags(symbols)
        accepts = check_orth(field, tagged_symbols) 

    return tagged_symbols


def generate_symbols_bitshift(field: TableField, data_fields:int, gen_size:int) -> list:
    '''generates random symbols with 1 column as an additional tag column used for signaling bitshifts
    it will be 0 if no error occurs or 1 if the zero tag error occurs, to then XOR the data with 1
    that should be simple enough, to recover later on
    
    returns a generation -> PACKETS ARE 1 ELEMENT LONGER'''

    assert data_fields > 0
    assert gen_size > 0
        
    min_int = 0
    max_int = field.max_value


    symbols = []

    for packet in range(gen_size):
        symbol = bytearray( [0] + [random.randint(min_int, max_int) for _ in range(data_fields)] + [0 for _ in range(gen_size)])
        symbols.append(symbol)

    #ic(len(symbols),symbols)
    '''
    for symbol in symbols:
        print_ints(symbol)
    '''
    return symbols


def generate_coefficient_row(field: TableField, gen_size:int) -> bytearray:
    assert gen_size > 0
    min_int = 0
    max_int = field.max_value
            
    return bytearray([random.randint(min_int, max_int) for _ in range(gen_size)])


def generate_coefficient_matrix(field: TableField, gen_size:int, count:int) -> list[bytearray]:
    ''' Used for coding and recoding, returns RANDOM coefficient Matrix
    '''
    coefficient_matrix = []
    for i in range(count):
        coefficient_matrix.append(generate_coefficient_row(field, gen_size))
    return coefficient_matrix


def generate_identity_coefficients(field: TableField, generation: list[bytearray]) -> list[bytearray]:
    ''' returns a coefficients Matrix with all pivot elements on the diagonal = 1
    '''
    gen_size = len(generation)
    
    assert gen_size > 0
    min_int = 0
    max_int = field.max_value
    coefficient_matrix = []
    for i in range(gen_size):
        coefficient_row = bytearray([0 for _ in range(gen_size)])
        coefficient_row[i] = 1
        coefficient_matrix.append(coefficient_row)

    if len(coefficient_matrix) != len(generation):
        raise ValueError
    
    full_matrix = []

    for row1, row2 in zip (coefficient_matrix, generation):
        new_row = row1 + row2
        full_matrix.append(new_row)
    return full_matrix


def recode(field: TableField, generation:list[bytearray], count=1) -> bytearray:
    '''returns <count> random recoded packets of our generation
    this is just 2 randomly combined packets, not real RLNC yet'''
#TODO: this recodes 2 random packets after multiplying them by a scalar, for real RLNC we need more
    if count == 1:

        min_value = 1
        max_value = field.max_value

        pckts = []
        for i in range(count):
            pkt1 = random.choice(generation).copy()
            pkt2 = random.choice(generation).copy()

            field.vector_multiply_into(pkt1, random.randint(min_value, max_value))

            result = field.vector_multiply_add_into(pkt1,pkt2,random.randint(min_value, max_value))
            ic(result)
        return result
    else:
        raise SyntaxError
    
def recode_rlnc(field:TableField, generation:list[bytearray], gen_size:int, count:int) -> bytearray:
    '''takes the original symbols as an argument, and return recoded packets
    ORIGINAL MATRIX DOESNT HAVE COEFFICIENTS YET, THIS WILL ADD THE COEFFICIENT MATRIX '''
    assert count > 0
    
    coefficient_matrix = []
    if count == 1:
        coefficient_matrix = [generate_coefficient_row(field, gen_size)]
    elif count >= 2:
        coefficient_matrix =  generate_coefficient_matrix(field, gen_size, count)


    rlnc_matrix = []
    for i in range(count):
        new_packet = [0 for _ in range(len(generation[0]))]
        for j, packet in enumerate(generation):
            coefficient = coefficient_matrix[i][j]
            ic(i,j,new_packet, packet, coefficient)
            new_packet = field.vector_multiply_add_into(new_packet, packet, coefficient)
        rlnc_matrix.append(coefficient_matrix[i] + new_packet)

    return rlnc_matrix


def recode_rlnc_without_coeffs(field:TableField, generation:list[bytearray], gen_size:int, count:int) -> bytearray:
    '''takes the original symbols as an argument, and return recoded packets
    USE THIS if the original Matrix ALREADY HAS COEFFICIENTS infront of the packet 
    if count == 1 -> returns 1 coded packet
    if count > 1  -> returns a matrix with ocded packets
    
    '''
    assert count > 0
    
    coefficient_matrix = []
    if count == 1:
        coefficient_row = list(generate_coefficient_row(field, gen_size))

        new_packet = [0 for _ in range(len(generation[0]))]
        for j, packet in enumerate(generation):
            coefficient = coefficient_row[j]
            #ic(j,new_packet, packet, coefficient)
            new_packet = field.vector_multiply_add_into(new_packet, packet, coefficient)

        return new_packet
    
    elif count >= 2:
        coefficient_matrix =  generate_coefficient_matrix(field, gen_size, count)


    rlnc_matrix = []
    for i in range(count):
        new_packet = [0 for _ in range(len(generation[0]))]
        for j, packet in enumerate(generation):
            coefficient = coefficient_matrix[i][j]
            #ic(i,j,new_packet, packet, coefficient)
            new_packet = field.vector_multiply_add_into(new_packet, packet, coefficient)
        rlnc_matrix.append(new_packet) # THE  ONLY  difference lies, here, could also be put in the original function probably

    return rlnc_matrix


def check_orth(field, generation: list[bytearray], log_dir: Path | None = None , check_packet: bytearray = None) -> bool:
    ''' returns True if all packets in the generation are orthogonal to each other'''
    failures = []
    successes = []

#TODO: Skip last element of the double for loop (i=j=len(gen)) without if statement
#idea -  slicing the generation going untio gen[::-1] or soemthing
#then checking the last packet seperately
    if check_packet is None:
        generation = generation + [check_packet]
        ic(generation)
    

    for i, packet in enumerate(generation):
        for j, p in enumerate(generation):
            prod = inner_product_bytes(field, packet, p)
            if prod != 0:
                failures.append(f"Non-orthogonal: packet[{i}] • packet[{j}] = {prod} (expected 0)")
            else:
                successes.append(f"Orthogonal: packet[{i}] • packet[{j}] = {prod} (expected 0)")


    if failures:
        if log_dir: # logging to passed directory
            log_failed_generation(generation, failures, log_dir)
        return False
    else:
        if log_dir: # logging to passed directory
            log_orthogonal_generation(generation, successes, log_dir)
        return True


def check_orth_for_recovery(field, generation: list[bytearray], gen_size:int, log_dir: Path | None = None) -> set[int]:
    ''' returns rows of the packets that are not fully zero in the generation, uses the full rref form of the generation'''
    failure_rows = set()
# skip the first rows of coefficients for now TODO: probably check ort of all packets
# idea just look for columns that are zero for now
    for i, packet in enumerate(generation[gen_size::]):
        if not packet.count(0) == len(packet): # if its not all zeros, add to failure
            failure_rows.add(i + gen_size)

    return failure_rows


def check_broken_column(field, packet: bytearray, ) -> list[int]:
    ''' returns the non zero, column locations (searchspaces for recovery)'''
    broken_columns = []
    for i,e in enumerate (packet):
        if e != 0:
            broken_columns.append(i)
    
    return broken_columns

def get_recovery_regions(field, generation:list[bytearray], gen_size:int,log_dir: Path | None = None ):
    failure_rows = check_orth_for_recovery(field, generation, gen_size)
    
    recovery_regions = dict()

    for e in failure_rows:
        broken_columns = check_broken_column(field, generation[e])
        recovery_regions.update({e: broken_columns})

    ic(recovery_regions)

    return recovery_regions


def nr_of_error_columns(row, columns) :
    ''' # can maybe take just 1 tuple and return the nr of errors for that
    param:: recovery_regions -> dict of {row: [error_column1, error_column2]}
    checks the ammount of error columns in a packet -> use this to check
    if its worth to recover the packet
    '''

    
    return len(columns)


def hamming_distance():
    '''check the hamming distance of a packet in the rref form of the generation'''
    # add up all the elements of a packet and calculate the total hamming distance
    # has to be relaitve to the field, like 7 in 2^3 is a distance of 1, i would guess, or maybe we use
    # bits for that... dunno yet
    # then add up all the hamming distances in total, not as elements of a field ( could get zero again, when adding up)
    # to big of a difference, will be discarded as a broken packet



    return


def check_no_tag_error(generation:list[bytearray]) -> bool:
    '''
    checks the original generation with their coefficients, and returns true if no self tag is zero
    atm assumes the generation already has coefficient matrix and tags,
    DOESTN WORK WITH BITSHIFT YET
    '''
    gen_size = len(generation)
    data_fields = len(generation[0]) - 2*gen_size
    #ic(data_fields)

    self_tags = []
    for i, packet in enumerate(generation):
        #ic(i,packet, i + data_fields,i + data_fields +  gen_size)
        self_tags.append(packet[i + data_fields + gen_size])

    if self_tags.count(0) == 0:
        ic("no Zero tags", self_tags)
        return True
    else:
        ic("yes Zero tags", self_tags)
        return False

def check_orth_skip_coeffs(field:TableField, generation_with_coefficients: list[bytearray], gen_size:int, log_dir: Path | None = None) -> bool:
    '''this is a wrapper to check orthogonality between all packets of a generateion
    but is skipping the coefficients'''
    generation_no_coefficients = skip_coefficients(field, generation_with_coefficients, gen_size)
    return check_orth(field, generation_no_coefficients, log_dir)


def skip_coefficients(field:TableField, generation_with_coefficients: list[bytearray], gen_size:int) -> list[bytearray]:
    generation_no_coefficients = []
    for packet in generation_with_coefficients:
        packet = packet[gen_size::]
        generation_no_coefficients.append(packet.copy())
    return generation_no_coefficients.copy()


def log_failed_generation(generation: list[bytearray], failures: Iterable[str], log_file: pathlib.Path = LOG_FILE) -> None:
    with log_file.open("a", encoding="utf-8") as f:
        f.write("=== Non-orthogonal generation ===\n")
        for line in failures:
            f.write(line + "\n")
        f.write("Packets:\n")
        for idx, pkt in enumerate(generation):
            f.write(f"  [{idx}] {list(pkt)}\n")
        f.write("\n")


def log_orthogonal_generation(generation: list[bytearray], successes: Iterable[str], log_file: pathlib.Path = LOG_FILE) -> None:
    with log_file.open("a", encoding="utf-8") as f:
        f.write("=== Orthogonal generation ===\n")
        for line in successes:
            f.write(line + "\n")
        f.write("Packets:\n")
        for idx, pkt in enumerate(generation):
            f.write(f"  [{idx}] {list(pkt)}\n")
        f.write("\n")


def test_generate_coefficient_matrix():
    field = create_field(3)
    coefficient_matrix = generate_coefficient_matrix(field, 3, 3)
    ic(coefficient_matrix)

    generation = [
        [1,0,0],
        [0,1,0],
        [0,0,1]
    ]

    gen_size = 3


    rlnc_matrix = recode_rlnc(field,generation, gen_size,5 )
    ic(rlnc_matrix)


    ic(check_orth(field, rlnc_matrix))
    return True


def test_remove_coefficients():
    
    matrix_with_coefficients = [
        [1,0,0,1,2,3],
        [0,1,0,1,2,3],
        [0,0,1,1,2,3]
    ]


    field = create_field(3)
    gen_size = 3


    matrix_no_coefficients = check_orth_skip_coeffs(field, matrix_with_coefficients,3)
    ic(matrix_no_coefficients)

    return True


def test_remove_coefficients_bytearray():

    matrix_with_coefficients = [
        [1,0,0,1,2,3],
        [0,1,0,1,2,3],
        [0,0,1,1,2,3]
    ]

    matrix_bytearray = []
    for packet in matrix_with_coefficients:
        matrix_bytearray.append(bytearray(packet))

    ic(matrix_bytearray)

    field = create_field(3)
    gen_size = 3

    matrix_no_coefficients_byteaaray = check_orth_skip_coeffs(field, matrix_bytearray,3)
    ic(matrix_no_coefficients_byteaaray)

    return True


if __name__ == "__main__":
    print("hi")

    field_int = 3
    field = create_field(field_int)
    data_fields = 4
    gen_size = 5

    generation = generate_symbols_until_nonzero(field, data_fields, gen_size, coefficients=True )
    
    ic(generation)


    '''failed_gen = []
    for i in range(100):
        gen = generate_symbols_random(3,5)

        tagged_gen = generate_all_tags(gen)

        if not test_orth_generation(tagged_gen):
            failed_gen = tagged_gen
            ic(failed_gen)
            break
'''



    '''
    symbols = generate_symbols_random(3,3)

    result = generate_all_tags(symbols)
    ic(test_orth_generation(result))
    '''

