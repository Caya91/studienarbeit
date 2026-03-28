from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.custom_field import TableField, create_field
from binary_ext_fields.generate_symbols import generate_symbols_until_nonzero, check_orth_for_recovery, recode_rlnc_without_coeffs

from binary_ext_fields.rref import calculate_rref, invert_pivot_rows

from utils.log_helpers import print_generation

from icecream import ic

import asyncio


class NetworkNode:
    def __init__(self, name):
            self.name = name
            self.inbox = asyncio.Queue()
            #self.outbox = asyncio.Queue()     # queue for output packets    # probably not necessary
            self.outboxes: set[asyncio.Queue] = set()  # output adresses (inboxes of other nodes)
            self.generation = []
            self.rref = []    # maybe add a new class for packets, that keep a reference to the orignal packet
                            # or the position in the original
            self.broken_packets = set() # just int references to the rows in self.generation
            self.threshhold = 3   # after how many packets we start decoding partially
            self.decoding_done:bool = False

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
            current_packet = await self.inbox.get()
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
            self.inbox.task_done()
            break
            #if len(generation) == 0:
                
                # if check_condition(previous_packet, current_packet):
                # print("condition met")
    async def run(self):
        print(f"[{self.name}] Node started and is waiting for packets...")
        while True:
            # THIS makes it non-blocking. It yields control back to the 
            # event loop until a packet is placed in this node's queue.
            packet = await self.inbox.get()
            
            if packet is None: # Sentinel value to shut down
                print(f"[{self.name}] Shutting down.")
                self.inbox.task_done()
                break
                
            print(f"[{self.name}] Processed: {packet}")
            self.inbox.task_done()



                

    def node_recode(self, field, gen_size, count):
        '''TODO:  find out if yield is better here, so we could just call this function as a generator
        , or if we use some async function'''
        return recode_rlnc_without_coeffs(field, self.generation, gen_size, count) 
    

    def connect_to_receiver(self, receiver:'NetworkNode'):
        self.outboxes.add(receiver.inbox)  # if i make this a set then probably the if statement is unnecessary


    def connect_multiple_receivers(self, receivers: list['NetworkNode']):
        for receiver in receivers:
            self.connect_to_receiver(receiver)

    def connect_to_sender(self, sender:'NetworkNode'):
        sender.outboxes.add(self.inbox)

    def connect_multiple_senders(self, senders: list['NetworkNode']):
        for sender in senders:
            self.connect_to_sender(sender)

    def disconnect_from_sender(self, sender:'NetworkNode'):
        ''' use this method to signal, that you receive enough packets -> remove from that nodes outbox'''
        if self.inbox in sender.outboxes:
            sender.outboxes.remove(self.inbox)

    def disconnect_multiple_senders(self, senders:list['NetworkNode']):
        ''' use this method to signal, that you receive enough packets -> remove from multiple nodes outboxes'''
        for sender in senders:
            self.disconnect_from_sender(sender)


    def print_config(self):
        print(f"================ {self.name} CONFIG ===============")

        print("Inboxes that im connected to:")
        [print(f"{outbox.__hash__}") for outbox in self.outboxes] # my outboxes are the inboxes of other nodes

        print(f"my own Inbox is: {self.inbox.__hash__}")


    def print_my_generation(self):
        print_generation(self.generation)

    def print_all(self):
        self.print_config()
        self.print_my_generation()


    def decoding_done(self):
        if self.decoding_done:
            return
        return

# TEST FUNCTION JUST FOR SENDING AND RECEIVING ONCE!

    async def _send_packet(self):
        print("_send_packet ENTERED", flush=True)  # <- Add this FIRST
        packet = [1,0,1]
        print(f"outboxes={self.outboxes}, len={len(self.outboxes)}", flush=True)
        for outbox in self.outboxes:
            print(type(outbox), flush=True)
            await outbox.put(packet.copy())
            print(outbox, flush=True)

    async def _receive_send(self):
        print(f"{self.name}")
        while True:
            ic(self.inbox)
            current_packet = await self.inbox.get()
            self.generation.append(current_packet)
            self.inbox.task_done()
            for outbox in self.outboxes:
                await outbox.put(current_packet)
            break
            #if len(generation) == 0:
                
                # if check_condition(previous_packet, current_packet):
                # print("condition met")        


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





async def node_connection_test():
    # lets take 3 nodes source, intermediate and sink
    
    source = NetworkNode("Source")
    
    i_1 = NetworkNode("Intermediate_Node_1")
    i_2 = NetworkNode("Intermediate_Node_2")
    i_3 = NetworkNode("Intermediate_Node_3")
    
    sink = NetworkNode("Sink")

    # connect them
    # source to 3 intermediate nodes
    source.connect_multiple_receivers([i_1, i_2, i_3])
    source.connect_multiple_receivers([i_1, i_2, i_3])   # testing if double connecting produces errors
    # intermediate nodes to sink

    sink.connect_multiple_senders([i_1, i_2, i_3])
    sink.connect_multiple_senders([i_1, i_2, i_3])   # testing if double connecting produces errors





    source.print_config()
    i_1.print_config()
    i_2.print_config()
    i_3.print_config()
    sink.print_config()


async def node_disconnect_test():
    # lets take 3 nodes source, intermediate and sink
    
    source = NetworkNode("Source")
    
    i_1 = NetworkNode("Intermediate_Node_1")
    i_2 = NetworkNode("Intermediate_Node_2")
    i_3 = NetworkNode("Intermediate_Node_3")
    
    sink = NetworkNode("Sink")

    # connect them
    # source to 3 intermediate nodes
    source.connect_multiple_receivers([i_1, i_2, i_3])
    

    i_1.disconnect_from_sender(source)
    i_2.disconnect_from_sender(source)
    i_3.disconnect_from_sender(source)


    sink.connect_multiple_senders([i_1, i_2, i_3])
    sink.disconnect_multiple_senders([i_1, i_2, i_3])

    source.print_config()
    i_1.print_config()
    i_2.print_config()
    i_3.print_config()
    sink.print_config()


async def node_send_receive_test():
    # lets take 3 nodes source, intermediate and sink
    
    source = NetworkNode("Source")
    
    i_1 = NetworkNode("Intermediate_Node_1")
    i_2 = NetworkNode("Intermediate_Node_2")
    i_3 = NetworkNode("Intermediate_Node_3")
    
    sink = NetworkNode("Sink")

    # connect them
    # source to 3 intermediate nodes
    source.connect_multiple_receivers([i_1, i_2, i_3])

    sink.connect_multiple_senders([i_1, i_2, i_3])


    print("=== CONNECTING ===", flush=True)
    print(f"i_1.inbox id={id(i_1.inbox)}", flush=True)
    sink.outboxes.add(i_1.inbox)
    print(f"sink.outboxes after add: {sink.outboxes}", flush=True)
    print(f"len(sink.outboxes)={len(sink.outboxes)}", flush=True)
    print(f"i_1.inbox in sink.outboxes: {i_1.inbox in sink.outboxes}", flush=True)

    # send the packets

    await source._send_packet()
    source.print_all()

    print("weh should send before this")
    await i_1._receive_send()
    await i_2._receive_send()
    await i_3._receive_send()
    await sink._receive_send()
    await sink._receive_send()
    await sink._receive_send()


    source.print_all()
    i_1.print_all()
    i_2.print_all()
    i_3.print_all()
    sink.print_all()


async def node_disconnect_test():
    # lets take 3 nodes source, intermediate and sink
    
    source = NetworkNode("Source")
    
    i_1 = NetworkNode("Intermediate_Node_1")
    i_2 = NetworkNode("Intermediate_Node_2")
    i_3 = NetworkNode("Intermediate_Node_3")
    
    sink = NetworkNode("Sink")

    # connect them
    # source to 3 intermediate nodes
    source.connect_multiple_receivers([i_1, i_2, i_3])
    

    i_1.disconnect_from_sender(source)
    i_2.disconnect_from_sender(source)
    i_3.disconnect_from_sender(source)


    sink.connect_multiple_senders([i_1, i_2, i_3])
    sink.disconnect_multiple_senders([i_1, i_2, i_3])

    source.print_config()
    i_1.print_config()
    i_2.print_config()
    i_3.print_config()
    sink.print_config()


async def node_concurrency_test():
    # lets take 3 nodes source, intermediate and sink
    
    source = NetworkNode("Source")
    
    i_1 = NetworkNode("Intermediate_Node_1")
    i_2 = NetworkNode("Intermediate_Node_2")
    i_3 = NetworkNode("Intermediate_Node_3")
    
    sink = NetworkNode("Sink")

    # This block automatically starts them concurrently and waits for them to finish
    async with asyncio.TaskGroup() as tg:
        tg.create_task(i_1.run())
        tg.create_task(i_2.run())
        tg.create_task(i_3.run())
    

    
    await i_1.inbox.put("Data 1")
    await i_2.inbox.put("Data 2") # stop node 1
    await i_3.inbox.put("Data 3") # stop node 2
    await i_1.inbox.put(None)
    await i_2.inbox.put(None)
    await i_3.inbox.put(None)


        # Feed them packets while they run in the background
    #source._send_packet()
    '''
    '''
    
    
    
    '''
    
    # connect them
    # source to 3 intermediate nodes
    source.connect_multiple_receivers([i_1, i_2, i_3])

    sink.connect_multiple_senders([i_1, i_2, i_3])


    print("=== CONNECTING ===", flush=True)
    print(f"i_1.inbox id={id(i_1.inbox)}", flush=True)
    sink.outboxes.add(i_1.inbox)
    print(f"sink.outboxes after add: {sink.outboxes}", flush=True)
    print(f"len(sink.outboxes)={len(sink.outboxes)}", flush=True)
    print(f"i_1.inbox in sink.outboxes: {i_1.inbox in sink.outboxes}", flush=True)

    # send the packets

    await source._send_packet()
    source.print_all()

    print("weh should send before this")
    await i_1._receive_send()
    await i_2._receive_send()
    await i_3._receive_send()
    await sink._receive_send()
    await sink._receive_send()
    await sink._receive_send()


    source.print_all()
    i_1.print_all()
    i_2.print_all()
    i_3.print_all()
    sink.print_all()


'''

if __name__ == "__main__":
    #asyncio.run(node_test_simple())

    #asyncio.run(node_test_recoding()) #TODO: sometimes an error with rref happens here

    #asyncio.run(node_connection_test())

    #asyncio.run(node_disconnect_test())

    #asyncio.run(node_send_receive_test())

    asyncio.run(node_concurrency_test())


