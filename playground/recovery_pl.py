

'''
what is the idea for combined recovery ?

we take packets that we think we are faulty and rows that we think are faulty
and with this intersection, we can determine which column exactly we will be searching for repairs

the combined recovery will be combining 2 packets / segments and their tags via XOR
and then repairing the resulting packet from that. The search space for that should be 
field_size^2

[1 0 0][1 0 0]
[0 1 0][0 1 0]
[0 0 1][0 0 1]

next packet
[1 2 3][1 2 3] # thats what it should be

we can guess the packet through our rref form before

but if the packet has an error , for example
[1 2 3][1 2 4]      # we should be able to see that error, check the hamming distance
                    # and repair it with searching the right columns, and afterwards checking again

in our rref it would look like this:

[1 0 0][1 0 0]
[0 1 0][0 1 0]
[0 0 1][0 0 1]
[0 0 0][0 0 1]  # this packet should be all zeros, but now its not which means
                # there is probably an error


idea:

- make 2 functions
1. takes broken packets with broken columns and trys to repair
2. other uses rref to find broken columns and orthogonality to find broken packets


'''
class NetworkNode:
     def __init__(self, name):
          self.name = name
          self.generation = []
          self.rref = []





matrix_healthy = [
    [1, 0, 0, 1, 0, 0],
    [0, 1, 0, 0, 1, 0],
    [0, 0, 1, 0, 0, 1],
    [0, 0, 0, 0, 0, 0]
    ]

matrix_1_bitflip = [
    [1, 0, 0, 1, 0, 0],
    [0, 1, 0, 0, 1, 0],
    [0, 0, 1, 0, 0, 1],
    [0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 1]
    ]

matrix_broken_coeff = [
    [1, 0, 0, 1, 0, 0],
    [0, 1, 0, 0, 1, 0],
    [0, 0, 0, 0, 0, 1],
    [0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0]
    ]


matrix_many_errors = [
    [1, 0, 0, 1, 0, 0],
    [0, 1, 0, 0, 1, 0],
    [0, 0, 1, 0, 0, 1],
    [0, 0, 0, 0, 1, 1],
    [0, 3, 2, 1, 1, 1],
    [1, 0, 0, 0, 1, 1],
    [0, 0, 0, 0, 1, 0],
    [0, 0, 0, 0, 0, 0]
    ]


from binary_ext_fields.custom_field import TableField, create_field
from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator as OTC
from binary_ext_fields.generate_symbols import generate_symbols_until_nonzero, check_orth_for_recovery, get_recovery_regions, nr_of_error_columns
from binary_ext_fields.generate_symbols import check_orth

import asyncio
import queue

from icecream import ic



'''
we should always know generation size, and through that , the lenght of the data segment of the packet
'''


async def process_packets(packet_queue: asyncio.Queue, generation:list[bytearray]):
    '''
    idea:  use queues for consumer producer relationship
    producer:  recoding at nodes, recoded packets will go to the consumer
    consumer: nodes that receive packet, will consume them and add them to rref until, 
    >>>they can become producers too( full rank matrix) -> then start recoding too 
    
    consumer should check orthogonality for incoming packet ( verify rows)
    then check rref for packet that are not zero 
    
    '''

    previous_packet = None

    while True:
        current_packet = await packet_queue.get()

        if len(generation) == 0:
            generation.append(current_packet)
            # check current packet to prior one
            # if check_condition(previous_packet, current_packet):
            # print("condition met")
            packet_queue.task_done()
            break
        
    previous_packet = current_packet   #  change to:  add the current packet to generation
    packet_queue.task_done()


def test_recovery():
     
    count_check = bytearray([1,2,2,2,2,2,0,0,2])
    gen_size = 3
    field = create_field(3)

    ic(get_recovery_regions(field, matrix_healthy, gen_size))
    ic(get_recovery_regions(field, matrix_1_bitflip, gen_size))
    ic(get_recovery_regions(field, matrix_broken_coeff, gen_size))
    ic(get_recovery_regions(field, matrix_many_errors, gen_size))

    # decide when or when not to fix packet heuristic:  
    # if more than 2 errors -> dont bother fixing

    less_errors_rr =get_recovery_regions(field, matrix_1_bitflip, gen_size)
    more_errors_rr =get_recovery_regions(field, matrix_many_errors, gen_size)
    
    ic(len(less_errors_rr),
    len(more_errors_rr))

    errors = 0
    for key, value in more_errors_rr.items():
        errors += len(value)

    ic(errors)


    # decide how many errors is too many
    error_boundary = 1

    recovery_candidates = set()
    for key,value in more_errors_rr.items():
        ic(key,value)
        ic(nr_of_error_columns(key,value))
        if nr_of_error_columns(key,value) > error_boundary:
            continue
        else:
            recovery_candidates.add(key)

    ic(recovery_candidates)

    # how to recover now?
    # brute force, all the possible values for the row and check if the error is fixed now


    # need the original packet
    # lets assume the row is the original row

    candidate_row_int = recovery_candidates.pop()


    # prepare the generation
    # remove original candidate packet, then add the new one, look for orthogonality now

    ic(matrix_many_errors)

    candidate_row = matrix_many_errors.pop(candidate_row_int)
    ic(candidate_row)
    ic(matrix_many_errors)

    # check here if the matrix itself is orthogonal, then proceed to check if changed 
    # version of the packet are orthogonal wth the rest

    matrix_many_errors_orthogonal = [
    [1, 0, 0, 1, 0, 0],
    [0, 1, 0, 0, 1, 0],
    [0, 0, 1, 0, 0, 1],
    [0, 0, 0, 0, 0, 0]
    ]

    matrix_many_errors_not_orthogonal = [
    [1, 0, 0, 1, 0, 0],
    [0, 1, 0, 0, 1, 0],
    [0, 0, 1, 0, 0, 1],
    [0, 0, 0, 2, 0, 1]
    ]

    accept = check_orth(field, matrix_many_errors_orthogonal)
    not_accept = check_orth(field, matrix_many_errors_not_orthogonal)

    ic(accept, not_accept)

    
        # TODO: this should become a function that takes in the nr of columns to repair
        # and then returns combinations of corrected packets to correct
    for column in more_errors_rr.get(candidate_row_int):
        accepts = False
        for i in range(field.max_value, -1, -1):
                new_row = candidate_row.copy()
                new_row[column] = i   # change element

                # check if now orthogonal to other elements, and self orthogonal, and zero
            
                accepts = ic(check_orth(field,matrix_many_errors_orthogonal ,check_packet=new_row ))
                if accepts:
                     break
                

    ic(accepts, new_row)

    matrix_many_errors_fixed = matrix_many_errors_orthogonal + [new_row]
    ic(matrix_many_errors_fixed)


def stepwise_rref(): 
    return



if __name__ == "__main__" :


    #generation = matrix_1_bitflip
    #for i, packet in enumerate(generation):


    count_check = bytearray([1,2,2,2,2,2,0,0,2])
    gen_size = 3
    field = create_field(3)


    stepwise_rref()



    '''
    failure_rows_1 = check_orth_for_recovery(field, matrix_healthy, gen_size)
    failure_rows_2 = check_orth_for_recovery(field, matrix_1_bitflip, gen_size)
    
    ic(failure_rows_1, failure_rows_2)

    broken_rows = []
    for e in failure_rows_1:
        broken_rows.append(matrix_healthy[e].copy())

    ic(broken_rows)

    broken_rows = []
    for e in failure_rows_2:
        broken_rows.append(matrix_1_bitflip[e].copy())

    ic(broken_rows)

    '''
            




