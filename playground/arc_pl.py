"""
k packets are necessary for decoing the matrix

we take k+1  and decode the original symbols
with that we guess the other packet

we are checking for each column
columns that dont chekc out get marked as potentially wrong

the wrong columns of our packets become our search spaces for recovery


ideas:

first start with identity matrix I + 1 packet
leave out the last packet 
-> calculate rref 
-> use coefficients from last packet
-> guess the symbol

How to note where and potential error columns are
and how to use that for repairing?

plan: make 2 functions, 1  where i take a deterministic packet out
and 1 where i take random packets out and check them



"""


from icecream import ic
import random

start_matrix =[
    [1,0,0],
    [0,1,0],
    [0,0,1],
    [1,1,1]
]

long_matrix =[
    [1,0,0],
    [0,1,0],
    [0,0,1],
    [1,1,1],
    [2,2,2],
    [3,3,3]
]



def acr_prepare_matrix(Matrix:list[list[int]], gen_size) -> tuple[list[list[int]], list[int]]: 
    return  Matrix[:gen_size], Matrix[-1]


def acr_prepare_matrix_random(Matrix:list[list[int]], gen_size) -> tuple[list[list[int]], list[int]]: 
    potential_packet = random.randint(gen_size, len(Matrix)-1)
    ic(potential_packet)
    ic(Matrix[potential_packet])
    return  Matrix[:gen_size], Matrix[potential_packet]


def acr_prepare_matrix_full_random(Matrix:list[list[int]], gen_size) -> tuple[list[list[int]], list[int]]: 
    # select random packet according to gen_size
    # other packets can be used for checking
    packet_list = list(range(0,len(Matrix)))
    ic(packet_list)
    base_matrix = []
    for i in range(0,gen_size):
        ic(i)
        random_row = packet_list.pop(random.randrange(0,len(packet_list))) # pop random item from list of packets
         
        base_matrix.append(Matrix[random_row].copy())

    # select random remaining packet
    random_packet = packet_list.pop(random.randrange(0,len(packet_list))) # pop random item from list of packets
    checked_packet = Matrix[random_packet].copy()


    ic(base_matrix)
    ic(checked_packet)
    ic(packet_list)
    
    return  #Matrix[:gen_size], Matrix[-1]


if __name__ == "__main__":
    '''
    ic(len(start_matrix))
    ic(acr_prepare_matrix(start_matrix,3))
    ic(acr_prepare_matrix_random(start_matrix,3))
    ic(acr_prepare_matrix_random(long_matrix,3))
    '''

    acr_prepare_matrix_full_random(start_matrix,3)
    acr_prepare_matrix_full_random(long_matrix,3)





