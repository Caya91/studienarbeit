from binary_ext_fields.generate_symbols import check_orth_packet
from binary_ext_fields.custom_field import create_field, TableField


# Testing false positives
test_packet = bytearray([1, 0, 0, 19, 15, 1, 10, 0, 0])
original = bytearray([1, 0, 0, 5, 15, 1, 10, 0, 0])



if __name__ == "__main__":
    field = create_field(5)


    print(list(test_packet))

    print(check_orth_packet(field, test_packet))
    print(check_orth_packet(field, original))

