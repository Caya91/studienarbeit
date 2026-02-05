import pyerasure
import pyerasure.finite_field
from icecream import ic


def inner_product_bytes(field:pyerasure.finite_field, x: bytes, y: bytes) -> int:
    """⟨x, y⟩ = ∑ x[i]·y[i] in GF(2^4) using PyErasure vector ops."""
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


def test_inner_product():
    ic(inner_product_bytes(pyerasure.finite_field.Binary4(),[5],[5])) # 5*5 = 2
    ic(inner_product_bytes(pyerasure.finite_field.Binary4(),[3],[3])) # 3*3 = 5
    ic(inner_product_bytes(pyerasure.finite_field.Binary4(),[0],[0])) # 0*0 = 0

    ic(inner_product_bytes(pyerasure.finite_field.Binary4(),[17],[17])) # should be an assertion error from pyerasure



if __name__ == "__main__":
    print("operations BIn4")