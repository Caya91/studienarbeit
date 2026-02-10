import random
from enum import Enum

from icecream import ic


class Pollution(Enum):
    ALL = 0
    DATA = 1
    TAG = 2

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



if __name__ == "__main__":
    print("Pollution")

