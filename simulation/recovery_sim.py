from dataclasses import dataclass
from copy import deepcopy
from icecream import ic


from playground.new_recovery import recover_generation
from binary_ext_fields.pollution import (pollute_generation, pollute_random, bit_error_rate_generation)
from utils.log_helpers import (print_generation)
from binary_ext_fields.custom_field import (TableField, CountingField, create_field)
from simulation.network_sim import (Relay, Sink)
from binary_ext_fields.custom_field import TableField
from binary_ext_fields.generate_symbols import (
    generate_symbols_until_nonzero,
    recode_rlnc_without_coeffs,
    check_generation_equal
)
from binary_ext_fields.rref import (
    calculate_only_partial_rref,
    stepwise_partial_rref,
    matrix_full_rank,
)


RELAY_BUFFER_THRESHOLD = 3  # ADR-0006: fixed buffer size before a relay starts recoding+forwarding


@dataclass
class RecoveryTrialResult:
    polluted_count: int
    #flagged_count: int          # sniffing flagged as broken
    #flagged_polluted: int       # true detections
    #flagged_clean: int          # false positives
    #recovered_correct: int      # accepted AND == ground truth
    #silent_failures: int        # accepted AND != ground truth  ← the safety number
    unrecovered: int
    mul_ops: int                # from CountingField
    add_ops: int
    used_bitflip_fallback: int
    status: str                 # recover_generation's verdict
    


class RelayPolluter:
    """Buffers received packets; once buffer_threshold is reached, recodes
    and forwards a fresh linear combination of the (still-growing) buffer
    on every subsequent tick."""

    def __init__(self, buffer_threshold: int = RELAY_BUFFER_THRESHOLD):
        self.buffer_threshold = buffer_threshold
        self.received: list = []

    def receive(self, packet) -> None:
        self.received.append(packet)

    def can_forward(self) -> bool:
        return len(self.received) >= self.buffer_threshold

    def emit(self, field: TableField):



        return recode_rlnc_without_coeffs(field, self.received, len(self.received), count=1)


@dataclass
class RecoveryTrialResult:
    polluted_count: int
    flagged_count: int          # sniffing flagged as broken
    flagged_polluted: int       # true detections
    flagged_clean: int          # false positives
    recovered_correct: int      # accepted AND == ground truth
    silent_failures: int        # accepted AND != ground truth  ← the safety number
    unrecovered: int
    mul_ops: int                # from CountingField
    add_ops: int
    used_bitflip_fallback: int
    status: str                 # recover_generation's verdict


def run_recovery_trial(field, data_fields, gen_size, pollution_rate, attacker) -> RecoveryTrialResult:
    """ Test the recovery Rate of packets 
    Use a simple channel: Source -> Relay_1 -> Sink
    The Relay_1 will be the polluter   
    """
    min_trusted_packets = gen_size - 4
    source_generation = generate_symbols_until_nonzero(field, data_fields, gen_size, coefficients=True)
    original = deepcopy(source_generation)

    polluted_generation = pollute_generation(field, source_generation, pollution_rate, pollute_random) 


    #print_generation(polluted_generation)
    #print_generation(original)
    print(check_generation_equal(polluted_generation, original))
    print(bit_error_rate_generation(polluted_generation, original,  8))

    
    tmp, status = recover_generation(field, polluted_generation, gen_size, 4, 10, 2)
    print("Status", status)


    print_generation(tmp)
    print_generation(original)
    print(check_generation_equal(tmp, original))
    print(bit_error_rate_generation(tmp, original, 8))


    #relay_1 = Relay()


if __name__ == "__main__":
    field = create_field(8)
    cnt_field = CountingField(field)
    data_fields = 5
    gen_size = 12
    pollution_rate = 10e-3
    attacker = "random"
    

    run_recovery_trial(field, data_fields, gen_size, pollution_rate, attacker)