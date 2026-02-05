import statistics
from icecream import ic

from binary_2pow8.pollution import Pollution, pollute_data_packet_bin8, pollute_tags_packet_bin8, pollute_full_packet_bin8

from binary_2pow8.generate_symbols import check_orth_bin8, check_orth_fixed, generate_symbols_random_bin8 


from binary_2pow8.operations_bin8 import print_ints, inner_product_bytes_bin8

from binary_2pow8.config import field, MIN_INT, MAX_INT

from binary_2pow8.orthogonal_tag_creator import * 

#DATA_FIELDS = 5
#GEN_SIZE = 5

#NUM_TRIALS = 10000



accepted_packets = set()

def test_prob(data_len:int):
    ic.disable()

    S1 = []
    S2 = []


    if data_len == 2:
        S1 = bytearray([13, 14, 3, 0])
        S2 = bytearray([5, 3, 10, 12])

    elif data_len == 3:
        S1 = bytearray([9, 15, 3, 5, 0])
        S2 =bytearray([15, 3, 10, 11, 13])


    assert len(S1) > 0

    ic(
        inner_product_bytes_bin8(S1,S1),
        inner_product_bytes_bin8(S1,S2),
        inner_product_bytes_bin8(S2,S2)
       )

    #add random data pollution here

    #print_ints(S2)
    S2_poll = pollute_data_packet_bin8(data_len, S2)

    ic("check S2 and S2_ poll, S2 should not be mutated by pollution")
    #print_ints(S2)
    #print_ints(S2_poll)

    # check acceptance
    ic(
        inner_product_bytes_bin8(S1,S1),
        inner_product_bytes_bin8(S1,S2_poll),
        inner_product_bytes_bin8(S2_poll,S2_poll)
       )

    accept = (
        inner_product_bytes_bin8(S1,S1) == 0
        and inner_product_bytes_bin8(S1,S2_poll) == 0
        and inner_product_bytes_bin8(S2_poll,S2_poll) == 0
    )

    ic.enable()
    if accept :

        accepted_packets.add(tuple(S2_poll))

        ic()
        ic(list(S1))
        ic(list(S2_poll))

        ic(
        inner_product_bytes_bin8(S1,S1),
        inner_product_bytes_bin8(S1,S2_poll),
        inner_product_bytes_bin8(S2_poll,S2_poll)
       )

        
    ic.disable()


    return accept

'''
def test_gen(generation:list[bytearray]) -> bool:

    accept = (
        inner_product_bytes_bin8(S1,S1) == 0
        and inner_product_bytes_bin8(S1,S2_poll) == 0
        and inner_product_bytes_bin8(S2_poll,S2_poll) == 0
    )
'''


def monte_carlo_test(num_trials, data_fields, gen_size):
    accepts = []

    tag_gen = OrthogonalTagGenerator(field)


    ic(num_trials, data_fields, gen_size)
    for trial in range(num_trials):
        generation = generate_symbols_random_bin8(data_fields,gen_size)
        tagged_gen = tag_gen.generate_all_tags(generation)
        accepts.append(check_orth_bin8(tagged_gen))

    ic.enable()
    prob = statistics.mean(accepts)
    std = statistics.stdev(accepts) / (num_trials ** 0.5) if len(accepts) > 1 else 0

    total_accepted = accepts.count(1)
    ic(total_accepted)
    #ic(accepts)
    ic(prob,std)

    ic.disable()
    print(f"Acceptance probability: {prob:.6f} ± {std:.6f} over {num_trials} trials")

    return prob, std


if __name__ == "__main__":
        ic(monte_carlo_test(10000, 3,3))