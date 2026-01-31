import os

from binary_2pow4.operations_bin4 import *
from binary_2pow4.generate_symbols import *



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

                ic(check_orth(result))


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

    return check_orth_fixed(gen)
    return check_orth(gen)


if __name__ == "__main__":
     
     print("hi")
     #test_1()
     #test_2()
     #gen_failed_generation()