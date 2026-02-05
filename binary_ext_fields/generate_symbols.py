import pyerasure
import pyerasure.finite_field
import random
import os

from icecream import ic
from binary_ext_fields.operations import inner_product_bytes, print_ints

import pathlib
from typing import Iterable

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


def check_orth_fixed(field, generation:list[bytearray]) -> bool:
    '''
    in diesem Test versuche ich den die Ausnahme aus dem orthogonalitätstest herauszufiltern
    TODO: das letzte Paket braucht diese Regel nicht
    '''

    gen_size = len(generation)
    data_len = len(generation[0]) - gen_size

    failures = []
    # TODO: Die Ausnahme wenn der eine Tag null ist muss hinzugefügt werden um richtig zu testen, weil machnmal pakete nicht orthogonal werden können wenn der korrespondierende tag 0 ist
    
    # auskommentiert für notebook use
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
    
    
    # print("All pairs orthogonal!")  # Success message
    
    ic(failures)

    return True


def check_orth(field, generation:list[bytearray]) -> bool:
    failures = []

    # TODO: Die Ausnahme wenn der eine Tag null ist muss hinzugefügt werden um richtig zu testen, weil machnmal pakete nicht orthogonal werden können wenn der korrespondierende tag 0 ist
    
    '''
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
    
    if failures:
        #print("\n".join(failures))
        log_failed_generation(generation, failures)
        # raise AssertionError("\n".join(failures))
    
    if not failures and verbose:
        print("All pairs orthogonal!")  # Success message
        
    if failures:
        return False
    #ic(failures)
    return True

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

