import random
from enum import Enum

from icecream import ic
from collections.abc import Callable
from binary_ext_fields.custom_field import (TableField, create_field)
from binary_ext_fields.generate_symbols import generate_symbols_until_nonzero
from utils.log_helpers import print_generation

class Pollution(Enum):
    ALL = 0
    DATA = 1
    TAG = 2
    SMART = 3

# TODO: min_int is usually 0, so could be left out of all operations
# TODO: max_int could be derived from used field, 
# TODO: implement coefficient pollution

def pollute_full_packet(packet:bytearray, min_int:int, max_int:int) -> bytearray:
    length = len(packet)
    # nicht das Original verändern
    poll_pack = bytearray(random.randint(min_int, max_int) for _ in range(length))
    return poll_pack


def pollute_data_packet(data_length:int, packet:bytearray ,min_int:int, max_int:int) -> bytearray:
    # soll nicht das Original verändern!
    # wichtig: hier eine Kopie machen, da sonst auch das Original geändert wird
    poll_pack = packet.copy()

    # bytearray expects an Integer from 0- 255 as an assignment
    poll_pack[0] = 5   # this is placeholder just to test if it works
    for i,e in enumerate(packet):
            if i >= data_length:
                continue
            poll_pack[i] = random.randint(min_int, max_int)

    return poll_pack


def pollute_tags_packet(data_length:int, packet:bytearray, min_int:int, max_int:int) -> bytearray:
    poll_pack = packet.copy()
    for i,e in enumerate(packet):
        if i < data_length:
            continue
        poll_pack[i] = random.randint(min_int, max_int)
    #ic(poll_pack, packet)
    return poll_pack


def pollute_intelligent(field, packet, trusted_packets, gen_size, data_length) -> bytearray:
    """Craft a corrupted packet aimed at passing the acceptance criteria
    while differing from the original `packet`. 

    White-box: assumes knowledge of the trusted generation.
    """

    # TODO:


def pollute_random(field, packet, bit_error_rate) -> bytearray:
    # Only flip the field.bit_lenght low bits (m for GF(2^m)); flipping higher
    # bits would push a symbol above field.max_value, out of the field. This also
    # keeps pollution in the same bit space the recoverer searches (bit_flip_candidates
    # / whole_packet both use field.bit_lenght).
    polluted_packet = bytearray(packet)

    for i in range(len(polluted_packet)):
        byte = polluted_packet[i]
        for bit_pos in range(field.bit_lenght):
            if random.random() < bit_error_rate:
                byte ^= (1 << bit_pos)
        polluted_packet[i] = byte

    return polluted_packet


def pollute_generation(field, generation, bit_error_rate, polluter: Callable,):
# TODO: make all pollution functions take the same Callable, so using them in for loop will be easy

#TODO: test the bit error Rate, by checking the number of broken bytes, when compared to the original, should be amount of symbols * error_rate

    polluted_generation = []
    for packet in generation:
        polluted_generation.append(polluter(field, packet, bit_error_rate))
        
        #apply pollution

    return polluted_generation


def bit_error_rate_generation(generation1, generation2, bits_per_element = 8):
    assert len(generation1) == len(generation2)
    #TODO:  should we return the whole data, like bit count and other things too?

    byte_count = len(generation1) * len(generation1[0])
    bit_count = byte_count * bits_per_element
    byte_errors = 0
    bit_errors = 0
    for packet1,packet2 in zip(generation1, generation2):        
        for byte1, byte2 in zip(packet1,packet2):
            if byte1 == byte2:
               continue
            else:
                byte_errors += 1
            #ic(format(byte1,'08b' ), format(byte2,'08b'))


            for bit1, bit2 in zip(format(byte1,'08b' ), format(byte2,'08b')):
                #ic(bit1, bit2)
                if bit1 == bit2:
                   continue
                else:
                    bit_errors += 1


    bit_error_rate = bit_errors / bit_count
    byte_error_rate = byte_errors / byte_count

    return bit_errors, byte_errors , bit_error_rate, byte_error_rate

def test_pollution():
    field = create_field(4)
    gen_size = 3
    data_fields = 4 

    generation = generate_symbols_until_nonzero(field, data_fields, gen_size, True)


    bit_error_rate = 0.01

    polluted_generation = pollute_generation(field, generation, bit_error_rate, pollute_random) 

    print_generation(generation)
    print_generation(polluted_generation)









if __name__ == "__main__":
    field = create_field(4)
    gen_size = 3
    data_fields = 4 

    generation = generate_symbols_until_nonzero(field, data_fields, gen_size, True)


    bit_error_rate = 0.01

    polluted_generation = pollute_generation(field, generation, bit_error_rate, pollute_random) 

    print_generation(generation)
    print_generation(polluted_generation)

    


    print("Pollution")
    print(byte_error_rate_generation(generation, polluted_generation))
    print(bit_error_rate_generation(generation, polluted_generation))
