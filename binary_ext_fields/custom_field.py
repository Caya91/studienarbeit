from icecream import ic
from pprint import pprint
import random


PRIMES_GF2M = {
    2: 0b111, # x^2 + x + 1
    3: 0b1011, # x^3 + x + 1
    4: 0b10011,     # x^4 + x + 1
    5: 0b100101, # x^5 + x^2 + 1
    6: 0b1000011 , # x^6 + x + 1 (alt: 0b1100011 for x^6 + x^4 + x^3 + x + 1)
    
    #6: 0b1000001, # x^6 + x + 1 (alt: 0b1100011 for x^6 + x^4 + x^3 + x + 1)
    7: 0b10000011, # x^7 + x + 1 (alt: 0b11000011 for x^7 + x^6 + x + 1)
    8: 0b1_0001_1101,  # AES polynomial x^8 + x^4 + x^3 + x + 1
}


# binary_ext_fields/custom_field.py
class TableField:
    def __init__(self, add_table: list[list[int]], mul_table: list[list[int]], prime:int):
        assert len(add_table) == len(mul_table)
        self._add = add_table
        self._mul = mul_table
        self.max_value = len(add_table) - 1
        self.prime = prime
        self.name = self._make_name()
        self.bit_lenght = self.prime.bit_length() - 1

    def add(self, a: int, b: int) -> int:
        #TODO:  maybe mit XOR ausrechen statt lookup
        return self._add[a][b]

    def mul(self, a: int, b: int) -> int:
        return self._mul[a][b]

    def vector_multiply_into(self, vec: bytearray | list[int], scalar: int) -> None:
        """
        CAREFUL - MUTATES THE VECTOR : vec
        result = vector * scalar 
        """
        for i, v in enumerate(vec):
            vec[i] = self.mul(v, scalar)

    def get_mul_inverse(self, value:int) -> int:
        ''' return the inverse of the given value 
        '''
        for i, row in enumerate(self._mul):
            #ic(i,row, row[value])
            if row[value] == 1:
                return i
        raise ValueError(f"No multiplicative inverse for {value} in {self.name} (0 has no inverse)")
            
    def get_mul_to_target(self, base:int, target:int) -> int:
        '''returns the scalar that results in
        >>> base * scalar = target
        '''
        for i, row in enumerate(self._mul):
            #ic(i,row, row[value])
            if row[base] == target:
                return i
        raise ValueError(f"No scalar s satisfying {base} * s = {target} in {self.name}")


    def vector_multiply_add_into(self, x: bytearray, y: bytes, c: int):
        """
        Multiply the vector y with the constant c and then add the result
        to vector x.
        SHOULDNT MUTATE
        #TODO: test if mutates
        """

        assert len(x) == len(y)
        assert c <= self.max_value

        y_copy = y.copy()
        self.vector_multiply_into(y_copy, c)

        tmp = bytearray(1)

        result = []
        for a, b in zip(x, y_copy):
            tmp = self.add(a, b)        # acc += a·b
            result.append(tmp)

        assert len(result) == len(x)
        #print(result)
        return bytearray(result)


    def get_key_from_value(self):
        """Find first key that maps to target_value."""
        for key, value in PRIMES_GF2M.items():
            if value == self.prime:
                return key
        return None # Not found
    

    def get_element_list(self):
        return list(range(0, self.max_value + 1))
    
    def _make_name(self):
        pow_int = 0
        for key, value in PRIMES_GF2M.items():
            if value == self.prime:
                pow_int = key
                return f"GF_2pow{pow_int}"
        return None # None found


class CountingField(TableField):
    """
    Wraps a field to count multiplications/additions. Used for ADR-007 - measuring the operations for recovery of polluted/broken packets

    """
    def __init__(self, base: TableField):
        super().__init__(base._add, base._mul, base.prime)
        self.mul_count = 0
        self.add_count = 0

    def mul(self, a, b):
        self.mul_count += 1
        return super().mul(a, b)

    def add(self, a, b):
        self.add_count += 1
        return super().add(a, b)

    def reset(self):
        self.mul_count = 0
        self.add_count = 0

        
def build_tables_gf2m(m: int, poly: int):
    """
    Build addition and multiplication tables for GF(2^m) using irreducible poly.
    """
    size = 1 << m
    add_table = [[0] * size for _ in range(size)]
    mul_table = [[0] * size for _ in range(size)]

    for a in range(size):
        for b in range(size):
            add_table[a][b] = gf_add_custom(a, b)
            mul_table[a][b] = gf_mul_custom(a, b, poly)

    return add_table, mul_table


def degree(x:int) -> int:
    return x.bit_length() - 1


def gf_add_custom(a, b):
    """Addition in GF(2^2) = bitwise XOR."""
    return (a ^ b)


def gf_mul_custom(a, b , prime:int):
    """Multiplication in GF(2^x) with modulus prime"""
    """TODO: warning when arguments are out of field range"""
    res = 0
    while b:
        if b & 1:
            res ^= a
        b >>= 1
        a <<= 1
        # if a has degree >= m, reduce modulo poly
        if a & (1 << degree(prime)):  # top bit (x^m) set
            a ^= prime
    return res & ((1 << degree(prime)) - 1)


def create_field(field_m:int, ) -> TableField:
    ''' field_size is  2^m, returns correspoonding Tablefield
    '''
    poly = PRIMES_GF2M[field_m]
    ADD_GF16, MUL_GF16 = build_tables_gf2m(field_m, poly)

    return TableField(ADD_GF16, MUL_GF16, poly)


def _test_sanity():

    m = 4
    poly = PRIMES_GF2M[m]
    ADD_GF16, MUL_GF16 = build_tables_gf2m(m, poly)

    ic(ADD_GF16, MUL_GF16)
    table_field = TableField(ADD_GF16, MUL_GF16, poly)



    # Sanity Test to get scalar to reach target
    target1 = 5
    target2 = 1
    target3 = 7

    scalar1 = table_field.get_mul_to_target(3,target1)
    scalar2 = table_field.get_mul_to_target(1,target2)
    scalar3 = table_field.get_mul_to_target(9,target3)

    ic(scalar1,scalar2, scalar3)


if __name__ == "__main__":
    '''
        add_table = []
        mul_table = []
        prime = 5

        field = TableField(add_table=add_table, mul_table=mul_table,prime = prime)
    '''

    m = 4
    field = create_field(m)
    counting_field = CountingField(field)





    # Sanity Test to get scalar to reach target
    target1 = 5
    target2 = 1
    target3 = 7

    scalar1 = counting_field.get_mul_to_target(3,target1)
    scalar2 = counting_field.get_mul_to_target(1,target2)
    scalar3 = counting_field.get_mul_to_target(9,target3)

    adds = random.randint(1, 100)
    muls = random.randint(1, 100)

    for i in range(muls):
        mul = counting_field.mul(3,2)

    for i in range(adds):
        add = counting_field.add(3,2)



    ic(scalar1,scalar2, scalar3)
    ic(adds, muls)
    ic(counting_field.add_count, counting_field.mul_count)

    assert counting_field.add_count == adds
    assert counting_field.mul_count == muls

    counting_field.reset()

    assert counting_field.add_count == 0
    assert counting_field.mul_count == 0




    '''    TESTING INVERSE
    table_field = TableField(ADD_GF16, MUL_GF16, poly)
    print("INVERSE")
    inv1 = table_field.get_mul_inverse(3)
    inv2 = table_field.get_mul_inverse(1)
    inverses = []
    for i in range(1,15):
        inv = table_field.get_mul_inverse(i)
        inverses.append(inv)
        print(f'Inverse of {i} = {inv} ')

    for i, e in enumerate(inverses):
        print(f'Inverse of {i} = {e} ')

    ic(inverses)
    '''