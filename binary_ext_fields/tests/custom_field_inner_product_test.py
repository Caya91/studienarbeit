from binary_ext_fields.custom_field import TableField, PRIMES_GF2M, build_tables_gf2m

from binary_ext_fields.operations import inner_product_bytes

from icecream import ic

if __name__ == "__main__":

    S1 = bytearray([1,2,3,3])
    S2 = bytearray([1,3,2,1])
    for i in range(2,9):

        prime = PRIMES_GF2M.get(i)
        add_table, mul_table = build_tables_gf2m(i,prime)
        field = TableField(add_table=add_table, mul_table=mul_table, prime=prime)

        ic(inner_product_bytes(field, S1, S2), field.max_value, S1, S2)



