import os

from pyerasure import finite_field
from icecream import ic


from binary_2pow8.generate_symbols import generate_symbols_random_bin8, check_orth_bin8, check_orth_fixed

from binary_2pow8.orthogonal_tag_creator import OrthogonalTagGenerator

from binary_2pow8.config import field


def test_1():
    symbols = generate_symbols_random_bin8(3,3)

    S1, S2, S3 = symbols

    ic(S1, S2, S3)

    symbols = generate_symbols_random_bin8(4,2)
    symbols = generate_symbols_random_bin8(4,5)
    symbols = generate_symbols_random_bin8(2,7)
    return

def test_2():
    tag_gen = OrthogonalTagGenerator(field)

    for d_num in range(3,5):
        for q_num in range(3,5):

                symbols = generate_symbols_random_bin8(d_num,q_num)

                result = tag_gen.generate_all_tags(symbols)

                '''
                for symbol in symbols:
                    print_ints(symbol)

                for packet in result:
                    print_ints(packet)
                '''
                #ic(check_orth_bin8(result))

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

    #return check_orth_fixed(gen)
    return check_orth_bin8(gen)


if __name__ == "__main__":
     
     print("hi")
     ic(test_1())
     ic(test_2())
     ic(gen_failed_generation())