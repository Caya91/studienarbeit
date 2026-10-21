"""
Segmented CRC-32 arm for the keyless-vs-CRC comparison (ADR-0014).

Layout: the same payload segments as the keyless arm (coeff segment, then the data
segments), each payload followed by its own CRC-32 (4 B, big-endian) instead of the
keyless salt byte + gen_size tag bytes. At gen_size=4 over GF(2^8) both arms carry
4 tag bytes per segment (the keyless salt byte is not counted, ADR-0014 point 2).
Single hop only: the source CRCs every coded packet itself -- a CRC does not survive
RLNC recoding over GF(2^m).

CRC implementation (user decision 2026-10-14, ADR-0014 point 6): the standard library's
`zlib.crc32` -- IEEE 802.3 CRC-32 (poly 0x04C11DB7, reflected, init/xorout 0xFFFFFFFF),
C code, i.e. what a real implementation would call. This supersedes ADR-0011's pure-Python
table CRC for this comparison (simulation/crc_recovery.py keeps it for the standalone
CRC-8/16/32 study). Consequence for wall-clock: the CRC check runs in C while the keyless
inner products run in Python -- stated with the results; a library-vs-library keyless
benchmark (galois / pyerasure) is future work (ticket 21).

Repair mirrors binary_ext_fields/segmented_mac_recovery.py 1:1 -- pairing, combined
search, per-half IC-refinement fallback, unpaired bit-flip, each search step with its
own budget -- with the acceptance oracle swapped for the segment's own CRC check, so
the CRC and keyless/keyed arms differ only in the oracle (ADR-0013 rule 4).

Combined filter: the standard CRC-32 is AFFINE over GF(2) (init/xorout 0xFFFFFFFF):
crc(a ^ b) == crc(a) ^ crc(b) ^ crc(0^L) for equal-length a, b (L = their length). XORing
two whole slices gives Sc = [a ^ b | crc_a ^ crc_b], so when both halves are correct
crc(payload of Sc) ^ crc(0^L) == stored CRC of Sc -- a necessary condition, so it is a safe
prune (crc_verify_combined). Detection is unaffected by the affine constant: an error e
of a fixed length is missed iff crc(e) ^ crc(0^L) == 0.

Two localization variants (ADR-0014 point 3):
  acr   -- candidate columns from ACR: the same _make_arc_localizer and injected
           helper basis the keyless arm uses (ACR is tag-independent).
  blind -- no localization: every payload column of the segment.
Both drop coeff-corrupted targets before pairing (their coefficients are untrusted;
symmetric with the keyless/keyed ARC-only drop), so blind differs from acr ONLY in
the columns searched.
"""
import zlib
from dataclasses import dataclass
from functools import lru_cache
from itertools import chain, combinations

from binary_ext_fields.segmented_recovery import (
    SegmentTrust, plan_pairing, PairRecoveryResult, SegmentRepairOutcome, SegmentedRecoveryReport,
    _make_arc_localizer, _redundancy_columns,
)

CRC_WIDTH = 32
CRC_BYTES = CRC_WIDTH // 8
BITS_PER_BYTE = 8
LOCALIZATIONS = ("acr", "blind")


@dataclass
class Crc32Instrument:
    """zlib.crc32 + native op counters: crc_ops = bytes fed through the CRC (attach + every
    check), correction_trials = bit-flip candidates tried by the repair search."""
    crc_ops: int = 0
    correction_trials: int = 0

    def crc(self, data: bytes) -> int:
        self.crc_ops += len(data)
        return zlib.crc32(data)


@lru_cache(maxsize=None)
def zero_crc(length: int) -> int:
    """crc32 of `length` zero bytes: the affine constant of zlib's CRC-32 at that length."""
    return zlib.crc32(bytes(length))


@dataclass(frozen=True)
class CrcSegment:
    """One segment's [payload | CRC-32] block in the assembled packet. Same duck type as
    TaggedSegment / MacSegment (name, kind, start, payload_length, total_length), so
    segment_slice, _redundancy_columns and the ARC localizer work on it unchanged."""
    name: str
    kind: str
    start: int
    payload_length: int

    @property
    def total_length(self) -> int:
        return self.payload_length + CRC_BYTES


def layout_crc_segments(reference_segments) -> list[CrcSegment]:
    """Same names / kinds / payload lengths as `reference_segments` (the keyless layout),
    packed back to back with a CRC-32 after each payload."""
    out, cursor = [], 0
    for seg in reference_segments:
        out.append(CrcSegment(seg.name, seg.kind, cursor, seg.payload_length))
        cursor += seg.payload_length + CRC_BYTES
    return out


def crc_tag_overhead_bytes(segments) -> int:
    return CRC_BYTES * len(segments)


def segment_slice(packet: bytearray, segment: CrcSegment) -> bytearray:
    return packet[segment.start: segment.start + segment.total_length]


def _write_segment(packet: bytearray, segment: CrcSegment, fixed_slice: bytearray) -> None:
    packet[segment.start: segment.start + segment.total_length] = fixed_slice


def tag_packets_crc(instrument: Crc32Instrument, source_packets, source_segments,
                    crc_segments: list[CrcSegment]) -> list[bytearray]:
    """Re-frame each source packet's segment payloads as [payload | CRC-32] blocks. The
    source packets are the keyless (or any) pool: only their payload columns are read, so
    the CRC pool carries byte-identical [coeff | data] information columns."""
    out = []
    for p in source_packets:
        packet = bytearray()
        for ss, cs in zip(source_segments, crc_segments):
            assert ss.payload_length == cs.payload_length and ss.name == cs.name
            payload = bytes(p[ss.start: ss.start + ss.payload_length])
            packet += payload + instrument.crc(payload).to_bytes(CRC_BYTES, "big")
        out.append(packet)
    return out


def crc_verify_segment(instrument: Crc32Instrument, slice_: bytearray, segment: CrcSegment) -> bool:
    """The acceptance oracle: the slice's payload recomputes to its stored CRC."""
    stored = int.from_bytes(slice_[segment.payload_length: segment.total_length], "big")
    return instrument.crc(bytes(slice_[:segment.payload_length])) == stored


def crc_verify_combined(instrument: Crc32Instrument, combined_slice: bytearray, segment: CrcSegment) -> bool:
    """Combined filter on Sc = slice_a ^ slice_b: necessary for both halves to verify
    (affine CRC, module docstring). Not an acceptance oracle -- each split half is still
    checked with crc_verify_segment."""
    stored = int.from_bytes(combined_slice[segment.payload_length: segment.total_length], "big")
    return instrument.crc(bytes(combined_slice[:segment.payload_length])) ^ zero_crc(segment.payload_length) == stored


def check_crc_segmented(instrument: Crc32Instrument, packets: list[bytearray],
                        segments: list[CrcSegment]) -> dict[str, bool]:
    """Per segment: does every packet pass its CRC? (CRC analogue of check_orth_segmented.)"""
    return {seg.name: all(crc_verify_segment(instrument, segment_slice(p, seg), seg) for p in packets)
            for seg in segments}


def classify_segment_trust_crc(instrument: Crc32Instrument, packets: list[bytearray],
                               segment: CrcSegment) -> SegmentTrust:
    """Per-packet CRC check: failing packets are broken, the rest trusted (no pool needed)."""
    broken = [i for i, p in enumerate(packets)
              if not crc_verify_segment(instrument, segment_slice(p, segment), segment)]
    broken_set = set(broken)
    return SegmentTrust(segment.name, broken=broken,
                        trusted=[i for i in range(len(packets)) if i not in broken_set])


# ── Search (mirror of segmented_mac_recovery) ─────────────────────────────────

def _bit_positions_for_columns(columns) -> list[int]:
    positions = []
    for c in columns:
        positions.extend(range(c * BITS_PER_BYTE, (c + 1) * BITS_PER_BYTE))
    return positions


def _flip_bits(data: bytearray, bit_positions) -> bytearray:
    out = bytearray(data)
    for pos in bit_positions:
        column, bit = divmod(pos, BITS_PER_BYTE)
        out[column] ^= (1 << bit)
    return out


def _powerset(items):
    return chain.from_iterable(combinations(items, r) for r in range(len(items) + 1))


def _bitflip_search_crc(instrument: Crc32Instrument, broken_slice: bytearray, segment: CrcSegment,
                        candidate_columns: list[int], max_hd: int,
                        candidates_budget: int | None) -> tuple[bytearray | None, int]:
    """Flip up to max_hd bits across candidate_columns, accept the first candidate whose
    CRC verifies. Returns (candidate_or_None, candidates_tried); fresh budget per call."""
    tried = 0
    for hd in range(1, max_hd + 1):
        for combo in combinations(_bit_positions_for_columns(candidate_columns), hd):
            if candidates_budget is not None and tried >= candidates_budget:
                return None, tried
            tried += 1
            instrument.correction_trials += 1
            candidate = _flip_bits(broken_slice, combo)
            if crc_verify_segment(instrument, candidate, segment):
                return candidate, tried
    return None, tried


def _search_pair_crc(instrument: Crc32Instrument, slice_a: bytearray, slice_b: bytearray, segment: CrcSegment,
                     candidate_columns: list[int], max_combined_hd: int, candidates_budget: int | None,
                     ic_refinement: bool = True, half_columns=None) -> PairRecoveryResult:
    """Combined search on Sc = a ^ b (affine CRC -> crc_verify_combined), split
    each combined hit between the halves and accept the first split where BOTH halves pass
    their own CRC. When that exhausts (same-position overlaps cancel in Sc) or hits the
    budget, IC-refinement corrects each half on its own, each step with a fresh budget --
    the keyed arm's _search_pair_mac exactly, oracle swapped."""
    bit_positions = _bit_positions_for_columns(candidate_columns)
    combined = bytearray(a ^ b for a, b in zip(slice_a, slice_b))

    tried = 0
    budget_hit = False
    for hd in range(1, max_combined_hd + 1):
        if budget_hit:
            break
        for combo in combinations(bit_positions, hd):
            if candidates_budget is not None and tried >= candidates_budget:
                budget_hit = True
                break
            tried += 1
            instrument.correction_trials += 1
            if not crc_verify_combined(instrument, _flip_bits(combined, combo), segment):
                continue  # combined CRC filter: no valid disjoint split here
            for a_bits in _powerset(combo):
                b_bits = [pos for pos in combo if pos not in a_bits]
                candidate_a = _flip_bits(slice_a, a_bits)
                candidate_b = _flip_bits(slice_b, b_bits)
                if not crc_verify_segment(instrument, candidate_a, segment):
                    continue
                if not crc_verify_segment(instrument, candidate_b, segment):
                    continue
                return PairRecoveryResult(True, candidate_a, candidate_b, hd, tried)

    if ic_refinement:
        cols_a, cols_b = half_columns if half_columns is not None else (candidate_columns, candidate_columns)
        fixed_a, tried_a = _bitflip_search_crc(instrument, slice_a, segment, cols_a, max_combined_hd,
                                               candidates_budget)
        tried += tried_a
        if fixed_a is not None:
            fixed_b, tried_b = _bitflip_search_crc(instrument, slice_b, segment, cols_b, max_combined_hd,
                                                   candidates_budget)
            tried += tried_b
            if fixed_b is not None:
                return PairRecoveryResult(True, fixed_a, fixed_b, None, tried)

    return PairRecoveryResult(False, None, None, None, tried)


def repair_segment_crc(instrument: Crc32Instrument, packets: list[bytearray], segment: CrcSegment,
                       candidate_columns_for, max_combined_hd: int = 2, candidates_budget: int | None = None,
                       ic_refinement: bool = True, drop_unlocalized: bool = False,
                       injected_trust: SegmentTrust | None = None) -> SegmentRepairOutcome:
    """Repair one segment across the pool in place (repair_segment_mac, oracle = CRC).
    candidate_columns_for(i) -> columns | None; None = unlocalized (dropped when
    drop_unlocalized, else whole segment)."""
    trust = injected_trust if injected_trust is not None \
        else classify_segment_trust_crc(instrument, packets, segment)
    if drop_unlocalized:
        dropped_indices = [i for i in trust.broken if candidate_columns_for(i) is None]
        dropped_set = set(dropped_indices)
        pairing_trust = SegmentTrust(segment.name, broken=[i for i in trust.broken if i not in dropped_set],
                                     trusted=trust.trusted)
    else:
        dropped_indices = []
        pairing_trust = trust
    plan = plan_pairing(pairing_trust)
    pair_columns = list(range(segment.total_length))  # whole segment (payload + CRC) when unlocalized

    pairs_recovered = pairs_failed = unpaired_recovered = unpaired_failed = 0
    for pair in plan.pairs:
        cols_a = candidate_columns_for(pair.packet_a)
        cols_b = candidate_columns_for(pair.packet_b)
        columns = pair_columns if (cols_a is None or cols_b is None) else sorted(set(cols_a) | set(cols_b))
        halves = None if (cols_a is None or cols_b is None) else (cols_a, cols_b)
        result = _search_pair_crc(instrument, segment_slice(packets[pair.packet_a], segment),
                                  segment_slice(packets[pair.packet_b], segment), segment, columns,
                                  max_combined_hd, candidates_budget, ic_refinement, half_columns=halves)
        if result.ok:
            _write_segment(packets[pair.packet_a], segment, result.fixed_a)
            _write_segment(packets[pair.packet_b], segment, result.fixed_b)
            pairs_recovered += 1
        else:
            pairs_failed += 1

    for unpaired in plan.unpaired:
        columns = candidate_columns_for(unpaired.packet_index)
        if columns is None:
            columns = pair_columns
        fixed, _ = _bitflip_search_crc(instrument, segment_slice(packets[unpaired.packet_index], segment),
                                       segment, columns, max_combined_hd, candidates_budget)
        if fixed is not None:
            _write_segment(packets[unpaired.packet_index], segment, fixed)
            unpaired_recovered += 1
        else:
            unpaired_failed += 1

    return SegmentRepairOutcome(segment.name, pairs_recovered, pairs_failed,
                                unpaired_recovered, unpaired_failed, dropped=len(dropped_indices))


def _make_blind_localizer(segment: CrcSegment, coeff_trusted_idx, repair_span: str):
    """No localization: every payload column (+ the CRC bytes for repair_span="segment"),
    for every target whose coefficients are trusted; None (-> dropped) otherwise."""
    assert repair_span in ("payload", "segment"), f"repair_span must be payload|segment, got {repair_span!r}"
    extra = _redundancy_columns(segment) if repair_span == "segment" else []
    columns = list(range(segment.payload_length)) + extra
    trusted = set(coeff_trusted_idx)
    return lambda i: list(columns) if i in trusted else None


def recover_arc_only_crc(field, instrument: Crc32Instrument, packets: list[bytearray], segments: list[CrcSegment],
                         gen_size: int, basis_idx: list[int], coeff_clean_target_idx: list[int],
                         localization: str = "acr", max_combined_hd: int = 2,
                         candidates_budget: int | None = None, ic_refinement: bool = True,
                         injected_trust_by_segment: dict[str, SegmentTrust] | None = None,
                         repair_span: str = "payload", final_check: bool = True) -> SegmentedRecoveryReport:
    """ARC-only CRC arm (mirror of recover_arc_only / recover_arc_only_mac): no coeff
    repair, DATA segments only, coeff-corrupted targets dropped. `localization` picks the
    candidate columns: "acr" (field ops of localize_errors land on `field`) or "blind"."""
    assert localization in LOCALIZATIONS, f"localization must be one of {LOCALIZATIONS}, got {localization!r}"
    tmp = [bytearray(p) for p in packets]
    coeff_segment = next(s for s in segments if s.kind == "coeff")
    basis = sorted(set(basis_idx))
    coeff_trusted = sorted(set(basis) | set(coeff_clean_target_idx))

    per_segment = []
    for segment in (s for s in segments if s.kind == "data"):
        if localization == "acr":
            localizer = _make_arc_localizer(field, tmp, coeff_segment, segment, gen_size,
                                            coeff_trusted, basis, repair_span=repair_span)
        else:
            localizer = _make_blind_localizer(segment, coeff_trusted, repair_span)
        injected = None if injected_trust_by_segment is None else injected_trust_by_segment.get(segment.name)
        per_segment.append(repair_segment_crc(instrument, tmp, segment, localizer, max_combined_hd,
                                              candidates_budget, ic_refinement, drop_unlocalized=True,
                                              injected_trust=injected))

    ok = all(check_crc_segmented(instrument, tmp, segments).values()) if final_check else None
    return SegmentedRecoveryReport(packets=tmp, per_segment=per_segment, ok=ok)
