import pyerasure
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

if __name__ == "__main__":

    field = pyerasure.finite_field.Binary8()

    # easy tests with bytearrays that use only 1 as value

    S1 = bytearray([0, 1, 1, 0, 0, 0, 0])  # data=0, tags=[1,1,0,0,0,0]
    S2 = bytearray([0, 0, 0, 1, 1, 0, 0])
    S3 = bytearray([0, 0, 0, 0, 0, 1, 1])
    S4 = bytearray([0, 0, 0, 0, 1, 1, 1])
    S5 = bytearray([0, 0, 0, 1, 1, 1, 1])


    ic(S1,S2, inner_product_bytes(field, S1, S2))
    ic(S1,S1, inner_product_bytes(field, S1, S1))
    ic(S2,S2, inner_product_bytes(field, S2, S2))
    ic(S1,S3, inner_product_bytes(field, S1, S3))
    ic(S1,S4, inner_product_bytes(field, S1, S4))
    ic(S3,S4, inner_product_bytes(field, S3, S4))
    ic(S4,S5, inner_product_bytes(field, S4, S5)) # this is the only one that should return not zero as inner product
    ic(S5,S5, inner_product_bytes(field, S5, S5))

    print("more Tests \n")
    # more tests

    S1 = bytearray([2, 4, 3, 0, 0, 0, 0])  # data=0, tags=[1,1,0,0,0,0]
    S2 = bytearray([0, 0, 1, 2, 3, 0, 0])
    S3 = bytearray([0, 0, 0, 2, 1, 2, 5])
    S4 = bytearray([0, 0, 0, 0, 3, 4, 1])
    S5 = bytearray([0, 0, 5, 5, 5, 5, 5])

    ic(S1,S2, inner_product_bytes(field, S1, S2))
    ic(S1,S1, inner_product_bytes(field, S1, S1))
    ic(S2,S2, inner_product_bytes(field, S2, S2))
    ic(S1,S3, inner_product_bytes(field, S1, S3))
    ic(S1,S4, inner_product_bytes(field, S1, S4))
    ic(S3,S4, inner_product_bytes(field, S3, S4))
    ic(S4,S5, inner_product_bytes(field, S4, S5)) 
    ic(S5,S5, inner_product_bytes(field, S5, S5))