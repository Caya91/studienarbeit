from binary_2pow4.debug_inspect import log_generation_detail, LOG_FILE

# this fiel is for checking generations manually so we can make check the failed packets generation by generation.

from examples.failed_generation_examples import generation


  # if you kept a set
# or load/reconstruct bad generations from a file

S1 = bytearray([5, 15, 10, 0, 0, 0, 0, 0])
S2 = bytearray([6, 2,  2,  9, 15, 0, 0, 0])
S3 = bytearray([5, 13, 0,  5, 1,  12, 0, 0])
S4 = bytearray([3, 8,  5,  5, 12, 13, 10, 0])
S5 = bytearray([15, 2, 3,  8, 3,  7,  11, 9])

generation_ex2 = [S1, S2, S3, S4, S5]

S1 = bytearray([9, 0, 9, 0, 0, 0])
S2 = bytearray([11, 13, 2, 1, 5, 0])
S3 = bytearray([5, 15, 6, 10, 0, 6])

generation_ex3 = [S1, S2, S3]


def inspect_generation(gen: list[bytearray]):
    # Clear old log if you like:
    open(LOG_FILE, "w").close()
    log_generation_detail(gen, log_only_nonzero=False)



if __name__ == "__main__":
    # Example: hard-code a generation you want to study

    inspect_generation(generation_ex3)