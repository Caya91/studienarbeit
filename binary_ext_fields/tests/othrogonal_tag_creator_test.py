from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator

from binary_ext_fields.custom_field import TableField, PRIMES_GF2M, build_tables_gf2m

from icecream import ic

from utils.logging import get_playground_dir, print_table

if __name__ == "__main__":
    for i in range(2,9):

        prime = PRIMES_GF2M.get(i)
        add_table, mul_table = build_tables_gf2m(i, prime)
        custom_field = TableField(add_table=add_table, mul_table=mul_table, prime=prime)
        tag_gen = OrthogonalTagGenerator(custom_field)

        log_dir = get_playground_dir(f"generating_custom_OTC_test")
        log_dir.mkdir(parents=True, exist_ok=True)

        file_name = f"OTC_gf2m{i}"

        add_table_dir = log_dir / (file_name +  "add_table.txt")
        mul_table_dir = log_dir / (file_name +  "mul_table.txt")
        root_table_dir = log_dir / (file_name + "root_table.txt")

        print_table(custom_field, add_table, add_table_dir)
        tag_gen.print_mul_table(mul_table_dir)
        tag_gen.print_square_to_root_table(root_table_dir)
        ic(tag_gen.generate_tag_cross(2,3))
        ic(tag_gen.square_to_root)
        ic(tag_gen.mul_table)

    print("All OTC generated")