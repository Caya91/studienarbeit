import pyerasure.finite_field
from icecream import ic

from binary_2pow4.config import field

ic("polynomial for 2^4= ", bin(field._prime))


# we use the addition and multiplication of pyerasure to build our tables
# later we will have to test the correctnes of these tables via another implementation to check if it is correct


# check if binary of ints are the same representation in pyerasure Binary4

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


def gf16_add(a,b):
    return a^b

def gf16_add_table():
    n = 16
    table = []
    for a in range(n):
        row = []
        for b in range(n):
            row.append(gf16_add(a, b))
        table.append(row)
    #ic(table)
    return table

def gf16_add_table_bin():
    n = 16
    table = []
    for a in range(n):
        row = []
        for b in range(n):
            row.append(bin(gf16_add(a, b)))
        table.append(row)
    #ic(table)
    return table


def gf16_mul_table():
    n = 16
    table = []
    for a in range(n):
        row = []
        for b in range(n):
            x = [b]
            field.vector_multiply_into(x,a)
            row.append(x[0])
        table.append(row)
    return table

def gf16_mul_table_bin():
    n = 16
    table = []
    for a in range(n):
        row = []
        for b in range(n):
            x = [b]
            field.vector_multiply_into(x,a)
            row.append(bin(x[0]))
        table.append(row)
    return table
    

def print_gf2m_table_bin(table, m=4, title=""):
    n = 2**m
    width = m      # bits per element

    if title:
        print(title)
    # Header row
    header = " " * (width + 1)  # corner cell
    for x in range(n):
        header += f"{x:0{width}b} "
    print(header)

    # Rows
    for i, row in enumerate(table):
        line = f"{i:0{width}b} "  # row label
        for val in row:
            line += f"{val:0{width}b} "
        print(line)
    print()

def print_gf2m_table(table, m=4, title=""):
    n = 2**m
    width = m      # bits per element

    if title:
        print(title)
    # Header row
    header = " " * (width + 1)  # corner cell
    for x in range(n):
        header += f"{x:0{width}} "
    print(header)

    # Rows
    for i, row in enumerate(table):
        line = f"{i:0{width}} "  # row label
        for val in row:
            line += f"{val:0{width}} "
        print(line)
    print()


def write_gf2m_table(table, path: str, m=4, title=""):
    """Write numeric table to a text file."""
    n = 2**m
    width = m

    with open(path, "w", encoding="utf-8") as f:
        if title:
            f.write(title + "\n")

        # Header row
        header = " " * (width + 1)
        for x in range(n):
            header += f"{x:0{width}} "
        f.write(header + "\n")

        # Rows
        for i, row in enumerate(table):
            line = f"{i:0{width}} "
            for val in row:
                line += f"{val:0{width}} "
            f.write(line + "\n")
        f.write("\n")


def write_gf2m_table_bin(table, path: str, m=4, title=""):
    """Write binary table to a text file."""
    n = 2**m
    width = m

    with open(path, "w", encoding="utf-8") as f:
        if title:
            f.write(title + "\n")

        header = " " * (width + 1)
        for x in range(n):
            header += f"{x:0{width}b} "
        f.write(header + "\n")

        for i, row in enumerate(table):
            line = f"{i:0{width}b} "
            for val in row:
                # here 'val' is int; if table already stores strings, drop the :b
                line += f"{val:0{width}b} "
            f.write(line + "\n")
        f.write("\n")


if __name__ == "__main__":

    
    add_table = gf16_add_table()
    add_table_bin = gf16_add_table_bin()

    print_gf2m_table(add_table, title="addition table")
    print_gf2m_table_bin(add_table, title="addition table binary")

    
    mul_table = gf16_mul_table()
    mul_table_bin = gf16_mul_table_bin()

    print_gf2m_table(mul_table, title="multiplication table")
    print_gf2m_table_bin(mul_table, title= "multiplication table binary")

    write_gf2m_table(mul_table,  "logs/gf16_mul_numeric.txt", m=4,
                     title="GF(2^4) multiplication table (numeric)")
    write_gf2m_table_bin(mul_table, "logs/gf16_mul_binary.txt", m=4,
                         title="GF(2^4) multiplication table (binary)")
    
    write_gf2m_table(add_table, "logs/gf16_add_numeric.txt", m=4,
                 title="GF(2^4) addition table (numeric)")
    write_gf2m_table_bin(add_table, "logs/gf16_add_binary.txt", m=4,
                     title="GF(2^4) addition table (binary)")


    for i, row in enumerate(mul_table):
        for j,element in enumerate(row):
            ic(element,bin(element), mul_table_bin[i][j])
            assert bin(element) == mul_table_bin[i][j]
            # hier könnte man den für den Test mit einer anderen Bibliothek / eigener Implementierung
            # testen ob i*j auch das richtige element ergibt

    print("all elements are equal")


