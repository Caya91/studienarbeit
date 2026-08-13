"""
Segment pairing and recovery for segmented orthogonal tagging
(ADR-0012, docs/adr/0012-segmented-orthogonal-tagging-and-combined-recovery.md).

segmented_tagging.py only builds and verifies segments; this module repairs
them. Two strategies, both built on the same pairing + combined-search
machinery, so the comparison between them isolates the "does ARC narrowing
help" question from the "does pairing/search work at all" question:

- recover_uniform_hd (ADR-0012 Option 1): every segment, coeff and data alike,
  repaired the same way. No ARC anywhere.
- recover_coefficient_first (ADR-0012 Option 2): the coeff-segment is repaired
  first (it can never be ARC-localized against itself -- ARC needs trusted
  coefficients to work from), then its now-trustworthy coefficients are handed
  to ARC (localize_errors) to narrow each data-segment's candidate columns
  before repairing them. ARC needs a trusted pool bigger than gen_size (see
  _make_arc_localizer) -- normally available, since both the real network and
  the sim keep sending recoded packets until a generation decodes.

Why "combine and check one tag" from the source paper (Fathi & Pahlevani,
"Combined Recovery") doesn't port over as a literal tag-XOR trick here: our
self/cross tags are built one packet at a time, each later packet's cross-tag
referencing an earlier packet's *already-fixed* tag value via a field
division -- there's no single fixed rule shared by every packet the way a
linear MAC has one fixed key vector. So a stored tag *byte* has no portable
XOR-combined meaning across two different packets.

What *does* transfer is the inner product itself: `inner_product` is
bilinear, and in a characteristic-2 field the self-product's cross term
cancels, so `inner_product(A^B, A^B) == inner_product(A,A) ^ inner_product(B,B)`
and `inner_product(A^B, T) == inner_product(A,T) ^ inner_product(B,T)` for any
third vector T -- always, regardless of how A and B's own tag bytes were
derived. So checking self+cross orthogonality of the XOR-combined *row*
(payload+salt+tags together) against the trusted pool is a sound, cheap
filter: it can never reject a split where both halves are individually
correct (necessary condition), so it's safe to prune the search with it.
It can, however, be satisfied by two candidates that are BOTH still wrong but
happen to have equal inner products (a genuine collision, the false-repair
analogue of the CRC arm's collision case) -- so every combined-filter pass is
still followed by verifying each split half individually before it's ever
accepted. That verification is the actual acceptance oracle (ADR-0001); the
combined filter is only ever a speed-up, never the thing that decides
correctness.

Known, documented limitation (ADR-0012's deferred "IC-refinement Case 2"):
this only recovers *disjoint* errors -- if both paired packets have a bit
flipped at the very same bit position, the two flips cancel inside the
XOR-combined row and no split can recover them. That case is expected to
surface as a failed pairing (recorded, not silently mishandled) -- see
test_recover_uniform_hd_cannot_split_overlapping_errors.
"""

from dataclasses import dataclass
from itertools import chain, combinations

from binary_ext_fields.custom_field import TableField
from binary_ext_fields.generate_symbols import check_orth_packet
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.segmented_tagging import TaggedSegment, check_orth_segmented
from playground.arc_pl import localize_errors
from playground.new_recovery import is_orthogonal_to_trusted, recover_packet_linear


def segment_slice(packet: bytearray, segment: TaggedSegment) -> bytearray:
    """The [payload | salt | tags] bytes belonging to one segment of one packet."""
    return packet[segment.start: segment.start + segment.total_length]


def _write_segment(packet: bytearray, segment: TaggedSegment, fixed_slice: bytearray) -> None:
    packet[segment.start: segment.start + segment.total_length] = fixed_slice


# ── Segment-scoped trust (ADR-0012's extension of ADR-0004's sniffing) ──────

@dataclass(frozen=True)
class SegmentTrust:
    segment_name: str
    broken: list[int]   # packet indices whose self-check fails on this segment
    trusted: list[int]  # packet indices whose self-check passes AND are cross-orthogonal
                         # to every other self-check-passing packet in this segment


def classify_segment_trust(field: TableField, packets: list[bytearray], segment: TaggedSegment) -> SegmentTrust:
    """
    Self-check failure -> broken (conclusive, ADR-0004). Self-check success ->
    trusted only if also cross-orthogonal to every other self-check-passing
    packet in this segment. A packet that passes self-check but fails a
    cross-check is left out of both lists: a rare self-tag collision (ADR-0010),
    known-suspect rather than provably broken or safely trustworthy.

    Unlike sniff_pool's streaming min_trust_count/min_pool_size gate, this
    generation is a closed pool of `gen_size` packets, so the full pairwise
    cross-check among self-check-passers is cheap and exact -- no threshold
    needed.
    """
    slices = [segment_slice(p, segment) for p in packets]
    self_pass = [i for i, s in enumerate(slices) if check_orth_packet(field, s)]
    broken = [i for i in range(len(packets)) if i not in self_pass]
    trusted = [
        i for i in self_pass
        if all(inner_product_bytes(field, slices[i], slices[j]) == 0 for j in self_pass if j != i)
    ]
    return SegmentTrust(segment.name, broken=broken, trusted=trusted)


# ── Pairing (ADR-0012's "Pairing model") ─────────────────────────────────────

@dataclass(frozen=True)
class SegmentPair:
    segment_name: str
    packet_a: int
    packet_b: int


@dataclass(frozen=True)
class UnpairedBroken:
    segment_name: str
    packet_index: int


@dataclass(frozen=True)
class PairingPlan:
    pairs: list[SegmentPair]
    unpaired: list[UnpairedBroken]


def plan_pairing(trust: SegmentTrust) -> PairingPlan:
    """FIFO pairing (ascending packet index) within one segment's broken list.
    An odd packet out falls back to single-packet recovery."""
    broken = sorted(trust.broken)
    pairs = [SegmentPair(trust.segment_name, a, b) for a, b in zip(broken[0::2], broken[1::2])]
    unpaired = [UnpairedBroken(trust.segment_name, broken[-1])] if len(broken) % 2 == 1 else []
    return PairingPlan(pairs=pairs, unpaired=unpaired)


# ── Combined-pair recovery (the paired half of ADR-0012's two strategies) ───

def _bit_positions_for_columns(columns, bits_per_symbol: int) -> list[int]:
    positions = []
    for c in columns:
        positions.extend(range(c * bits_per_symbol, (c + 1) * bits_per_symbol))
    return positions


def _flip_bits(data: bytearray, bit_positions, bits_per_symbol: int) -> bytearray:
    out = bytearray(data)
    for pos in bit_positions:
        column, bit = divmod(pos, bits_per_symbol)
        out[column] ^= (1 << bit)
    return out


def _powerset(items):
    return chain.from_iterable(combinations(items, r) for r in range(len(items) + 1))


@dataclass(frozen=True)
class PairRecoveryResult:
    ok: bool
    fixed_a: bytearray | None
    fixed_b: bytearray | None
    combined_hd_found: int | None
    candidates_tried: int


def recover_pair_by_combined_search(field: TableField, slice_a: bytearray, slice_b: bytearray,
                                     trusted_slices: list[bytearray], candidate_columns: list[int],
                                     max_combined_hd: int, candidates_budget: int | None = None
                                     ) -> PairRecoveryResult:
    """
    Search low-Hamming-distance corrections to the XOR-combined row of two
    broken same-segment packets, restricted to `candidate_columns` (payload-local
    byte indices; salt and tag bytes are never searched -- a known blind spot,
    documented at module level).

    For each combined candidate that survives the cheap combined self+cross
    filter (see module docstring), try every way of splitting its flipped bit
    positions between packet A and packet B, and accept the first split where
    BOTH repaired packets independently pass the real acceptance oracle
    (self+cross orthogonal to the trusted pool) AND are mutually orthogonal to
    each other. This only ever recovers disjoint errors (module docstring);
    overlapping errors legitimately exhaust the search and return ok=False.

    `candidates_budget` (None = unbounded) caps combined-candidate attempts, same
    idea as the CRC arm's `whole_budget` (simulation/integrity_schemes.py): without
    Option 1's ARC narrowing, `candidate_columns` can be the whole payload, and
    combinations(bit_positions, hd) grows combinatorially in both segment size and
    max_combined_hd -- a sim sweep needs this bounded, not just a correctness
    demo. A budget give-up returns ok=False exactly like exhausting max_combined_hd
    honestly (this IS a search-budget give-up, not a "provably unrecoverable"
    result -- a larger budget might still find it).
    """
    bits_per_symbol = field.bit_lenght
    bit_positions = _bit_positions_for_columns(candidate_columns, bits_per_symbol)
    combined = bytearray(a ^ b for a, b in zip(slice_a, slice_b))

    candidates_tried = 0
    for hd in range(1, max_combined_hd + 1):
        for combo in combinations(bit_positions, hd):
            if candidates_budget is not None and candidates_tried >= candidates_budget:
                return PairRecoveryResult(False, None, None, None, candidates_tried)
            candidates_tried += 1
            combined_candidate = _flip_bits(combined, combo, bits_per_symbol)
            if not is_orthogonal_to_trusted(field, combined_candidate, trusted_slices):
                continue  # combined filter: cannot be a valid disjoint split, skip cheaply

            for a_bits in _powerset(combo):
                b_bits = [pos for pos in combo if pos not in a_bits]
                candidate_a = _flip_bits(slice_a, a_bits, bits_per_symbol)
                candidate_b = _flip_bits(slice_b, b_bits, bits_per_symbol)

                if not is_orthogonal_to_trusted(field, candidate_a, trusted_slices):
                    continue
                if not is_orthogonal_to_trusted(field, candidate_b, trusted_slices):
                    continue
                if inner_product_bytes(field, candidate_a, candidate_b) != 0:
                    continue

                return PairRecoveryResult(True, candidate_a, candidate_b, hd, candidates_tried)

    return PairRecoveryResult(False, None, None, None, candidates_tried)


# ── Unpaired fallback: the existing ADR-0002 single-packet linear solve ─────

def recover_unpaired_segment(field: TableField, broken_slice: bytearray, candidate_columns: list[int],
                              trusted_slices: list[bytearray]) -> bytearray | None:
    """ADR-0012's fallback for a broken segment with no pairing partner: reuse
    ADR-0002's linear solve unmodified, since a segment slice has exactly the
    [payload+salt | tags] shape recover_packet_linear already expects. Returns
    None if underdetermined or the solved candidate fails the acceptance oracle."""
    fixed = recover_packet_linear(field, broken_slice, set(candidate_columns), trusted_slices)
    if fixed is None:
        return None
    return fixed if is_orthogonal_to_trusted(field, fixed, trusted_slices) else None


# ── One segment, either strategy ─────────────────────────────────────────────

@dataclass(frozen=True)
class SegmentRepairOutcome:
    segment_name: str
    pairs_recovered: int
    pairs_failed: int
    unpaired_recovered: int
    unpaired_failed: int


def repair_segment(field: TableField, packets: list[bytearray], segment: TaggedSegment,
                    candidate_columns_for, max_combined_hd: int = 4,
                    candidates_budget: int | None = None) -> SegmentRepairOutcome:
    """
    Repairs one segment across the whole generation, mutating `packets` in
    place: pairs broken packets (plan_pairing) and combined-searches each pair
    (recover_pair_by_combined_search), then linear-solves whatever is left
    unpaired (recover_unpaired_segment).

    candidate_columns_for(packet_index) -> list[int] | None supplies per-packet
    candidate payload columns (None = search/solve over the whole payload, the
    no-localization default). This is the one hook that differs between
    Option 1 (always None) and Option 2 (ARC-narrowed for data segments).

    candidates_budget: forwarded to recover_pair_by_combined_search per pair
    (None = unbounded). Does not apply to the unpaired linear solve, which is
    polynomial, not a search.
    """
    trust = classify_segment_trust(field, packets, segment)
    plan = plan_pairing(trust)
    trusted_slices = [segment_slice(packets[i], segment) for i in trust.trusted]
    all_columns = list(range(segment.payload_length))

    pairs_recovered = pairs_failed = unpaired_recovered = unpaired_failed = 0

    for pair in plan.pairs:
        cols_a = candidate_columns_for(pair.packet_a)
        cols_b = candidate_columns_for(pair.packet_b)
        # Either side missing localization -> search the whole payload for the pair,
        # rather than silently narrowing to only the side that did localize.
        columns = all_columns if (cols_a is None or cols_b is None) else sorted(set(cols_a) | set(cols_b))

        slice_a = segment_slice(packets[pair.packet_a], segment)
        slice_b = segment_slice(packets[pair.packet_b], segment)
        result = recover_pair_by_combined_search(field, slice_a, slice_b, trusted_slices, columns,
                                                  max_combined_hd, candidates_budget=candidates_budget)

        if result.ok:
            _write_segment(packets[pair.packet_a], segment, result.fixed_a)
            _write_segment(packets[pair.packet_b], segment, result.fixed_b)
            pairs_recovered += 1
        else:
            pairs_failed += 1

    for unpaired in plan.unpaired:
        columns = candidate_columns_for(unpaired.packet_index)
        if columns is None:
            columns = all_columns
        broken_slice = segment_slice(packets[unpaired.packet_index], segment)
        fixed = recover_unpaired_segment(field, broken_slice, columns, trusted_slices)

        if fixed is not None:
            _write_segment(packets[unpaired.packet_index], segment, fixed)
            unpaired_recovered += 1
        else:
            unpaired_failed += 1

    return SegmentRepairOutcome(segment.name, pairs_recovered, pairs_failed, unpaired_recovered, unpaired_failed)


# ── Top level: the two strategies ADR-0012 asks to measure against each other ─

@dataclass(frozen=True)
class SegmentedRecoveryReport:
    packets: list[bytearray]
    per_segment: list[SegmentRepairOutcome]
    ok: bool  # ground truth: every segment orthogonal after repair (ADR-0001 style acceptance)


def recover_uniform_hd(field: TableField, packets: list[bytearray], segments: list[TaggedSegment],
                        max_combined_hd: int = 4, candidates_budget: int | None = None
                        ) -> SegmentedRecoveryReport:
    """ADR-0012 Option 1: every segment, coeff and data alike, repaired via
    pairing + combined search, unpaired via the ADR-0002 linear solve. No ARC
    anywhere -- the coeff-segment gets exactly the same treatment as any
    data-segment, which is the point: closing the coefficient blind spot the
    whole-packet scheme's ARC-based recovery (playground/new_recovery.py modes
    C/D) has always had."""
    tmp = [bytearray(p) for p in packets]
    per_segment = [
        repair_segment(field, tmp, segment, candidate_columns_for=lambda i: None,
                       max_combined_hd=max_combined_hd, candidates_budget=candidates_budget)
        for segment in segments
    ]
    ok = all(check_orth_segmented(field, tmp, segments).values())
    return SegmentedRecoveryReport(packets=tmp, per_segment=per_segment, ok=ok)


def _make_arc_localizer(field: TableField, packets: list[bytearray], coeff_segment: TaggedSegment,
                         data_segment: TaggedSegment, gen_size: int, coeff_trusted_idx: list[int],
                         data_trusted_idx: list[int]):
    """
    Builds a candidate_columns_for(packet_index) callable that ARC-localizes
    (localize_errors) a broken packet's corrupted columns within `data_segment`,
    using that packet's own now-trusted coefficients and a gen_size trusted
    basis built the same way (coefficients + this data-segment's payload,
    exactly the [coefficients | data] shape ARC expects -- sound because RLNC
    recoding is applied to the whole data vector, so it holds column-slice by
    column-slice too, not just on the whole packet).

    Needs gen_size trusted packets as the decoding basis PLUS the broken packet
    itself as a separate, (gen_size+1)-th row to check against that basis --
    localize_errors' own requirement (see playground/arc_pl.py). `packets` is
    therefore expected to be a pool bigger than gen_size, e.g. the original
    generation plus recoded packets accumulated in transit: in both the real
    network and the sim, packets keep arriving as recoded RLNC combinations
    until the generation decodes, so a receiver almost always has more than
    gen_size packets on hand by the time it runs recovery. Recoding is
    segment-agnostic -- it linearly combines whole rows, and since each
    segment's tag pool is itself a self+cross-orthogonal set, the same
    bilinear argument from the module docstring shows any linear combination
    of the pool stays self+cross-orthogonal per segment too -- so a recoded
    packet's segments are exactly as decodable/localizable as an original
    packet's, no special-casing needed (verified directly: recoding a
    segmented-tagged generation and checking every segment of the combined
    pool holds).

    Falls back to "no localization" (None for every packet) when fewer than
    gen_size packets are trusted in BOTH the coeff-segment and this
    data-segment (no full-rank basis to localize against yet -- e.g. too early
    in reception, before enough recoded packets have arrived), or when the
    chosen basis turns out not full rank (localize_errors raises on a zero
    pivot). ADR-0003's "wait for more trusted packets" gate, short-circuited
    to "give up localizing for this call" since this function reports a
    result once rather than blocking -- a caller polling recovery over time
    (as the real pipeline does) simply gets a narrower column set on a later
    call once the pool has grown.
    """
    basis_indices = sorted(set(coeff_trusted_idx) & set(data_trusted_idx))[:gen_size]
    if len(basis_indices) < gen_size:
        return lambda i: None

    def synthetic(i):
        coeffs = segment_slice(packets[i], coeff_segment)[:gen_size]
        data = segment_slice(packets[i], data_segment)[:data_segment.payload_length]
        return bytearray(coeffs) + bytearray(data)

    trusted_basis = [synthetic(i) for i in basis_indices]
    coeff_trusted_set = set(coeff_trusted_idx)

    def localizer(i):
        if i not in coeff_trusted_set:
            return None  # this packet's own coefficients aren't trustworthy yet, ARC can't use them
        try:
            columns = localize_errors(field, [bytearray(p) for p in trusted_basis], synthetic(i), gen_size)
        except (ValueError, ZeroDivisionError):
            return None  # basis not full rank -- give up localizing this data-segment
        return sorted(c - gen_size for c in columns)

    return localizer


def recover_coefficient_first(field: TableField, packets: list[bytearray], segments: list[TaggedSegment],
                               gen_size: int, max_combined_hd: int = 4, candidates_budget: int | None = None
                               ) -> SegmentedRecoveryReport:
    """ADR-0012 Option 2: repair the coeff-segment first (same pairing/combined-
    search machinery as Option 1 -- it can never ARC-localize itself), then use
    the now-trustworthy coefficients to ARC-narrow each data-segment's candidate
    columns before repairing them, restricting the same pairing/search machinery
    to a much smaller column set."""
    tmp = [bytearray(p) for p in packets]
    coeff_segment = next(s for s in segments if s.kind == "coeff")
    data_segments = [s for s in segments if s.kind == "data"]

    per_segment = [
        repair_segment(field, tmp, coeff_segment, candidate_columns_for=lambda i: None,
                       max_combined_hd=max_combined_hd, candidates_budget=candidates_budget)
    ]

    coeff_trust = classify_segment_trust(field, tmp, coeff_segment)
    for segment in data_segments:
        data_trust = classify_segment_trust(field, tmp, segment)
        localizer = _make_arc_localizer(
            field, tmp, coeff_segment, segment, gen_size, coeff_trust.trusted, data_trust.trusted,
        )
        per_segment.append(
            repair_segment(field, tmp, segment, candidate_columns_for=localizer,
                           max_combined_hd=max_combined_hd, candidates_budget=candidates_budget)
        )

    ok = all(check_orth_segmented(field, tmp, segments).values())
    return SegmentedRecoveryReport(packets=tmp, per_segment=per_segment, ok=ok)
