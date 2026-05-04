import pyerasure
import pyerasure.finite_field
import random
import statistics
from icecream import ic

def write_to_file(text):
    with open("debug.log", "a") as f:
        f.write(text + "\n")


#ic.configureOutput(outputFunction=write_to_file)

# TODO: implement functions for estimating
# 1. probability of polluted packet to be accepted
# 2. probability of generating a packet with inner product 0
# 3. 




def calculate_prob_data_pollution(field:pyerasure.finite_field, gen_size, data_len):
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


#def prob_one_generation_no_error()


def calculate_error_prob(field_size: int, gen_size: int, k: int):
    '''
    Probability that k random vectors over GF(q)^k do NOT span the full space.
    k: number of received packets
    gen_size: generation size (dimension)
    field_size: field size (e.g. 256 for GF(2^8))
    '''
    # no error, one packet
    ic(f"field size: {field_size}")
    elements = 2**field_size
    ic(f"Elements: {elements}")
    ic(f"Chance for error in one packet: {1/elements}")
    p = 1 - 1/elements
    ic("Prob -> no error in one packet packet", p)

    # no error, times gen_size (except last one)
    p = p ** (gen_size - 1)
    ic("Prob -> no error in generation", p)

    # 1 - no error: -> 1 or more errors in the generation
    #p = 1 - p
    #ic("Prob -> 1 or more packets have errors in the generation", p)

    # error prob with swap
    #p = (p ** (k-1) ) * ((1- 1/elements) ** (gen_size - 1))
    #ic(f"Prob -> Probability of no error in a generation with {k} swaps", p)


    # for the k-th packet
    #p = (p ** (k -1 )) * ((1 - 1/field_size) ** (gen_size -1)  )
    #ic("Prob -> 1 or)

    # p = ((1-(1-1/field_size)**(gen_size - 1))**(k - 1)) * (1-1/field_size)**(gen_size - 1) 

    return p


def acceptance_probability_tag_error( field_size:int, gen_size:int):
    sigma = ic(1 - (1/field_size))
    
    return sigma ** gen_size

if __name__ == "__main__":
    #monte_carlo_test()

    #ic.enable()
    #ic(len(accepted_packets), accepted_packets)
    #ic(calculate_prob_data_pollution(GEN_SIZE, DATA_FIELDS))
    #ic(monte_carlo_test())
    
    
    #ic(acceptance_probability_tag_error(256, 7))
    
    '''
    field_4 = pyerasure.finite_field.Binary4()
    field_8 = pyerasure.finite_field.Binary8()


    ic(calculate_prob_data_pollution(field_4, 2, 10))
    ic(calculate_prob_data_pollution(field_4, 4, 10))
    
    ic(calculate_prob_data_pollution(field_8, 2, 10))
    ic(calculate_prob_data_pollution(field_8, 4, 10))
    '''

    print( calculate_error_prob(2,8,0))
    #print( calculate_error_prob(8,100,3))

    error_probs = []
    for gen_size in [8 , 16 , 32 , 64 , 128 ]:
        #print(calculate_error_prob(8, gen_size, 3))
        error_probs.append(f"Error Probability for gen size: {gen_size} = {calculate_error_prob(8, gen_size, 3)}")
    for field_size in [2, 3 , 4 , 5 , 6 , 7 ]:
        #print(calculate_error_prob(field_size, 100, 3))
        error_probs.append(f"Error Probability for field size:{field_size} = {calculate_error_prob(field_size, 100, 3)}")   

    ic(error_probs)

