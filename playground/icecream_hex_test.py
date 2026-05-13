from icecream import ic

def custom_format(obj):
    if isinstance(obj, (bytearray, bytes)):
        # Converts bytearray(b'\x07\x05\t\x01') into [7, 5, 9, 1]
        return str(list(obj))
    
    # Fallback to the default formatting for everything else
    return repr(obj)

# Configure icecream to use your custom formatter
ic.configureOutput(argToStringFunction=custom_format)

# Now test it!
packet = bytearray(b'\x07\x05\t\x01\x03\r\x04\x04\x00\x00\x00\x00\x00')
ic(packet)
