import os
import pyerasure
import pyerasure.finite_field
import pyerasure.generator
from icecream import ic

field = pyerasure.finite_field.Binary4()

field = pyerasure.finite_field.Binary4()

pyerasure.finite_field.Binary4().elements_to_bytes

# Packets as GF(2^4) elements (ints 0-15)
P1 = [0, 1, 1, 0, 0, 0, 0]
P2 = [0, 1, 1, 0, 0, 0, 0]
P3 = [0, 0, 0, 1, 1, 0, 0]



encoder = pyerasure.Encoder(
    field=field,
    symbols=3,
    symbol_bytes=140)
decoder = pyerasure.Decoder(
    field=field,
    symbols=15,
    symbol_bytes=140)

generator = pyerasure.generator.RandomUniform(
    field=field,
    symbols=encoder.symbols)

data_in = bytearray(os.urandom(encoder.block_bytes))
ic(data_in,len(data_in))
encoder.set_symbols(data_in)

while not decoder.is_complete():
    coefficients = generator.generate()
    symbol = encoder.encode_symbol(coefficients)
    decoder.decode_symbol(symbol, bytearray(coefficients))

assert data_in == decoder.block_data()
print("Success!")