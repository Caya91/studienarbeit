import pyerasure
import pyerasure.finite_field
import random
from icecream import ic
from operations_bin4.operations_bin4 import inner_product_bytes, print_ints
from operations_bin4.operations_bin4 import MIN_INT, MAX_INT
from orthogonal_tag_creator import OrthogonalTagGenerator


field = pyerasure.finite_field.Binary4()

tag_gen = OrthogonalTagGenerator(field)


def generate_examples(data_len:int):

    tag_gen = OrthogonalTagGenerator(field)

    data = [random.randint(0, 15) for _ in range(data_len)]

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
    
def generate_symbols_random(data_len:int, gen_size:int) -> list:
    assert data_len > 0
    assert gen_size > 0
        
    
    symbols = []

    for packet in range(gen_size):
        symbol = bytearray([random.randint(MIN_INT, MAX_INT) for _ in range(data_len)] + [0 for _ in range(gen_size)])
        symbols.append(symbol)

    #ic(len(symbols),symbols)
    '''
    for symbol in symbols:
        print_ints(symbol)
    '''
    return symbols

# TODO: implement complete generation of all tags in one function

def generate_all_tags(generation:list[bytearray]):
    
    gen_size = len(generation)
    data_len = len(generation[0]) - gen_size

    new_symbols = []

    i = data_len

    #ic(generation)

    for count, symbol in enumerate(generation):
        #ic("OUTER LOOP", i, count, symbol)

        i = data_len + 1

        new_symbol = symbol.copy()
        for tag_nr in range(count + 1):

            #ic("INNER LOOP", tag_nr, count)
            if tag_nr == count: # if the tag_nr and the count is the same, we calculate our own inner product, to make packet self orthogonal
                tag = tag_gen.generate_tag(inner_product_bytes(field, new_symbol, new_symbol))
                new_symbol[data_len + tag_nr] = tag
                new_symbols.append(new_symbol)
                continue

            corresponding_packet = new_symbols[tag_nr]  # tag_nr is also the corrseponding symbol in the generation, so we take innerproduct with that packet

            tag = tag_gen.generate_tag_cross(corresponding_packet[data_len + tag_nr ],inner_product_bytes(field,new_symbol, corresponding_packet))

            new_symbol[data_len + tag_nr] = tag


    return new_symbols


def test_orth_fixed(generation:list[bytearray]) -> bool:
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


def test_orth_generation(generation:list[bytearray]) -> bool:
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
        print("\n".join(failures))
        # raise AssertionError("\n".join(failures))
    
    print("All pairs orthogonal!")  # Success message
    if failures:
        return False
    #ic(failures)
    return True

def test_1():
    symbols = generate_symbols_random(3,3)

    S1, S2, S3 = symbols

    ic(S1, S2, S3)

    symbols = generate_symbols_random(4,2)
    symbols = generate_symbols_random(4,5)
    symbols = generate_symbols_random(2,7)
    return

def test_2():

    for d_num in range(2,5):
        for q_num in range(2,5):
                symbols = generate_symbols_random(d_num,q_num)
                result = generate_all_tags(symbols)

                for symbol in symbols:
                    print_ints(symbol)

                for packet in result:
                    print_ints(packet)

                ic(test_orth_generation(result))


    return 




def gen_failed_generation():
    '''# this is our specific case where the tag is generated as 0, which then makes other packets unable to create a corresponding tag for  <p1,p2>= 0
    '''
    S1 = bytearray([5, 15, 10, 0, 0, 0, 0, 0])
    S2 = bytearray([6, 2, 2, 9, 15, 0, 0, 0])
    S3 = bytearray([5, 13, 0, 5, 1, 12, 0, 0])
    S4 = bytearray([3, 8, 5, 5, 12, 13, 10, 0])
    S5 = bytearray([15, 2, 3, 8, 3, 7, 11, 9])

    gen = [S1,S2,S3,S4,S5]


    ic(gen, len(gen))

    return test_orth_fixed(gen)
    return test_orth_generation(gen)






if __name__ == "__main__":
    # test_1()

    #test_2()
    
    ic(gen_failed_generation())
    
    
    
    
    
    
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

