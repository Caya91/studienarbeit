from binary_ext_fields.custom_field import TableField, PRIMES_GF2M, build_tables_gf2m

from binary_ext_fields.operations import inner_product_bytes

from icecream import ic
from pprint import pprint



if __name__ == "__main__":

    m = 4
    poly = PRIMES_GF2M[m]
    ADD_GF16, MUL_GF16 = build_tables_gf2m(m, poly)

    ic(ADD_GF16, MUL_GF16)

    with open("logs/gf16_tables.txt", "w", encoding="utf-8") as f:
        f.write("# Auto-generated GF(2^{}) tables\n".format(m))
        f.write("M = {}\n".format(m))
        f.write("POLY = 0b{:b}\n\n".format(poly))


        f.write("ADD_TABLE = \n")
        pprint(ADD_GF16, stream=f, width=120)
        f.write("\n\nMUL_TABLE = \n")
        pprint(MUL_GF16, stream=f, width=120)
        f.write("\n")

    table_field = TableField(ADD_GF16, MUL_GF16, poly)

    ic(table_field.name)