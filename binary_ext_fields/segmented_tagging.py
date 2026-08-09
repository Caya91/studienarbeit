"""
Segmented orthogonal tagging (ADR-0012, docs/adr/0012-segmented-orthogonal-tagging-and-combined-recovery.md).

Today's OrthogonalTagGenerator.generate_all_tags treats a whole packet
[coefficients | data] as one self/cross-orthogonal pool. This module splits
that pool into N independent ones instead: a fixed coeff-segment plus
num_data_segments equal-length data-segments, each tagged and verified only
against the same segment of the other packets in the generation. This gives
the coefficient block its own detectable/repairable orthogonality check,
which the whole-packet scheme does not have.

N=1 (today's baseline, whole packet as one segment) is unchanged and lives in
orthogonal_tag_creator.py / generate_symbols.py -- this module only covers
N >= 2, i.e. num_data_segments >= 1.

Pairing and recovery on top of these segments (Combined Recovery-style XOR
pairing, Uniform HD / Coefficient-first recovery) are explicitly out of scope
here -- see ADR-0012's Decision section -- this module only builds and
verifies the segmented tag structure itself.
"""

import random
from dataclasses import dataclass

from binary_ext_fields.custom_field import TableField
from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator
from binary_ext_fields.generate_symbols import check_orth


@dataclass(frozen=True)
class Segment:
    """One segment's location in the *untagged* [coefficients | data] packet."""
    name: str
    kind: str  # "coeff" or "data"
    start: int
    length: int


@dataclass(frozen=True)
class TaggedSegment:
    """
    Where a segment ends up in the final tagged packet: payload bytes, then one
    salt byte (ADR-0010, resampled independently per segment), then that
    segment's own gen_size tag columns.
    """
    name: str
    kind: str
    start: int
    payload_length: int
    gen_size: int

    @property
    def salt_index(self) -> int:
        return self.start + self.payload_length

    @property
    def tags_start(self) -> int:
        return self.salt_index + 1

    @property
    def total_length(self) -> int:
        return self.payload_length + 1 + self.gen_size


@dataclass(frozen=True)
class SegmentedTagResult:
    ok: bool
    packets: list[bytearray] | None
    segments: list[TaggedSegment]
    failed_segment: str | None = None


def build_segments(gen_size: int, data_len: int, num_data_segments: int) -> list[Segment]:
    """
    One fixed coeff-segment of length gen_size, plus num_data_segments equal-length
    data-segments splitting the data block.

    Uneven splits (data_len not a multiple of num_data_segments) are not supported:
    ADR-0012 explicitly defers how remainder bytes should be distributed.

    Caller beware: a segment's payload length (+1 for its salt byte) is the dimension
    of the vector space its gen_size packets live in. If that dimension is smaller
    than gen_size, the segment's Gram matrix is rank-deficient by construction, so
    at least one packet's self-tag MUST come out zero -- no salt draw or reorder can
    fix it (this is a hard rank limit, not the small-field give-up ADR-0010 documents).
    Keep each data-segment's length >= gen_size - 1 to avoid this.
    """
    assert num_data_segments >= 1
    if data_len % num_data_segments != 0:
        raise ValueError(
            f"data_len={data_len} does not split evenly into {num_data_segments} "
            "data-segments; uneven splits are deferred (ADR-0012)."
        )
    data_segment_length = data_len // num_data_segments

    segments = [Segment(name="coeff", kind="coeff", start=0, length=gen_size)]
    for i in range(num_data_segments):
        segments.append(Segment(
            name=f"data-{i}",
            kind="data",
            start=gen_size + i * data_segment_length,
            length=data_segment_length,
        ))
    return segments


def _layout_tagged_segments(segments: list[Segment], gen_size: int) -> list[TaggedSegment]:
    """Where each segment's [payload | salt | tags] block lands in the assembled packet."""
    layouts = []
    cursor = 0
    for segment in segments:
        layouts.append(TaggedSegment(
            name=segment.name, kind=segment.kind, start=cursor,
            payload_length=segment.length, gen_size=gen_size,
        ))
        cursor += segment.length + 1 + gen_size
    return layouts


def _tag_segment_with_salt(field: TableField, payload_rows: list[bytearray], gen_size: int,
                            max_salt_draws: int) -> tuple[list[bytearray] | None, bool]:
    """
    Tag one segment's per-packet payload rows (ADR-0010's salt-fallback, applied to a
    single segment instead of the whole packet): append a salt byte to each row and
    resample the salt VECTOR until every row's self-tag is nonzero, then tag each row
    against the other rows of this same segment. payload_rows themselves are never
    rewritten -- only the salt and tag columns are.

    Returns (None, False) if no salt draw works within max_salt_draws (ADR-0010's
    documented small-field give-up path, unchanged per segment).
    """
    otc = OrthogonalTagGenerator(field)
    payload_length = len(payload_rows[0])
    self_tag_offset = payload_length + 1  # +1 for the salt byte

    for _ in range(max_salt_draws):
        salts = [random.randint(0, field.max_value) for _ in range(gen_size)]
        rows = [
            bytearray(list(payload_rows[k]) + [salts[k]] + [0] * gen_size)
            for k in range(gen_size)
        ]
        tagged_rows = otc.generate_all_tags(rows)
        if all(tagged_rows[k][self_tag_offset + k] != 0 for k in range(gen_size)):
            return tagged_rows, True

    return None, False


def tag_generation_segmented(field: TableField, packets: list[bytearray], gen_size: int,
                              num_data_segments: int, max_salt_draws: int = 1000) -> SegmentedTagResult:
    """
    Tag every packet of a generation with N = 1 + num_data_segments independent
    segments (ADR-0012): the coeff-segment and each data-segment get their own
    self/cross-orthogonal tag pool and salt byte, instead of one whole-packet pool.

    `packets` are plain [coefficients | data] rows with no tags yet -- the same
    shape generate_identity_coefficients() produces.
    """
    assert len(packets) == gen_size
    data_len = len(packets[0]) - gen_size
    segments = build_segments(gen_size, data_len, num_data_segments)

    tagged_rows_per_segment = []
    for segment in segments:
        payload_rows = [packet[segment.start:segment.start + segment.length] for packet in packets]
        tagged_rows, ok = _tag_segment_with_salt(field, payload_rows, gen_size, max_salt_draws)
        if not ok:
            return SegmentedTagResult(ok=False, packets=None, segments=[], failed_segment=segment.name)
        tagged_rows_per_segment.append(tagged_rows)

    assembled = [bytearray() for _ in range(gen_size)]
    for tagged_rows in tagged_rows_per_segment:
        for i in range(gen_size):
            assembled[i] += tagged_rows[i]

    layouts = _layout_tagged_segments(segments, gen_size)
    return SegmentedTagResult(ok=True, packets=assembled, segments=layouts, failed_segment=None)


def check_orth_segmented(field: TableField, packets: list[bytearray],
                          segments: list[TaggedSegment]) -> dict[str, bool]:
    """
    Per-segment orthogonality check (ADR-0012): each segment is checked for
    self/cross orthogonality only against the SAME segment of every other packet
    -- never against a different segment, and never against the whole packet.

    Returns {segment_name: is_orthogonal}.
    """
    return {
        segment.name: check_orth(
            field,
            [packet[segment.start:segment.start + segment.total_length] for packet in packets],
        )
        for segment in segments
    }
