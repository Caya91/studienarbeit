from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.custom_field import TableField, create_field
from binary_ext_fields.generate_symbols import generate_symbols_until_nonzero, check_orth_for_recovery, recode_rlnc_without_coeffs

from binary_ext_fields.rref import calculate_rref, invert_pivot_rows

from icecream import ic

import asyncio

class NetworkNode:
    def __init__(self, name):
            self.name = name
            self.queue = asyncio.Queue()
            self.generation = []
            self.rref = []    # maybe add a new class for packets, that keep a reference to the orignal packet
                            # or the position in the original
            self.broken_packets = set() # just int references to the rows in self.generation
            self.threshhold = 3   # after how many packets we start decoding partially

    async def process_packets(self, field:TableField, gen_size:int):
        '''
        idea:  use queues for consumer producer relationship
        producer:  recoding at nodes, recoded packets will go to the consumer
        consumer: nodes that receive packet, will consume them and add them to rref until, 
        >>>they can become producers too( full rank matrix) -> then start recoding too 
        
        consumer should check orthogonality for incoming packet ( verify rows)
        then check rref for packet that are not zero 
        
        '''

        while True:
            current_packet = await self.queue.get()
            self.generation.append(current_packet)
            ic(current_packet, current_packet)
            self_product = inner_product_bytes(field,current_packet, current_packet) 
            ic(self_product)
            #if self_product == 0:
            ic(self.generation, len(self.generation))
            if len(self.generation) >= 3 :
                partial_rref, self.rref = calculate_rref(self.generation, field, gen_size)
                self.rref = invert_pivot_rows(self.rref, field, gen_size)
                ic(self.rref)
            self.queue.task_done()
            break
            #if len(generation) == 0:
                
                # if check_condition(previous_packet, current_packet):
                # print("condition met")

    def node_recode(self, field, gen_size, count):
        '''TODO:  find out if yield is better here, so we could just call this function as a generator
        , or if we use some async function'''
        return recode_rlnc_without_coeffs(field, self.generation, gen_size, count) 
        


async def node_test_simple():
    node1 = NetworkNode("N1")
    field = create_field(3)
    gen_size = 3

    p1 = bytearray([1, 0, 0, 1, 1, 1])
    p2 = bytearray([0, 2, 0, 2, 2, 3])
    p3 = bytearray([0, 0, 3, 3, 5, 5])

    generation = node1.generation

    # Send packets
    await node1.queue.put(p1)
    ic(node1.queue)
    await node1.queue.put(p2)
    ic(node1.queue)
    await node1.queue.put(p3)
    ic(node1.queue)

    ic(node1.generation)

    # Process them (you can call this once, or in a loop in your thesis)
    for _ in range(3):
        await node1.process_packets(field, gen_size)

    ic(node1, node1.generation, node1.rref)


    p4 = bytearray([1, 0, 0, 1, 1, 1])
    p5 = bytearray([0, 2, 0, 2, 2, 3])
    p6 = bytearray([0, 0, 3, 3, 5, 4])   # this should result in 1 flipped bit

    await node1.queue.put(p4)
    ic(node1.queue)
    await node1.queue.put(p5)
    ic(node1.queue)
    await node1.queue.put(p6)
    ic(node1.queue)    

    for _ in range(3):
        await node1.process_packets(field, gen_size)


async def node_test_recoding():
    # lets take 3 nodes source, intermediate and sink
    
    source = NetworkNode("Source")
    intermediate = NetworkNode("Intermediate_Node")
    sink = NetworkNode("Sink")

    field = create_field(3)
    gen_size = 3
    data_fields = 4
    generation = generate_symbols_until_nonzero(field,  data_fields, gen_size, coefficients= True)

    source.generation = generation

    ic(source.generation)

    for packet in source.generation:
        ic(packet)
        await intermediate.queue.put(packet)

    for _ in range(3):
        await intermediate.process_packets(field, gen_size)


    intermediate_recode = []

    intermediate_recode= intermediate.node_recode(field, gen_size, 5)

    ic(intermediate.rref)
    ic(intermediate_recode)

    for packet in intermediate_recode:
        ic(packet)
        await sink.queue.put(packet)
    
    ic(sink.queue)
    ic(sink.generation, sink.rref)

    

    for packet in intermediate_recode:
        ic(packet)
        await sink.process_packets(field, gen_size)

    ic(sink.generation, sink.rref)

'''
    # Send packets
    await node1.queue.put(p1)
    ic(node1.queue)
    await node1.queue.put(p2)
    ic(node1.queue)
    await node1.queue.put(p3)
    ic(node1.queue)

    ic(node1.generation)

    # Process them (you can call this once, or in a loop in your thesis)
    for _ in range(3):
        await node1.process_packets(field, gen_size)

    ic(node1, node1.generation, node1.rref)


    p4 = bytearray([1, 0, 0, 1, 1, 1])
    p5 = bytearray([0, 2, 0, 2, 2, 3])
    p6 = bytearray([0, 0, 3, 3, 5, 4])   # this should result in 1 flipped bit

    await node1.queue.put(p4)
    ic(node1.queue)
    await node1.queue.put(p5)
    ic(node1.queue)
    await node1.queue.put(p6)
    ic(node1.queue)    

    for _ in range(3):
        await node1.process_packets(field, gen_size)

'''



if __name__ == "__main__":
    #asyncio.run(node_test_simple())

    asyncio.run(node_test_recoding())