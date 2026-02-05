import os
import pyerasure
#import pyerasure.finite_field
from icecream import ic
from pyerasure_extended.inner_product_test import inner_product_bytes

def main():
    # Field GF(2^8)
    field = pyerasure.finite_field.Binary8()  # [web:129]

        #TODO:  Here we take the given data, append our generated tags 
        # and treat that as the new packets
        # these will be 

    S1 = bytearray([0, 1, 1, 0, 0, 0, 0])  # data=0, tags=[1,1,0,0,0,0]
    S2 = bytearray([0, 0, 0, 1, 1, 0, 0])
    S3 = bytearray([0, 0, 0, 0, 0, 1, 1])
    symbols_bytes = [S1, S2, S3]

    symbols = len(symbols_bytes)
    symbol_bytes = len(S1)  # 4

    encoder = pyerasure.Encoder(field, symbols, symbol_bytes)
    decoder = pyerasure.Decoder(field, symbols, symbol_bytes)

    # Build encoder block by simple concatenation
    block = bytearray()
    for s in symbols_bytes:
        assert len(s) == symbol_bytes
        block.extend(s)
    
    ic(block)

    # Install data into encoder
    encoder.set_symbols(block)

    # Helper to pretty-print one outgoing packet
    def print_packet(coeffs, symbol, label):
        print(label)
        print("  coefficients (bytes):", list(coeffs))
        print("  symbol bytes:", list(symbol))
        print()

    # Identity coefficients for 3 symbols
    c1 = bytearray([1, 0, 0])
    c2 = bytearray([0, 1, 0])
    c3 = bytearray([0, 0, 1])
    coeff_list = [c1, c2, c3]

    encoded_packets = []

    for i, coeffs in enumerate(coeff_list):
        symbol = encoder.encode_symbol(coeffs)        # encode with chosen coeffs
        print_packet(coeffs, symbol, f"PACKET {i}")
        ic(symbol)

        #TODO:  Here is the place where our wrapper works the magic
        # so after repairing, cleaning we have to return 
        # coeffs and symbol in the same form as before


        decoder.decode_symbol(symbol, coeffs)         # decode with same coeffs
        print("  decoder rank:", decoder.rank, "\n")
        
        encoded_packets.append(symbol)

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
def inner_product_mod2(x: bytes, y: bytes) -> int:
    """⟨x, y⟩ over GF(2): sum_i x_i * y_i mod 2, with x_i,y_i ∈ {0,1}."""
    assert len(x) == len(y)
    acc = 0
    for a, b in zip(x, y):
        acc ^= (a & b) & 1   # multiply in GF(2): a*b = a&b, then XOR sum
    return acc



if __name__ == "__main__":
    main()
