import pyerasure
import pyerasure.finite_field
from icecream import ic

field = pyerasure.finite_field.Binary8()

class OrthogonalTagGenerator:
    def __init__(self, field):
        self.field = field
        self.square_to_root = {}  # key: square  ; value: root

        tmp = bytearray(1)
        for x in range(field.max_value + 1):
            tmp[0] = x
            field.vector_multiply_into(tmp, x)  # tmp[0] = x * x   mod fieldsize
            sq = tmp[0]
            if sq not in self.square_to_root:
                self.square_to_root[sq] = x  # write square, root pair into dict
    
    def tags(self, d: int) ->  int:

        assert d <= self.field.max_value

        t2 = self.square_to_root.get(d, None)
        if t2 is not None:
            return t2
        
        # Rare fallback: try next t1
        return None # self.tags(d)  # Recurse (very rare
    


## TESTING


def gf_square(field, x: int) -> int:
    tmp = bytearray(1)
    tmp[0] = x
    field.vector_multiply_into(tmp, x)
    return tmp[0]



def test_orthogonalgenerator():
    generator = OrthogonalTagGenerator(field)
        # 1) All squares must map back
    for a in range(256):
        s = gf_square(field, a)
        r = generator.square_to_root[s]
        # Check: r is *a* or another root with same square
        assert gf_square(field, r) == s

    print("All squares map to a valid root.")


    tests = [0, 1, 2, 3, 5, 7, 0x53, 0x57, 0xAE, 0xFF]

    for a in tests:
        s = gf_square(field, a)
        r = generator.square_to_root[s]
        print(f"a={a:3d} (0x{a:02X}) (0b{a:08b})  a^2={s:3d} (0x{s:02X}) (0b{s:08b})  root={r:3d} (0x{r:02X}) (0b{r:08b})")
        assert gf_square(field, r) == s


if __name__ == "__main__":
    test_orthogonalgenerator()