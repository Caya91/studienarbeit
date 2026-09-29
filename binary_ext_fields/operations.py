import pyerasure
import pyerasure.finite_field
from icecream import ic
from typing import Any
from binary_ext_fields.custom_field import TableField


def inner_product_bytes(field: Any, x: bytes, y: bytes) -> int:
    """⟨x, y⟩ = ∑ x[i]·y[i] in GF(2^m) using PyErasure vector ops.

    Fast path (2026-09-29): a field exposing `inner_product` (TableField / CountingField)
    computes the same sum by direct table lookups and charges the same op counts
    (len(x) muls + len(x) adds, phase-attributed) -- identical result and counts to the
    per-element loop below, ~10x faster. Other fields (pyerasure) use the loop."""
    assert len(x) == len(y)
    fast = getattr(field, "inner_product", None)
    if fast is not None:
        return fast(x, y)
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

