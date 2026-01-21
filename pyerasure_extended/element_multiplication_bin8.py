import pyerasure.finite_field
import pyerasure
from precomputed_squares_bin8 import OrthogonalTagGenerator

# TODO: this was uneccesary, the refular multiply into works , so there is no need for this


def multiply(field, x: int, y: int) -> int:  # ints, not bytes!
    '''Multiply 2 field elements x and y and return the result as an Element of the field'''
    tmp = bytearray(1)
    tmp[0] = x              # Load x into tmp
    field.vector_multiply_into(tmp, y)  # tmp[0] = x * y
    return tmp[0]


def test_multiply(field):
    assert multiply(field, 7, 7) == 21   # from your square table
    assert multiply(field, 5, 5) == 17
    assert multiply(field, 3, 3) == 5
    assert multiply(field, 0, 42) == 0
    assert multiply(field, 1, 42) == 42
    print("✓ All multiply tests PASS")


if __name__ == "__main__":
    field = pyerasure.finite_field.Binary8()
    test_multiply(field)

    # Test 4: Squaring table consistency
    gen = OrthogonalTagGenerator(field)
    for x in range(16):
        manual_sq = multiply(field, x, x)
        table_root = gen.square_to_root.get(manual_sq)
        assert table_root is not None
    print("✓ Matches square table")