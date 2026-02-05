import pyerasure
import pyerasure.finite_field
import random
import statistics
from icecream import ic

from binary_2pow8.config import field


def write_to_file(text):
    with open("debug.log", "a") as f:
        f.write(text + "\n")


#ic.configureOutput(outputFunction=write_to_file)

# TODO: implement functions for estimating
# 1. probability of polluted packet to be accepted
# 2. probability of generating a packet with inner product 0
# 3. 




def calculate_prob_data_pollution(gen_size, data_len):
    '''
    returns the probability of a single data polluted packet 
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


    field_size = field.max_value + 1 
    #ic(field_size)

    # for only data pollution mutable fields is the len(data_fields)or data_len
    # for whole packet its len(packet)


    # for p1 its 1   <p1,p1> = 0
    # for p2 its 2   <p2,p1> = 0   and <p2,p2> = 0 
    # but since we only accept packages when we collect a certain number of packets
    # its equal to the number of packets we collect or the generation
    # that is if we only pollute one packet of the whole generation
    # so for gen = 5, should -> constraints = 5
    ic(data_len, gen_size)
    dof = data_len - gen_size

    ic(field_size)
    ic(field_size**dof, field_size**data_len)
    prob = ic((field_size**dof)/ (field_size**data_len ))


    # we need atleast as many mutable fields as constraints or pollution is
    # not possible. But that should always be the case, since we send more data
    # than tags probably
    if data_len < gen_size:
        prob = 0

    return prob


if __name__ == "__main__":
    #monte_carlo_test()
    ic(calculate_prob_data_pollution(3, 4))
    #ic.enable()
    #ic(len(accepted_packets), accepted_packets)
    #ic(monte_carlo_test())
    
    
    
    '''
    for i in range(1,6): # generation (no 0)
        for j in range(1,7): # number of data fields
            ic(f"probability for generation of {i} and data_fields of {j}:",calculate_prob(i,j))
    '''