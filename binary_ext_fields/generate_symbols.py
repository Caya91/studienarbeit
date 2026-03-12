import pyerasure
import pyerasure.finite_field
import random
import os
from pathlib import Path
from icecream import ic
from binary_ext_fields.operations import inner_product_bytes, print_ints
from binary_ext_fields.custom_field import TableField, create_field

import pathlib
from typing import Iterable, Any

logs_dir = pathlib.Path("logs")
logs_dir.mkdir(exist_ok=True)  

LOG_PATH = pathlib.Path(os.getenv("LOG_FOLDER"))
LOG_FILE = LOG_PATH / "orth_failures.log"
bad_packets: set[tuple[int, ...]] = set()


verbose = False


def generate_symbols_random(min_int:int, max_int:int,data_fields:int, gen_size:int) -> list:
    assert data_fields > 0
    assert gen_size > 0
        
    
    symbols = []

    for packet in range(gen_size):
        symbol = bytearray([random.randint(min_int, max_int) for _ in range(data_fields)] + [0 for _ in range(gen_size)])
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
    coefficient_matrix = []
    for i in range(count):
        coefficient_matrix.append(generate_coefficient_row(field, gen_size))
    return coefficient_matrix


def recode(field: Any, generation:list[bytearray], count=1) -> bytearray:
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
        return SyntaxError
    
def recode_rlnc(field:TableField, generation:list[bytearray], gen_size:int, count:int) -> bytearray:
    '''takes the original symbols as an argument, and return recoded packets
    ORIGINAL MATRIX DOESNT HAVE COEFFICIENTS YET, MUST '''
    assert count > 0
    
    coefficient_matrix = []
    if count == 1:
        coefficient_matrix = list[generate_coefficient_row(field, gen_size)]
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
    USE THIS if the original Matrix already has coefficients infront of the packet '''
    assert count > 0
    
    coefficient_matrix = []
    if count == 1:
        coefficient_matrix = list[generate_coefficient_row(field, gen_size)]
    elif count >= 2:
        coefficient_matrix =  generate_coefficient_matrix(field, gen_size, count)


    rlnc_matrix = []
    for i in range(count):
        new_packet = [0 for _ in range(len(generation[0]))]
        for j, packet in enumerate(generation):
            coefficient = coefficient_matrix[i][j]
            ic(i,j,new_packet, packet, coefficient)
            new_packet = field.vector_multiply_add_into(new_packet, packet, coefficient)
        rlnc_matrix.append(new_packet) # THE  ONLY  difference lies, here, could also be put in the original function probably

    return rlnc_matrix


def check_orth_fixed(field, generation:list[bytearray]) -> bool:
    '''
    in diesem Test versuche ich den die Ausnahme aus dem orthogonalitätstest herauszufiltern
    TODO: das letzte Paket braucht diese Regel nicht
    '''

    gen_size = len(generation)
    data_len = len(generation[0]) - gen_size

    failures = []
    # TODO: Die Ausnahme wenn der eine Tag null ist muss hinzugefügt werden um richtig zu testen, weil machnmal pakete nicht orthogonal werden können wenn der korrespondierende tag 0 ist
    
    '''
    ic()
    ic(generation)
    for p in generation:
        print_ints(p)
    '''
    # filter the 0 self orthogonal packets

    new_gen = []
    for i in range(gen_size):
        #ic(generation[i][data_len + i], i , data_len + i,gen_size)
        if i == (gen_size - 1): # last packet doesnt need this check
            new_gen.append(generation[i])
            continue
        if not generation[i][data_len + i] == 0:
            new_gen.append(generation[i])

    '''
    print("NEW Generation")
    for p in new_gen:
        print_ints(p)   
    '''

    for i, packet in enumerate(new_gen):
        for j, p in enumerate(new_gen):
            prod = inner_product_bytes(field, packet, p)
            if prod != 0:
                failures.append(f"Non-orthogonal: packet[{i}] • packet[{j}] = {prod} (expected 0)")
    if failures:
        raise AssertionError("\n".join(failures))
    
    
    # print("All pairs orthogonal!") 
    
    ic(failures)

    return True


def check_orth(field, generation: list[bytearray], log_dir: Path | None = None) -> bool:
    failures = []
    successes = []
    # TODO: Die Ausnahme wenn der eine Tag null ist muss hinzugefügt werden um richtig zu testen, weil machnmal pakete nicht orthogonal werden können wenn der korrespondierende tag 0 ist
    '''
    extra_check = False
    if log_dir == Path("D:\projects\studienarbeit\logs\error_logthat.txt"):
        ic("THIS is the culprit", generation)
        extra_check = True
    
    ic()
    ic(generation)
    for p in generation:
        print_ints(p)
    ''' 

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
    
    return True


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
'''
def generate_examples(data_len:int):

    tag_gen = OrthogonalTagGenerator(field)

    data = [random.randint(MIN_INT, MAX_INT) for _ in range(data_len)]

    S1= bytearray([random.randint(MIN_INT, MAX_INT) for _ in range(data_len)] + [0,0])
    S2= bytearray([random.randint(MIN_INT, MAX_INT) for _ in range(data_len)] + [0,0])
    
    t11 = tag_gen.generate_tag(inner_product_bytes(field, S1,S1))

    S1[data_len] = t11

    t21 = tag_gen.generate_tag_cross(t11, inner_product_bytes(field,S1,S2))

    S2[data_len] = t21

    t22 = tag_gen.generate_tag(inner_product_bytes(field,S2,S2))

    S2[data_len+1] = t22
    print_ints(S1)
    print_ints(S2)

    ic(
        inner_product_bytes(field,S1,S1),
        inner_product_bytes(field,S1,S2),
        inner_product_bytes(field,S2,S2)
       )
    '''



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

