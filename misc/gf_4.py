# GF(2^2) with primitive polynomial x^2 + x + 1 over GF(2).
# Elements are 2-bit ints: 0..3

RED_POLY = 0b11  # corresponds to x + 1 when reducing x^2

def gf4_add(a, b):
    """Addition in GF(2^2) = bitwise XOR."""
    return (a ^ b) & 0b11

def gf4_mul(a, b):
    """Multiplication in GF(2^2) with modulus x^2 + x + 1."""
    """TODO: warning when arguments are out of field range"""
    a &= 0b11
    b &= 0b11
    res = 0
    for _ in range(2):  # degree 2 => 2 bits
        if b & 1:
            res ^= a
        b >>= 1
        # shift a and reduce if x^2 term appears
        carry = (a & 0b10) >> 1  # highest bit before shift
        a = (a << 1) & 0b11
        if carry:
            a ^= RED_POLY
    return res & 0b11

def gf4_scalar_mul_packet(alpha, p):
    """Multiply every symbol in the packet by scalar alpha in GF(2^2)."""
    return [gf4_mul(alpha, x) for x in p]



def gf4_add_packet(p1, p2):
    """Element-wise addition in GF(2^2) for two equal-length packets."""
    assert len(p1) == len(p2)
    return [gf4_add(a, b) for a, b in zip(p1, p2)]



def gf4_inner_product(p1, p2):
    """Standard inner product in GF(2^2)."""
    assert len(p1) == len(p2)
    acc = 0
    for a, b in zip(p1, p2):
        acc = gf4_add(acc, gf4_mul(a, b))
    return acc


for i in range(4):
    row = [gf4_mul(i, j) for j in range(4)]
    print(i, ":", row)

p = [1, 2, 3]        # packet 1
q = [3, 1, 2]        # packet 2

sum_pq = gf4_add_packet(p, q)
ip = gf4_inner_product(p, q)
scaled = gf4_scalar_mul_packet(2, p)

print("p+q:", sum_pq)
print("<p,q>:", ip)
print("2*p:", scaled)


