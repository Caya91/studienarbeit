from icecream import ic
from utils.log_helpers import log_packet
from random import choice

from binary_ext_fields.custom_field import TableField, create_field

from binary_ext_fields.generate_symbols import inner_product_bytes, check_orth, check_orth_packet
from binary_ext_fields.generate_symbols import generate_symbols_until_nonzero
from utils.log_helpers import make_ic_logger, print_generation, print_packet, get_playground_dir 
from utils.log_helpers import log_generation_detail, log_inner_product_detail

from itertools import combinations, product
import random
from playground.arc_pl import  error_into_packet, error_into_packet_chosen_bit
from playground.new_recovery import recover_packet_bitflip





def false_positive_example():
    field = create_field(8)

    #org_pkt = bytearray([0, 0, 1, 0, 0, 235, 119, 102, 186, 178, 215, 36, 0, 0])
    org_pkt = bytearray([0, 1, 0, 189, 105, 14, 127, 164, 0])

    flipped_byte = org_pkt[0] | (1 << 1)

    print(list(org_pkt))

    flipped_pkt = bytearray(org_pkt)
    flipped_pkt[0] = flipped_byte

    print(list(flipped_pkt))
    #pkt_bitflip = org_pkt[0] = org_pkt[]

    print(check_orth_packet(field, flipped_pkt))
    log_inner_product_detail(field, flipped_pkt, flipped_pkt)


    mask = 0
    mask ^= (1 << 1)
    print(mask)


    for i in range(1, len(org_pkt)):
        tmp = bytearray(flipped_pkt)
        tmp[i] ^= mask
        log_inner_product_detail(field, tmp, tmp)


def false_positive_pair():
    p1 = bytearray([1, 0, 0, 252, 118, 139, 0, 0])
    p2 = bytearray([0, 1, 0, 3, 99, 145, 240, 0])
    field = create_field(8)


    print("are the 2 test packets orthogonal? ", check_orth(field, [p1,p2]))

    flipped_bit = 3
    chosen_column = 4
    p1_flipped = error_into_packet_chosen_bit(p1, chosen_column, flipped_bit)
    print(list(p1))
    print(list(p1_flipped))


    print("the two packets shoudnt be orthogonal after bitflipp: (false) ", check_orth(field, [p1_flipped,p2]))
    print("p1_flipped: orth: ", check_orth_packet(field, p1_flipped))
    print("p2: orth: ", check_orth_packet(field, p2))


    print("===== Retest after flipping every other bit in p1 =========")


    # we flip every other bit than the original and check if we still get a positive self orthogonality -> false positives
    false_positives = []
    cross_checked = []

    for i in list(range(0, len(p1_flipped))):
        if i == chosen_column: continue
        err_pkt = error_into_packet_chosen_bit(p1_flipped, i, flipped_bit)
        print(i)
        print(list(err_pkt))
        print("Check orth of 2 packets after different bitflip: (false) ", check_orth(field, [err_pkt,p2]))
        print("err_pkt: orth: ", check_orth_packet(field, err_pkt))
        print("p2: orth: ", check_orth_packet(field, p2))
        log_inner_product_detail(field, err_pkt, p2)

        false_positives.append(check_orth_packet(field, err_pkt))
        cross_checked.append(check_orth(field, [err_pkt,p2]))


    print("==== False Positives ====")
    print(false_positives)

    print("==== Cross Checking with another packet ====")
    print(cross_checked)



if __name__ == "__main__":
    false_positive_pair()





