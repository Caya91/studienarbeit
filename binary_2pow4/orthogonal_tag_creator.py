import pyerasure
import pyerasure.finite_field
import random
from icecream import ic

from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator as _OTG

from binary_2pow4.config import field


class OrthogonalTagGenerator(_OTG):
    def __init__(self, verbose: bool = False):
        super().__init__(field)


if __name__ == "__main__":
    print("Orthogonal Tag Creator Bin 4 ")
    tag_gen = OrthogonalTagGenerator(field)
    ic(tag_gen.square_to_root)

    #test_orthogonalgenerator()
    #test_cross_generation()
    #test_case_2()
    #test_failed_packets()
    #failed_test_case()

    #generate_examples(3)

    '''
    generator=OrthogonalTagGenerator(field)


    ic(generator.square_to_root)

    ic(generator.mul_table)
    
    ic(generator.generate_tag_cross(3,0))
    ic(generator.generate_tag_cross(3,1))

    '''