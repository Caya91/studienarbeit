import asyncio

# =====================================================================
# 1. THE SOURCE NODE
# =====================================================================
class SourceNode:
    def __init__(self, name, interval=2):
        self.name = name
        self.queue = asyncio.Queue()
        self.outboxes = []
        self.interval = interval
        self.generation = []
        self.rref = []    # maybe add a new class for packets, that keep a reference to the orignal packet
                        # or the position in the original


    def connect_to_receiver(self, receiver):
        self.outboxes.append(receiver.queue)


    def connect_multiple_receivers(self, receivers: list):
        for receiver in receivers:
            self.connect_to_receiver(receiver)
    '''
    def connect_to_sender(self, sender:'NetworkNode'):
        sender.outboxes.add(self.inbox)

    def connect_multiple_senders(self, senders: list['NetworkNode']):
        for sender in senders:
            self.connect_to_sender(sender)

    def disconnect_from_sender(self, sender:'NetworkNode'):
         use this method to signal, that you receive enough packets -> remove from that nodes outbox
        if self.inbox in sender.outboxes:
            sender.outboxes.remove(self.inbox)

    def disconnect_multiple_senders(self, senders:list['NetworkNode']):
         use this method to signal, that you receive enough packets -> remove from multiple nodes outboxes
        for sender in senders:
            self.disconnect_from_sender(sender)


    '''
    async def run(self, global_shutdown: asyncio.Event):
        packet_id = 0
        print(f"[{self.name}] 🟢 Started transmitting.")
        
        # Keep sending until the final node says we are done
        while self.outboxes and not global_shutdown.is_set():
            packet_id += 1
            
            # --- YOUR ENCODING LOGIC HERE ---
            # e.g., random linear combination of your original data matrix
            coded_packet = f"Orig_Coded_Pkt_{packet_id}"
            # --------------------------------
            
            for outbox in self.outboxes:
                await outbox.put(coded_packet)
                
            await asyncio.sleep(self.interval)

# =====================================================================
# 2. THE RELAY NODE (Receives, and later Sends)
# =====================================================================
class RelayNode:
    def __init__(self, name, gen_size, interval=0.5):
        self.name = name
        self.queue = asyncio.Queue()
        self.outboxes = set()
        self.generation = []
        self.gen_size = gen_size
        self.interval = interval
        
        # This acts as a traffic light. Red by default.
        self.can_transmit = asyncio.Event()

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
                # We use a timeout so the loop can periodically check if it 
                # should shut down, rather than blocking forever on an empty queue.
                packet = await asyncio.wait_for(self.queue.get(), timeout=0.2)
                
                # --- YOUR RREF LOGIC HERE ---
                # if calculate_rref(...) shows it's linearly independent:
                if len(self.generation) < self.gen_size:
                    self.generation.append(packet)
                    print(f"[{self.name}] Received. Rank: {len(self.generation)}/{self.gen_size}")
                    
                    if len(self.generation) == self.gen_size:
                        print(f"[{self.name}] 🟢 FULL RANK! Turning on transmitter.")
                        # This instantly wakes up the _sender_task
                        self.can_transmit.set() 
                # ----------------------------
                self.queue.task_done()
            except asyncio.TimeoutError:
                continue

    async def _sender_task(self, global_shutdown: asyncio.Event):
        """Waits until full rank, then pumps out recoded packets."""
        
        # Wait here until the receiver task sets the event (light turns green)
        while not self.can_transmit.is_set() and not global_shutdown.is_set():
            try:
                await asyncio.wait_for(self.can_transmit.wait(), timeout=0.2)
            except asyncio.TimeoutError:
                pass

        packet_id = 0
        # Light is green! Start transmitting recoded data.
        while not global_shutdown.is_set():
            packet_id += 1
            
            # --- YOUR RECODING LOGIC HERE ---
            # e.g., combine rows of self.generation
            recoded_packet = f"Recoded_by_{self.name}_{packet_id}"
            # --------------------------------
            
            for outbox in self.outboxes:
                await outbox.put(recoded_packet)
                
            await asyncio.sleep(self.interval)

    async def run(self, global_shutdown: asyncio.Event):
        """Runs both receiver and sender at the same time."""
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._receiver_task(global_shutdown))
            tg.create_task(self._sender_task(global_shutdown))

# =====================================================================
# 3. THE SINK NODE (Final Destination)
# =====================================================================
class SinkNode:
    def __init__(self, name, gen_size):
        self.name = name
        self.queue = asyncio.Queue()
        self.generation = []
        self.gen_size = gen_size

    async def run(self, global_shutdown: asyncio.Event):
        while not global_shutdown.is_set():
            try:
                packet = await asyncio.wait_for(self.queue.get(), timeout=0.2)
                
                if len(self.generation) < self.gen_size:
                    self.generation.append(packet)
                    print(f"[{self.name}] Received. Rank: {len(self.generation)}/{self.gen_size}")
                    
                    if len(self.generation) == self.gen_size:
                        print(f"\n🎉 [{self.name}] DECODED ALL DATA! Ending simulation. 🎉\n")
                        # This triggers EVERY node in the network to stop
                        global_shutdown.set()
                        
                self.queue.task_done()
            except asyncio.TimeoutError:
                continue

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

    # Global event used to gracefully stop the simulation
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
    
    source = SourceNode("Source", interval=2)
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


if __name__ == "__main__":
    #asyncio.run(main())
    asyncio.run(nodes_2_intermediate())
