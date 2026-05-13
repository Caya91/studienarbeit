import random
import os
from icecream import ic
from utils.log_helpers import make_ic_logger, get_playground_dir, clear_run_logs, custom_format, log_header
from binary_ext_fields.generate_symbols import check_orth



ic.configureOutput(outputFunction=make_ic_logger(dir))


def gen_packet_random(min_int, max_int):
    return random.randint(min_int, max_int)

sys_rand = random.SystemRandom()
def gen_packet_sysrandom(min_int, max_int):
    return sys_rand.randint(min_int, max_int)

def gen_packet_urandom(min_int, max_int):
    raw_byte = os.urandom(1)

    raw_int = int.from_bytes(raw_byte, 'little')

    return raw_int & 0x0F


generators = {
        "random.Random": gen_packet_random,
        "SystemRandom": gen_packet_sysrandom,
        "os.urandom": gen_packet_urandom
    }


def generate_symbols_random(min_int:int, max_int:int,data_fields:int, gen_size:int, rng_func) -> list:
    assert data_fields > 0
    assert gen_size > 0
        
    
    symbols = []

    for packet in range(gen_size):
        symbol = bytearray([rng_func(min_int, max_int) for _ in range(data_fields)] + [0 for _ in range(gen_size)])
        symbols.append(symbol)

    #ic(len(symbols),symbols)
    '''
    for symbol in symbols:
        print_ints(symbol)
    '''
    return symbols


if __name__ == "__main__":


    dir = get_playground_dir("rng_test.txt")
    ic.configureOutput(outputFunction=make_ic_logger(dir))
    ic.configureOutput(argToStringFunction=custom_format)


    ic("RNG TEST of different functions")
    for name, func in generators.items():
        log_header(f"Testing: {func.__name__}", dir)
        symbols = generate_symbols_random(0, 15, 8,5, func)
        for symbol in symbols:
            ic(symbol)