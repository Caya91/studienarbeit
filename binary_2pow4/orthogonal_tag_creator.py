import pyerasure
import pyerasure.finite_field
import random
from icecream import ic
from operations_bin4.operations_bin4 import inner_product_bytes, print_ints
from operations_bin4.operations_bin4 import MIN_INT, MAX_INT

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
        ic(self.mul_table[t1])
        for i, element in enumerate(self.mul_table[t1]):
            if element == d:
                t2 = i
                ic("t1 * i = d", t1, i, d)
                ic("check mit inner product, should be d", inner_product_bytes(field, bytearray([t1]),bytearray([i])))
                return t2
        
        # Rare fallback:
        ic("t2 should not be none for cross tag generation", t2)
        return None # self.tags(d)  # Recurse (very rare



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

def test_orthogonalgenerator():
    generator = OrthogonalTagGenerator(field)
    
    tests = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0x0A,0x0B,0x0C, 0x0D, 0x0E, 0x0F]

    for a in tests:
        s = gf_square(field, a)
        r = generator.generate_tag(s)
        print(f"a={a:3d} (0x{a:1X}) (0b{a:04b})  a^2={s:3d} (0x{s:1X}) (0b{s:04b})  root={r:3d} (0x{r:1X}) (0b{r:04b})")
        assert gf_square(field, r) == s
    print("All squares map back to a valid root")

    ic(generator.square_to_root)

def test_cross_generation():
    generator = OrthogonalTagGenerator(field)

    test_tags = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0x0A,0x0B,0x0C, 0x0D, 0x0E, 0x0F]
    test_residue = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0x0A,0x0B,0x0C, 0x0D, 0x0E, 0x0F]
    for t1 in test_tags:
        for d in  test_residue:
            new_tag = generator.generate_tag_cross(t1,d)
            new_tag_test = new_tag
            ic(t1,new_tag_test,d)
            ic(multiply_helper(field, t1,new_tag_test))

            if t1 == 0:
                continue
            assert d == multiply_helper(field, t1,new_tag_test)
    print("all multiplication tests worked out")

    return None

def test_case_1():

    S1 = bytearray([random.randint(MIN_INT, MAX_INT)])  
    S2 = bytearray([random.randint(MIN_INT, MAX_INT)])

    ic(S1,S2)

    data_len = len(S1)
    tag_gen = OrthogonalTagGenerator(field)

    tag11 = tag_gen.generate_tag(d=inner_product_bytes(field, S1,S1)) # generate self orthogonal tag
    tag12 = 0                       # first packet is only self orthogonal

    S1_orth = S1 +  bytearray([tag11,tag12])

    ic(S1_orth, S1 ,tag11 , ic(bytearray([tag11,tag12])))

    assert inner_product_bytes(field,S1_orth, S1_orth) == 0

    S2_padded = S2 + bytearray(2)
    ic(S2_padded)
    
    d = ic(inner_product_bytes(field, S1_orth, S2_padded),S1_orth, S2_padded)
    tag21 = tag_gen.generate_tag_cross(tag11, d= inner_product_bytes(field, S1_orth, S2_padded))  # orthogonal to S1 
    S2_padded[1] = tag21
    ic("S2_padded after adding the tag21", S2_padded, tag21)
    tag22 = tag_gen.generate_tag(d= inner_product_bytes(field,S2_padded, S2_padded))
    ic(tag22)


    ic(tag21,tag22)
    S2_orth = S2 + bytearray([tag21,tag22])
    ic(S2_orth)

    # when using bytearray be careful:
    # bytearray(1)  ->   x00
    # bytearray([1]) ->  x01

    #testing orthogonality of packets
    ic(S1_orth, S2_orth)
    ic(inner_product_bytes(field, S1_orth, S1_orth))
    ic(inner_product_bytes(field, S1_orth, S2_orth))
    ic(inner_product_bytes(field, S2_orth, S2_orth))

    return

def test_case_2():
    # test case with 2 data fields
    
    data_len = 2

    S1 = bytearray([random.randint(MIN_INT, MAX_INT),random.randint(MIN_INT, MAX_INT)])  
    S2 = bytearray([random.randint(MIN_INT, MAX_INT),random.randint(MIN_INT, MAX_INT)])

    print_ints(S1)
    print_ints(S2)

    data_len = len(S1)
    ic(data_len)


    tag_gen = OrthogonalTagGenerator(field)

    ic(data_len-1)
    ic(S1[:data_len])


    #tag11 = tag_gen.generate_tag(d=inner_product_bytes(field, S1[:data_len],S1[:data_len])) # generate self orthogonal tag
    tag11 = tag_gen.generate_tag(d=inner_product_bytes(field, S1,S1)) # generate self orthogonal tag
    
    tag12 = 0                       # first packet is only self orthogonal

    S1_orth = S1 +  bytearray([tag11,tag12])

    ic(S1_orth, S1 ,tag11 , ic(bytearray([tag11,tag12])))
    ic(inner_product_bytes(field,S1_orth, S1_orth))
    assert inner_product_bytes(field,S1_orth, S1_orth) == 0


    S2_padded = S2 + bytearray(2)
    ic(S2_padded)
    
    d = ic(inner_product_bytes(field, S1_orth, S2_padded),S1_orth, S2_padded)

    tag21 = tag_gen.generate_tag_cross(tag11, d= inner_product_bytes(field, S1_orth, S2_padded))  # orthogonal to S1 
    
    S2_padded[data_len] = tag21
    ic("S2_padded after adding the tag21", S2_padded, tag21)
    tag22 = tag_gen.generate_tag(d= inner_product_bytes(field,S2_padded, S2_padded))
    ic(tag22)


    ic(tag21,tag22)
    S2_orth = S2 + bytearray([tag21,tag22])
    ic(S2_orth)

    # when using bytearray be careful:
    # bytearray(1)  ->   x00
    # bytearray([1]) ->  x01

    #testing orthogonality of packets
    print_ints(S1_orth)
    print_ints(S2_orth)
    ic(inner_product_bytes(field, S1_orth, S1_orth))
    ic(inner_product_bytes(field, S1_orth, S2_orth))
    ic(inner_product_bytes(field, S2_orth, S2_orth))

    return

def test_failed_packets():

    data_len = 2

    tag_gen = OrthogonalTagGenerator(field)

    S1 = bytearray([8, 8, 0, 0])
    S2 = bytearray([12, 0, 14, 2])
    
    print_ints(S1)
    print_ints(S2)
    ic(inner_product_bytes(field, S1, S2))

    # how can this case happen?
    tag11 = tag_gen.generate_tag(d=inner_product_bytes(field, S1[:data_len],S1[:data_len])) # generate self orthogonal tag
    tag12 = 0                       # first packet is only self orthogonal

    S1[2] = tag11
    S1[3] = tag12

    S1_orth = S1.copy()

    ic(S1_orth, S1 ,tag11 , bytearray([tag11,tag12]))
    ic(inner_product_bytes(field,S1_orth, S1_orth))
    assert inner_product_bytes(field,S1_orth, S1_orth) == 0

    S2_padded = S2.copy()
    ic(S2_padded)
    
    ic(S1_orth, S2_padded)

    d = ic(inner_product_bytes(field, S1_orth, S2_padded))

    tag21 = tag_gen.generate_tag_cross(tag11, d)  # orthogonal to S1

    
    S2_padded[data_len] = tag21
    ic("S2_padded after adding the tag21", S2_padded, tag21)
    tag22 = tag_gen.generate_tag(d= inner_product_bytes(field,S2_padded, S2_padded))
    ic(tag22)


    ic(tag21,tag22)
    S2_padded[data_len+1] = tag22
    S2_orth = S2_padded.copy()
    ic(S2_orth)

    # when using bytearray be careful:
    # bytearray(1)  ->   x00
    # bytearray([1]) ->  x01

    #testing orthogonality of packets
    print_ints(S1_orth)
    print_ints(S2_orth)
    ic(inner_product_bytes(field, S1_orth, S1_orth))
    ic(inner_product_bytes(field, S1_orth, S2_orth))
    ic(inner_product_bytes(field, S2_orth, S2_orth))






    return

def failed_test_case():
    '''
    This case shows that if the packet t1 has an inner product of 0, which results in tag 11 to be 0
    the packet t2 cant generate a corresponding tag21 that will result in <t1,t2> + <t11,t21> = 0

    That means we need to ignore these packets when checking for orthogonality later
    or we have to generate new data for the packets
    
    the probability of this occurring will get less with higher field size
    '''

    ic(inner_product_bytes(field,bytearray([8]), bytearray([10])))

    S1 = bytearray([8, 8, 0, 0])
    S2 = bytearray([12, 0, 14, 2])

    ic(inner_product_bytes(field,S1,S1))
    ic(inner_product_bytes(field,S1,S2))
    ic(inner_product_bytes(field,S2,S2))
    ic(inner_product_bytes(field,S1[:1], S2[:1]))
    ic(inner_product_bytes(field,S1[:2],S2[:2]))

    return


def generate_examples(data_len:int):

    tag_gen = OrthogonalTagGenerator(field)

    data = [random.randint(0, 15) for _ in range(data_len)]

    S1= bytearray([random.randint(MIN_INT, MAX_INT) for _ in range(data_len)] + [0,0])
    S2= bytearray([random.randint(MIN_INT, MAX_INT) for _ in range(data_len)] + [0,0])
    
    t11 = tag_gen.generate_tag(inner_product_bytes(field, S1,S1))

    S1[data_len] = t11

    t21 = tag_gen.generate_tag_cross(t11, inner_product_bytes(field,S1,S2))

    S2[data_len] = t21

    t22 = tag_gen.generate_tag(inner_product_bytes(field,S2,S2))

    S2[data_len+1] = t22
    print_ints(S1)
    print_ints(S2)

    ic(
        inner_product_bytes(field,S1,S1),
        inner_product_bytes(field,S1,S2),
        inner_product_bytes(field,S2,S2)
       )



if __name__ == "__main__":
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