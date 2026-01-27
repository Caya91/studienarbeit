import pyerasure
import pyerasure.finite_field
import random
import statistics
from icecream import ic
from operations_bin4 import inner_product_bytes, print_ints
from operations_bin4 import MIN_INT, MAX_INT
from operations_bin4 import pollute_packet, pollute_data_packet, pollute_tags_packet


field = pyerasure.finite_field.Binary4()


DATA_FIELDS = 3
NUM_TRIALS = 100000

accepted_packets = set()


def write_to_file(text):
    with open("debug.log", "a") as f:
        f.write(text + "\n")


#ic.configureOutput(outputFunction=write_to_file)



def probability():
    
    return 


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
        inner_product_bytes(field,S1,S1),
        inner_product_bytes(field,S1,S2),
        inner_product_bytes(field,S2,S2)
       )

    #add random data pollution here

    #print_ints(S2)
    S2_poll = pollute_data_packet(data_len, S2)

    ic("check S2 and S2_ poll, S2 should not be mutated by pollution")
    #print_ints(S2)
    #print_ints(S2_poll)

    # check acceptance
    ic(
        inner_product_bytes(field,S1,S1),
        inner_product_bytes(field,S1,S2_poll),
        inner_product_bytes(field,S2_poll,S2_poll)
       )

    accept = (
        inner_product_bytes(field,S1,S1) == 0
        and inner_product_bytes(field,S1,S2_poll) == 0
        and inner_product_bytes(field,S2_poll,S2_poll) == 0
    )

    ic.enable()
    if accept :

        accepted_packets.add(tuple(S2_poll))

        ic()
        ic(list(S1))
        ic(list(S2_poll))

        ic(
        inner_product_bytes(field,S1,S1),
        inner_product_bytes(field,S1,S2_poll),
        inner_product_bytes(field,S2_poll,S2_poll)
       )

        
    ic.disable()


    return accept


def monte_carlo_test():
    accepts = []

    for trial in range(NUM_TRIALS):
        accepts.append(test_prob(DATA_FIELDS))

    ic.enable()
    prob = statistics.mean(accepts)
    std = statistics.stdev(accepts) / (NUM_TRIALS ** 0.5) if len(accepts) > 1 else 0

    total_accepted = accepts.count(1)
    ic(total_accepted)
    #ic(accepts)
    ic(prob,std)

    ic.disable()
    print(f"Acceptance probability: {prob:.6f} ± {std:.6f} over {NUM_TRIALS} trials")

    return


def calculate_prob(gen_size, data_len):
    '''
    returns the probability of a single polluted packet 
    to be accepted
    dof : degrees of freedom
    dof = data_len - constraints

    prob = field_size ^dof / field ^data_len
    
    :param gen_size: number of original packets
    :param data_len: number of data fields that can be mutated
    '''

    # calculate the theoretical probability and compare to measured one
    
    # pro extra paket in der generation benötigen wir einen Tag
    # Jeder Tag erfüllt einen constraint
    tags_len = gen_size  


    field_size = field.max_value + 1 
    #ic(field_size)

    # for only data pollution mutable fields is the len(data_fields)or data_len
    # for whole packet its len(packet)
    mutable_fields = data_len

    # for p1 its 1   <p1,p1> = 0
    # for p2 its 2   <p2,p1> = 0   and <p2,p2> = 0 
    # but since we only accept packages when we collect a certain number of packets
    # its equal to the number of packets we collect or the generation
    # that is if we only pollute one packet of the whole generation
    # so for gen = 5, should -> constraints = 5

    constraints = gen_size

    dof = mutable_fields - constraints


    prob = (field_size**dof)/ (field_size**mutable_fields )


    # we need atleast as many mutable fields as constraints or pollution is
    # not possible. But that should always be the case, since we send more data
    # than tags probably
    if mutable_fields < constraints:
        prob = 0

    return prob


if __name__ == "__main__":
    #monte_carlo_test()

    #ic.enable()
    #ic(len(accepted_packets), accepted_packets)

    
    for i in range(1,6): # generation (no 0)
        for j in range(1,7): # number of data fields
            ic(f"probability for generation of {i} and data_fields of {j}:",calculate_prob(i,j))