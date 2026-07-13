"""Discrete-event network simulator for throughput/KPI measurement.

Topology (fixed, see docs/adr/0006-relay-topology-and-forwarding-policy.md):
Source -> {Relay_1, Relay_2} -> Sink.

Tick semantics (see docs/adr/0005-tick-based-simulation-and-goodput-metric.md):
one tick lets every link carry exactly one packet, independent of packet
byte size. Ticks are logical, not wall-clock.

This module only runs a clean channel (no corruption injected) and only
produces raw counters; KPI derivation lives in simulation/kpi_metrics.py.
"""

from dataclasses import dataclass

from binary_ext_fields.custom_field import TableField
from binary_ext_fields.generate_symbols import (
    generate_symbols_until_nonzero,
    recode_rlnc_without_coeffs,
)
from binary_ext_fields.rref import (
    calculate_only_partial_rref,
    stepwise_partial_rref,
    matrix_full_rank,
)

RELAY_BUFFER_THRESHOLD = 3  # ADR-0006: fixed buffer size before a relay starts recoding+forwarding


class Relay:
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
        # One random coefficient per buffered packet, not per gen_size slot:
        # the buffer is never capped at gen_size (ADR-0006), so it can outgrow
        # the network's nominal gen_size while the sink is still converging.
        return recode_rlnc_without_coeffs(field, self.received, len(self.received), count=1)


class Sink:
    """Accumulates packets and incrementally reduces them, tracking whether
    the generation's coefficient columns have reached full rank."""

    def __init__(self, gen_size: int):
        self.gen_size = gen_size
        self.generation: list = []
        self.rref: list = []

    def receive(self, packet, field: TableField) -> None:
        self.generation.append(packet)
        if not self.rref:
            if len(self.generation) >= self.gen_size:
                self.rref = calculate_only_partial_rref(self.generation, field, self.gen_size)
        else:
            reduced = stepwise_partial_rref(self.rref, packet, field, self.gen_size)
            self.rref.append(reduced)

    def is_full_rank(self) -> bool:
        if not self.rref:
            return False
        return bool(matrix_full_rank(self.rref, self.gen_size))


@dataclass
class TrialResult:
    ticks_to_full_rank: int | None
    packets_sent: int
    payload_symbols: int  # data_fields * gen_size: total useful payload of the generation
    tag_symbols: int      # gen_size * gen_size: total tag overhead of the generation


def run_trial(field: TableField, data_fields: int, gen_size: int, max_ticks: int | None = None) -> TrialResult:
    """Runs one clean-channel trial through Source -> {Relay_1, Relay_2} -> Sink
    and returns the raw counters the trial produced.
    """
    if max_ticks is None:
        max_ticks = 10 * gen_size + 50

    source_generation = generate_symbols_until_nonzero(field, data_fields, gen_size, coefficients=True)

    relay_1 = Relay()
    relay_2 = Relay()
    sink = Sink(gen_size)

    packets_sent = 0
    ticks_to_full_rank = None

    for tick in range(1, max_ticks + 1):
        # Source -> relays: one freshly recoded packet per outbound link.
        for relay in (relay_1, relay_2):
            packet = recode_rlnc_without_coeffs(field, source_generation, gen_size, count=1)
            relay.receive(packet)
            packets_sent += 1

        # Relay -> sink: only once a relay's buffer has reached the threshold.
        for relay in (relay_1, relay_2):
            if relay.can_forward():
                packet = relay.emit(field)
                sink.receive(packet, field)
                packets_sent += 1

        if sink.is_full_rank():
            ticks_to_full_rank = tick
            break

    return TrialResult(
        ticks_to_full_rank=ticks_to_full_rank,
        packets_sent=packets_sent,
        payload_symbols=data_fields * gen_size,
        tag_symbols=gen_size * gen_size,
    )
