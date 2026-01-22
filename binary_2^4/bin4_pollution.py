import os
import pyerasure
import pyerasure.finite_field
import random
from icecream import ic
from operations_bin4.operations_bin4 import inner_product_bytes, pollute_packet, pollute_data_packet, pollute_tags_packet

from operations_bin4.operations_bin4 import MIN_INT, MAX_INT
from operations_bin4.operations_bin4 import print_ints

from orthogonal_tag_creator import OrthogonalTagGenerator
from enum import Enum
import statistics

class Pollution(Enum):
    ALL = 0
    DATA = 1
    TAG = 2

pollution = False
poll_enum: Pollution = Pollution.TAG

print_packets = True   # Print accepted packets yes or no

NUM_TRIALS = 10



def static_data():
    ic.disable()

    # Field GF(2^4)
    field = pyerasure.finite_field.Binary4()

        #TODO:  Here we take the given data, append our generated tags 
        # and treat that as the new packets
        # these will be 

    S1 = bytearray([1])  # data=1, tags=[1,]
    S2 = bytearray([3])

    data_len = len(S1)
    #generate the necessary tags t1 and t2 for both packets
    tag_gen = OrthogonalTagGenerator(field)

    tag11 = tag_gen.generate_tag(d=inner_product_bytes(field, S1,S1)) # generate self orthogonal tag
    tag12 = 0                       # first packe is only self orthogonal

    S1_orth = S1 +  bytearray([tag11,tag12])
    ic(S1_orth, S1 ,tag11 , ic(bytearray([tag11,tag12])))

    assert inner_product_bytes(field,S1_orth, S1_orth) == 0

    S2_padded = S2 + bytearray(2)
    ic(S2_padded)

    d = ic(inner_product_bytes(field, S1_orth, S2_padded),S1_orth, S2_padded)
    tag21 = tag_gen.generate_tag_cross(tag11, d= inner_product_bytes(field, S1_orth, S2_padded))  # orthogonal to
    tag22 = 0   
    ic(tag21,tag22)
    S2_orth = S2 + bytearray([tag21,tag22])
    ic(S2_orth)

    # when using bytearray be careful:
    # bytearray(1)  ->   x00
    # bytearray([1]) ->  x01

    #testing orthogonality of packets
    ic(inner_product_bytes(field, S1_orth, S2_orth))




    symbols_bytes = [S1_orth, S2_orth]

    symbols = len(symbols_bytes)
    ic(symbols)
    elements = len(S1_orth)  # 
    ic(elements)

    encoder = pyerasure.Encoder(field, symbols, elements)
    decoder = pyerasure.Decoder(field, symbols, elements)

    # Build encoder block by simple concatenation
    block = bytearray()
    for s in symbols_bytes:
        assert len(s) == elements
        block.extend(s)
    
    ic(block, len(block), len(block)/8)

    # Install data into encoder
    encoder.set_symbols(block)

    # Helper to pretty-print one outgoing packet
    def print_packet(coeffs, symbol, label):
        print(label)
        print("  coefficients (bytes):", list(coeffs))
        print("  symbol bytes:", list(symbol))
        print()

    # Identity coefficients for 3 symbols
    # For 2^4  every Byte is 2 coefficients 
    # for a 2-hex number like 0x01 in Binary 4 the Encoder will
    # interpret the last Hex as teh first and the first as the second
    # so 0x01 = (1 , 0)     as coefficients
    #    0x10 = (0 , 1)

    c1 = bytearray([0x01, 0])
    c2 = bytearray([0x10, 0])

    coeff_list = [c1, c2]
    ic(coeff_list)


# TODO: So for generating and multiplying coefficients we have to implement some function that
# does taht reliably for us 


    received_packets = []
    orig_encoded_packets = []   # packets that cam directly from encoder

    for i, coeffs in enumerate(coeff_list):
        ic(i,coeffs)
        symbol = encoder.encode_symbol(coeffs)        # encode with chosen coeffs
        
        orig_encoded_packets.append(symbol.copy())


        # insert our polluted packet here for packet 2 atm. will be changed down the line
        if i == 1 and pollution:
            match poll_enum:
                case Pollution.ALL: symbol = pollute_packet(symbol)
                case Pollution.DATA : symbol = pollute_data_packet(data_len, symbol)
                case Pollution.TAG : symbol = pollute_tags_packet(data_len, symbol)
                case _: print("no matching Pollution", poll_enum)


        # print_packet(coeffs, symbol, f"PACKET {i}")
        ic(symbol)

        #TODO:  Here is the place where our wrapper works the magic
        # so after repairing, cleaning we have to return 
        # coeffs and symbol in the same form as before



        # The decoder changes The symbols that you feed him with "decode_symbol()"
        # so if he decodes a symbol it will mutate the symbol you give him


        ic("before decode", symbol)
        decoder.decode_symbol(symbol, coeffs)         # decode with same coeffs
        # print("  decoder rank:", decoder.rank, "\n")
        ic("after decode", symbol)
        
        received_packets.append(ic(symbol))
        ic(received_packets,symbol)

    #print("decoder complete:", decoder.is_complete())
    #print("decoded == original:", decoder.block_data() == block)

    P1 = received_packets[0]
    P2 = received_packets[1]

    #ic(orig_encoded_packets)
    #ic(received_packets)
    #ic(P1,P2)

    ic(inner_product_bytes(field,P1,P1))
    ic(inner_product_bytes(field,P1,P2))
    ic(inner_product_bytes(field,P2,P2))

# TODO: this implementation is wrong and only works with 1's as data for XORING
# because we only use the first of 8 bits in the byte and addition is just XOring that
    accept = (
        inner_product_bytes(field,P1,P1) == 0 and
        inner_product_bytes(field,P1,P2) == 0 and
        inner_product_bytes(field,P2,P2) == 0
    )

    ic.enable()
    if accept:
        ic(orig_encoded_packets, received_packets)
    ic.disable()

    return accept

def random_data():
    '''
    random values for data fields
    len_data_fields = 2    # 
    '''

    ic.disable()

    # Field GF(2^4)
    field = pyerasure.finite_field.Binary4()

        #TODO:  Here we take the given data, append our generated tags 
        # and treat that as the new packets
        # these will be 

    data_len = 2

    S1 = bytearray([random.randint(MIN_INT, MAX_INT),random.randint(MIN_INT, MAX_INT)])  
    S2 = bytearray([random.randint(MIN_INT, MAX_INT),random.randint(MIN_INT, MAX_INT)])


    data_len = len(S1)
    #generate the necessary tags t1 and t2 for both packets
    tag_gen = OrthogonalTagGenerator(field)

    tag11 = tag_gen.generate_tag(d=inner_product_bytes(field, S1,S1)) # generate self orthogonal tag
    tag12 = 0                       # first packe is only self orthogonal

    S1_orth = S1 +  bytearray([tag11,tag12])
    ic(S1_orth, S1 ,tag11 , ic(bytearray([tag11,tag12])))

    assert inner_product_bytes(field,S1_orth, S1_orth) == 0

    S2_padded = S2 + bytearray(2)
    ic(S2_padded)

    d = ic(inner_product_bytes(field, S1_orth, S2_padded))
    tag21 = tag_gen.generate_tag_cross(tag11, d)  # orthogonal to S1_orth
    S2_padded[data_len] = tag21
    tag22 = tag_gen.generate_tag(d= inner_product_bytes(field,S2_padded, S2_padded))
    
    S2_padded[data_len+1] = tag22

    ic(S2_padded,tag21,tag22)
    S2_orth = S2_padded.copy()
    ic(S2_orth)

    # when using bytearray be careful:
    # bytearray(1)  ->   x00
    # bytearray([1]) ->  x01

    #testing orthogonality of packets
    ic(inner_product_bytes(field, S1_orth, S2_orth))




    symbols_bytes = [S1_orth, S2_orth]

    symbols = len(symbols_bytes)
    ic(symbols)
    elements = len(S1_orth)  # 
    ic(elements)

    encoder = pyerasure.Encoder(field, symbols, elements)
    decoder = pyerasure.Decoder(field, symbols, elements)

    # Build encoder block by simple concatenation
    block = bytearray()
    for s in symbols_bytes:
        assert len(s) == elements
        block.extend(s)
    
    ic(block, len(block), len(block)/8)

    # Install data into encoder
    encoder.set_symbols(block)

    # Helper to pretty-print one outgoing packet
    def print_packet(coeffs, symbol, label):
        print(label)
        print("  coefficients (bytes):", list(coeffs))
        print("  symbol bytes:", list(symbol))
        print()

    # Identity coefficients for 3 symbols
    # For 2^4  every Byte is 2 coefficients 
    # for a 2-hex number like 0x01 in Binary 4 the Encoder will
    # interpret the last Hex as teh first and the first as the second
    # so 0x01 = (1 , 0)     as coefficients
    #    0x10 = (0 , 1)

    c1 = bytearray([0x01, 0])
    c2 = bytearray([0x10, 0])

    coeff_list = [c1, c2]
    ic(coeff_list)


# TODO: So for generating and multiplying coefficients we have to implement some function that
# does taht reliably for us 


    received_packets = []
    orig_encoded_packets = []   # packets that cam directly from encoder

    for i, coeffs in enumerate(coeff_list):
        ic(i,coeffs)
        symbol = encoder.encode_symbol(coeffs)        # encode with chosen coeffs
        
        orig_encoded_packets.append(symbol.copy())


        # insert our polluted packet here for packet 2 atm. will be changed down the line
        if i == 1 and pollution:
            match poll_enum:
                case Pollution.ALL: symbol = pollute_packet(symbol)
                case Pollution.DATA : symbol = pollute_data_packet(data_len, symbol)
                case Pollution.TAG : symbol = pollute_tags_packet(data_len, symbol)
                case _: print("no matching Pollution", poll_enum)


        # print_packet(coeffs, symbol, f"PACKET {i}")
        ic(symbol)

        #TODO:  Here is the place where our wrapper works the magic
        # so after repairing, cleaning we have to return 
        # coeffs and symbol in the same form as before



        # The decoder changes The symbols that you feed him with "decode_symbol()"
        # so if he decodes a symbol it will mutate the symbol you give him


        ic("before decode", symbol)
        decoder.decode_symbol(symbol, coeffs)         # decode with same coeffs
        # print("  decoder rank:", decoder.rank, "\n")
        ic("after decode", symbol)
        
        received_packets.append(ic(symbol))
        ic(received_packets,symbol)

    #print("decoder complete:", decoder.is_complete())
    #print("decoded == original:", decoder.block_data() == block)

    P1 = received_packets[0]
    P2 = received_packets[1]

    #ic(orig_encoded_packets)
    #ic(received_packets)
    #ic(P1,P2)

    ic(inner_product_bytes(field,P1,P1))
    ic(inner_product_bytes(field,P1,P2))
    ic(inner_product_bytes(field,P2,P2))

    # accept if all inner products are 0

    accept = (
        inner_product_bytes(field,P1,P1) == 0 and
        inner_product_bytes(field,P1,P2) == 0 and
        inner_product_bytes(field,P2,P2) == 0
    )

    t11 = S1_orth[data_len]

    if t11 == 0 and not accept:
        accept = True
        print("EDGE CASE: t11 was 0")
        print_ints(S1_orth)
        print_ints(S2_orth)






    ic.enable()
    if accept and pollution and print_packets:
        for i,packet in enumerate(orig_encoded_packets):
            print("Original Packets: ", i)
            print_ints(packet)
            print("Received packets: ", i)
            print_ints(received_packets[i])

    # if there is no pollution all the packets should be accepted
    # this is to find the errors here

    if not accept and not pollution and print_packets:
        for i,packet in enumerate(orig_encoded_packets):
            print("Original Packets: ", i)
            print_ints(packet)
            print("Received packets: ", i)
            print_ints(received_packets[i])

        ic(inner_product_bytes(field,P1,P1),
        inner_product_bytes(field,P1,P2),
        inner_product_bytes(field,P2,P2))



    ic.disable()

    return accept

if __name__ == "__main__":
    accepts = []

    for trial in range(NUM_TRIALS):
        accepts.append(random_data())

    ic.enable()
    prob = statistics.mean(accepts)
    std = statistics.stdev(accepts) / (NUM_TRIALS ** 0.5) if len(accepts) > 1 else 0

    total_accepted = accepts.count(1)/NUM_TRIALS
    ic(total_accepted)
    #ic(accepts)
    ic(prob,std)

    ic.disable()
    print(f"Acceptance probability: {prob:.6f} ± {std:.6f} over {NUM_TRIALS} trials")
