"""
Segmented homomorphic-MAC tagging -- the keyed benchmark arm for the segmented
orthogonal scheme (ADR-0012, docs/adr/0012-...-combined-recovery.md, line 11:
"the deferred pairing optimization on the *benchmark* homomorphic-MAC arm").

This is a FAITHFUL port of Fathi & Pahlevani's Combined Recovery MAC, segmented
exactly like binary_ext_fields/segmented_tagging.py's keyless orthogonal scheme,
so the two arms are directly comparable and overhead drops out as a differentiator.
It deliberately mirrors that module's structure, with one decisive difference:

  orthogonal self-tag: built per packet with a field division against an earlier
    packet's already-fixed tag -- no single fixed rule shared by every packet, so
    a stored tag BYTE has no portable XOR-combined meaning across two packets
    (see segmented_recovery.py's module docstring). Hence the paper's literal
    tag-XOR trick could NOT be ported there; only the bilinear inner product could.

  homomorphic MAC (here): ONE fixed key VECTOR per tag symbol, shared by every
    packet. The tag is a plain linear form t_j = XOR_i (p_i . k_ij) over GF(2^m),
    so T(A XOR B) == T(A) XOR T(B) holds LITERALLY -- the paper ports verbatim,
    and Tc = T1 XOR T2 is a real, verifiable combined tag.

Design decisions (from the benchmark ticket, settled):
- Segment layout is IDENTICAL to the orthogonal arm's payload split (we reuse
  build_segments): one coeff-segment of gen_size symbols + num_data_segments
  data-segments (round-robin remainder). So segment boundaries match column for
  column, making the arms directly comparable.
- Overhead parity: each segment carries V = gen_size tag symbols (the orthogonal
  arm's per-segment tag-block width), so total tag overhead is N*gen_size symbols.
  V independent key vectors per segment -> collision probability ~ q^-V.
- NO salt byte. The orthogonal self-tag needs one because a zero self-tag is a
  degenerate (ADR-0010) failure; a MAC tag of 0 is perfectly valid, so there is
  no zero-tag problem and no salt. (This is the one overhead item that differs
  from the orthogonal arm, which spends 1 extra salt symbol per segment.)
- Keys are held by source + receiver only. Relays recode WITHOUT the key: the tag
  is homomorphic, so a recoded packet's tags are exactly the MAC of its recoded
  payload (proved by linearity, exercised in the tests).

Recovery on top of these segments lives in segmented_mac_recovery.py.
"""

from binary_ext_fields.custom_field import TableField
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.segmented_tagging import build_segments  # reused: identical payload split


class MacSegment:
    """Where one segment's [payload | V tag symbols] block lands in the assembled
    tagged packet. Mirrors segmented_tagging.TaggedSegment, minus the salt byte
    (a MAC needs none) and with num_keys tag symbols instead of gen_size."""

    __slots__ = ("name", "kind", "start", "payload_length", "num_keys")

    def __init__(self, name: str, kind: str, start: int, payload_length: int, num_keys: int):
        self.name = name
        self.kind = kind
        self.start = start
        self.payload_length = payload_length
        self.num_keys = num_keys

    @property
    def tags_start(self) -> int:
        return self.start + self.payload_length

    @property
    def total_length(self) -> int:
        return self.payload_length + self.num_keys

    def __repr__(self) -> str:
        return (f"MacSegment(name={self.name!r}, kind={self.kind!r}, start={self.start}, "
                f"payload_length={self.payload_length}, num_keys={self.num_keys})")

    def __eq__(self, other) -> bool:
        return (isinstance(other, MacSegment) and self.name == other.name and self.kind == other.kind
                and self.start == other.start and self.payload_length == other.payload_length
                and self.num_keys == other.num_keys)


def layout_mac_segments(gen_size: int, data_len: int, num_data_segments: int, num_keys: int) -> list[MacSegment]:
    """Where each segment's [payload | tags] block lands, computed deterministically
    from (gen_size, data_len, num_data_segments, num_keys) alone -- the receiver
    recomputes the same boundaries the sender used, no tagging state needed.

    Payload boundaries come from build_segments (the orthogonal arm's exact split),
    so the two arms carve the packet identically."""
    segments = build_segments(gen_size, data_len, num_data_segments)
    layouts = []
    cursor = 0
    for segment in segments:
        layouts.append(MacSegment(name=segment.name, kind=segment.kind, start=cursor,
                                   payload_length=segment.length, num_keys=num_keys))
        cursor += segment.length + num_keys
    return layouts


def generate_keyset(field: TableField, segments: list[MacSegment], rng) -> list[list[bytearray]]:
    """One key VECTOR per tag symbol per segment: keyset[s] is a list of
    segments[s].num_keys vectors, each segments[s].payload_length symbols long,
    drawn uniformly from the field. Fresh per trial, secret to source + receiver.

    Aligned by position with `segments`, so keyset[s] tags segment s. Keys are
    plain field elements (the paper draws from GF(2^m)); a zero key element is
    allowed -- an all-zero key vector is astronomically unlikely and, unlike the
    orthogonal zero-SELF-tag, not a correctness problem, only a weaker tag symbol."""
    keyset = []
    for segment in segments:
        keys = [bytearray(rng.randint(0, field.max_value) for _ in range(segment.payload_length))
                for _ in range(segment.num_keys)]
        keyset.append(keys)
    return keyset


def mac_tag_vector(field: TableField, keys: list[bytearray], payload) -> list[int]:
    """The homomorphic MAC tag vector of one segment's payload: t_j = XOR_i(p_i . k_ij)
    for each key vector k_j. That inner product IS inner_product_bytes, so we reuse it
    (and its field muls/adds are charged to a CountingField, keeping the computation
    metric comparable to the orthogonal arm's op count -- benchmark ticket #7)."""
    return [inner_product_bytes(field, payload, k) for k in keys]


def tag_generation_mac(field: TableField, packets: list[bytearray], gen_size: int,
                       num_data_segments: int, keyset: list[list[bytearray]],
                       num_keys: int) -> list[bytearray]:
    """Tag every packet of a generation with N = 1 + num_data_segments segments, each
    carrying its own V = num_keys MAC tag symbols appended after the payload.

    `packets` are plain [coefficients | data] rows (generate_identity_coefficients
    shape). The assembled packet is [coeff-payload | coeff-tags | data0-payload |
    data0-tags | ...], concatenated in segment order -- the same column order the
    orthogonal arm uses, so _strip_to_code (dropping each segment's tag suffix)
    rebuilds a clean [coeffs | data] for the RLNC decode.

    No salt (a MAC tag of 0 is valid). The tags ride on the wire and are exposed to
    the channel BER like every payload byte."""
    assert len(packets) == gen_size
    data_len = len(packets[0]) - gen_size
    segments = layout_mac_segments(gen_size, data_len, num_data_segments, num_keys)
    # Payload boundaries in the UNTAGGED packet, to slice each segment's payload out.
    untagged = build_segments(gen_size, data_len, num_data_segments)

    assembled = [bytearray() for _ in range(gen_size)]
    for seg_idx, (seg, keys) in enumerate(zip(untagged, keyset)):
        for i in range(gen_size):
            payload = packets[i][seg.start:seg.start + seg.length]
            tags = mac_tag_vector(field, keys, payload)
            assembled[i] += bytearray(payload) + bytearray(tags)
    return assembled


def mac_verify_segment(field: TableField, keys: list[bytearray], segment_slice, segment: MacSegment,
                       W: int | None = None) -> bool:
    """Self-sufficient MAC verification of one segment slice ([payload | tags]):
    recompute the tag vector over the received payload and compare to the received
    tag symbols. No cross-check against other packets (a MAC needs none -- contrast
    the orthogonal scheme's self + cross check). "Broken" = tag mismatch.

    W (ADR-0013, recovery-acceptance width): None = verify ALL num_keys tags
    (today's behaviour, unchanged for every existing caller). An int W verifies only
    the FIRST W tags (keys[:W] against the first W received tag symbols), so the
    keyed arm's acceptance width matches the keyless arm's W cross-checks -- nominal
    collision ~q^-W (exact here, since generate_keyset's keys are i.i.d.). The
    remaining num_keys-W tags still ride the wire (overhead parity, ticket 11), they
    are simply not consulted. W must not exceed num_keys."""
    if W is not None:
        assert W <= segment.num_keys, f"W={W} exceeds num_keys={segment.num_keys}"
    n = segment.num_keys if W is None else W
    payload = segment_slice[:segment.payload_length]
    recv_tags = list(segment_slice[segment.payload_length:segment.payload_length + n])
    return mac_tag_vector(field, keys[:n], payload) == recv_tags


def mac_tag_overhead_symbols(segments: list[MacSegment]) -> int:
    """Total tag symbols a MAC-tagged generation carries on the wire: the sum of
    num_keys over segments, no salt (ADR-0013 overhead accounting, ticket 11).

    At the isolated harness's num_keys = gen_size this is N*gen_size -- exactly the
    keyless arm's tag columns. The keyless arm additionally spends one salt symbol
    per segment (a zero self-tag is degenerate, ADR-0010; a zero MAC tag is valid so
    the keyed arm needs none), so keyless redundancy = keyed tags + N salt. That one
    salt/segment is the whole, and only, overhead gap between the arms."""
    return sum(seg.num_keys for seg in segments)


def check_mac_segmented(field: TableField, keyset: list[list[bytearray]], packets: list[bytearray],
                        segments: list[MacSegment]) -> dict[str, bool]:
    """Per-segment ground-truth check: True iff EVERY packet's tag verifies in that
    segment. Returns {segment_name: all_verify}."""
    return {
        segment.name: all(
            mac_verify_segment(field, keyset[s], packet[segment.start:segment.start + segment.total_length], segment)
            for packet in packets
        )
        for s, segment in enumerate(segments)
    }
