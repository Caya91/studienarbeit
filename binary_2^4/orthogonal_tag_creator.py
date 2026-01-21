import pyerasure
import pyerasure.finite_field
import random
from icecream import ic
from operations_bin4.operations_bin4 import inner_product_bytes

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
            ic(t2)
            return t2
        
        # Rare fallback: try next t1
        ic("t2 should not be none", t2)
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

if __name__ == "__main__":
    test_orthogonalgenerator()
    test_cross_generation()
    '''
    generator=OrthogonalTagGenerator(field)


    ic(generator.square_to_root)

    ic(generator.mul_table)
    
    ic(generator.generate_tag_cross(3,0))
    ic(generator.generate_tag_cross(3,1))

    '''