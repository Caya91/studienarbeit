from icecream import ic
from utils.log_helpers import log_packet
from random import choice

from binary_ext_fields.custom_field import TableField, create_field

from binary_ext_fields.generate_symbols import inner_product_bytes, check_orth, check_orth_packet
from binary_ext_fields.generate_symbols import generate_symbols_until_nonzero
from binary_ext_fields.bitops import bit_flip_candidates
from utils.log_helpers import make_ic_logger, print_generation, print_packet
from playground.arc_pl import error_into_generation, error_into_packet, error_into_packet_chosen_bit
from itertools import combinations, product


def recover_packet_combined(field, p1:bytearray, p2:bytearray, recovery_columns: list[int]):
    # TODO: implement combined recovery from the base case of the single recovered packet
    # we take 2 packets -> XOR them, then recover this combined packet
    # then when that worked -> recover the old packets by xoring them to their original versions
    # the 2 recovery columns have to be different i think ...

    pass


def recover_packet(field: TableField, packet: bytearray, recovery_column: int):
    '''
    takes a broken packet and
    tries out all the elements of the field at the recovery column for that packet
    and returns the fixed packet, or the old packet if no solution was found
    '''
    if check_orth_packet(field, packet):
        print("packet was orthogonal")
        return packet
    
    print(f"packet before recovery {list(packet)}")
    tmp = packet.copy()
    element_list = list(range(0,field.max_value + 1 ))

    for e in element_list: 
        packet[recovery_column] = e
        if check_orth_packet(field, packet):
            break # is the packet orthogonal after the fix then this is our recovered packet

    return packet


def recover_packet_bitflip(field: TableField, packet: bytearray, recovery_column: int, hamming_distance: int):
    '''flips bits up to a hamming distance and then checks if packet is recovered. \n
    If recovery is not possible -> returns Original Packet \n
    Return: (Recovered Packed | Original Packet)
    '''
    if check_orth_packet(field, packet):
        print("packet was orthogonal")
        print(" This shouldnt happen here")
        return packet
    
    #print(f"packet before recovery {list(packet)}")

    tmp = bytearray(packet)
    recovery_success = False
    for flipped, mask in bit_flip_candidates(packet[recovery_column], hamming_distance, field.bit_lenght):
        tmp = bytearray(packet)
        #ic(tmp)
        tmp[recovery_column] = flipped
        if check_orth_packet(field, tmp):
            ic(flipped, mask)
            recovery_success = True
            print(f"Bit {recovery_column} wird geflippt   {tmp[recovery_column]:08b} ({tmp[recovery_column]}) ") 
            break

    if recovery_success:
        return tmp, recovery_success
    else:
        return packet, recovery_success
    

def recover_generation(field: TableField, generation: list[bytearray], columns:list[int], rows:list[int], hamming_distance: int ):

    tmp = [bytearray(packet) for packet in generation] # TODO: this tmp has to be recovered
    # to the original generation when a partial recovery was unsuccessful
    print_generation(tmp)


    kartesian = product(columns, rows)
    print(kartesian)
    print(list(kartesian))

    
    # TODO: was wenn Fehler mal nicht genau gelichverteilt sind?
    # ignorieren wir das einfach, weil das so unwarhscheinlich ist?
    

    # TODO: erstmal naiver approach -> später mehr Varianten, wie weitermachen falls ein Packet nicht repaired wurde?
    # eine andere Kombination an rows und columns probieren
    
    # Idee für jetzt: wir gehen packet durch für alle columns, fixed eine column das packet
    # -> dann streichen wir die column
    # was tun wenn 2 fehler pro packet auftreten?

    #while not check_orth(field, tmp):
        #TODO: Was ist eine Abbruchsbedingung, falls Generation nicht recovered werden kann?
        # change the for loop to go through all columns for a package and then stop

    ''' Algoritm Idea:

    liste unserer Reihen und Spalten

    1. Fix 1 Bit Errors everywhere
    1.1 check orthogonality
    1.2 recheck ACR (Only the column)

    1.3 remove columns from lists
    1.4 remove packets from lists
    
    ====== Still Errors ? ======

    2. Fix 2 Bit Errors 
    2. check orthogonality
    
    -> and so on for different depths of errors that we fix

    
    ===== After thoughts : What happens when generation is not fixed? ======

    (do we go again with different combinations?
     do we save every way to fix a packet and then restart with different )





    ...









    '''


    




    recovered_columns = []
    recovered_rows = []

    packet = []
    for column, row in zip(columns, rows):
        packet, status = recover_packet_bitflip(field, generation[row], column, hamming_distance)
        if status == True:
            recovered_columns.append(column)
            recovered_rows.append(row)
            tmp[row] = bytearray(packet)        
            continue
    
    return tmp


def recover_generation_v2(field: TableField, generation: list[bytearray], columns:list[int], rows:list[int], hamming_distance: int ):
    """
    TODO: Implement: after we recover a packet from a bitflip, we should check orthogonality
    against another packet, because there is a lot of false positives


    """



    #kartesian = product(columns, rows)
    #print(kartesian)
    #print(list(kartesian))

    
    # TODO: was wenn Fehler mal nicht genau gelichverteilt sind?
    # ignorieren wir das einfach, weil das so unwarhscheinlich ist?
    

    # TODO: erstmal naiver approach -> später mehr Varianten, wie weitermachen falls ein Packet nicht repaired wurde?
    # eine andere Kombination an rows und columns probieren
    
    # Idee für jetzt: wir gehen packet durch für alle columns, fixed eine column das packet
    # -> dann streichen wir die column
    # was tun wenn 2 fehler pro packet auftreten?

    #while not check_orth(field, tmp):
        #TODO: Was ist eine Abbruchsbedingung, falls Generation nicht recovered werden kann?
        # change the for loop to go through all columns for a package and then stop

    ''' Algoritm Idea:

    liste unserer Reihen und Spalten

    1. Fix 1 Bit Errors everywhere
    1.1 check orthogonality
    1.2 recheck ACR (Only the column)

    1.3 remove columns from lists
    1.4 remove packets from lists
    
    ====== Still Errors ? ======

    2. Fix 2 Bit Errors 
    2. check orthogonality
    
    -> and so on for different depths of errors that we fix

    
    ===== After thoughts : What happens when generation is not fixed? ======

    (do we go again with different combinations?
     do we save every way to fix a packet and then restart with different )

    '''





    #print("====== Before recovery Process =======")
    tmp = [bytearray(packet) for packet in generation]
    #print_generation(tmp)


    # combined list of broken packets
    indexed_packets = [ (p ,bytearray(generation[p])) for p in rows]
    packet_column_tuples = []

    while columns and indexed_packets:
        #ic(columns, indexed_packets)
        solved_any = False

        for i, col in enumerate(columns):
            status = None

            for j, pkt in enumerate(indexed_packets):

                packet, success = recover_packet_bitflip(field, pkt[1], col, hamming_distance)
                if not success:
                    continue

                indexed_packets[j] = packet

                packet_column_tuples.append((pkt[0], packet, col))   #  row, packet, column
                indexed_packets.pop(j)
                columns.pop(i)
                #ic(packet_column_tuples)

                solved_any = True
                break
    
            if solved_any:
                break
        if not solved_any:
            break
    
    # falls alle Fehler gefunden wurden, können wir returnen -> sonst starten wir von vorn bis zur nächsten hamming distance
    
    if len(columns) == 0 or len(indexed_packets) == 0:
        for row, pkt, col in packet_column_tuples:
            tmp[row] = pkt

        print("===== The returned fully repaired generation =======")
        print_generation(tmp)
        return tmp
    else:
        print("ERROR: couldnt repair generation" )
        return None
    return tmp



    '''

    recovered_columns = []
    recovered_rows = []

    packet = []
    for column, row in zip(columns, rows):
        packet, status = recover_packet_bitflip(field, generation[row], column, hamming_distance)
        if status == True:
            recovered_columns.append(column)
            recovered_rows.append(row)
            tmp[row] = bytearray(packet)        
            continue
    '''
    return tmp


def recovery_loop(field: TableField, generation: list[bytearray], columns:list[int], rows:list[int], hamming_distance: int ):
    if hamming_distance <= 1:
        hds = [1]
    elif hamming_distance <= 8:
        hds = list(range(1, hamming_distance + 1))

    i = 1
    while( i <= hamming_distance ):
        print(f"Recovery Loop {i}")
        i += 1
        tmp = [bytearray(p) for p in generation]
        tmp = recover_generation_v2(field, tmp, columns, rows, i)

        if check_orth(field,tmp):
            return tmp
    return None








def test_full_recovery():
    field = create_field(5)
    generation = generate_symbols_until_nonzero(field, 3 , 3)

    print("generation Before introducing Error")
    print_generation(generation)


def base_recovery_test():

    field = create_field(5)
    generation = generate_symbols_until_nonzero(field, 3 , 3)

    print("generation Before introducing Error")
    print_generation(generation)


    print(check_orth(field, generation))

    error_column = 3
    error_packet = 0

    generation[error_packet] = error_into_packet(generation[error_packet], error_column)

    print("Generation After Introducing Error")
    print_generation(generation)

    print(check_orth(field, generation))

    print("===== Start packet recovery =====")
    print(f"Original polluted Packet: {error_packet} with the Error Column: {error_column}")

    #recovered_packet = recover_packet(field, generation[error_packet], error_column)
    recovered_packet, status= recover_packet_bitflip(field, generation[error_packet], error_column, 2)

    generation[error_packet] = recovered_packet

    print("==== Recovered Generation ==== ")
    print_generation(generation)


# Run the tests
if __name__ == "__main__":
    # TODO: test how to find false positives
    # TODO: implement full recovery with rows and columns

    # This tests right now to put an error in one packet and then recovering that error
    # to make the generation orthogonal again

    error_packets = [0,2]
    error_columns = [0,3]
    hamming_distance = 1


    field = create_field(8)
    generation = generate_symbols_until_nonzero(field, 3 , 3)

    print("===== Generation Before Error =====")
    print_generation(generation)

    for packet,column in zip(error_packets, error_columns):
        ic()
        generation[packet] = error_into_packet(generation[packet], column, hamming_distance)
    
    
    print("===== Generation After Error =====")
    print_generation(generation)

    #   just use the 

    error_packets = [0, 2]
    error_columns = [3, 0]



    tmp = recover_generation_v2(field, generation, error_columns, error_packets, hamming_distance)


    
    print("===== Generation After Recovery =====")
    print_generation(tmp)

    print(check_orth(field, tmp))

    for pkt in tmp:
        print(check_orth_packet(field, pkt))

    tmp = recovery_loop(field, generation, error_columns, error_packets, hamming_distance)
    if tmp == None:
        print("couldnt recover the error")
    else:
        print(check_orth(field, tmp))
        for pkt in tmp:
            print(check_orth_packet(field, pkt))
    



    #packet
    '''
    test_verify_tag()
    test_successful_repair()
    test_failed_repair()
    print("All tests finished successfully!")
    '''