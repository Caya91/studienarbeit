from binary_ext_fields.log_utils import clear_logs
from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator as OTC_custom

from binary_ext_fields.custom_field import TableField, build_tables_gf2m, PRIMES_GF2M
from binary_ext_fields.generate_symbols import generate_symbols_random, check_orth


from utils.log_helpers import get_run_log_dir, get_field_subdir, save_generation_txt, print_generation
from utils.plot_utils import plot_acceptance_rates_comparison, get_playground_dir

import pathlib
from pathlib import Path

from icecream import ic
import statistics
import random
from typing import Any


def recode(field: Any, generation:list[bytearray], count: int) -> list[bytearray]:
    '''returns <count> random recoded packets of our generation'''
#TODO: this recodes 2 random packets after multiplying them by a scalar, for real RLNC we need more
#  
    min_value = 1
    max_value = table_field.max_value

    pckts = []
    for i in range(count):
        pkt1 = random.choice(generation).copy()
        pkt2 = random.choice(generation).copy()

        table_field.vector_multiply_into(pkt1, random.randint(min_value, max_value))

        result = table_field.vector_multiply_add_into(pkt1,pkt2,random.randint(min_value, max_value))

        pckts.append(result)

    return pckts



if __name__ == "__main__":
    clear_logs()
    dir = get_playground_dir("recoding_pl.txt")

    accepts = False
    while not accepts:
        print("playground")

        data_fields = 3
        gen_size = 5
        field = 3

        prime = PRIMES_GF2M.get(field)
        add_table, mul_table = build_tables_gf2m(field,prime)
        table_field = TableField(add_table, mul_table, prime)
        tag_gen = OTC_custom(table_field)

        generation = generate_symbols_random(0,table_field.max_value,data_fields,gen_size)

        # new matrix with Identity matrix in the front

        gen_w_coefficients = []
        generation_size = len(generation)

        coefficients = bytearray(generation_size)


        for i, pkt in enumerate(generation):
            coefficients = bytearray(generation_size)
            coefficients[i] = 1
    
            gen_w_coefficients.append(coefficients.copy() + pkt.copy())

        print_generation(gen_w_coefficients)



        tagged_gen = tag_gen.generate_all_tags(gen_w_coefficients)

        accepts = (check_orth(table_field, tagged_gen, dir)) # loop until a generation doesnt have the 0 tag error

    print(accepts)
    print(tagged_gen)
    print_generation(tagged_gen)




    print(tagged_gen[0])

    print_generation(tagged_gen)

# test recode function
    recoded_packets = recode(table_field, tagged_gen, 5)

    print_generation(recoded_packets)

    print_generation(tagged_gen)

    ic(check_orth(table_field, recoded_packets))

# recode manual test
 
    '''
    tmp1 =table_field.vector_multiply_add_into(tagged_gen[0],tagged_gen[1],3) 

    tmp2 =table_field.vector_multiply_add_into(tagged_gen[2],tagged_gen[4],6) 

# check if still orthogonal to each other


    boli = check_orth(table_field,[tmp1, tmp2], dir)

    print(boli)
    print_generation(tagged_gen)

# recode randomly

    min_value = 1
    max_value = table_field.max_value

    pkt1 = random.choice(tagged_gen).copy()
    pkt2 = random.choice(tagged_gen).copy()


    pakte = [pkt1, pkt2]
    print_generation(pakte)

    table_field.vector_multiply_into(pkt1, random.randint(min_value, max_value))
    table_field.vector_multiply_into(pkt2, random.randint(min_value, max_value))

    print_generation(pakte)

    boli = check_orth(table_field,[pkt1, pkt2], dir)

    print(boli)
    print_generation(tagged_gen)


    # tmp1_random =     


    '''


    '''


    '''
