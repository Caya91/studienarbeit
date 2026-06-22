from icecream import ic
from utils.log_helpers import log_packet
from random import choice

from binary_ext_fields.custom_field import TableField, create_field

from binary_ext_fields.generate_symbols import inner_product_bytes, check_orth, check_orth_packet
from binary_ext_fields.generate_symbols import generate_symbols_until_nonzero
from utils.log_helpers import make_ic_logger, print_generation, print_packet
from arc_pl import error_into_generation, error_into_packet


def verify_tag(data: bytearray, tag: bytearray) -> bool:
    # A very simple verification check (XOR checksum)
    checksum = 0
    for byte in data:
        checksum ^= byte
        
    return bytearray([checksum]) == tag


def repair_packet(packet: bytearray, data_len: int, error_pos: int) -> bytearray | None:
    # 1. Split the packet into its two parts
    data = packet[:data_len]
    tag = packet[data_len:]

    # 2. Save the original broken byte so we don't lose it
    original_byte = data[error_pos]

    # 3. Guess every possible byte value (0 through 255)
    for guess in range(12):
        data[error_pos] = guess  # Insert our guess into the data
        
        # 4. Test if this guess makes the tag match
        if verify_tag(data, tag):
            return data + tag    # It worked! Return the joined, fixed packet

    # 5. If no guess worked, put the broken byte back and give up
    data[error_pos] = original_byte
    return None


def test_verify_tag():
    # 1 XOR 2 XOR 3 = 0
    data = bytearray([1, 2, 3])
    good_tag = bytearray([0])
    bad_tag = bytearray([99])
    
    assert verify_tag(data, good_tag) == True
    assert verify_tag(data, bad_tag) == False
    print("✅ test_verify_tag passed")

def test_successful_repair():
    # Original data: [10, 20, 30]. Tag: [20] (because 10^20^30 = 20)
    # The perfect packet looks like this:
    perfect_packet = bytearray([1, 2, 3, 0])
    
    # Let's break the byte at index 1 (change 20 to 99)
    broken_packet = bytearray([1, 9, 3, 0])
    
    # Tell the function: data is 3 bytes long, the error is at position 1
    fixed_packet = repair_packet(broken_packet, data_len=3, error_pos=1)
    
    # It should exactly match the perfect packet
    
    print(fixed_packet)
    assert fixed_packet == perfect_packet
    print("✅ test_successful_repair passed")

def test_failed_repair():
    # Perfect packet: [10, 20, 30, 20]
    # Let's break TWO bytes (index 0 and index 1)
    really_broken_packet = bytearray([88, 99, 30, 20])
    
    # Tell the function to fix position 1. 
    # Even if it guesses '20' correctly, position 0 is still '88', so the tag won't match!
    fixed_packet = repair_packet(really_broken_packet, data_len=3, error_pos=1)
    
    # It should fail and return None
    assert fixed_packet is None
    print("✅ test_failed_repair passed")

def recover_packet_combined(field, p1:bytearray, p2:bytearray, recovery_columns: list[int]):
    # TODO: implement combined recovery from the base case of the single recovered packet
    # we take 2 packets -> XOR them, then recover this combined packet
    # then when that worked -> recover the old packets by xoring them to their original versions
    # the 2 recovery columns have to be different i think ...

    pass


def recover_packet(field: TableField, packet: bytearray, recovery_column: int):
    '''
    takes a broken packet and
    tries out all the elements of the field at the recovery column for that packet
    and returns the fixed packet, or the old packet if no solution was found
    '''
    if check_orth_packet(field, packet):
        print("packet was orthogonal")
        return packet
    
    print(f"packet before recovery {list(packet)}")
    tmp = packet.copy()
    element_list = list(range(0,field.max_value + 1 ))

    for e in element_list: 
        packet[recovery_column] = e
        if check_orth_packet(field, packet):
            break # is the packet orthogonal after the fix then this is our recovered packet

    return packet

def recover_packet_bitflip(field: TableField, packet: bytearray, recovery_column: int, hamming_distance: int):
    '''try to make the function for a single bit flip first, then lets see how to to a bigger hamming distance
    this now recovers any single bitflip
    TODO: How to what to do about flips that push the element outside of the field size?
    '''

    if check_orth_packet(field, packet):
        print("packet was orthogonal")
        return packet
    
    print(f"packet before recovery {list(packet)}")
    tmp = packet.copy()

    i = 0
    print(f"Original byte before recovery {packet[recovery_column]:08b} ")
    while ((not check_orth_packet(field, packet)) and i < 8):
        #print(f"{i}, {packet}")
        packet = bytearray(tmp)
        packet[recovery_column] = packet[recovery_column] ^ (1 << i)
        print(f"Bit {i} wird geflippt   {packet[recovery_column]:08b} ({packet[recovery_column]}) ") 
        i +=  1

    return packet


def base_test():

    faulty_columns = set(1)

    #packet


# Run the tests
if __name__ == "__main__":

    # This tests right now to put an error in one packet and then recovering that error
    # to make the generation orthogonal again

    field = create_field(5)
    generation = generate_symbols_until_nonzero(field, 3 , 3)

    print("generation Before introducing Error")
    print_generation(generation)


    print(check_orth(field, generation))

    error_column = 3
    error_packet = 0

    generation[error_packet] = error_into_packet(generation[error_packet], error_column)

    print("Generation After Introducing Error")
    print_generation(generation)

    print(check_orth(field, generation))

    print("===== Start packet recovery =====")
    print(f"Original polluted Packet: {error_packet} with the Error Column: {error_column}")

    #recovered_packet = recover_packet(field, generation[error_packet], error_column)
    recovered_packet = recover_packet_bitflip(field, generation[error_packet], error_column, 0)

    generation[error_packet] = recovered_packet

    print("==== Recovered Generation ==== ")
    print_generation(generation)


    #packet
    '''
    test_verify_tag()
    test_successful_repair()
    test_failed_repair()
    print("All tests finished successfully!")
    '''