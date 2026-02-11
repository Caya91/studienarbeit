from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator

from binary_ext_fields.custom_field import TableField, PRIMES_GF2M, build_tables_gf2m
from binary_ext_fields.operations import inner_product_bytes

from icecream import ic
import random

from utils.log_helpers import get_playground_dir, print_table

def test_mul_table(m:int):
    '''Test GF(2^m) multiplication table'''
    prime = PRIMES_GF2M[m]
    add_table, mul_table = build_tables_gf2m(m, prime)
    field = TableField(add_table=add_table, mul_table=mul_table, prime=prime)
    
    tag_gen = OrthogonalTagGenerator(field)
    
    # Test multiplication table completeness
    print(f"\n=== Testing GF(2^{m}) ===")
    print(f"Field max_value: {field.max_value}")
    print(f"Mul table size: {len(tag_gen.mul_table)} x {len(tag_gen.mul_table[0])}")
    
    # Check: For each t1, what values are achievable?
    t1 = 5  # Example tag value
    achievable = set(tag_gen.mul_table[t1])
    print(f"\nFor t1={t1}, achievable products: {sorted(achievable)}")
    print(f"Missing values: {set(range(field.max_value + 1)) - achievable}")
    
    # Test problematic case
    print("\n=== Simulating problematic scenario ===")
    # Create two random packets
    pkt1 = bytearray([random.randint(0, field.max_value) for _ in range(10)])
    pkt2 = bytearray([random.randint(0, field.max_value) for _ in range(10)])
    
    # Compute inner product
    d = inner_product_bytes(field, pkt1, pkt2)
    t1 = random.randint(1, field.max_value)
    
    print(f"t1 = {t1}")
    print(f"d (inner product) = {d}")
    print(f"Is d in mul_table[{t1}]? {d in tag_gen.mul_table[t1]}")
    
    if d not in tag_gen.mul_table[t1]:
        print(f"❌ PROBLEM: d={d} not achievable with t1={t1}")
        print(f"Row {t1} contains: {tag_gen.mul_table[t1]}")


def test_generating_otc():
    

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
        #ic(tag_gen.generate_tag_cross(2,3))
        #ic(tag_gen.square_to_root)
        #ic(tag_gen.mul_table)

    print("All OTC generated")



if __name__ == "__main__":

    test_mul_table(6)
    test_generating_otc()