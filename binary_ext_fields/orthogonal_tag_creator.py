import pyerasure
import pyerasure.finite_field
import random
from typing import Any
from icecream import ic
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.custom_field import TableField, build_tables_gf2m, PRIMES_GF2M


from utils.log_helpers import log_packet, get_playground_dir, _interal_log_packet, write_to_file

ic.configureOutput(outputFunction=write_to_file)



verbose = False

dir =  get_playground_dir("generate_with_bitshift.txt")

class OrthogonalTagGenerator:
    def __init__(self, field:TableField):
        self.field = field
        self.square_to_root = {}  # key: square  ; value: root
        self.mul_table = []

        tmp = bytearray(1)
        for x in range(field.max_value + 1):
            tmp[0] = x
            field.vector_multiply_into(tmp, x)  # tmp[0] = x * x   mod fieldsize
            sq = tmp[0]
            if sq not in self.square_to_root:
                self.square_to_root[sq] = x  # write square, root pair into dict
        
        self.mul_table = []
        for i in range(field.max_value +1):
            row = []
            for j in range (field.max_value + 1):
                x = [j]
                field.vector_multiply_into(x,i)
                row.append(x[0])
            self.mul_table.append(row)

    
    def generate_tag(self, d: int) ->  int:
        assert d <= self.field.max_value

        t2 = self.square_to_root.get(d, None)
        if t2 is not None:
            return t2
        
        # Rare fallback: try next t1
        #ic("t2 should not be none", t2)
        return None # self.tags(d)  # Recurse (very rare
    

    def generate_tag_cross(self, t1: int, d: int) ->  int:
        '''
        for a the given value of the tag of another packet and the inner product d = <t1,t2>
        generates the tag to make the packet orthogonal
        by looking up the given tag in a multiplication table and looking for the element that
        generates the same value

        '''
        assert d <= self.field.max_value
        assert t1 <= self.field.max_value

        # falls der Tag des anderen Packets 0 ist -> wähle einen Tag random aus
        #ic.disable()
        #if verbose:
        #    ic.enable()
            
        
        if t1 == 0:
            return random.randint(0, self.field.max_value)
        #ic(self.mul_table[t1])
        for i, element in enumerate(self.mul_table[t1]):
            if element == d:
                t2 = i
                #ic("t1 * i = d", t1, i, d)
                #ic("check mit inner product, should be d", inner_product_bytes(field, bytearray([t1]),bytearray([i])))
                return t2
        
        # Rare fallback:
        #ic("t2 should not be none for cross tag generation", t2)
        return None # self.tags(d)  # Recurse (very rare

    def generate_all_tags(self, generation:list[bytearray]):
        # TODO: implement a flag and function that switches the order of packets when there is one that is has self ortho tag = 0 
        # or make a new function for that
        
        #ic.enable()
        #ic()
        gen_size = len(generation)
        data_len = len(generation[0]) - gen_size

        new_symbols = []

        i = data_len

        #ic(generation)

        for count, symbol in enumerate(generation):
            #ic("OUTER LOOP", i, count, symbol)
            #ic()
            i = data_len + 1

            new_symbol = symbol.copy()
            for tag_nr in range(count + 1):

                #ic("INNER LOOP", tag_nr, count)
                if tag_nr == count: # if the tag_nr and the count is the same, we calculate our own inner product, to make packet self orthogonal
                    tag = self.generate_tag(inner_product_bytes(self.field, new_symbol, new_symbol))
                    new_symbol[data_len + tag_nr] = tag
                    new_symbols.append(new_symbol)
                    continue

                corresponding_packet = new_symbols[tag_nr]  # tag_nr is also the corrseponding symbol in the generation, so we take innerproduct with that packet


                tag = self.generate_tag_cross(corresponding_packet[data_len + tag_nr ],inner_product_bytes(self.field,new_symbol, corresponding_packet))
                #ic()
                new_symbol[data_len + tag_nr] = tag
                #ic(new_symbols)

        #ic(new_symbol)
        return new_symbols

    def generate_all_tags_with_swap(self, generation: list[bytearray]) -> list[bytearray]:
        '''
        Like generate_all_tags, but whenever a packet would get self-tag == 0,
        swap it with a random later packet that has not been processed yet (if any).
        '''
        gen_size = len(generation)
        data_len = len(generation[0]) - gen_size

        # Work on a local copy of the generation so we can reorder safely
        work_gen = [g.copy() for g in generation]
        new_symbols: list[bytearray] = []

        for count in range(gen_size):
            # If this is not the last packet, and we detect self-tag 0, try swapping
            # Pick current symbol
            symbol = work_gen[count]
            new_symbol = symbol.copy()

            # First, generate all cross-tags to already processed packets
            for tag_nr in range(count):
                corresponding_packet = new_symbols[tag_nr]
                tag = self.generate_tag_cross(
                    corresponding_packet[data_len + tag_nr],
                    inner_product_bytes(self.field, new_symbol, corresponding_packet),
                )
                new_symbol[data_len + tag_nr] = tag

            # Now compute self-tag
            self_tag = self.generate_tag(inner_product_bytes(self.field, new_symbol, new_symbol))

            # If self-tag is 0 and there are remaining unused packets, swap with a random one
            if self_tag == 0 and count < gen_size - 1:
                # choose a random index from the remaining packets [count+1, gen_size)
                swap_idx = random.randrange(count + 1, gen_size)
                # swap packets in work_gen
                work_gen[count], work_gen[swap_idx] = work_gen[swap_idx], work_gen[count]

                # re-start this iteration with the swapped-in packet
                symbol = work_gen[count]
                new_symbol = symbol.copy()

                # re-generate cross-tags for already processed packets
                for tag_nr in range(count):
                    corresponding_packet = new_symbols[tag_nr]
                    tag = self.generate_tag_cross(
                        corresponding_packet[data_len + tag_nr],
                        inner_product_bytes(self.field, new_symbol, corresponding_packet),
                    )
                    new_symbol[data_len + tag_nr] = tag

                # recompute self-tag (hope it is non-zero now)
                self_tag = self.generate_tag(inner_product_bytes(self.field, new_symbol, new_symbol))

            # write (possibly still 0) self-tag and store packet
            new_symbol[data_len + count] = self_tag
            new_symbols.append(new_symbol)

        return new_symbols


    def generate_all_tags_bitshift(self, generation: list[bytearray], bitshift:int = 1 ) -> list[bytearray]:
            '''
            bitshift determines how many fields can be altered, when shifting bits( 1 means only the first field, 2 means first 2 fields etc)
            Like generate_all_tags, but whenever a packet would get self-tag == 0,
            swap it with a random later packet that has not been processed yet (if any).
            '''
            
            def _shift_firstbit(packet:list[int] | bytearray, i:int) ->  list[int]| bytearray:
                '''shifts first bit of the packet, and sets the bitshift column to 1'''
                assert packet[0] == 0 # if we want to bitshift, the last element of the packet must  be 0
                assert len(packet) == data_len + gen_size + 1  # if we bitshift, the packets need to be 1 element longer
                packet[i] = self.field.add(packet[i], 1)
                packet[0] = i
                return packet

            def _shift_bits(packet:list[int] | bytearray, i:int) ->  list[int]| bytearray:
                '''shifts all bits until i and sets the bitshift column to 1'''
                assert packet[0] == 0 # if we want to bitshift, the last element of the packet must  be 0
                assert len(packet) == data_len + gen_size + 1  # if we bitshift, the packets need to be 1 element longer
                for column in range(i):
                    packet[column+ 1] = self.field.add(packet[column + 1], 1)
                    packet[0] = i
                return packet
            
            DISPATCH = {
                "first": _shift_firstbit,
                "all": _shift_bits,
            }

            helper_func:function = DISPATCH["first"]
            assert bitshift > 0
            if bitshift > 1:
                helper_func = DISPATCH["all"]
            ic("this is the helper function", helper_func)

            gen_size = len(generation)
            data_len = len(generation[0]) - gen_size -1  # -1 FOR Extra bitshift column

            # Work on a local copy of the generation so we can reorder safely
            work_gen = [g.copy() for g in generation]
            new_symbols: list[bytearray] = []

            ic("NEW GENERATION")
            ic(work_gen)

            for count in range(gen_size):
                # If this is not the last packet, and we detect self-tag 0, try swapping
                # Pick current symbol
                symbol = work_gen[count]
                new_symbol = symbol.copy()  
                # First, generate all cross-tags to already processed packets
                # what happnes at tag 0?
                self_tag = 0
                bitshift = 1

                loop_counter = 0
                while self_tag == 0:
                    loop_counter += 1
                    # copy our current symbol
                    for tag_nr in range(count):
                        
                        corresponding_packet = new_symbols[tag_nr]
                        tag = self.generate_tag_cross(
                            corresponding_packet[data_len + tag_nr + bitshift ],
                            inner_product_bytes(self.field, new_symbol, corresponding_packet),
                        )
                        ic()
                        new_symbol[data_len + tag_nr + bitshift] = tag
                        ic(tag_nr, tag, corresponding_packet,new_symbol )

                    # Now compute self-tag
                    self_tag = self.generate_tag(inner_product_bytes(self.field, new_symbol, new_symbol))
                    
                    if self_tag == 0:

                        ic(self_tag, loop_counter)
                        ic("Packet before bitshift", symbol)
                        new_symbol = helper_func(symbol.copy(), loop_counter)   # using the designated helper function
                        ic("Packet after bitshift", new_symbol)
                        
                        if loop_counter > bitshift:   # when there is more necessary bitshifts than we allow, break
                            ic("ERROR: sellf tag is still zero after bitshifts", )
                            break     # TODO: there should be an value error here, 
                                      #but for testing the sucessrate, we let it stay for now

                            raise ValueError



                ic("Packet before adding self Tag", new_symbol)
                new_symbol[data_len + count + bitshift] = self_tag
                ic("Packet After adding self Tag", new_symbol)
                new_symbols.append(new_symbol)

            return new_symbols

    def print_square_to_root_table(self, filename: str):
        """Print the square-to-root dictionary as a formatted table.
        
        Similar to add_table, mul_table in finite field table builders.
        
        Args:
            filename: If provided, save to this text file instead of printing.
        """
        maxv = self.field.max_value
        lines = []
        for sq in range(maxv + 1):
            root = self.square_to_root.get(sq, "-")
            line = f"{sq:6} | {root}"
            lines.append(line)
        
        if filename:
            with open(filename, 'w') as f:
                f.write("Square to Root Table (GF(2^m)):\n")
                f.write("Square | Root\n")
                f.write("-" * 20 + "\n")
                f.write("\n".join(lines) + "\n")
            print(f"Table saved to {filename}")

    def print_mul_table(self, filename: str):
        """Print the multiplication table as a formatted table.
        
        Args:
            filename: If provided, save to this text file instead of printing.
        """
        maxv = self.field.max_value
        header = "   " + " ".join(f"{i:3}" for i in range(maxv + 1))
        lines = [header]
        
        for i in range(maxv + 1):
            row_str = f"{i:2} " + " ".join(f"{self.mul_table[i][j]:3}" for j in range(maxv + 1))
            lines.append(row_str)
        
        if filename:
            with open(filename, 'w') as f:
                f.write("Multiplication Table (GF(2^m)):\n")
                f.write("\n".join(lines) + "\n")
            print(f"Table saved to {filename}")

## TESTING



if __name__ == "__main__":
    print("Orthogonal Tag Creator ")
    '''
    tag_gen1 = OrthogonalTagGenerator(pyerasure.finite_field.Binary4())
    tag_gen2 = OrthogonalTagGenerator(pyerasure.finite_field.Binary8())

    ic(tag_gen1.square_to_root)
    ic(tag_gen2.square_to_root)
    '''


    '''
        tag_gen = OrthogonalTagGenerator(pyerasure.finite_field.Binary4(), )
        ic.enable()
        ic(tag_gen.generate_tag_cross(7,10))

        ic(tag_gen.generate_tag_cross(7,10))
    '''

    print("OTC")

    #test_orthogonalgenerator()
    #test_cross_generation()
    #test_case_2()
    #test_failed_packets()
    #failed_test_case()

    #generate_examples(3)

    '''
    generator=OrthogonalTagGenerator(field)


    ic(generator.square_to_root)

    ic(generator.mul_table)
    
    ic(generator.generate_tag_cross(3,0))
    ic(generator.generate_tag_cross(3,1))

    '''