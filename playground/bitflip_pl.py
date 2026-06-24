from itertools import combinations
from icecream import ic


def flip_bit(byte: int, position: int) -> int:
    """Flippe das BIt an Position """


    return byte ^ (1 << position)


def flip_bit_2(byte: int, position: int) -> int:
    """Flippe das BIt an Position """
    hd = 2








    return byte ^ (1 << position)


def bit_flip_candidates(byte: int, max_hamming_dist: int, n_bits: int = 8):
    '''Generiere alle möglichen Bitflips bis zur gegebenen Hamming Distanz.
    Yields: (flipped_byte, mask, distance)'''
    #TODO: HIER gehts weiter

    for dist in range(1, max_hamming_dist + 1):
        #ic(dist)
        #ic(n_bits, list(combinations(range(n_bits), dist)))
        for positions in combinations(range(n_bits), dist):
            #ic(positions)
            mask = 0
            for p in positions:
                mask |= (1 << p)
            yield byte ^ mask, mask, dist

def test_bitflip():
    byte = 0b00000000

    print(byte)

    for i in range(8):
        flipped = flip_bit(byte, i)
        print(f"Bit {i} geflippt: {flipped:08b} ({flipped})")    


if __name__ == "__main__":


    byte = 0b00000000  

    for flipped, mask, dist in bit_flip_candidates(byte, max_hamming_dist=2, n_bits=4):
        print(f"dist={dist}  mask={mask:08b}  result={flipped:08b} ({flipped})")