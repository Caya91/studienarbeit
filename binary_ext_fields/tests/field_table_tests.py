from binary_ext_fields.custom_field import build_tables_gf2m, PRIMES_GF2M

from binary_2pow8.tables_2pow8 import gf255_add_table, gf255_mul_table
from binary_2pow4.tables_2pow4 import gf16_add_table, gf16_mul_table
from icecream import ic

def tables_equal(t1: list[list[int]], t2: list[list[int]]) -> bool:
    return t1 == t2


def assert_tables_equal(t1, t2):
    assert len(t1) == len(t2), "Different number of rows"
    for i, (row1, row2) in enumerate(zip(t1, t2)):
        assert len(row1) == len(row2), f"Row {i}: different length"
        for j, (a, b) in enumerate(zip(row1, row2)):
            if a != b:
                raise AssertionError(
                    f"Mismatch at ({i}, {j}): {a} != {b}"
                )


if __name__ == "__main__":

    m = 4
    prime = PRIMES_GF2M.get(m)
    ic(prime, bin(prime))

    add_table_custom, mul_table_custom = build_tables_gf2m(m, prime)

    ic(add_table_custom, mul_table_custom)

    add_table = gf16_add_table()
    mul_table = gf16_mul_table()

    ic(add_table, mul_table)

    ic(tables_equal(add_table, add_table_custom))
    ic(tables_equal(mul_table, mul_table_custom))



    m = 8
    prime = PRIMES_GF2M.get(m)
    ic(m, prime)

    add_table_custom, mul_table_custom = build_tables_gf2m(m, prime)

    add_table = gf255_add_table()
    mul_table = gf255_mul_table()


    ic(tables_equal(add_table, add_table_custom))
    ic(tables_equal(mul_table, mul_table_custom))

    ic(mul_table, mul_table_custom)




