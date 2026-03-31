import asyncio

from binary_ext_fields.generate_symbols import generate_symbols_until_nonzero, recode_rlnc_without_coeffs, recode_rlnc
from binary_ext_fields.custom_field import create_field, TableField
from binary_ext_fields.rref import matrix_full_rank, calculate_only_partial_rref, stepwise_partial_rref


from utils.log_helpers import print_generation

from icecream import ic


threshold = 3


# =====================================================================
# 1. THE SOURCE NODE
# =====================================================================
class SourceNode:
    def __init__(self, name, generation:list[list], field:TableField, interval=0.5):
        self.name = name
        self.queue = asyncio.Queue()
        self.outboxes = []
        self.interval = interval    # dunno if we need an interval
        self.field = field
        self.generation = generation
        self.gen_size = len(generation)
        self.send_packets = []


    def connect_to_receiver(self, receiver):
        self.outboxes.append(receiver.queue)


    def connect_multiple_receivers(self, receivers: list):
        for receiver in receivers:
            self.connect_to_receiver(receiver)


    async def run(self, global_shutdown: asyncio.Event):
        packet_id = 0
        print(f"[{self.name}] 🟢 Started transmitting.")
        
        # Keep sending until the final node says we are done
        while self.outboxes and not global_shutdown.is_set():


            for outbox in self.outboxes:
                packet = recode_rlnc_without_coeffs(self.field, self.generation, self.gen_size, count=1 )
                self.send_packets.append(packet.copy())
                print(f"Sending packet:    {packet}")
                await outbox.put(packet)
                
            await asyncio.sleep(self.interval)

    def print_config(self):
            print(f"================ {self.name} CONFIG ===============")

            print("Inboxes that im connected to:")
            [print(f"{outbox.__hash__}") for outbox in self.outboxes] # my outboxes are the inboxes of other nodes

            #print(f"my own Inbox is: {self.queue.__hash__}")

    def print_my_generation(self):
        print_generation(self.generation)

        print("____Packets that I send: ____")
        print_generation(self.send_packets)

    def print_all(self):
        self.print_config()
        self.print_my_generation()
    

# =====================================================================
# 2. THE RELAY NODE (Receives, and later Sends)
# =====================================================================
class RelayNode:
    def __init__(self, name, field:TableField, gen_size, interval=0.5):
        self.name = name
        self.queue = asyncio.Queue()
        self.outboxes = set()
        self.field = field
        self.generation = []
        self.gen_size = gen_size
        self.interval = interval
        self.rref = []
        

        self.can_transmit = asyncio.Event()  # this is off by default, has to be turned on

    def connect_to_receiver(self, receiver):
        self.outboxes.add(receiver.queue)


    def connect_multiple_receivers(self, receivers: list):
        for receiver in receivers:
            self.connect_to_receiver(receiver)
    

    def connect_to_sender(self, sender):
        sender.outboxes.add(self.inbox)

    def connect_multiple_senders(self, senders: list):
        for sender in senders:
            self.connect_to_sender(sender)

    def disconnect_from_sender(self, sender):
        if self.inbox in sender.outboxes:
            sender.outboxes.remove(self.inbox)

    def disconnect_multiple_senders(self, senders:list):
        for sender in senders:
            self.disconnect_from_sender(sender)


    async def _receiver_task(self, global_shutdown: asyncio.Event):
        """Listens for packets and builds the matrix."""
        while not global_shutdown.is_set():
            try:
                packet = await asyncio.wait_for(self.queue.get(), timeout=0.4)
                
                self.generation.append(packet)
                print(f"[{self.name}] Received. Rank: {len(self.generation)}/{self.gen_size}")

                if len(self.rref) > 0:
                    ic("Before", self.rref)
                    packet_for_rref = stepwise_partial_rref(self.generation, packet, self.field, self.gen_size)
                    self.rref.append(packet_for_rref) 
                    ic("After", self.rref)

                if len(self.generation) == threshold and len(self.rref) == 0:
                    # ic("Before", self.rref)
                    self.rref = calculate_only_partial_rref(self.generation, self.field, self.gen_size)
                    # ic("After", self.rref)


                if matrix_full_rank(self.rref, self.gen_size):
                    print(f"[{self.name}] 🟢 FULL RANK! Turning on transmitter.")
                    self.print_my_generation()
                    self.can_transmit.set() 
                # ----------------------------
                self.queue.task_done()
            except asyncio.TimeoutError:
                continue

    async def _sender_task(self, global_shutdown: asyncio.Event):
        """Waits until full rank, then pumps out recoded packets."""
        
        # Wait until the receiver task sets the event
        while not self.can_transmit.is_set() and not global_shutdown.is_set():
            try:
                await asyncio.wait_for(self.can_transmit.wait(), timeout=0.4)
            except asyncio.TimeoutError:
                pass

        packet_id = 0

        while not global_shutdown.is_set():
            packet_id += 1
            
            ic("Checking all variables before calling recode", self.field, self.rref[::self.gen_size + 1 ], self.gen_size)
            recoded_packet = recode_rlnc_without_coeffs(self.field, self.rref[::self.gen_size +1 ], self.gen_size, 1)  # slice until gen.size
            
            for outbox in self.outboxes:
                await outbox.put(recoded_packet)
                
            await asyncio.sleep(self.interval)

    async def run(self, global_shutdown: asyncio.Event):
        """Runs both receiver and sender at the same time."""
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._receiver_task(global_shutdown))
            tg.create_task(self._sender_task(global_shutdown))


    def print_config(self):
            print(f"================ {self.name} CONFIG ===============")

            print("Inboxes that im connected to:")
            [print(f"{outbox.__hash__}") for outbox in self.outboxes] # my outboxes are the inboxes of other nodes

            print(f"my own Inbox is: {self.queue.__hash__}")

    def print_my_generation(self):
        print("======= My received packets ======")
        print_generation(self.generation)

        print("======= My partial rref ======")
        print_generation(self.rref)

    def print_all(self):
        self.print_config()
        self.print_my_generation()

# =====================================================================
# 3. THE SINK NODE
# =====================================================================
class SinkNode:
    def __init__(self, name,  field, gen_size ):
        self.name = name
        self.queue = asyncio.Queue()
        self.generation = []
        self.gen_size = gen_size
        self.field = field 
        self.rref = []

    async def run(self, global_shutdown: asyncio.Event):
        while not global_shutdown.is_set():
            try:
                packet = await asyncio.wait_for(self.queue.get(), timeout=0.2)

                self.generation.append(packet)
                print(f"[{self.name}] Received. Rank: {len(self.generation)}/{self.gen_size}")

                if len(self.rref) > 0:
                    ic(self.rref)
                    packet_for_rref = stepwise_partial_rref(self.generation, packet, self.field, self.gen_size)
                    self.rref.append(packet_for_rref) 

                if len(self.generation) == threshold and len(self.rref) == 0:
                    ic(self.rref)
                    self.rref = calculate_only_partial_rref(self.generation, self.field, self.gen_size)
                    ic(self.rref)


                if matrix_full_rank(self.rref, self.gen_size):
                    print(f"[{self.name}] 🟢 FULL RANK! Turning on transmitter.")
                    global_shutdown.set()
                    self.print_my_generation()                
                        
                self.queue.task_done()
            except asyncio.TimeoutError:
                continue

    def print_config(self):
        print(f"================ {self.name} CONFIG ===============")

        print(f"my own Inbox is: {self.queue.__hash__}")

    def print_my_generation(self):
        print("======= My received packets ======")
        print_generation(self.generation)

        print("======= My partial rref ======")
        print_generation(self.rref)

    def print_all(self):
        self.print_config()
        self.print_my_generation()

# =====================================================================
# SIMULATION RUNNER
# =====================================================================
async def main():
    # Require 3 packets to achieve full rank
    gen_size = 3 
    
    source = SourceNode("Source", interval=2)
    relay1 = RelayNode("Relay_1", gen_size=gen_size, interval=0.3)
    relay2 = RelayNode("Relay_2", gen_size=gen_size, interval=0.3)
    sink = SinkNode("Final_Sink", gen_size=gen_size)

    # Topology: Source -> Relay1 -> Relay2 -> Sink
    source.connect_to_receiver(relay1)
    relay1.connect_to_receiver(relay2)
    relay2.connect_to_receiver(sink)

    # Global event to stop simulation
    global_shutdown = asyncio.Event()

    print("--- Starting Network Coding Simulation ---")
    async with asyncio.TaskGroup() as tg:
        tg.create_task(source.run(global_shutdown))
        tg.create_task(relay1.run(global_shutdown))
        tg.create_task(relay2.run(global_shutdown))
        tg.create_task(sink.run(global_shutdown))
        
    print("--- Simulation Safely Shut Down ---")


async def nodes_2_intermediate():
    # Require 3 packets to achieve full rank
    gen_size = 3 
    
    source = SourceNode("Source", interval=0.3)
    relay1 = RelayNode("Relay_1", gen_size=gen_size, interval=0.3)
    relay2 = RelayNode("Relay_2", gen_size=gen_size, interval=0.3)
    sink = SinkNode("Final_Sink", gen_size=gen_size)

    # Topology: Source -> Relay1 -> Relay2 -> Sink
    source.connect_to_receiver(relay1)
    source.connect_to_receiver(relay2)
    relay1.connect_to_receiver(sink)
    relay2.connect_to_receiver(sink)

    # Global event used to gracefully stop the simulation
    global_shutdown = asyncio.Event()

    print("--- Starting Network Coding Simulation ---")
    async with asyncio.TaskGroup() as tg:
        tg.create_task(source.run(global_shutdown))
        tg.create_task(relay1.run(global_shutdown))
        tg.create_task(relay2.run(global_shutdown))
        tg.create_task(sink.run(global_shutdown))
        
    print("--- Simulation Safely Shut Down ---")


async def stepwise_rref_test():
    # Require 3 packets to achieve full rank
    gen_size = 3 
    data_fields = 3
    field_int= 3
    field = create_field(field_int)
    
    generation = generate_symbols_until_nonzero(field, data_fields, gen_size, True)

    source = SourceNode("Source", generation, field, interval=0.3)
    relay1 = RelayNode("Relay_1", field, gen_size=gen_size, interval=0.4)
    relay2 = RelayNode("Relay_2", field, gen_size=gen_size, interval=0.5)
    sink = SinkNode("Final_Sink", field,  gen_size=gen_size)

    # Topology: Source -> Relay1 -> Relay2 -> Sink
    source.connect_to_receiver(relay1)
    source.connect_to_receiver(relay2)
    relay1.connect_to_receiver(sink)
    relay2.connect_to_receiver(sink)

    # Global event used to gracefully stop the simulation
    global_shutdown = asyncio.Event()

    print("--- Starting Network Coding Simulation ---")
    async with asyncio.TaskGroup() as tg:
        tg.create_task(source.run(global_shutdown))
        tg.create_task(relay1.run(global_shutdown))
        tg.create_task(relay2.run(global_shutdown))
        tg.create_task(sink.run(global_shutdown))
        
    print("--- Simulation Safely Shut Down ---")

    source.print_all()
    relay1.print_all()
    relay2.print_all()
    sink.print_all()





if __name__ == "__main__":
    #asyncio.run(main())
    #asyncio.run(nodes_2_intermediate())
    asyncio.run(stepwise_rref_test())
