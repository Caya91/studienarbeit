from icecream import ic

from binary_ext_fields.generate_symbols import *
from binary_ext_fields.rref import invert_pivot_rows, calculate_rref
from binary_ext_fields.custom_field import TableField, create_field
from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator as OTC

from utils.log_helpers import log_generation_detail, print_generation, make_ic_logger

def test_generating_nonzero(field_int:int, data_fields:int, gen_size:int):
    field = create_field(field_int)
    tagged_symbols = generate_symbols_until_nonzero(field,data_fields,gen_size )
    return check_orth(field,tagged_symbols)

def test_nonzero():
 ic( 
        test_generating_nonzero(2,3,3),
        test_generating_nonzero(3,4,4),
        test_generating_nonzero(4,4,4),
        test_generating_nonzero(5,5,5),
        test_generating_nonzero(6,5,5),
        test_generating_nonzero(7,5,5),
        test_generating_nonzero(8,5,5)
       )


def test_general_bitshift():
   
    field_int = 3
    field = create_field(field_int)
    data_size = 3
    gen_size = 3

    generation = generate_symbols_bitshift(field, data_size, gen_size)
    otc = OTC(field)
    tagged_generation = otc.generate_all_tags_bitshift(generation)

    dir = get_playground_dir("bitshift")
    log_generation_detail(tagged_generation, field)
    print_generation(tagged_generation)

    return  check_orth(field,tagged_generation, dir)

def test_zero_tag_error_example(field_int:int, data_fields:int, gen_size:int):

    field = create_field(field_int)
    generation = generate_with_zero_tag_error(field,data_fields, gen_size )


    return generation
   


def test_generation_and_rref():
    field_int = 3
    data_fields = 2
    gen_size= 3


    dir = get_playground_dir("test_string.txt")
    ic(dir)

    ic.configureOutput(outputFunction=make_ic_logger(dir))
    field = create_field(field_int)

    generation = generate_symbols_until_nonzero(field,data_fields, gen_size, coefficients=True )
    ic(generation)

    recoded_packets = recode_rlnc_without_coeffs(field, generation, gen_size, count=7)
    ic(recoded_packets)

    partial_rref, cleaned_rref = calculate_rref(recoded_packets, field, gen_size)
    ic(partial_rref, cleaned_rref)
    
    inverted_rref = invert_pivot_rows(cleaned_rref, field, gen_size)
    ic(inverted_rref)

    return True


if __name__ == "__main__":
    #ic(test_generation_and_rref())

    field_int = 3
    data_fields = 3
    gen_size = 3

    ic(test_zero_tag_error_example(field_int, data_fields, gen_size))