import os
import pyerasure
#import pyerasure.finite_field
from icecream import ic

def inner_product_bytes(field, x: bytes, y: bytes) -> int:
    """⟨x, y⟩ = ∑ x[i]·y[i] in GF(2^8) using PyErasure vector ops."""
    assert len(x) == len(y)
    acc = 0
    tmp = bytearray(1)

    for a, b in zip(x, y):
        tmp[0] = a
        field.vector_multiply_into(tmp, b)  # tmp[0] = a·b
        acc = field.add(acc, tmp[0])        # acc += a·b

    return acc


def main():
    # Field GF(2^4)
    field = pyerasure.finite_field.Binary4()

        #TODO:  Here we take the given data, append our generated tags 
        # and treat that as the new packets
        # these will be 

    S1 = bytearray([0, 1, 1, 0, 0, 0, 0, 0])  # data=0, tags=[1,1,0,0,0,0]
    S2 = bytearray([0, 0, 0, 1, 1, 0, 0, 0])
    S3 = bytearray([0, 0, 0, 0, 0, 1, 1, 0])
    symbols_bytes = [S1, S2, S3]

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
    c3 = bytearray([0, 0x09])
    coeff_list = [c1, c2, c3]
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

    P1, P2, P3 = encoded_packets
    ic(P1,P2,P3)

    ic(inner_product_bytes(field,P1,P1))
    ic(inner_product_bytes(field,P2,P2))
    ic(inner_product_bytes(field,P3,P3))
    ic(inner_product_bytes(field,P1,P2))
    ic(inner_product_bytes(field,P1,P3))
    ic(inner_product_bytes(field,P2,P3))


# TODO: this implementation is wrong and only works with 1's as data for XORING
# because we only use the first of 8 bits in the byte and addition is just XOring that




if __name__ == "__main__":
    main()
