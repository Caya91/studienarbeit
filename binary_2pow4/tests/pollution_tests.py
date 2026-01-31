from icecream import ic
from binary_2pow4.pollution import *
from binary_2pow4.operations_bin4 import print_ints

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

    p1 = pollute_full_packet(b4)
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