import os
import pyerasure
import pyerasure.finite_field
from icecream import ic
from operations_bin4.operations_bin4 import inner_product_bytes
from orthogonal_tag_creator import OrthogonalTagGenerator

def gen_polluted_packet():
    poll_packet = []


    return poll_packet


def main():
    # Field GF(2^4)
    field = pyerasure.finite_field.Binary4()

        #TODO:  Here we take the given data, append our generated tags 
        # and treat that as the new packets
        # these will be 

    S1 = bytearray([1])  # data=1, tags=[1,]
    S2 = bytearray([3])

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

    ic.disable()
    symbols_bytes = [S1, S2]

    symbols = len(symbols_bytes)
    ic(symbols)
    elements = len(S1)  # 
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


    encoded_packets = []

    for i, coeffs in enumerate(coeff_list):
        ic(i,coeffs)
        symbol = encoder.encode_symbol(coeffs)        # encode with chosen coeffs
        print_packet(coeffs, symbol, f"PACKET {i}")
        ic(symbol)

        #TODO:  Here is the place where our wrapper works the magic
        # so after repairing, cleaning we have to return 
        # coeffs and symbol in the same form as before



        # The decoder changes The symbols that you feed him with "decode_symbol()"
        # so if he decodes a symbol it will mutate the symbol you give him
        ic("before decode", symbol)
        decoder.decode_symbol(symbol, coeffs)         # decode with same coeffs
        print("  decoder rank:", decoder.rank, "\n")
        ic("after decode", symbol)
        
        encoded_packets.append(ic(symbol))
        ic(encoded_packets,symbol)

    print("decoder complete:", decoder.is_complete())
    print("decoded == original:", decoder.block_data() == block)

    P1, P2 = encoded_packets
    ic(P1,P2)

    ic(inner_product_bytes(field,P1,P1))
    ic(inner_product_bytes(field,P1,P2))
    ic(inner_product_bytes(field,P2,P2))

# TODO: this implementation is wrong and only works with 1's as data for XORING
# because we only use the first of 8 bits in the byte and addition is just XOring that




if __name__ == "__main__":
    main()
