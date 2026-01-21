import pyerasure.finite_field
import random
import pyerasure
from icecream import ic

# My own files
from inner_product_test import inner_product_bytes
from precomputed_squares_bin8 import OrthogonalTagGenerator
from element_multiplication_bin8 import multiply





field = pyerasure.finite_field.Binary8()
tag_gen = OrthogonalTagGenerator(field)



def generate_self_orthogonal_tags(field, d: bytes) -> tuple[int, int]:
    """
    For data bytes d, return tags t1,t2 where ⟨[d,t1,t2],[d,t1,t2]⟩ = 0.
    """

    # Pick random t1 (non-zero to ensure linear independence)
    t1 = random.randrange(1, field.max_value)
    d_sq = inner_product_bytes(field,d,d) # d^2     
    t1_sq = multiply(field, t1, t1)
    # Compute required t2² = -(d² + t1²)

    target = field.add(d_sq, t1_sq)  # d² + t1²
    
    t2 = tag_gen.square_to_root.get(target)
    
    return t1, t2


#TODO: function togenerate the tags to be orthgonal to previous packet
# should be be possible with 1 or more packets
# tag 1 and 2  or corresponding to packet 1
# tag 3 and 4 or corresponding to packet 2  etc
#

def test_tag_generation():


    S2 = bytearray([0, 0, 1, 2, 3, 4, 0])
    S3 = bytearray([0, 0, 0, 2, 1, 2, 5])


    d = S2  # e.g., take first 5 bytes of S2 as data
    t1, t2 = generate_self_orthogonal_tags(field, d)
    ic(t1,t2)

    packet = bytearray(d) + bytearray([t1, t2])
    ip = inner_product_bytes(field, packet, packet)
    print("packet:", list(packet), "⟨packet,packet⟩ =", ip)
    assert ip == 0

if __name__ == "__main__":
    test_tag_generation()