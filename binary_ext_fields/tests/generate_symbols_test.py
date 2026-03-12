from icecream import ic

from binary_ext_fields.generate_symbols import *
from binary_ext_fields.custom_field import TableField, create_field


def test_generating_nonzero(field_int:int, data_fields:int, gen_size:int):
    field = create_field(field_int)
    tagged_symbols = generate_symbols_until_nonzero(field,data_fields,gen_size )
    return check_orth(field,tagged_symbols)


if __name__ == "__main__":

    
    ic( 
        test_generating_nonzero(2,3,3),
        test_generating_nonzero(3,4,4),
        test_generating_nonzero(4,4,4),
        test_generating_nonzero(5,5,5),
        test_generating_nonzero(6,5,5),
        test_generating_nonzero(7,5,5),
        test_generating_nonzero(8,5,5)
       )