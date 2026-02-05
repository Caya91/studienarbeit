import pyerasure
import pyerasure.finite_field

from binary_2pow8.config import field, MIN_INT, MAX_INT
from binary_ext_fields.operations import inner_product_bytes as _inner_product_bytes, print_ints as _print_ints

from icecream import ic



def inner_product_bytes_bin8( x: bytes, y: bytes) -> int:
    return _inner_product_bytes(field,x=x,y=y)

def pretty_bytearray(ba, name="ba"):
    ints = ', '.join(map(str, ba))
    hexs = ba.hex(' ')
    bins = ', '.join(f'{x:04b}' for x in ba)
    print(f"{name}:\n  ints: [{ints}]\n  hex:  {hexs}\n  bin:  [{bins}]")

print_ints = _print_ints

'''
def print_ints(ba, name="ba"):
    print(f"{name}: length: {len(ba)} [{', '.join(map(str, ba))}]")
'''

'''
def test_inner_product():
    ic(inner_product_bytes(pyerasure.finite_field.Binary4(),[5],[5])) # 5*5 = 2
    ic(inner_product_bytes(pyerasure.finite_field.Binary4(),[3],[3])) # 3*3 = 5
    ic(inner_product_bytes(pyerasure.finite_field.Binary4(),[0],[0])) # 0*0 = 0

    ic(inner_product_bytes(pyerasure.finite_field.Binary4(),[17],[17])) # should be an assertion error from pyerasure
'''


if __name__ == "__main__":
    print("operations BIn4")