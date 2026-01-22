import pyerasure
import pyerasure.finite_field
import random
from icecream import ic

MIN_INT = 0
MAX_INT = 15

def inner_product_bytes(field:pyerasure.finite_field, x: bytes, y: bytes) -> int:
    """⟨x, y⟩ = ∑ x[i]·y[i] in GF(2^8) using PyErasure vector ops."""
    assert len(x) == len(y)
    acc = 0
    tmp = bytearray(1)

    for a, b in zip(x, y):
        tmp[0] = a
        field.vector_multiply_into(tmp, b)  # tmp[0] = a·b
        acc = field.add(acc, tmp[0])        # acc += a·b

    return acc

def pretty_bytearray(ba, name="ba"):
    ints = ', '.join(map(str, ba))
    hexs = ba.hex(' ')
    bins = ', '.join(f'{x:04b}' for x in ba)
    print(f"{name}:\n  ints: [{ints}]\n  hex:  {hexs}\n  bin:  [{bins}]")

def print_ints(ba, name="ba"):
    print(f"{name}: length: {len(ba)} [{', '.join(map(str, ba))}]")

# TODO: implement coefficient pollution

def pollute_packet(packet:bytearray) -> bytearray:
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
    ic(poll_pack, packet)
    return poll_pack

# TODO: implement data, tag pollution 


def test_inner_product():
    ic(inner_product_bytes(pyerasure.finite_field.Binary4(),[5],[5])) # 5*5 = 2
    ic(inner_product_bytes(pyerasure.finite_field.Binary4(),[3],[3])) # 3*3 = 5
    ic(inner_product_bytes(pyerasure.finite_field.Binary4(),[0],[0])) # 0*0 = 0

    ic(inner_product_bytes(pyerasure.finite_field.Binary4(),[17],[17])) # should be an assertion error becasue from pyerasure


def test_packet_pollution():
    #ic(pollute_packet(3))
    b1 = bytearray(1)
    b2 = bytearray([2,1])
    b3 = bytearray(3)


    ic(len(b1), len(b2), len(b3))
    ic(b1,b2,b3)

    ic(b2[0],b2[1])
    ic(b1[0], b2[1], b3[2])

    ic(b2)
    polluted_packet = pollute_data_packet(1,b2)
    p2 = pollute_tags_packet(1,b2)
    ic (polluted_packet,p2, b2)
    print(p2)

    # test mit größerem Packet

    b4 = bytearray([1,2,3,4,5,6,7,8,9])

    p1 = pollute_packet(b4)
    p2 = pollute_data_packet(3,b4)
    p3 = pollute_tags_packet(3,b4)

    ic(b4,p1,p2,p3)
    print(p1)

    values = [p1,p2,p3]
    for p in values:
        print_ints(p)    
    
    
    return



if __name__ == "__main__":
    test_packet_pollution()