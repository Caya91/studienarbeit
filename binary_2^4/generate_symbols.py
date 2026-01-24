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

    for symbol in symbols:
        print_ints(symbol)

    return symbols

# TODO: implement complete generation of all tags in one function

def generate_all_tags(generation:list[bytearray]):
    
    gen_size = len(generation)
    data_len = len(generation[0]) - gen_size

    new_symbols = []

    i = data_len

    ic(generation)

    for count, symbol in enumerate(generation):
        ic("OUTER LOOP", i, count, symbol)

        i = data_len + 1

        new_symbol = symbol.copy()
        for tag_nr in range(count + 1):

            ic("INNER LOOP", tag_nr, count)
            if tag_nr == count: # if the tag_nr and the count is the same, we calculate our own inner product, to make packet self orthogonal
                tag = tag_gen.generate_tag(inner_product_bytes(field, new_symbol, new_symbol))
                new_symbol[data_len + tag_nr] = tag
                new_symbols.append(new_symbol)
                continue

            corresponding_packet = new_symbols[tag_nr]  # tag_nr is also the corrseponding symbol in the generation, so we take innerproduct with that packet

            tag = tag_gen.generate_tag_cross(corresponding_packet[data_len + tag_nr ],inner_product_bytes(field,new_symbol, corresponding_packet))

            new_symbol[data_len + tag_nr] = tag


    return new_symbols


def test_orth_generation(generation:list[bytearray]):
    # TODO: Die Ausnahme wenn der eine Tag null ist muss hinzugefügt werden um richtig zu testen, weil machnmal pakete nicht orthogonal werden können wenn der korrespondierende tag 0 ist
    for packet in generation:
        for p in generation:
            assert inner_product_bytes(field,packet,p) == 0

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

if __name__ == "__main__":
    # test_1()

    test_2()

    '''
    symbols = generate_symbols_random(3,3)

    result = generate_all_tags(symbols)
    ic(test_orth_generation(result))
    '''

