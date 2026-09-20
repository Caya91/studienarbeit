"""
Tests for ticket 11 (ADR-0013): the keyed MAC arm carries num_keys = gen_size tags
on the wire (overhead parity with the keyless arm's gen_size tag columns) but
verifies only the W-subset at recovery/trust.

Meant to be read, not just run. Ticket 10 already gave mac_verify_segment its W cap;
this file pins down the ticket-11 invariants that build on it:
  - the keyed scheme instantiates, tags, and verifies at num_keys = gen_size;
  - at recovery acceptance only the FIRST W tags are consulted while the remaining
    gen_size - W tags are physically present on the wire (overhead parity, not extra
    collision resistance);
  - homomorphism (tag survives RLNC recoding) still holds at num_keys = gen_size;
  - the overhead readout: keyed = gen_size tag symbols/segment, keyless = gen_size + 1
    (the extra 1 is the keyless salt byte, a separate negligible overhead item).

Judge pass/fail by exit code (0 = pass); the banners print "assert"/"error" as prose.
"""
import random

from binary_ext_fields.custom_field import create_field
from binary_ext_fields.generate_symbols import (
    generate_identity_coefficients,
    recode_rlnc_without_coeffs,
)
from binary_ext_fields.segmented_tagging import layout_segments
from binary_ext_fields.segmented_mac_tagging import (
    layout_mac_segments,
    generate_keyset,
    mac_tag_vector,
    tag_generation_mac,
    mac_verify_segment,
    check_mac_segmented,
    mac_tag_overhead_symbols,
)


def _banner(name):
    print(f"\n=== {name} ===")


# Shared config: 4 packets, 3 data-segments, V = num_keys = gen_size tag symbols.
FIELD = create_field(8)
GEN_SIZE = 4
DATA_FIELDS = 12
NUM_DATA_SEGMENTS = 3
NUM_KEYS = GEN_SIZE  # overhead parity: one tag symbol per generation column


def _build_mac_pool(field, gen_size, data_fields, num_data_segments, num_keys, seed):
    """A MAC-tagged generation + its keyset + segment layout, all aligned."""
    rng = random.Random(seed)
    data_rows = [bytearray(rng.randint(0, field.max_value) for _ in range(data_fields))
                 for _ in range(gen_size)]
    plain = generate_identity_coefficients(field, data_rows)
    segments = layout_mac_segments(gen_size, data_fields, num_data_segments, num_keys)
    keyset = generate_keyset(field, segments, rng)
    packets = tag_generation_mac(field, plain, gen_size, num_data_segments, keyset, num_keys)
    return packets, keyset, segments


# ── (1) num_keys = gen_size builds, tags, and verifies ────────────────────────

def test_keyed_at_num_keys_equals_gen_size_builds_tags_and_verifies():
    _banner("keyed: num_keys = gen_size builds, tags, and verifies")
    packets, keyset, segments = _build_mac_pool(
        FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, NUM_KEYS, seed=1)

    assert len(segments) == 1 + NUM_DATA_SEGMENTS
    for seg in segments:
        assert seg.num_keys == GEN_SIZE, "each segment must carry gen_size tag symbols"
    verified = check_mac_segmented(FIELD, keyset, packets, segments)
    print(f"  {len(segments)} segments, num_keys={GEN_SIZE} each; all verify: {all(verified.values())}")
    assert all(verified.values()), "clean pool at num_keys = gen_size must verify"


# ── (2) only first-W tags consulted; extra tags ride the wire ─────────────────

def test_only_first_W_tags_consulted_extra_tags_present_on_the_wire():
    _banner("keyed: only first-W tags consulted at acceptance; gen_size - W extras on wire")
    W = 2
    assert W < GEN_SIZE, "the point is W strictly below the carried tag count"
    packets, keyset, segments = _build_mac_pool(
        FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, NUM_KEYS, seed=2)

    seg = segments[1]  # a data segment
    keys = keyset[1]
    pkt = packets[0]
    seg_slice = pkt[seg.start:seg.start + seg.total_length]

    # The wire carries gen_size tag symbols per segment (payload then all tags).
    on_wire_tags = seg.total_length - seg.payload_length
    print(f"  segment carries {on_wire_tags} tag symbols on the wire (gen_size={GEN_SIZE})")
    assert on_wire_tags == GEN_SIZE, "all gen_size tags must be present on the wire"

    # Corrupt tags[W:] only: first-W still verify, but any wider check fails.
    corrupted = bytearray(seg_slice)
    q = FIELD.max_value + 1
    for j in range(W, GEN_SIZE):
        idx = seg.payload_length + j
        corrupted[idx] = (corrupted[idx] + 1) % q

    print(f"  first {W} tags left intact, tags[{W}:{GEN_SIZE}] flipped")
    assert mac_verify_segment(FIELD, keys, corrupted, seg, W=W) is True, \
        "first-W acceptance must ignore the corrupted later tags"
    assert mac_verify_segment(FIELD, keys, corrupted, seg, W=W + 1) is False, \
        "consulting one more tag must catch the corruption"
    assert mac_verify_segment(FIELD, keys, corrupted, seg, W=GEN_SIZE) is False
    assert mac_verify_segment(FIELD, keys, corrupted, seg, W=None) is False, \
        "verify-all must catch the corrupted extras"


# ── (3) homomorphism holds at num_keys = gen_size ─────────────────────────────

def test_homomorphism_holds_at_num_keys_equals_gen_size():
    _banner("keyed: homomorphism survives recoding at num_keys = gen_size")
    packets, keyset, segments = _build_mac_pool(
        FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, NUM_KEYS, seed=7)
    assert all(check_mac_segmented(FIELD, keyset, packets, segments).values()), "clean pool must verify"

    recoded = recode_rlnc_without_coeffs(FIELD, packets, GEN_SIZE, count=5)
    pool = packets + [bytearray(p) for p in recoded]
    verified = check_mac_segmented(FIELD, keyset, pool, segments)
    print(f"  originals + 5 recoded all verify: {all(verified.values())} ({verified})")
    assert all(verified.values()), "recoded packets' tags must still verify at num_keys = gen_size"


# ── (4) overhead readout: keyed gen_size vs keyless gen_size + 1(salt) ─────────

def test_overhead_readout_keyed_gen_size_vs_keyless_gen_size_plus_salt():
    _banner("overhead: keyed = gen_size tags/segment; keyless = gen_size + 1(salt)")
    mac_segments = layout_mac_segments(GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, NUM_KEYS)
    orth_segments = layout_segments(GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    N = len(mac_segments)
    assert N == len(orth_segments)

    keyed_total = mac_tag_overhead_symbols(mac_segments)
    # keyless tag columns = gen_size per segment; +1 salt symbol per segment.
    keyless_tag_total = sum(seg.gen_size for seg in orth_segments)
    keyless_salt_total = N  # one salt byte per segment
    keyless_redundancy_total = sum(seg.total_length - seg.payload_length for seg in orth_segments)

    print(f"  N={N} segments, gen_size={GEN_SIZE}")
    print(f"  keyed tag symbols total    = {keyed_total}  ({keyed_total // N}/segment)")
    print(f"  keyless tag symbols total  = {keyless_tag_total} + {keyless_salt_total} salt "
          f"= {keyless_redundancy_total} ({keyless_redundancy_total // N}/segment)")

    # keyed: exactly gen_size tag symbols per segment, no salt.
    assert keyed_total == N * GEN_SIZE
    for seg in mac_segments:
        assert seg.num_keys == GEN_SIZE
    # keyless: gen_size tag symbols PLUS one salt per segment.
    assert keyless_tag_total == N * GEN_SIZE, "keyless tag columns match keyed exactly"
    assert keyless_redundancy_total == N * (GEN_SIZE + 1), "keyless additionally spends 1 salt/segment"
    # The parity claim: keyed tags == keyless tags; the only gap is the salt.
    assert keyed_total == keyless_tag_total
    assert keyless_redundancy_total - keyed_total == keyless_salt_total


if __name__ == "__main__":
    tests = [
        test_keyed_at_num_keys_equals_gen_size_builds_tags_and_verifies,
        test_only_first_W_tags_consulted_extra_tags_present_on_the_wire,
        test_homomorphism_holds_at_num_keys_equals_gen_size,
        test_overhead_readout_keyed_gen_size_vs_keyless_gen_size_plus_salt,
    ]
    for test in tests:
        test()
        print(f"{test.__name__} passed")
    print("\nAll keyed overhead-parity / W-subset tests passed!")
