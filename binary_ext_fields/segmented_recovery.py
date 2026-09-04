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

IC-refinement / Case 2 (ADR-0012, ticket 07 -- keyless analog of the MAC arm's
port): the combined search only recovers *disjoint* errors -- if both paired
packets have a bit flipped at the very same bit position, the two flips cancel
inside the XOR-combined row and no split can see them. Rather than drop such a
pair, when the combined search exhausts (and ic_refinement is on) each half is
routed into the single-packet ADR-0002 linear solve (recover_unpaired_segment)
over its own narrowed columns -- the keyless analog of the MAC arm's per-half
tag brute-force, since there is no per-packet keyed tag to solve against here.
recover_unpaired_segment only ever returns a slice that passes the real
acceptance oracle (self + cross-orthogonal to the trusted pool), so this fallback
introduces NO silent decode -- a wrong "fix" would need a genuine orthogonality
collision, exactly as for the combined path and the unpaired path. A genuinely
unrecoverable pair (neither half solvable/searchable within budget) still fails
honestly (pairs_failed). Toggle with ic_refinement=False. See
test_recover_uniform_hd_recovers_overlapping_errors_via_ic_refinement.
"""

from dataclasses import dataclass
from itertools import chain, combinations

from binary_ext_fields.custom_field import TableField
from binary_ext_fields.generate_symbols import check_orth_packet
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.segmented_tagging import TaggedSegment, check_orth_segmented
from playground.arc_pl import localize_errors
from playground.new_recovery import is_orthogonal_to_trusted, recover_packet_linear


from contextlib import contextmanager


@contextmanager
def _count_phase(field: TableField, name: str):
    """Attribute the field ops done in this block to `name` when `field` is a
    CountingField that supports phase bucketing; a no-op for a plain field (tests,
    non-counting callers). Keeps the detection/recovery split contained here rather
    than threading a second counter through every recovery signature."""
    fn = getattr(field, "phase", None)
    if fn is None:
        yield
    else:
        with fn(name):
            yield


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


def classify_segment_trust(field: TableField, packets: list[bytearray], segment: TaggedSegment,
                           verify_count: int | None = None) -> SegmentTrust:
    """
    Self-check failure -> broken (conclusive, ADR-0004). Among the self-check
    passers, decide who is *trusted* (cross-consistent) via a POISONER-TOLERANT
    rule, not the old all-or-nothing unanimity.

    Why not unanimity: a corrupted packet can slip past its own self-check (a
    rare self-tag collision, ~1/q per segment, ADR-0010) yet be non-orthogonal to
    the clean packets. Under "trusted iff orthogonal to EVERY other self-passer",
    that single poisoner is non-orthogonal to all the clean packets, so *every*
    clean packet fails its cross-check against it and the whole segment's trusted
    set collapses to zero -- the N=5 starvation-timeout root cause (a poisoner in
    the coeff/data segment zeroes trust, nothing is ever admissible).

    Poisoner-tolerant rule, two stages:
      1. CORE by greedy peel: among self-passers, repeatedly drop the one that
         disagrees with (is non-orthogonal to) the most others, until the
         survivors all mutually agree. A lone poisoner disagrees with everyone,
         so it has the highest disagreement count and is peeled first, leaving
         the clean mutually-orthogonal group intact.
      2. WITNESS CHECK: each self-passer is trusted iff it agrees with the core
         witnesses it is checked against. `verify_count` (None = check against
         the whole core) caps how many core witnesses each packet is verified
         against -- the security/cost dial: more witnesses = harder for a forged
         packet to be accepted (it must agree with every one checked), fewer =
         cheaper. verify_count=0 disables the cross-check entirely (self-check
         only). Core members trivially agree with each other, so the core is
         always trusted; the dial only governs how strictly non-core self-passers
         are admitted.

    All field ops (self-checks + the one-time pairwise agreement matrix) are
    charged to the "detection" phase; the peel and witness check operate on the
    cached boolean matrix, so they cost no field ops. The O(m^2) matrix build is
    the same order as the old check -- an O(m*verify_count) incremental build is a
    deferred optimization, not done here (correctness first)."""
    slices = [segment_slice(p, segment) for p in packets]
    with _count_phase(field, "detection"):
        self_pass = [i for i, s in enumerate(slices) if check_orth_packet(field, s)]
        broken = [i for i in range(len(packets)) if i not in self_pass]
        m = len(self_pass)
        # One-time pairwise agreement among self-passers (True == disagree == not
        # orthogonal). Everything below reads this matrix -- no more field ops.
        disagree = [[False] * m for _ in range(m)]
        for a in range(m):
            for b in range(a + 1, m):
                bad = inner_product_bytes(field, slices[self_pass[a]], slices[self_pass[b]]) != 0
                disagree[a][b] = disagree[b][a] = bad

    # Stage 1: greedy-peel the core (indices into self_pass).
    alive = set(range(m))
    while alive:
        counts = {a: sum(1 for b in alive if b != a and disagree[a][b]) for a in alive}
        worst = max(alive, key=lambda a: counts[a])
        if counts[worst] == 0:
            break  # survivors are fully mutually orthogonal
        alive.discard(worst)
    core = sorted(alive)

    # Stage 2: witness check against up to `verify_count` core members.
    trusted = []
    for a in range(m):
        witnesses = [c for c in core if c != a]
        if verify_count is not None:
            witnesses = witnesses[:verify_count]
        if all(not disagree[a][c] for c in witnesses):
            trusted.append(self_pass[a])
    return SegmentTrust(segment.name, broken=broken, trusted=sorted(trusted))


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


def _pair_cache_key(slice_a: bytearray, slice_b: bytearray, trusted_slices: list[bytearray],
                    candidate_columns: list[int], max_combined_hd: int,
                    candidates_budget: int | None):
    """Canonical, hashable key over everything the search's output depends on.
    Trusted slices are sorted because they enter only through order-independent
    orthogonality checks -- so the same trusted *set* must key the same result
    regardless of the order classify_segment_trust happened to list them in.
    candidate_columns is kept in order: it drives the combination-iteration
    order, so it genuinely affects which split is found first."""
    return (
        bytes(slice_a), bytes(slice_b),
        tuple(sorted(bytes(t) for t in trusted_slices)),
        tuple(candidate_columns), max_combined_hd, candidates_budget,
    )


def recover_pair_by_combined_search(field: TableField, slice_a: bytearray, slice_b: bytearray,
                                     trusted_slices: list[bytearray], candidate_columns: list[int],
                                     max_combined_hd: int, candidates_budget: int | None = None,
                                     pair_cache: dict | None = None) -> PairRecoveryResult:
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

    `pair_cache` (None = no caching) persists results across calls keyed by this
    pair's exact inputs. This search is a pure function of (slice_a, slice_b,
    trusted set, candidate_columns, max_combined_hd, budget), so a cache hit
    returns a result identical to recomputing it -- but without re-spending the
    (up to `candidates_budget`) field operations. That is the whole point: a
    broken pair the sim re-examines every round with unchanged bytes and an
    unchanged trusted set (the common high-BER case) is searched once, not once
    per round. A change to either packet or to the trusted set changes the key
    and forces a fresh search (ADR-0012; ticket 01 "per-pair persistence").
    """
    if pair_cache is not None:
        key = _pair_cache_key(slice_a, slice_b, trusted_slices, candidate_columns,
                              max_combined_hd, candidates_budget)
        cached = pair_cache.get(key)
        if cached is not None:
            return cached
        result = _search_pair_by_combined_search(field, slice_a, slice_b, trusted_slices,
                                                  candidate_columns, max_combined_hd, candidates_budget)
        pair_cache[key] = result
        return result
    return _search_pair_by_combined_search(field, slice_a, slice_b, trusted_slices,
                                           candidate_columns, max_combined_hd, candidates_budget)


def _search_pair_by_combined_search(field: TableField, slice_a: bytearray, slice_b: bytearray,
                                     trusted_slices: list[bytearray], candidate_columns: list[int],
                                     max_combined_hd: int, candidates_budget: int | None
                                     ) -> PairRecoveryResult:
    """The actual combined search, extracted so recover_pair_by_combined_search can
    wrap it with the per-pair cache. Pure and deterministic in its inputs."""
    bits_per_symbol = field.bit_lenght
    bit_positions = _bit_positions_for_columns(candidate_columns, bits_per_symbol)
    combined = bytearray(a ^ b for a, b in zip(slice_a, slice_b))

    candidates_tried = 0
    with _count_phase(field, "recovery"):
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

def _search_single_by_bitflip(field: TableField, broken_slice: bytearray, trusted_slices: list[bytearray],
                               candidate_columns: list[int], max_hd: int,
                               candidates_budget: int | None) -> bytearray | None:
    """Single-packet analogue of _search_pair_by_combined_search: flip up to `max_hd`
    bits across `candidate_columns`, accept the first candidate that passes the
    acceptance oracle (self- AND cross-orthogonal to the trusted pool). Unlike the pair
    search there is no partner to XOR against, so there is no differing-column shortcut
    to localize the error -- it searches candidate_columns directly. Budget-bounded for
    the same reason the pair search is; None on give-up. Callers still hold the HD bound
    small, which is what keeps a salt/tag flip from silently masking a data error."""
    bits_per_symbol = field.bit_lenght
    bit_positions = _bit_positions_for_columns(candidate_columns, bits_per_symbol)
    tried = 0
    for hd in range(1, max_hd + 1):
        for combo in combinations(bit_positions, hd):
            if candidates_budget is not None and tried >= candidates_budget:
                return None
            tried += 1
            candidate = _flip_bits(broken_slice, combo, bits_per_symbol)
            if is_orthogonal_to_trusted(field, candidate, trusted_slices):
                return candidate
    return None


def recover_unpaired_segment(field: TableField, broken_slice: bytearray, candidate_columns: list[int],
                              trusted_slices: list[bytearray], whole_segment_columns: list[int] | None = None,
                              max_hd: int = 2, candidates_budget: int | None = None) -> bytearray | None:
    """ADR-0012's fallback for a broken segment with no pairing partner.

    Two-stage, mirroring the whole-packet pipeline (playground/new_recovery.py
    recover_generation): first ADR-0002's exact linear solve over candidate_columns
    (cheap and exact when ARC has narrowed the unknown set small enough to be
    determined, K <= #trusted); if that is underdetermined/rejected, fall back to a
    bounded whole-segment bit-flip search.

    The fallback is the unpaired analogue of the pair path's whole-segment fix: the
    linear solve can only ever touch payload columns it was given, so a salt/tag flip
    -- or a uniform_hd packet whose K exceeds the trusted count -- is unsolvable and
    used to return None (dropping the packet). The bit-flip search covers the whole
    segment (payload+salt+tags via whole_segment_columns), bounded by max_hd and
    candidates_budget. Returns None only if BOTH stages give up."""
    with _count_phase(field, "recovery"):
        fixed = recover_packet_linear(field, broken_slice, set(candidate_columns), trusted_slices)
        if fixed is not None and is_orthogonal_to_trusted(field, fixed, trusted_slices):
            return fixed
        cols = whole_segment_columns if whole_segment_columns is not None else candidate_columns
        return _search_single_by_bitflip(field, broken_slice, trusted_slices, cols, max_hd, candidates_budget)


# ── One segment, either strategy ─────────────────────────────────────────────

@dataclass(frozen=True)
class SegmentRepairOutcome:
    segment_name: str
    pairs_recovered: int
    pairs_failed: int
    unpaired_recovered: int
    unpaired_failed: int


def _ic_refine_pair(field: TableField, packets: list[bytearray], segment: TaggedSegment,
                    pair, cols_a, cols_b, all_columns, pair_columns, trusted_slices,
                    max_combined_hd: int, candidates_budget: int | None) -> bool:
    """IC-refinement (ticket 07) for one pair the combined search could not split --
    the same-position overlap Case 2. The keyless analog of the MAC arm's per-half tag
    brute-force is the ADR-0002 EXACT single-packet linear solve (recover_packet_linear)
    over each half's NARROWED columns -- its ARC localization from coefficient_first.
    Deliberately NOT the blind whole-segment bit-flip: with no keyed tag, that weak
    search accepts collision fixes that pass the ~1/q-per-witness orthogonality oracle,
    which measurably RAISES the silent-decode rate -- the one thing ticket 07 decision 4
    forbids. The exact solve is deterministic: it recovers when the narrowed column set
    pins the error (K <= #trusted, which ARC delivers) and returns None (-> honest
    failure) when underdetermined. So IC-refinement lifts recovery for coefficient_first
    (ARC-narrowed) and is a safe no-op for uniform_hd (no narrowing -> underdetermined),
    never trading recovery for silent errors.

    Both halves are solved and gated BEFORE either is written, so a pair where only one
    half recovers stays untouched (failed, not half-repaired). Each half must be
    self+cross-orthogonal to the trusted pool AND the two halves mutually orthogonal
    (the joint constraint the combined-pair path enforces), so no silent decode enters.
    Returns True iff both halves were recovered and written.

    candidate_columns unused (candidates_budget/pair_columns/max_combined_hd kept in the
    signature for symmetry with the MAC arm's budgeted fallback; the exact solve is
    polynomial, not a budgeted search)."""
    cols_a_solve = cols_a if cols_a is not None else all_columns
    cols_b_solve = cols_b if cols_b is not None else all_columns
    slice_a = segment_slice(packets[pair.packet_a], segment)
    slice_b = segment_slice(packets[pair.packet_b], segment)
    with _count_phase(field, "recovery"):
        fixed_a = recover_packet_linear(field, slice_a, set(cols_a_solve), trusted_slices)
        if fixed_a is None or not is_orthogonal_to_trusted(field, fixed_a, trusted_slices):
            return False
        fixed_b = recover_packet_linear(field, slice_b, set(cols_b_solve), trusted_slices)
        if fixed_b is None or not is_orthogonal_to_trusted(field, fixed_b, trusted_slices):
            return False
        # Mutual-orthogonality: two genuinely-correct halves are orthogonal to each
        # other; requiring it rejects the residual collision fixes a per-half solve
        # could otherwise admit (the combined path enforces the same constraint).
        if inner_product_bytes(field, fixed_a, fixed_b) != 0:
            return False
    _write_segment(packets[pair.packet_a], segment, fixed_a)
    _write_segment(packets[pair.packet_b], segment, fixed_b)
    return True


def repair_segment(field: TableField, packets: list[bytearray], segment: TaggedSegment,
                    candidate_columns_for, max_combined_hd: int = 4,
                    candidates_budget: int | None = None,
                    pair_cache: dict | None = None,
                    verify_count: int | None = None,
                    ic_refinement: bool = True) -> SegmentRepairOutcome:
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

    pair_cache: forwarded to recover_pair_by_combined_search (None = no caching);
    persists per-pair search results across rounds. The unpaired linear solve is
    not cached -- it is polynomial, not a budgeted search, so it is not the cost
    the persistence is aimed at.
    """
    trust = classify_segment_trust(field, packets, segment, verify_count=verify_count)
    plan = plan_pairing(trust)
    trusted_slices = [segment_slice(packets[i], segment) for i in trust.trusted]
    all_columns = list(range(segment.payload_length))  # payload cols for the exact linear solve stage
    # Pair search covers the WHOLE segment -- payload + salt + tags (ADR-0012 blind-spot
    # fix). A flip in a salt/tag byte otherwise makes a packet unrepairable, and when
    # that packet is paired with one carrying a genuinely recoverable payload error, it
    # drags the recoverable one down too (confirmed: scripts/segmented_inspect_failure.py,
    # seed 3: coeff payload[3] flip in one packet + tag[2] flip in its partner -> both
    # dropped, though the payload error alone was HD-1 recoverable). The max_combined_hd
    # bound keeps this safe: masking a data error by bending redundancy bytes would take
    # far more than that many flips. The unpaired odd-one-out path below reuses these
    # same whole-segment columns for its bit-flip fallback stage.
    pair_columns = list(range(segment.total_length))

    pairs_recovered = pairs_failed = unpaired_recovered = unpaired_failed = 0

    for pair in plan.pairs:
        cols_a = candidate_columns_for(pair.packet_a)
        cols_b = candidate_columns_for(pair.packet_b)
        # Either side missing localization -> search the whole segment for the pair,
        # rather than silently narrowing to only the side that did localize.
        columns = pair_columns if (cols_a is None or cols_b is None) else sorted(set(cols_a) | set(cols_b))

        slice_a = segment_slice(packets[pair.packet_a], segment)
        slice_b = segment_slice(packets[pair.packet_b], segment)
        result = recover_pair_by_combined_search(field, slice_a, slice_b, trusted_slices, columns,
                                                  max_combined_hd, candidates_budget=candidates_budget,
                                                  pair_cache=pair_cache)

        if result.ok:
            _write_segment(packets[pair.packet_a], segment, result.fixed_a)
            _write_segment(packets[pair.packet_b], segment, result.fixed_b)
            pairs_recovered += 1
        elif ic_refinement and _ic_refine_pair(field, packets, segment, pair, cols_a, cols_b,
                                               all_columns, pair_columns, trusted_slices,
                                               max_combined_hd, candidates_budget):
            # Case-2 fallback (ticket 07, keyless analog): the combined search is
            # blind to same-position overlaps, so repair each half on its own via the
            # ADR-0002 single-packet linear solve. _ic_refine_pair writes both halves
            # in place and returns True only if BOTH pass the real acceptance oracle
            # (self+cross orthogonal to the trusted pool) -- so no silent decode.
            pairs_recovered += 1
        else:
            pairs_failed += 1

    for unpaired in plan.unpaired:
        columns = candidate_columns_for(unpaired.packet_index)
        if columns is None:
            columns = all_columns
        broken_slice = segment_slice(packets[unpaired.packet_index], segment)
        # Linear solve over `columns` (ARC-narrowed payload if available), then a
        # bounded whole-segment bit-flip fallback so an unpaired salt/tag flip -- or a
        # uniform_hd packet the solve can't determine -- is still recoverable instead
        # of dropped (mirrors the pair path's whole-segment fix).
        fixed = recover_unpaired_segment(field, broken_slice, columns, trusted_slices,
                                         whole_segment_columns=pair_columns,
                                         max_hd=max_combined_hd, candidates_budget=candidates_budget)

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
                        max_combined_hd: int = 4, candidates_budget: int | None = None,
                        pair_cache: dict | None = None,
                        verify_count: int | None = None,
                        ic_refinement: bool = True) -> SegmentedRecoveryReport:
    """ADR-0012 Option 1: every segment, coeff and data alike, repaired via
    pairing + combined search, unpaired via the ADR-0002 linear solve. No ARC
    anywhere -- the coeff-segment gets exactly the same treatment as any
    data-segment, which is the point: closing the coefficient blind spot the
    whole-packet scheme's ARC-based recovery (playground/new_recovery.py modes
    C/D) has always had.

    pair_cache (None = no caching) persists per-pair combined-search results
    across calls; see recover_pair_by_combined_search."""
    tmp = [bytearray(p) for p in packets]
    per_segment = [
        repair_segment(field, tmp, segment, candidate_columns_for=lambda i: None,
                       max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                       pair_cache=pair_cache, verify_count=verify_count, ic_refinement=ic_refinement)
        for segment in segments
    ]
    with _count_phase(field, "detection"):
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
                               gen_size: int, max_combined_hd: int = 4, candidates_budget: int | None = None,
                               pair_cache: dict | None = None,
                               verify_count: int | None = None,
                               ic_refinement: bool = True) -> SegmentedRecoveryReport:
    """ADR-0012 Option 2: repair the coeff-segment first (same pairing/combined-
    search machinery as Option 1 -- it can never ARC-localize itself), then use
    the now-trustworthy coefficients to ARC-narrow each data-segment's candidate
    columns before repairing them, restricting the same pairing/search machinery
    to a much smaller column set.

    pair_cache (None = no caching) persists per-pair combined-search results
    across calls; see recover_pair_by_combined_search. The ARC-narrowed
    candidate_columns are part of the cache key, so a data-segment pair is only
    reused when its localization also came out identical."""
    tmp = [bytearray(p) for p in packets]
    coeff_segment = next(s for s in segments if s.kind == "coeff")
    data_segments = [s for s in segments if s.kind == "data"]

    per_segment = [
        repair_segment(field, tmp, coeff_segment, candidate_columns_for=lambda i: None,
                       max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                       pair_cache=pair_cache, verify_count=verify_count, ic_refinement=ic_refinement)
    ]

    coeff_trust = classify_segment_trust(field, tmp, coeff_segment, verify_count=verify_count)
    for segment in data_segments:
        data_trust = classify_segment_trust(field, tmp, segment, verify_count=verify_count)
        localizer = _make_arc_localizer(
            field, tmp, coeff_segment, segment, gen_size, coeff_trust.trusted, data_trust.trusted,
        )
        per_segment.append(
            repair_segment(field, tmp, segment, candidate_columns_for=localizer,
                           max_combined_hd=max_combined_hd, candidates_budget=candidates_budget,
                           pair_cache=pair_cache, verify_count=verify_count, ic_refinement=ic_refinement)
        )

    with _count_phase(field, "detection"):
        ok = all(check_orth_segmented(field, tmp, segments).values())
    return SegmentedRecoveryReport(packets=tmp, per_segment=per_segment, ok=ok)
