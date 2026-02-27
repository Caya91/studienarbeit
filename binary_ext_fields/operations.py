import pyerasure
import pyerasure.finite_field
from icecream import ic
from typing import Any
from binary_ext_fields.custom_field import TableField


def inner_product_bytes(field: Any, x: bytes, y: bytes) -> int:
    """⟨x, y⟩ = ∑ x[i]·y[i] in GF(2^m) using PyErasure vector ops."""
    assert len(x) == len(y)
    acc = 0
    tmp = bytearray(1)

    for a, b in zip(x, y):
        tmp[0] = a
        field.vector_multiply_into(tmp, b)  # tmp[0] = a·b
        acc = field.add(acc, tmp[0])        # acc += a·b

    return acc

#TODO:


def vector_multiply_add_into(field:Any, x: bytearray, y: bytes, c: int):
    """
    Multiply the vector y with the constant c and then add the result
    to vector x.
    """

    assert len(x) == len(y)
    assert c <= field.max_value

    field.vector_multiply_into(y, c)

    tmp = bytearray(1)

    result = []
    for a, b in zip(x, y):
        tmp = field.add(a, b)        # acc += a·b
        result.append(tmp)

    assert len(result) == len(x)

    return bytearray([result])


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

