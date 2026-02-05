import os
import pyerasure
import pyerasure.finite_field
import pyerasure.generator
from icecream import ic

field = pyerasure.finite_field.Binary8()
encoder = pyerasure.Encoder(
    field=field,
    symbols=15 **+ TAG SYMBOLS**,
    symbol_bytes=140    **+  TAG BYTES**)
decoder = pyerasure.Decoder(
    field=field,
    symbols=15 **+ TAG SYMBOLS**,
    symbol_bytes=140    **+  TAG BYTES**)

generator = pyerasure.generator.RandomUniform(
    field=field,
    symbols=encoder.symbols)



data_in = bytearray(os.urandom(encoder.block_bytes))

**Tagged_data =  "hier die Symbole/Pakete taggen und als ganzes Paket weiterschicken**
**die weitergesendeten Pakete + tags müssen dann genau die Länge eines erwarteten Symbols haben**  
**Anzahl der Tag:  -> 2 mal (Anzahl der Ursprungssymbole)**
**Extra Tag Bytes: -> (Field size) mal (Anzahl der Tags)**


ic(data_in,len(data_in))
encoder.set_symbols(data_in **ersetzen durch unsere GETAGTEN Pakete**)

while not decoder.is_complete():
    coefficients = generator.generate()
    symbol = encoder.encode_symbol(coefficients)

**zwischen Encoding und Decoding kommt hier unsere Paket Recovery und Security Check**
**das heißt wir bauen eine Matrix der Pakete auf, checken auf orthogonalität und reparieren bzw discarden kaputte Pakete**
**Hier findet dann auch unser RREF statt ( row reduced echelon form)**
**Danach wird zum Decoder weitergeleitet**

    decoder.decode_symbol(symbol, bytearray(coefficients))

assert data_in == decoder.block_data()
print("Success!")