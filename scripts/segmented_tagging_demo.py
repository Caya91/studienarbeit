"""
Text walkthrough of segmented orthogonal tagging (ADR-0012, binary_ext_fields/segmented_tagging.py).

Builds one small generation, tags it segment-by-segment, prints the resulting
layout and per-packet values, checks orthogonality, then corrupts one byte at
a time (first in the coeff-segment, then in a data-segment) and re-checks --
showing that a corruption only ever flips its own segment's verdict.

Run with LOG_FOLDER + PYTHONPATH=. set, e.g.:
    PYTHONPATH=. LOG_FOLDER=./logs python scripts/segmented_tagging_demo.py
"""
import random

from binary_ext_fields.custom_field import create_field
from binary_ext_fields.generate_symbols import generate_identity_coefficients
from binary_ext_fields.segmented_tagging import build_segments, tag_generation_segmented, check_orth_segmented
from playground.arc_pl import error_into_packet_chosen_bit

random.seed(0)

FIELD = create_field(8)
GEN_SIZE = 4
DATA_FIELDS = 12
NUM_DATA_SEGMENTS = 3


def print_segments(title, segments):
    print(f"\n{title}")
    for s in segments:
        if hasattr(s, "total_length"):
            print(f"  {s.name:8} kind={s.kind:5} start={s.start:3} payload={s.payload_length:3} "
                  f"salt@{s.salt_index:3} tags@{s.tags_start:3} total_len={s.total_length:3}")
        else:
            print(f"  {s.name:8} kind={s.kind:5} start={s.start:3} length={s.length:3}")


def print_packet_segments(packets, segments):
    for p_idx, packet in enumerate(packets):
        print(f"  packet[{p_idx}]:")
        for s in segments:
            payload = list(packet[s.start:s.start + s.payload_length])
            salt = packet[s.salt_index]
            tags = list(packet[s.tags_start:s.tags_start + s.gen_size])
            print(f"    {s.name:8} payload={payload} salt={salt} tags={tags}")


def print_orth(title, orth):
    print(f"  {title}: " + ", ".join(f"{name}={'OK' if ok else 'BROKEN'}" for name, ok in orth.items()))


def main():
    print(f"field=GF(2^{FIELD.bit_lenght}) gen_size={GEN_SIZE} "
          f"data_fields={DATA_FIELDS} num_data_segments={NUM_DATA_SEGMENTS}")

    plain_segments = build_segments(GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    print_segments("Segment layout (untagged [coeffs|data] packet):", plain_segments)

    data_rows = [bytearray(random.randint(0, FIELD.max_value) for _ in range(DATA_FIELDS)) for _ in range(GEN_SIZE)]
    plain_packets = generate_identity_coefficients(FIELD, data_rows)

    result = tag_generation_segmented(FIELD, plain_packets, GEN_SIZE, NUM_DATA_SEGMENTS)
    assert result.ok, f"tagging gave up on segment {result.failed_segment!r}"

    print_segments("\nTagged segment layout ([payload|salt|tags] per segment):", result.segments)
    print("\nTagged packets:")
    print_packet_segments(result.packets, result.segments)

    orth = check_orth_segmented(FIELD, result.packets, result.segments)
    print()
    print_orth("Fresh generation", orth)

    coeff_segment = next(s for s in result.segments if s.name == "coeff")
    result.packets[0] = error_into_packet_chosen_bit(result.packets[0], coeff_segment.start, chosen_bit=0)
    orth = check_orth_segmented(FIELD, result.packets, result.segments)
    print_orth("After flipping a bit in packet[0]'s coeff-segment", orth)

    data1_segment = next(s for s in result.segments if s.name == "data-1")
    result.packets[2] = error_into_packet_chosen_bit(result.packets[2], data1_segment.start, chosen_bit=3)
    orth = check_orth_segmented(FIELD, result.packets, result.segments)
    print_orth("...then also flipping a bit in packet[2]'s data-1 segment", orth)


if __name__ == "__main__":
    main()
