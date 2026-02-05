import random
from enum import Enum

from icecream import ic
from binary_2pow8.config import MIN_INT, MAX_INT
from binary_ext_fields.pollution import *


# TODO: implement coefficient pollution

def pollute_full_packet_bin8(packet:bytearray) -> bytearray:
    return pollute_full_packet(packet=packet, min_int=MIN_INT, max_int=MAX_INT)


def pollute_data_packet_bin8(data_length:int, packet:bytearray ) -> bytearray:
    return pollute_data_packet(data_length = data_length, packet=packet,min_int=MIN_INT, max_int=MAX_INT)


def pollute_tags_packet_bin8(data_length:int, packet:bytearray) -> bytearray:
    return pollute_tags_packet(data_length=data_length, packet=packet, min_int=MIN_INT, max_int=MAX_INT)



def apply_pollution(data_len: int, packet: bytearray, poll_enum: Pollution) -> bytearray:
    if poll_enum is Pollution.ALL:
        return pollute_full_packet_bin8(packet)
    if poll_enum is Pollution.DATA:
        return pollute_data_packet_bin8(data_len, packet)
    if poll_enum is Pollution.TAG:
        return pollute_tags_packet_bin8(data_len, packet)
    return packet



if __name__ == "__main__":
    print("Pollution Bin8")


    S1 = bytearray(5)
    print(S1)

    S1 = apply_pollution(3,S1,Pollution.DATA)
    print(S1)

