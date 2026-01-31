import random
from enum import Enum

from icecream import ic
from binary_2pow4.operations_bin4 import MIN_INT, MAX_INT



class Pollution(Enum):
    ALL = 0
    DATA = 1
    TAG = 2

poll_enum: Pollution = Pollution.DATA

# TODO: implement coefficient pollution

def pollute_full_packet(packet:bytearray) -> bytearray:
    length = len(packet)
    # nicht das Original verändern
    poll_pack = bytearray(random.randint(MIN_INT, MAX_INT) for _ in range(length))
    return poll_pack


def pollute_data_packet(data_length:int, packet:bytearray ) -> bytearray:
    # soll nicht das Original verändern!
    # wichtig: hier eine Kopie machen, da sonst auch das Original geändert wird
    poll_pack = packet.copy()

    # bytearray expects an Integer from 0- 255 as an assignment
    poll_pack[0] = 5   # this is placeholder just to test if it works
    for i,e in enumerate(packet):
            if i >= data_length:
                continue
            poll_pack[i] = random.randint(MIN_INT, MAX_INT)

    return poll_pack


def pollute_tags_packet(data_length:int, packet:bytearray) -> bytearray:
    poll_pack = packet.copy()
    for i,e in enumerate(packet):
        if i < data_length:
            continue
        poll_pack[i] = random.randint(MIN_INT, MAX_INT)
    #ic(poll_pack, packet)
    return poll_pack


def apply_pollution(data_len: int, packet: bytearray, poll_enum: Pollution) -> bytearray:
    if poll_enum is Pollution.ALL:
        return pollute_full_packet(packet)
    if poll_enum is Pollution.DATA:
        return pollute_data_packet(data_len, packet)
    if poll_enum is Pollution.TAG:
        return pollute_tags_packet(data_len, packet)
    return packet



if __name__ == "__main__":
    print("Pollution")

