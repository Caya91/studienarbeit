import pyerasure
import pyerasure.finite_field
import random
from icecream import ic
from binary_2pow4.operations_bin4 import inner_product_bytes

verbose = False


field = pyerasure.finite_field.Binary4()

class OrthogonalTagGenerator:
    def __init__(self, field):
        self.field = field
        self.square_to_root = {}  # key: square  ; value: root
        self.mul_table = []

        tmp = bytearray(1)
        for x in range(field.max_value + 1):
            tmp[0] = x
            field.vector_multiply_into(tmp, x)  # tmp[0] = x * x   mod fieldsize
            sq = tmp[0]
            if sq not in self.square_to_root:
                self.square_to_root[sq] = x  # write square, root pair into dict
        
        self.mul_table = []
        for i in range(field.max_value +1):
            row = []
            for j in range (field.max_value + 1):
                x = [j]
                field.vector_multiply_into(x,i)
                row.append(x[0])
            self.mul_table.append(row)

    
    def generate_tag(self, d: int) ->  int:

        assert d <= self.field.max_value

        t2 = self.square_to_root.get(d, None)
        if t2 is not None:
            return t2
        
        # Rare fallback: try next t1
        #ic("t2 should not be none", t2)
        return None # self.tags(d)  # Recurse (very rare
    

    def generate_tag_cross(self, t1: int, d: int) ->  int:
        '''
        for a the given value of the tag of another packet and the inner product d = <t1,t2>
        generates the tag to make the packet orthogonal
        by looking up the given tag in a multiplication table and looking for the element that
        generates the same value

        '''
        assert d <= self.field.max_value
        assert t1 <= self.field.max_value

        # falls der Tag des anderen Packets 0 ist -> wähle einen Tag random aus
        ic.disable()
        if verbose:
            ic.enable()
            
        
        if t1 == 0:
            return random.randint(0, field.max_value)
        #ic(self.mul_table[t1])
        for i, element in enumerate(self.mul_table[t1]):
            if element == d:
                t2 = i
                #ic("t1 * i = d", t1, i, d)
                #ic("check mit inner product, should be d", inner_product_bytes(field, bytearray([t1]),bytearray([i])))
                return t2
        
        # Rare fallback:
        #ic("t2 should not be none for cross tag generation", t2)
        return None # self.tags(d)  # Recurse (very rare

    def generate_all_tags(self, generation:list[bytearray]):
        # TODO: implement a flag and function that switches the order of packets when there is one that is has self ortho tag = 0 
        # or make a new function for that


        gen_size = len(generation)
        data_len = len(generation[0]) - gen_size

        new_symbols = []

        i = data_len

        #ic(generation)

        for count, symbol in enumerate(generation):
            #ic("OUTER LOOP", i, count, symbol)

            i = data_len + 1

            new_symbol = symbol.copy()
            for tag_nr in range(count + 1):

                #ic("INNER LOOP", tag_nr, count)
                if tag_nr == count: # if the tag_nr and the count is the same, we calculate our own inner product, to make packet self orthogonal
                    tag = self.generate_tag(inner_product_bytes(field, new_symbol, new_symbol))
                    new_symbol[data_len + tag_nr] = tag
                    new_symbols.append(new_symbol)
                    continue

                corresponding_packet = new_symbols[tag_nr]  # tag_nr is also the corrseponding symbol in the generation, so we take innerproduct with that packet

                tag = self.generate_tag_cross(corresponding_packet[data_len + tag_nr ],inner_product_bytes(field,new_symbol, corresponding_packet))

                new_symbol[data_len + tag_nr] = tag


        return new_symbols


## TESTING

def gf_square(field, x: int) -> int:
    tmp = bytearray(1)
    tmp[0] = x
    field.vector_multiply_into(tmp, x)
    return tmp[0]

def multiply_helper(field, x:int, y:int) -> int:
    assert x <= field.max_value
    assert y <= field.max_value

    tmp = bytearray(1)
    tmp[0] = x
    field.vector_multiply_into(tmp, y)
    return tmp[0]

if __name__ == "__main__":
    print("Orthogonal Tag Creator ")
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