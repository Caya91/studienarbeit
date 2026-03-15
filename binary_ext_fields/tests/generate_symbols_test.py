from icecream import ic

from binary_ext_fields.generate_symbols import *
from binary_ext_fields.custom_field import TableField, create_field
from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator as OTC

from utils.log_helpers import log_generation_detail, print_generation

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


if __name__ == "__main__":

    field_int = 3
    field = create_field(field_int)
    data_size = 3
    gen_size = 3


    generation = generate_symbols_bitshift(field, data_size, gen_size)
    otc = OTC(field)
    tagged_generation = otc.generate_all_tags_bitshift(generation)
    ic(generation)
    ic(tagged_generation)

    dir = get_playground_dir("bitshift")
    ic(check_orth(field,tagged_generation, dir))
    log_generation_detail(tagged_generation, field)
    print_generation(tagged_generation)