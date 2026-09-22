"""
Combined Recovery for the segmented homomorphic-MAC benchmark arm
(Fathi & Pahlevani; ADR-0012's deferred benchmark MAC arm).

segmented_mac_tagging.py builds and verifies the MAC segments; this module
repairs them. It mirrors segmented_recovery.py 1:1 -- same pairing + combined
search machinery, same two strategies -- so the MAC arm and the orthogonal arm
differ ONLY in the tag/oracle, never in the recovery structure:

- recover_uniform_hd_mac (Option 1): every segment repaired the same way,
  combined search over the whole segment, no ARC.
- recover_coefficient_first_mac (Option 2): repair the coeff-segment first, then
  use the now-trusted coefficients to ARC-localize (localize_errors) each
  data-segment's candidate columns before repairing -- the exact same
  _make_arc_localizer glue the orthogonal arm uses.

The decisive difference from the orthogonal arm (segmented_recovery.py): here the
tag is a linear MAC with ONE fixed key vector per symbol, so the paper's literal
trick ports verbatim. The XOR-combined row's tag Tc = T1 XOR T2 is a real,
verifiable tag, and verification is SELF-SUFFICIENT: a slice is trusted iff its
own MAC tag recomputes to its transmitted tag (mac_verify_segment). There is NO
trusted pool, NO cross-check, and NO mutual-orthogonality test between the two
split halves -- each half is accepted on its own MAC alone.

Combined filter (the paper's Correct step, ported): mac(Sc_candidate) == Tc is a
NECESSARY condition for any valid disjoint split (linearity: if mac(a)==Ta and
mac(b)==Tb then mac(a^b)==Ta^Tb), so it prunes the search cheaply and safely. It
can still be satisfied by two candidates that are both wrong but collide (prob
~q^-V) -- the false-repair analogue -- so every combined pass is still followed by
verifying each split half against its OWN tag before acceptance.

IC-refinement / Case 2 (ticket #07, ported here): when two paired packets are
broken at the SAME position, the two errors cancel inside the XOR-combined row Sc,
so the combined search can never see them -- it exhausts with ok=False. Rather than
give the pair up, we then fall back to correcting EACH half on its own against its
OWN MAC tag over the same candidate columns (_bitflip_search_mac -- the identical
single-packet oracle the unpaired path uses). Only single-position overlap is in
scope; a genuinely unrecoverable pair (per-half correction beyond max_combined_hd,
or budget exhausted) still fails honestly (pairs_failed). Every accepted half must
MAC-verify before it is written, so this fallback introduces NO silent decode -- a
wrong "fix" is only ever a q^-V tag collision, exactly as for the combined path and
the unpaired path. Toggle with ic_refinement=False; cap with candidates_budget
(None = unlimited, per ticket #07 decision 3). See
test_recover_uniform_hd_mac_recovers_overlapping_errors_via_ic_refinement.
"""

from itertools import chain, combinations

from binary_ext_fields.custom_field import TableField
from binary_ext_fields.segmented_mac_tagging import MacSegment, mac_verify_segment, check_mac_segmented
from binary_ext_fields.segmented_recovery import (
    SegmentTrust, PairingPlan, plan_pairing,
    PairRecoveryResult, SegmentRepairOutcome, SegmentedRecoveryReport,
    _redundancy_columns,
)
from playground.arc_pl import localize_errors


def segment_slice(packet: bytearray, segment: MacSegment) -> bytearray:
    """The [payload | tags] bytes belonging to one segment of one packet."""
    return packet[segment.start: segment.start + segment.total_length]


def _write_segment(packet: bytearray, segment: MacSegment, fixed_slice: bytearray) -> None:
    packet[segment.start: segment.start + segment.total_length] = fixed_slice


# ── Segment-scoped MAC trust (self-sufficient -- no cross-check) ──────────────

def classify_segment_trust_mac(field: TableField, keys: list[bytearray], packets: list[bytearray],
                               segment: MacSegment) -> SegmentTrust:
    """A packet is broken iff its MAC tag mismatches in this segment, trusted
    otherwise. Unlike classify_segment_trust (orthogonal), there is no cross-check
    middle ground: a MAC verification is conclusive on its own, so every packet
    lands in exactly one of broken/trusted."""
    trusted, broken = [], []
    for i, p in enumerate(packets):
        if mac_verify_segment(field, keys, segment_slice(p, segment), segment):
            trusted.append(i)
        else:
            broken.append(i)
    return SegmentTrust(segment.name, broken=broken, trusted=trusted)


# ── Combined-pair recovery (the paper's Combined Recovery, ported literally) ──

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


def _pair_cache_key(slice_a: bytearray, slice_b: bytearray, candidate_columns: list[int],
                    max_combined_hd: int, candidates_budget, ic_refinement: bool, W: int | None = None):
    """Hashable key over everything the search depends on. The keyset is constant
    for a trial (the pair_cache lives on the per-trial instrument), so it is not
    part of the key -- unlike the orthogonal cache, which keys on the trusted set
    because its oracle depends on it. A MAC oracle depends only on the fixed key,
    so (a, b, columns, hd, budget, ic_refinement, W) fully determines the result --
    ic_refinement is in the key because it changes the output (the Case-2 fallback),
    and W (ADR-0013 acceptance width) because it changes how many tags are verified
    and hence which fixes are accepted."""
    return (bytes(slice_a), bytes(slice_b), tuple(candidate_columns), max_combined_hd,
            candidates_budget, ic_refinement, W)


def recover_pair_by_combined_search_mac(field: TableField, keys: list[bytearray], slice_a: bytearray,
                                        slice_b: bytearray, candidate_columns: list[int], segment: MacSegment,
                                        max_combined_hd: int, candidates_budget: int | None = None,
                                        pair_cache: dict | None = None,
                                        ic_refinement: bool = True, W: int | None = None) -> PairRecoveryResult:
    """Combined Recovery on one broken pair (paper Algorithm 1, Case-1 part).

    Sc = slice_a XOR slice_b, Tc = T1 XOR T2 (both fall out of XORing the whole
    slices, since the tag bytes are the slice suffix). Search low-Hamming-distance
    corrections to Sc, restricted to `candidate_columns` (slice-local byte indices;
    the pair path passes the WHOLE segment -- payload + tags -- so a BER hit in a
    tag byte is repairable, mirroring the orthogonal arm's blind-spot fix). For each
    combined candidate that satisfies the combined MAC filter, try every split of
    its flipped bits between A and B, and accept the first split where BOTH halves
    verify against their own MAC (mac_verify_segment). Only disjoint errors recover;
    overlapping same-position errors legitimately exhaust the search (ok=False).

    candidates_budget caps combined-candidate attempts (the orthogonal arm's
    pair_budget knob). pair_cache memoises results per pair across admit rounds --
    a pure function of (slice_a, slice_b, columns, hd, budget, ic_refinement), so a
    hit returns an identical result without re-spending field ops.

    ic_refinement (default True) enables the Case-2 same-position fallback described
    in the module docstring; pass False to restore the disjoint-only combined search."""
    if pair_cache is not None:
        key = _pair_cache_key(slice_a, slice_b, candidate_columns, max_combined_hd,
                              candidates_budget, ic_refinement, W)
        cached = pair_cache.get(key)
        if cached is not None:
            return cached
        result = _search_pair_mac(field, keys, slice_a, slice_b, candidate_columns, segment,
                                  max_combined_hd, candidates_budget, ic_refinement, W=W)
        pair_cache[key] = result
        return result
    return _search_pair_mac(field, keys, slice_a, slice_b, candidate_columns, segment,
                            max_combined_hd, candidates_budget, ic_refinement, W=W)


def _search_pair_mac(field: TableField, keys: list[bytearray], slice_a: bytearray, slice_b: bytearray,
                     candidate_columns: list[int], segment: MacSegment, max_combined_hd: int,
                     candidates_budget: int | None, ic_refinement: bool = True,
                     W: int | None = None) -> PairRecoveryResult:
    """The actual combined search, extracted so the public wrapper can cache it.
    Pure and deterministic in its inputs (keys constant per trial).

    Two stages: (1) the paper's combined search over Sc = a XOR b -- recovers any
    DISJOINT error split; (2) when that exhausts and ic_refinement is on, the Case-2
    IC-refinement fallback (module docstring) correcting each half individually. Both
    stages share one candidates_budget so a high-BER cell cannot blow up."""
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
            if not mac_verify_segment(field, keys, combined_candidate, segment, W=W):
                continue  # combined MAC filter: cannot be a valid disjoint split, skip cheaply

            for a_bits in _powerset(combo):
                b_bits = [pos for pos in combo if pos not in a_bits]
                candidate_a = _flip_bits(slice_a, a_bits, bits_per_symbol)
                candidate_b = _flip_bits(slice_b, b_bits, bits_per_symbol)
                if not mac_verify_segment(field, keys, candidate_a, segment, W=W):
                    continue
                if not mac_verify_segment(field, keys, candidate_b, segment, W=W):
                    continue
                return PairRecoveryResult(True, candidate_a, candidate_b, hd, candidates_tried)

    # Stage 2 -- IC-refinement (paper Case 2). The combined search is blind to
    # same-position overlaps (they cancel in Sc), so fall back to correcting each
    # half on its own MAC over the same candidate columns. Each half is only
    # accepted if it MAC-verifies (done inside _bitflip_search_mac), so no silent
    # decode is introduced. The two searches continue the shared budget count.
    if ic_refinement:
        fixed_a, candidates_tried = _bitflip_search_mac(field, slice_a, keys, candidate_columns, segment,
                                                        max_combined_hd, candidates_budget,
                                                        start_tried=candidates_tried, W=W)
        if fixed_a is not None:
            fixed_b, candidates_tried = _bitflip_search_mac(field, slice_b, keys, candidate_columns, segment,
                                                            max_combined_hd, candidates_budget,
                                                            start_tried=candidates_tried, W=W)
            if fixed_b is not None:
                return PairRecoveryResult(True, fixed_a, fixed_b, None, candidates_tried)

    return PairRecoveryResult(False, None, None, None, candidates_tried)


# ── Unpaired fallback: single-packet bit-flip search against the MAC ──────────

def _bitflip_search_mac(field: TableField, broken_slice: bytearray, keys: list[bytearray],
                        candidate_columns: list[int], segment: MacSegment, max_hd: int,
                        candidates_budget: int | None, start_tried: int = 0,
                        W: int | None = None) -> tuple[bytearray | None, int]:
    """Flip up to max_hd bits across candidate_columns, accept the first candidate
    whose MAC verifies. Returns (candidate_or_None, total_candidates_tried). The MAC
    check is the real acceptance oracle, so a returned candidate is always valid --
    a wrong "fix" would need a q^-V tag collision.

    start_tried lets a caller run several of these under ONE shared candidates_budget
    (the IC-refinement pair path runs two, after the combined search): the budget is
    compared against the cumulative count, and the cumulative count is returned so the
    next call can carry on where this one stopped."""
    bits_per_symbol = field.bit_lenght
    bit_positions = _bit_positions_for_columns(candidate_columns, bits_per_symbol)
    tried = start_tried
    for hd in range(1, max_hd + 1):
        for combo in combinations(bit_positions, hd):
            if candidates_budget is not None and tried >= candidates_budget:
                return None, tried
            tried += 1
            candidate = _flip_bits(broken_slice, combo, bits_per_symbol)
            if mac_verify_segment(field, keys, candidate, segment, W=W):
                return candidate, tried
    return None, tried


def _search_single_by_bitflip_mac(field: TableField, broken_slice: bytearray, keys: list[bytearray],
                                  candidate_columns: list[int], segment: MacSegment, max_hd: int,
                                  candidates_budget: int | None, W: int | None = None) -> bytearray | None:
    """Single-packet analogue of _search_pair_mac for an odd-one-out broken segment
    with no partner (thin wrapper over _bitflip_search_mac, discarding the count).
    The orthogonal arm can also try an exact linear solve here; the MAC has no equally
    cheap closed form, so this is a bit-flip search only -- kept small by max_hd,
    budget-bounded."""
    candidate, _ = _bitflip_search_mac(field, broken_slice, keys, candidate_columns, segment,
                                       max_hd, candidates_budget, W=W)
    return candidate


# ── One segment, either strategy ─────────────────────────────────────────────

def repair_segment_mac(field: TableField, keys: list[bytearray], packets: list[bytearray], segment: MacSegment,
                       candidate_columns_for, max_combined_hd: int = 4, candidates_budget: int | None = None,
                       pair_cache: dict | None = None, ic_refinement: bool = True,
                       W: int | None = None, drop_unlocalized: bool = False,
                       injected_trust: "SegmentTrust | None" = None) -> SegmentRepairOutcome:
    """Repair one segment across the generation, mutating `packets` in place: pair
    broken packets (plan_pairing, reused from the orthogonal arm -- it is tag-
    agnostic) and combined-search each pair, then bit-flip whatever is left unpaired.

    candidate_columns_for(packet_index) -> list[int] | None supplies per-packet
    ARC-narrowed payload columns (None = whole segment). The one hook that differs
    between Option 1 (always None) and Option 2 (ARC-narrowed for data segments).

    drop_unlocalized (ADR-0013 ARC-only, default off): mirror of the orthogonal arm's
    flag -- a broken packet the localizer returns None for is DROPPED before pairing
    (counted in `dropped`, left untouched) rather than whole-segment-searched, so
    coeff-corrupted targets drop symmetrically with the keyless arm. Off for every
    coefficient_first_mac / uniform_hd_mac caller, so their behaviour is unchanged.

    injected_trust (ADR-0013 isolated harness, default None): mirror of the orthogonal
    arm -- use this ground-truth SegmentTrust verbatim instead of running
    classify_segment_trust_mac, so the harness's injected helper/target split replaces
    per-packet MAC sniffing. None = classify as before (every existing caller
    unchanged)."""
    trust = injected_trust if injected_trust is not None \
        else classify_segment_trust_mac(field, keys, packets, segment)
    if drop_unlocalized:
        dropped_indices = [i for i in trust.broken if candidate_columns_for(i) is None]
        dropped_set = set(dropped_indices)
        pairing_trust = SegmentTrust(segment.name,
                                     broken=[i for i in trust.broken if i not in dropped_set],
                                     trusted=trust.trusted)
    else:
        dropped_indices = []
        pairing_trust = trust
    plan = plan_pairing(pairing_trust)
    all_columns = list(range(segment.payload_length))          # payload cols (narrowed default set)
    pair_columns = list(range(segment.total_length))           # whole segment: payload + tags

    pairs_recovered = pairs_failed = unpaired_recovered = unpaired_failed = 0

    for pair in plan.pairs:
        cols_a = candidate_columns_for(pair.packet_a)
        cols_b = candidate_columns_for(pair.packet_b)
        # Either side missing localization -> search the whole segment for the pair.
        columns = pair_columns if (cols_a is None or cols_b is None) else sorted(set(cols_a) | set(cols_b))

        slice_a = segment_slice(packets[pair.packet_a], segment)
        slice_b = segment_slice(packets[pair.packet_b], segment)
        result = recover_pair_by_combined_search_mac(field, keys, slice_a, slice_b, columns, segment,
                                                     max_combined_hd, candidates_budget=candidates_budget,
                                                     pair_cache=pair_cache, ic_refinement=ic_refinement, W=W)
        if result.ok:
            _write_segment(packets[pair.packet_a], segment, result.fixed_a)
            _write_segment(packets[pair.packet_b], segment, result.fixed_b)
            pairs_recovered += 1
        else:
            pairs_failed += 1

    for unpaired in plan.unpaired:
        columns = candidate_columns_for(unpaired.packet_index)
        if columns is None:
            columns = pair_columns   # whole segment (payload + tags) when unlocalized
        broken_slice = segment_slice(packets[unpaired.packet_index], segment)
        fixed = _search_single_by_bitflip_mac(field, broken_slice, keys, columns, segment,
                                              max_hd=max_combined_hd, candidates_budget=candidates_budget, W=W)
        if fixed is not None:
            _write_segment(packets[unpaired.packet_index], segment, fixed)
            unpaired_recovered += 1
        else:
            unpaired_failed += 1

    return SegmentRepairOutcome(segment.name, pairs_recovered, pairs_failed,
                                unpaired_recovered, unpaired_failed, dropped=len(dropped_indices))


# ── Top level: the two strategies ─────────────────────────────────────────────

def recover_uniform_hd_mac(field: TableField, keyset: list[list[bytearray]], packets: list[bytearray],
                           segments: list[MacSegment], max_combined_hd: int = 4,
                           candidates_budget: int | None = None,
                           pair_cache: dict | None = None,
                           ic_refinement: bool = True, W: int | None = None) -> SegmentedRecoveryReport:
    """Option 1: every segment, coeff and data alike, repaired via pairing + combined
    search. No ARC anywhere. ic_refinement (default on) adds the Case-2 same-position
    fallback per pair."""
    tmp = [bytearray(p) for p in packets]
    per_segment = [
        repair_segment_mac(field, keyset[s], tmp, segment, candidate_columns_for=lambda i: None,
                           max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                           pair_cache=pair_cache, ic_refinement=ic_refinement, W=W)
        for s, segment in enumerate(segments)
    ]
    ok = all(check_mac_segmented(field, keyset, tmp, segments).values())
    return SegmentedRecoveryReport(packets=tmp, per_segment=per_segment, ok=ok)


def recover_arc_only_mac(field: TableField, keyset: list[list[bytearray]], packets: list[bytearray],
                         segments: list[MacSegment], gen_size: int, basis_idx: list[int],
                         coeff_clean_target_idx: list[int], max_combined_hd: int = 4,
                         candidates_budget: int | None = None, pair_cache: dict | None = None,
                         ic_refinement: bool = True, W: int | None = None,
                         injected_trust_by_segment: "dict[str, SegmentTrust] | None" = None,
                         repair_span: str = "payload") -> SegmentedRecoveryReport:
    """ADR-0013 ARC-only variant, keyed arm -- the exact mirror of the orthogonal
    arm's recover_arc_only (segmented_recovery.py), differing ONLY in the acceptance
    oracle (MAC verification vs orthogonality-to-helpers). Skips coeff repair, repairs
    DATA segments only, ARC-localizes from the same injected helper basis, and drops
    coeff-corrupted targets symmetrically (drop_unlocalized). See that function's
    docstring for the basis_idx / coeff_clean_target_idx contract and the (a)/(b)
    error-model handling -- both are identical here by construction."""
    tmp = [bytearray(p) for p in packets]
    seg_index = {segment.name: s for s, segment in enumerate(segments)}
    coeff_segment = next(s for s in segments if s.kind == "coeff")
    data_segments = [s for s in segments if s.kind == "data"]
    basis = sorted(set(basis_idx))
    coeff_trusted = sorted(set(basis) | set(coeff_clean_target_idx))

    per_segment = []  # coeff segment intentionally NOT repaired (ARC-only)
    for segment in data_segments:
        keys = keyset[seg_index[segment.name]]
        localizer = _make_arc_localizer_mac(field, tmp, coeff_segment, segment, gen_size,
                                            coeff_trusted, basis, repair_span=repair_span)
        injected = None if injected_trust_by_segment is None else injected_trust_by_segment.get(segment.name)
        per_segment.append(
            repair_segment_mac(field, keys, tmp, segment, candidate_columns_for=localizer,
                               max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                               pair_cache=pair_cache, ic_refinement=ic_refinement, W=W,
                               drop_unlocalized=True, injected_trust=injected)
        )

    ok = all(check_mac_segmented(field, keyset, tmp, segments).values())
    return SegmentedRecoveryReport(packets=tmp, per_segment=per_segment, ok=ok)


def _make_arc_localizer_mac(field: TableField, packets: list[bytearray], coeff_segment: MacSegment,
                            data_segment: MacSegment, gen_size: int, coeff_trusted_idx: list[int],
                            data_trusted_idx: list[int], repair_span: str = "payload"):
    """Builds candidate_columns_for(packet_index) that ARC-localizes a broken
    packet's corrupted columns within `data_segment`, exactly like the orthogonal
    arm's _make_arc_localizer: a gen_size trusted [coefficients | data-payload]
    basis + the broken packet as a (gen_size+1)-th row, fed to localize_errors.

    ARC is tag-scheme-independent (it re-derives expected data from trusted
    coefficients), so nothing MAC-specific enters here except how trust is
    determined (MAC verification). Falls back to no-localization (None) when fewer
    than gen_size packets are trusted in BOTH segments, or the basis is rank-
    deficient (localize_errors raises)."""
    assert repair_span in ("payload", "segment"), f"repair_span must be payload|segment, got {repair_span!r}"
    extra = _redundancy_columns(data_segment) if repair_span == "segment" else []  # ADR-0013 ticket 16 (tags, no salt)
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
            return None  # this packet's own coefficients aren't trustworthy yet
        try:
            columns = localize_errors(field, [bytearray(p) for p in trusted_basis], synthetic(i), gen_size)
        except (ValueError, ZeroDivisionError):
            return None
        # payload columns ARC found + (repair_span="segment") the tag redundancy span. A None
        # above stays None, so the symmetric drop of coeff-corrupted targets is unaffected.
        return sorted(set(c - gen_size for c in columns) | set(extra))

    return localizer


def recover_coefficient_first_mac(field: TableField, keyset: list[list[bytearray]], packets: list[bytearray],
                                  segments: list[MacSegment], gen_size: int, max_combined_hd: int = 4,
                                  candidates_budget: int | None = None,
                                  pair_cache: dict | None = None,
                                  ic_refinement: bool = True, W: int | None = None,
                                  injected_trust_by_segment: "dict[str, SegmentTrust] | None" = None,
                                  repair_span: str = "payload") -> SegmentedRecoveryReport:
    """Option 2: repair the coeff-segment first (same combined search -- it can never
    ARC-localize itself), then ARC-narrow each data-segment's candidate columns from
    the now-trusted coefficients before repairing them. ic_refinement (default on)
    adds the Case-2 same-position fallback per pair, over the ARC-narrowed columns."""
    tmp = [bytearray(p) for p in packets]
    seg_index = {segment.name: s for s, segment in enumerate(segments)}
    coeff_segment = next(s for s in segments if s.kind == "coeff")
    data_segments = [s for s in segments if s.kind == "data"]

    # ADR-0013 harness: injected ground-truth trust replaces classify_segment_trust_mac
    # for both the ARC localizer and repair_segment_mac's pool. When not injected (every
    # existing caller), the path is identical to before.
    def _injected(segment):
        return None if injected_trust_by_segment is None else injected_trust_by_segment.get(segment.name)

    per_segment = [
        repair_segment_mac(field, keyset[seg_index[coeff_segment.name]], tmp, coeff_segment,
                           candidate_columns_for=lambda i: None, max_combined_hd=max_combined_hd,
                           candidates_budget=candidates_budget, pair_cache=pair_cache,
                           ic_refinement=ic_refinement, W=W, injected_trust=_injected(coeff_segment))
    ]

    coeff_trust = _injected(coeff_segment) if injected_trust_by_segment is not None \
        else classify_segment_trust_mac(field, keyset[seg_index[coeff_segment.name]], tmp, coeff_segment)
    for segment in data_segments:
        keys = keyset[seg_index[segment.name]]
        data_trust = _injected(segment) if injected_trust_by_segment is not None \
            else classify_segment_trust_mac(field, keys, tmp, segment)
        localizer = _make_arc_localizer_mac(field, tmp, coeff_segment, segment, gen_size,
                                            coeff_trust.trusted, data_trust.trusted, repair_span=repair_span)
        per_segment.append(
            repair_segment_mac(field, keys, tmp, segment, candidate_columns_for=localizer,
                               max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                               pair_cache=pair_cache, ic_refinement=ic_refinement, W=W,
                               injected_trust=_injected(segment))
        )

    ok = all(check_mac_segmented(field, keyset, tmp, segments).values())
    return SegmentedRecoveryReport(packets=tmp, per_segment=per_segment, ok=ok)
