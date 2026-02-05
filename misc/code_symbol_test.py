import pyerasure
import pyerasure.finite_field

field = pyerasure.finite_field.Binary8()  # GF(2^8)[web:129]

# One source symbol: 3 bytes
S = bytearray([1, 2, 3])  # decimal: 1,2,3

symbols = 1
symbol_bytes = len(S)

encoder = pyerasure.Encoder(field, symbols, symbol_bytes)
decoder = pyerasure.Decoder(field, symbols, symbol_bytes)

# Build block = S
block = bytearray(S)
encoder.set_symbols(block)  # store original symbol[web:121]

print("original symbol bytes:", list(encoder.symbol_data(0)))  # [1, 2, 3][web:182]

orig = encoder.symbol_data(0) # original symbol bytes[web:182]
print("original:", list(orig))

# Coeff vector [2] => coded symbol = 2 * S in GF(2^8)
coeffs = bytearray([2])
scaled = encoder.encode_symbol(coeffs)  # [web:121]

print("coeffs:", list(coeffs))
print("scaled (2 * S in GF(2^8)):", list(scaled))


# ---- New: show an example where GF(2^8) != integer *2 ----

# Change S to bytes with high bit set
S_high = bytearray([0x80, 0xFF])
symbols = 1
symbol_bytes = len(S_high)

encoder = pyerasure.Encoder(field, symbols, symbol_bytes)
decoder = pyerasure.Decoder(field, symbols, symbol_bytes)

block = bytearray(S_high)
encoder.set_symbols(block)

orig_high = encoder.symbol_data(0)
print("original high symbol bytes:", list(orig_high))  # [128, 255]

coeffs_high = bytearray([2])
scaled_high = encoder.encode_symbol(coeffs_high)

print("scaled high (2 * [0x80,0xFF] in GF(2^8)):", list(scaled_high))

# For comparison: integer multiplication by 2 modulo 256
int_high = [(2 * x) & 0xFF for x in orig_high]
print("integer 2 * [0x80,0xFF] mod 256:", int_high)


# Another example
# One symbol containing the single byte 7

S = bytearray([7])

symbols = 1
symbol_bytes = len(S)

encoder = pyerasure.Encoder(field, symbols, symbol_bytes)
decoder = pyerasure.Decoder(field, symbols, symbol_bytes)

# Install S into the encoder
block = bytearray(S)
encoder.set_symbols(block)

print("original symbol:", list(encoder.symbol_data(0)))  # [7]

# Coeff [7] => coded symbol = 7 * S in GF(2^8), i.e. 7 * 7
coeffs = bytearray([7])
scaled = encoder.encode_symbol(coeffs)

field_result = scaled[0]
int_result = (7 * 7) & 0xFF

print("GF(2^8): 7 * 7 =", field_result)
print("int mod 256: 7 * 7 =", int_result)