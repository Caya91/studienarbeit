"""
Tests for segment pairing and recovery (ADR-0012, binary_ext_fields/segmented_recovery.py).

Meant to be read, not just run -- each test demonstrates one property of the
mechanism: who gets classified broken/trusted, how pairing groups them up, that
a genuinely disjoint two-packet corruption is repaired byte-for-byte back to
the original (not just "some" orthogonal value), that the coefficient block
-- the whole-packet scheme's documented blind spot -- is repaired exactly like
any data segment, that an odd one out correctly falls back to the ADR-0002
linear solve, that a same-bit-position overlap the combined search cannot split
is recovered by the IC-refinement fallback (ticket 07 -- each half routed into
the ADR-0002 linear solve), and that anything genuinely beyond that fallback's
reach still fails honestly instead of silently.
"""
import random

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import (
    generate_identity_coefficients,
    code_with_given_coefficients,
    recode_rlnc_without_coeffs,
)
from binary_ext_fields.segmented_tagging import (
    TaggedSegment,
    build_segments,
    tag_generation_segmented,
    check_orth_segmented,
)
from binary_ext_fields.segmented_recovery import (
    SegmentTrust,
    SegmentPair,
    classify_segment_trust,
    plan_pairing,
    recover_pair_by_combined_search,
    recover_uniform_hd,
    recover_coefficient_first,
    _make_arc_localizer,
)
from playground.arc_pl import error_into_packet_chosen_bit


# ── Read-along print helpers ─────────────────────────────────────────────────
# These exist purely so a human running the test can *see* what happens to the
# packets: the bytes before corruption, exactly where a bit was flipped, and
# what recovery gave back. They do no work the assertions depend on.

def _hex(buf):
    """A byte buffer as space-separated 2-digit hex, e.g. '0a ff 00'."""
    return " ".join(f"{b:02x}" for b in buf)


def _seg_slice(packet, segment):
    """The bytes of one segment (payload+salt+tag) out of a full packet."""
    return packet[segment.start:segment.start + segment.total_length]


def _show_segment(label, packets, segment, indices=None):
    """Print the chosen segment of each packet so its contents are visible."""
    indices = range(len(packets)) if indices is None else indices
    print(f"    {label} -- segment {segment.name!r} "
          f"(start={segment.start}, payload_length={segment.payload_length}):")
    for i in indices:
        print(f"      packet[{i}]: {_hex(_seg_slice(packets[i], segment))}")


def _show_diff(label, before, after):
    """Print two byte buffers and mark the columns that differ."""
    # Each byte is 2 hex chars + 1 separating space -> a 3-char column; put the
    # "^^" under the byte itself (first two chars), keeping every column aligned.
    marks = "".join("^^ " if x != y else "   " for x, y in zip(before, after))
    print(f"    {label}:")
    print(f"      before: {_hex(before)}")
    print(f"      after:  {_hex(after)}")
    print(f"              {marks.rstrip()}")


def _banner(name):
    print(f"\n=== {name} ===")


def _random_data_rows(field, data_fields, gen_size):
    return [
        bytearray(random.randint(0, field.max_value) for _ in range(data_fields))
        for _ in range(gen_size)
    ]


def _build_tagged_pool(field, gen_size, data_fields, num_data_segments):
    plain_packets = generate_identity_coefficients(field, _random_data_rows(field, data_fields, gen_size))
    result = tag_generation_segmented(field, plain_packets, gen_size, num_data_segments)
    assert result.ok, f"segmented tagging gave up on segment {result.failed_segment!r}"
    return result


# Shared config for most tests: 4 packets, 3 equal data-segments of 4 bytes each
# (mirrors segmented_tagging_test.py's own convention, so payload lengths stay
# above the rank-deficiency floor build_segments documents).
FIELD = create_field(8)
GEN_SIZE = 4
DATA_FIELDS = 12
NUM_DATA_SEGMENTS = 3


def test_classify_segment_trust_marks_only_the_corrupted_packet_broken():
    '''A single corrupted packet fails its own self-check; everyone else, still
    pairwise cross-orthogonal, is trusted.'''
    _banner("classify_segment_trust: one corrupt packet, rest trusted")
    random.seed(10)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    segment = next(s for s in result.segments if s.name == "data-1")
    print(f"  built {GEN_SIZE} tagged packets; watching segment {segment.name!r}")
    _show_segment("clean pool", result.packets, segment)

    packets = [bytearray(p) for p in result.packets]
    before = _seg_slice(packets[2], segment)
    packets[2] = error_into_packet_chosen_bit(packets[2], segment.start, chosen_bit=1)
    print("  flipping bit 1 of segment column 0 in packet[2]:")
    _show_diff("packet[2] segment", before, _seg_slice(packets[2], segment))

    trust = classify_segment_trust(FIELD, packets, segment)
    print(f"  -> classified broken={trust.broken}, trusted={trust.trusted}")

    assert trust.broken == [2]
    assert trust.trusted == [0, 1, 3]


def test_plan_pairing_pairs_fifo_and_leaves_odd_one_out():
    '''Pure unit test of the pairing rule: ascending index, pairs of two, last
    leftover (if any) becomes the unpaired fallback case. No field/tagging
    needed -- this only exercises the FIFO grouping logic.'''
    _banner("plan_pairing: FIFO pairs, odd one left over")
    even = SegmentTrust(segment_name="data-0", broken=[5, 1, 3, 0], trusted=[])
    print(f"  broken (as given): {even.broken}  -> sorted, paired two-by-two")
    plan = plan_pairing(even)
    print(f"  pairs:    {[(p.packet_a, p.packet_b) for p in plan.pairs]}")
    print(f"  unpaired: {[u.packet_index for u in plan.unpaired]}")
    assert plan.pairs == [
        SegmentPair("data-0", 0, 1),
        SegmentPair("data-0", 3, 5),
    ]
    assert plan.unpaired == []

    odd = SegmentTrust(segment_name="data-0", broken=[4, 0, 2], trusted=[])
    print(f"  broken (odd count): {odd.broken}  -> one packet has no partner")
    plan = plan_pairing(odd)
    print(f"  pairs:    {[(p.packet_a, p.packet_b) for p in plan.pairs]}")
    print(f"  unpaired: {[u.packet_index for u in plan.unpaired]}  (falls back to linear solve)")
    assert [(p.packet_a, p.packet_b) for p in plan.pairs] == [(0, 2)]
    assert [(u.packet_index) for u in plan.unpaired] == [4]


def test_recover_pair_by_combined_search_fixes_two_disjoint_single_bit_errors():
    '''The core mechanism, exercised directly (not through the full pipeline):
    two packets broken at different columns of the same segment, each by one
    flipped bit. The combined search must recover BOTH exactly, byte-for-byte.'''
    _banner("recover_pair_by_combined_search: two disjoint single-bit errors")
    random.seed(11)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    segment = next(s for s in result.segments if s.name == "data-0")
    original_a = bytearray(result.packets[0][segment.start:segment.start + segment.total_length])
    original_b = bytearray(result.packets[1][segment.start:segment.start + segment.total_length])

    broken_a = error_into_packet_chosen_bit(original_a, 0, chosen_bit=2)
    broken_b = error_into_packet_chosen_bit(original_b, 1, chosen_bit=6)
    print("  packet a broken at column 0 bit 2; packet b broken at column 1 bit 6 (disjoint):")
    _show_diff("packet a segment", original_a, broken_a)
    _show_diff("packet b segment", original_b, broken_b)
    trusted_slices = [result.packets[i][segment.start:segment.start + segment.total_length] for i in (2, 3)]

    columns = list(range(segment.payload_length))
    print(f"  searching columns {columns} with max_combined_hd=2 against 2 trusted rows...")
    out = recover_pair_by_combined_search(FIELD, broken_a, broken_b, trusted_slices, columns, max_combined_hd=2)
    print(f"  -> ok={out.ok}")
    if out.ok:
        print(f"     fixed a matches original: {out.fixed_a == original_a}  ({_hex(out.fixed_a)})")
        print(f"     fixed b matches original: {out.fixed_b == original_b}  ({_hex(out.fixed_b)})")

    assert out.ok, "expected the disjoint two-error pair to be recoverable"
    assert out.fixed_a == original_a
    assert out.fixed_b == original_b


def test_recover_pair_by_combined_search_gives_up_within_budget_not_forever():
    '''A combined weight-2 correction needs max_combined_hd >= 2; capped at 1 it
    must report ok=False (an honest budget give-up), not loop or crash.'''
    _banner("recover_pair_by_combined_search: honest give-up under budget")
    random.seed(12)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    segment = next(s for s in result.segments if s.name == "data-0")
    original_a = bytearray(result.packets[0][segment.start:segment.start + segment.total_length])
    original_b = bytearray(result.packets[1][segment.start:segment.start + segment.total_length])

    broken_a = error_into_packet_chosen_bit(original_a, 0, chosen_bit=2)
    broken_b = error_into_packet_chosen_bit(original_b, 1, chosen_bit=6)
    trusted_slices = [result.packets[i][segment.start:segment.start + segment.total_length] for i in (2, 3)]

    columns = list(range(segment.payload_length))
    print("  same weight-2 pair as before, but capping max_combined_hd=1 (too small):")
    out = recover_pair_by_combined_search(FIELD, broken_a, broken_b, trusted_slices, columns, max_combined_hd=1)
    print(f"  -> ok={out.ok}, fixed_a={out.fixed_a}, fixed_b={out.fixed_b}  (budget exhausted, no guess)")

    assert out.ok is False
    assert out.fixed_a is None and out.fixed_b is None


def test_recover_uniform_hd_repairs_two_broken_packets_in_a_data_segment():
    '''Full pipeline (Option 1): two packets broken in the same data segment at
    disjoint columns must both come back byte-for-byte identical to the
    original clean generation, and the whole pool must check out afterwards.'''
    _banner("recover_uniform_hd: full pipeline repairs a data segment")
    random.seed(13)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    original = [bytearray(p) for p in result.packets]
    segment = next(s for s in result.segments if s.name == "data-1")

    broken = [bytearray(p) for p in result.packets]
    broken[0] = error_into_packet_chosen_bit(broken[0], segment.start, chosen_bit=2)
    broken[2] = error_into_packet_chosen_bit(broken[2], segment.start + 1, chosen_bit=5)
    print("  corrupting packet[0] (col 0) and packet[2] (col 1) in segment 'data-1':")
    _show_segment("broken pool", broken, segment)
    orth_ok = check_orth_segmented(FIELD, broken, result.segments)["data-1"]
    print(f"  orthogonality check for 'data-1' now: {orth_ok}  (False = corruption detected)")
    assert orth_ok is False

    print("  running recover_uniform_hd(max_combined_hd=2)...")
    report = recover_uniform_hd(FIELD, broken, result.segments, max_combined_hd=2)
    outcome = next(o for o in report.per_segment if o.segment_name == "data-1")
    print(f"  -> ok={report.ok}, packets restored to original: {report.packets == original}")
    print(f"     'data-1' outcome: pairs_recovered={outcome.pairs_recovered}, "
          f"pairs_failed={outcome.pairs_failed}")

    assert report.ok is True
    assert report.packets == original
    assert outcome.pairs_recovered == 1
    assert outcome.pairs_failed == 0


def test_recover_uniform_hd_repairs_coefficient_segment_corruption():
    '''This is the gap ADR-0012 exists to close: the whole-packet scheme's ARC
    recovery can never repair the coefficient block (playground/new_recovery.py's
    documented "intrinsic blind spot"). Here, corrupting TWO packets' coeff
    segments must still recover exactly, via the exact same pairing/search
    mechanism used for any data segment -- no special-casing needed.'''
    _banner("recover_uniform_hd: repairs the COEFFICIENT segment (ADR-0012 gap)")
    random.seed(14)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    original = [bytearray(p) for p in result.packets]
    segment = next(s for s in result.segments if s.name == "coeff")

    broken = [bytearray(p) for p in result.packets]
    broken[1] = error_into_packet_chosen_bit(broken[1], segment.start, chosen_bit=1)
    broken[3] = error_into_packet_chosen_bit(broken[3], segment.start + 2, chosen_bit=4)
    print("  corrupting the coeff block of packet[1] (col 0) and packet[3] (col 2)")
    print("  -- the whole-packet ARC scheme's documented blind spot:")
    _show_segment("broken pool", broken, segment)

    report = recover_uniform_hd(FIELD, broken, result.segments, max_combined_hd=2)
    print(f"  -> ok={report.ok}, coeff block restored to original: {report.packets == original}")

    assert report.ok is True
    assert report.packets == original


def test_recover_uniform_hd_single_broken_packet_uses_unpaired_fallback():
    '''One broken packet has no pairing partner: plan_pairing must route it to
    the ADR-0002 linear solve, and (with enough trusted rows to fully determine
    the K=payload_length unknowns) recover it exactly.'''
    _banner("recover_uniform_hd: lone broken packet uses linear-solve fallback")
    random.seed(15)
    field = create_field(8)
    gen_size = 6
    data_fields = 5  # one data-segment of length 5 == gen_size - 1, at build_segments' documented floor
    num_data_segments = 1

    result = _build_tagged_pool(field, gen_size, data_fields, num_data_segments)
    original = [bytearray(p) for p in result.packets]
    segment = next(s for s in result.segments if s.kind == "data")
    print(f"  gen_size={gen_size}, single data segment {segment.name!r} of length {segment.payload_length}")

    broken = [bytearray(p) for p in result.packets]
    before = _seg_slice(broken[0], segment)
    broken[0] = error_into_packet_chosen_bit(broken[0], segment.start, chosen_bit=3)
    print("  only packet[0] corrupted -> no pairing partner -> ADR-0002 linear solve:")
    _show_diff("packet[0] segment", before, _seg_slice(broken[0], segment))

    report = recover_uniform_hd(field, broken, result.segments, max_combined_hd=2)
    outcome = next(o for o in report.per_segment if o.segment_name == segment.name)
    print(f"  -> ok={report.ok}, restored: {report.packets == original}, "
          f"unpaired_recovered={outcome.unpaired_recovered}, pairs_recovered={outcome.pairs_recovered}")

    assert report.ok is True
    assert report.packets == original
    assert outcome.unpaired_recovered == 1
    assert outcome.pairs_recovered == 0


def test_recover_coefficient_first_recovers_overlapping_errors_via_ic_refinement():
    '''Ticket 07 (IC-refinement, Case 2 -- keyless arm): two packets corrupted at the
    SAME bit position of a data segment cancel in the XOR-combined row, so the combined
    search alone cannot split them. IC-refinement routes each half into the ADR-0002
    EXACT single-packet linear solve over its ARC-narrowed column -- the keyless analog
    of the MAC arm's per-half tag brute-force -- and recovers BOTH byte-for-byte with no
    silent wrong fix. ARC (coefficient_first + recoded spares) is what makes the solve
    exact: it pins each broken packet to its single corrupted column (K=1 <= #trusted).
    With ic_refinement disabled the same pair fails honestly, proving the fallback is
    what recovers it.'''
    _banner("recover_coefficient_first: overlapping errors recovered by IC-refinement (Case 2)")
    random.seed(19)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    recoded = recode_rlnc_without_coeffs(FIELD, result.packets, GEN_SIZE, count=5)
    pool = [bytearray(p) for p in result.packets] + [bytearray(p) for p in recoded]
    original = [bytearray(p) for p in pool]
    data_segment = next(s for s in result.segments if s.name == "data-0")

    broken = [bytearray(p) for p in pool]
    broken[0] = error_into_packet_chosen_bit(broken[0], data_segment.start, chosen_bit=2)
    broken[2] = error_into_packet_chosen_bit(broken[2], data_segment.start, chosen_bit=2)  # SAME column+bit
    print("  packet[0] and packet[2] flipped at the SAME column 0, SAME bit 2 of data-0;")
    print("  coefficients clean, recoded spares present -> ARC pins the column, solve is exact.")

    # Without the fallback -> honest failure (the pre-ticket-07 behaviour).
    off = recover_coefficient_first(FIELD, [bytearray(p) for p in broken], result.segments,
                                    GEN_SIZE, max_combined_hd=2, ic_refinement=False)
    off_outcome = next(o for o in off.per_segment if o.segment_name == "data-0")
    print(f"  ic_refinement=False: ok={off.ok} (expect False), pairs_failed={off_outcome.pairs_failed}")
    assert off.ok is False
    assert off_outcome.pairs_failed == 1
    assert off_outcome.pairs_recovered == 0

    # With the fallback (default on) -> both halves recovered, byte-for-byte exact.
    report = recover_coefficient_first(FIELD, broken, result.segments, GEN_SIZE, max_combined_hd=2)
    outcome = next(o for o in report.per_segment if o.segment_name == "data-0")
    print(f"  ic_refinement=True:  ok={report.ok} (expect True), "
          f"pairs_recovered={outcome.pairs_recovered}, restored exactly={report.packets == original}")
    assert report.ok is True
    assert outcome.pairs_recovered == 1
    assert outcome.pairs_failed == 0
    assert report.packets == original  # no silent wrong repair -- exact originals back


def test_ic_refinement_uniform_hd_overlap_fails_honestly_without_arc():
    '''The safe no-op case: in uniform_hd there is no ARC narrowing, so a same-position
    overlap leaves the per-half linear solve with K=payload_length unknowns and only a
    couple of trusted rows -- underdetermined. IC-refinement (exact-solve only, never a
    blind bit-flip that would risk a collision fix) therefore recovers nothing here and
    the pair fails HONESTLY, rather than trading recovery for a silent decode. This is
    the deliberate keyless-arm scoping: IC-refinement lifts recovery where ARC makes the
    solve exact and is a no-op where it cannot.'''
    _banner("IC-refinement (uniform_hd, no ARC): same-position overlap fails honestly")
    random.seed(23)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    original = [bytearray(p) for p in result.packets]
    segment = next(s for s in result.segments if s.name == "data-1")

    broken = [bytearray(p) for p in result.packets]
    broken[0] = error_into_packet_chosen_bit(broken[0], segment.start, chosen_bit=2)
    broken[2] = error_into_packet_chosen_bit(broken[2], segment.start, chosen_bit=2)  # identical column+bit

    report = recover_uniform_hd(FIELD, broken, result.segments, max_combined_hd=2)
    outcome = next(o for o in report.per_segment if o.segment_name == "data-1")
    print(f"  -> ok={report.ok} (expect False), pairs_failed={outcome.pairs_failed}, "
          f"pairs_recovered={outcome.pairs_recovered}")
    assert report.ok is False
    assert outcome.pairs_failed == 1
    assert outcome.pairs_recovered == 0
    # The overlapping packets are left broken, not silently mutated into a wrong "fix".
    assert report.packets[0] != original[0]
    assert report.packets[2] != original[2]


def test_arc_localizer_narrows_to_the_true_corrupted_column_given_a_full_rank_basis():
    '''Isolated correctness check for _make_arc_localizer's glue code (building
    the [coefficients | data-segment payload] synthetic packets and converting
    localize_errors' offsets back to segment-local columns), independent of
    whether a real segmented generation can supply the gen_size-sized trusted
    basis this needs (see the next test: within a single closed generation, it
    generally cannot -- see that test's docstring for why).

    Hand-built scenario, mirroring playground/arc_pl.py's own ARC tests: a
    gen_size trusted basis with identity coefficients, and a 5th packet coded
    with different (recoded) coefficients and one corrupted data byte.
    '''
    _banner("_make_arc_localizer: narrows to the true corrupted column")
    random.seed(17)
    field = create_field(8)
    gen_size = 4
    data_len = 6

    coeff_segment = TaggedSegment(name="coeff", kind="coeff", start=0, payload_length=gen_size, gen_size=gen_size)
    data_segment = TaggedSegment(
        name="data-0", kind="data", start=coeff_segment.total_length, payload_length=data_len, gen_size=gen_size,
    )

    def synthetic_packet(coeffs, data):
        # segment_slice only ever reads the payload prefix of each block, so the
        # salt+tag bytes after it are never inspected here -- zero-fill is enough.
        return bytearray(coeffs) + bytearray(1 + gen_size) + bytearray(data) + bytearray(1 + gen_size)

    identity_rows = [[1 if i == j else 0 for j in range(gen_size)] for i in range(gen_size)]
    source_data = [bytearray(random.randint(0, field.max_value) for _ in range(data_len)) for _ in range(gen_size)]
    packets = [synthetic_packet(identity_rows[i], source_data[i]) for i in range(gen_size)]

    recode_coeffs = bytearray(random.randint(1, field.max_value) for _ in range(gen_size))
    true_data = code_with_given_coefficients(source_data, recode_coeffs, field)
    broken_data = bytearray(true_data)
    broken_data[2] ^= 0x04
    packets.append(synthetic_packet(recode_coeffs, broken_data))
    print(f"  {gen_size} identity-coded trusted packets + 1 recoded 5th packet")
    print("  corrupting data column 2 of the 5th (recoded) packet:")
    _show_diff("packet[4] data", true_data, broken_data)

    localizer = _make_arc_localizer(
        field, packets, coeff_segment, data_segment, gen_size,
        coeff_trusted_idx=[0, 1, 2, 3, 4],  # coefficients are clean on every packet, including the broken one
        data_trusted_idx=[0, 1, 2, 3],
    )
    located = localizer(4)
    print(f"  -> localizer(4) = {located}  (expected [2], the true corrupted column)")

    assert located == [2]


def test_recover_coefficient_first_falls_back_when_pool_has_no_recoding_headroom_yet():
    '''ADR-0012 Option 2, full pipeline, but fed a bare gen_size generation (no
    recoded packets accumulated yet -- e.g. right at the start of reception).
    localize_errors needs gen_size TRUSTED packets as a decoding basis PLUS a
    separate broken packet to check against them (playground/arc_pl.py), so a
    pool of exactly gen_size packets never has a spare one to spend on the
    basis. _make_arc_localizer correctly detects this and falls back to None
    rather than guessing, so Option 2 still recovers correctly here via the
    same combined-search fallback Option 1 uses -- the ARC-narrowing step
    just doesn't get to run yet. See
    test_recover_coefficient_first_narrows_via_arc_once_recoded_packets_have_accumulated
    for the realistic case (a receiver almost always has more than gen_size
    packets on hand by the time recovery runs, per the real send-until-decoded
    network/sim behaviour), where narrowing does engage.'''
    _banner("recover_coefficient_first: no recoding headroom -> ARC falls back")
    random.seed(18)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    original = [bytearray(p) for p in result.packets]
    coeff_segment = next(s for s in result.segments if s.name == "coeff")
    data_segment = next(s for s in result.segments if s.name == "data-0")

    broken = [bytearray(p) for p in result.packets]
    broken[0] = error_into_packet_chosen_bit(broken[0], coeff_segment.start, chosen_bit=1)
    broken[2] = error_into_packet_chosen_bit(broken[2], coeff_segment.start + 2, chosen_bit=3)
    broken[1] = error_into_packet_chosen_bit(broken[1], data_segment.start, chosen_bit=5)
    broken[3] = error_into_packet_chosen_bit(broken[3], data_segment.start + 1, chosen_bit=6)
    print(f"  bare {GEN_SIZE}-packet pool (no recoded spares): coeff broken on [0,2], data on [1,3]")
    print("  -> no spare packet for an ARC basis; localizer returns None, combined-search fallback runs")

    report = recover_coefficient_first(FIELD, broken, result.segments, GEN_SIZE, max_combined_hd=2)
    coeff_outcome = next(o for o in report.per_segment if o.segment_name == "coeff")
    print(f"  -> ok={report.ok}, restored: {report.packets == original}, "
          f"coeff pairs_recovered={coeff_outcome.pairs_recovered}")

    assert report.ok is True
    assert report.packets == original
    assert coeff_outcome.pairs_recovered == 1


def test_recover_coefficient_first_narrows_via_arc_once_recoded_packets_have_accumulated():
    '''The realistic case: in both the real network and the sim, a generation
    is sent as recoded packets until it decodes, so a receiver normally has
    more than gen_size packets on hand by the time recovery runs. Recoding
    (recode_rlnc_without_coeffs) linearly combines whole rows, and every
    segment's tag pool is itself a self+cross-orthogonal set, so the same
    bilinear argument the module docstring makes for pairing shows a linear
    combination of the pool stays self+cross-orthogonal per segment too --
    recoded packets are exactly as decodable/localizable as originals, no
    special-casing needed. With that headroom, ARC narrowing must actually
    engage and pin each broken packet down to its true, single corrupted
    column -- not just fall back to a full-payload search.'''
    _banner("recover_coefficient_first: ARC narrowing engages with recoded spares")
    random.seed(19)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    recoded = recode_rlnc_without_coeffs(FIELD, result.packets, GEN_SIZE, count=5)
    pool = [bytearray(p) for p in result.packets] + [bytearray(p) for p in recoded]
    original = [bytearray(p) for p in pool]
    print(f"  pool = {GEN_SIZE} originals + {len(recoded)} recoded = {len(pool)} packets (realistic receiver state)")
    orth = check_orth_segmented(FIELD, pool, result.segments)
    print(f"  every segment orthogonal before corruption: {all(orth.values())}  ({orth})")
    assert all(orth.values()), (
        "recoded packets must stay orthogonal in every segment before any corruption"
    )

    coeff_segment = next(s for s in result.segments if s.name == "coeff")
    data_segment = next(s for s in result.segments if s.name == "data-0")

    broken = [bytearray(p) for p in pool]
    broken[0] = error_into_packet_chosen_bit(broken[0], coeff_segment.start, chosen_bit=1)
    broken[1] = error_into_packet_chosen_bit(broken[1], coeff_segment.start + 2, chosen_bit=3)
    broken[2] = error_into_packet_chosen_bit(broken[2], data_segment.start, chosen_bit=5)
    broken[3] = error_into_packet_chosen_bit(broken[3], data_segment.start + 1, chosen_bit=6)

    # Confirm ARC narrowing actually fires (not the no-localization fallback)
    # before checking end-to-end recovery: repair coeffs, then ask the same
    # localizer recover_coefficient_first would build for the exact columns.
    coeff_fixed_probe = [bytearray(p) for p in broken]
    coeff_fixed_probe[0][coeff_segment.start:coeff_segment.start + coeff_segment.total_length] = \
        original[0][coeff_segment.start:coeff_segment.start + coeff_segment.total_length]
    coeff_fixed_probe[1][coeff_segment.start:coeff_segment.start + coeff_segment.total_length] = \
        original[1][coeff_segment.start:coeff_segment.start + coeff_segment.total_length]
    coeff_trust = classify_segment_trust(FIELD, coeff_fixed_probe, coeff_segment)
    data_trust = classify_segment_trust(FIELD, coeff_fixed_probe, data_segment)
    localizer = _make_arc_localizer(
        FIELD, coeff_fixed_probe, coeff_segment, data_segment, GEN_SIZE, coeff_trust.trusted, data_trust.trusted,
    )
    loc2, loc3 = localizer(2), localizer(3)
    print(f"  ARC localizer(2) = {loc2} (expect [0]); localizer(3) = {loc3} (expect [1])")
    assert loc2 == [0], "ARC should pin packet 2's error to exactly its true corrupted column"
    assert loc3 == [1], "ARC should pin packet 3's error to exactly its true corrupted column"

    report = recover_coefficient_first(FIELD, broken, result.segments, GEN_SIZE, max_combined_hd=2)
    print(f"  -> ok={report.ok}, whole {len(pool)}-packet pool restored: {report.packets == original}")

    assert report.ok is True
    assert report.packets == original


# ── Per-pair search persistence (ticket 01, ADR-0012's deferred cost) ────────
#
# The cache is an exact memo of a pure function: a hit must return a result
# identical to recomputing, but WITHOUT re-spending the search's field ops. A
# CountingField makes "was it actually re-searched?" observable -- zero new muls
# on a hit, nonzero on a genuine miss.

def _failed_pair_inputs(seed):
    """A recoverable-only-at-hd>=2 pair; searched at max_combined_hd=1 it is an
    honest budget give-up (ok=False) that still spends field ops filtering
    candidates -- the exact stale-but-unchanged pair the sim re-hits every round."""
    random.seed(seed)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    segment = next(s for s in result.segments if s.name == "data-0")
    sl = lambda i: bytearray(result.packets[i][segment.start:segment.start + segment.total_length])
    broken_a = error_into_packet_chosen_bit(sl(0), 0, chosen_bit=2)
    broken_b = error_into_packet_chosen_bit(sl(1), 1, chosen_bit=6)
    trusted = [sl(2), sl(3)]
    columns = list(range(segment.payload_length))
    return broken_a, broken_b, trusted, columns


def test_pair_cache_skips_the_search_on_an_unchanged_failed_pair():
    '''Second call with the same inputs and the same cache returns the identical
    give-up result and spends ZERO additional field multiplications -- the pair
    is not re-searched.'''
    _banner("pair_cache: unchanged failed pair is not re-searched")
    broken_a, broken_b, trusted, columns = _failed_pair_inputs(20)
    cnt = CountingField(FIELD)
    cache = {}

    first = recover_pair_by_combined_search(cnt, broken_a, broken_b, trusted, columns,
                                            max_combined_hd=1, candidates_budget=10_000, pair_cache=cache)
    muls_after_first = cnt.mul_count
    print(f"  first call:  ok={first.ok}, field muls spent={muls_after_first}, cache entries={len(cache)}")
    assert first.ok is False
    assert muls_after_first > 0, "the first search must actually do field work"
    assert len(cache) == 1

    second = recover_pair_by_combined_search(cnt, broken_a, broken_b, trusted, columns,
                                             max_combined_hd=1, candidates_budget=10_000, pair_cache=cache)
    print(f"  second call: same result={second == first}, "
          f"total muls now={cnt.mul_count} (should equal {muls_after_first}, i.e. +0)")
    assert second == first
    assert cnt.mul_count == muls_after_first, "a cache hit must not re-spend any field ops"


def test_pair_cache_reuses_a_successful_repair_without_researching():
    '''A recoverable disjoint pair is searched once; the cached hit returns the
    same byte-for-byte fix with no further field ops.'''
    _banner("pair_cache: successful repair reused without re-searching")
    random.seed(21)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    segment = next(s for s in result.segments if s.name == "data-0")
    original_a = bytearray(result.packets[0][segment.start:segment.start + segment.total_length])
    original_b = bytearray(result.packets[1][segment.start:segment.start + segment.total_length])
    broken_a = error_into_packet_chosen_bit(original_a, 0, chosen_bit=2)
    broken_b = error_into_packet_chosen_bit(original_b, 1, chosen_bit=6)
    trusted = [result.packets[i][segment.start:segment.start + segment.total_length] for i in (2, 3)]
    columns = list(range(segment.payload_length))

    cnt = CountingField(FIELD)
    cache = {}
    first = recover_pair_by_combined_search(cnt, broken_a, broken_b, trusted, columns,
                                            max_combined_hd=2, pair_cache=cache)
    muls_after_first = cnt.mul_count
    print(f"  first call:  ok={first.ok}, exact fix={first.fixed_a == original_a and first.fixed_b == original_b}, "
          f"muls spent={muls_after_first}")
    assert first.ok and first.fixed_a == original_a and first.fixed_b == original_b

    second = recover_pair_by_combined_search(cnt, broken_a, broken_b, trusted, columns,
                                             max_combined_hd=2, pair_cache=cache)
    print(f"  second call: same result={second == first}, total muls now={cnt.mul_count} (should be +0)")
    assert second == first
    assert cnt.mul_count == muls_after_first, "a cache hit must not re-spend any field ops"


def test_pair_cache_miss_when_the_trusted_set_changes():
    '''Changing the trusted set changes the key -- the pair is genuinely
    re-searched (new field ops, a second cache entry), never a stale hit.'''
    _banner("pair_cache: changed trusted set forces a fresh search")
    broken_a, broken_b, trusted, columns = _failed_pair_inputs(22)
    cnt = CountingField(FIELD)
    cache = {}

    recover_pair_by_combined_search(cnt, broken_a, broken_b, trusted, columns,
                                    max_combined_hd=1, pair_cache=cache)
    muls_after_first = cnt.mul_count
    print(f"  first call (2 trusted rows): muls spent={muls_after_first}, cache entries={len(cache)}")

    recover_pair_by_combined_search(cnt, broken_a, broken_b, trusted[:1], columns,
                                    max_combined_hd=1, pair_cache=cache)
    print(f"  second call (1 trusted row): total muls now={cnt.mul_count} (> {muls_after_first}), "
          f"cache entries={len(cache)} (a new key)")
    assert cnt.mul_count > muls_after_first, "a changed trusted set must force a fresh search"
    assert len(cache) == 2


def test_pair_cache_does_not_change_recovery_output():
    '''End-to-end: recover_uniform_hd with a cache produces exactly the same
    repaired packets and per-segment outcome as without one -- the cache is a
    pure speed-up, never a behaviour change.'''
    _banner("pair_cache: cache never changes recovery output (pure speed-up)")
    random.seed(23)
    result = _build_tagged_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS)
    segment = next(s for s in result.segments if s.name == "data-1")

    def broken_pool():
        pool = [bytearray(p) for p in result.packets]
        pool[0] = error_into_packet_chosen_bit(pool[0], segment.start, chosen_bit=2)
        pool[2] = error_into_packet_chosen_bit(pool[2], segment.start + 1, chosen_bit=5)
        return pool

    uncached = recover_uniform_hd(FIELD, broken_pool(), result.segments, max_combined_hd=2)
    cached = recover_uniform_hd(FIELD, broken_pool(), result.segments, max_combined_hd=2, pair_cache={})
    print(f"  ok:          uncached={uncached.ok}, cached={cached.ok}  (match: {uncached.ok == cached.ok})")
    print(f"  packets:     identical={cached.packets == uncached.packets}")
    print(f"  per_segment: identical={cached.per_segment == uncached.per_segment}")

    assert cached.ok == uncached.ok
    assert cached.packets == uncached.packets
    assert cached.per_segment == uncached.per_segment


if __name__ == "__main__":
    tests = [
        test_classify_segment_trust_marks_only_the_corrupted_packet_broken,
        test_plan_pairing_pairs_fifo_and_leaves_odd_one_out,
        test_recover_pair_by_combined_search_fixes_two_disjoint_single_bit_errors,
        test_recover_pair_by_combined_search_gives_up_within_budget_not_forever,
        test_recover_uniform_hd_repairs_two_broken_packets_in_a_data_segment,
        test_recover_uniform_hd_repairs_coefficient_segment_corruption,
        test_recover_uniform_hd_single_broken_packet_uses_unpaired_fallback,
        test_recover_coefficient_first_recovers_overlapping_errors_via_ic_refinement,
        test_ic_refinement_uniform_hd_overlap_fails_honestly_without_arc,
        test_arc_localizer_narrows_to_the_true_corrupted_column_given_a_full_rank_basis,
        test_recover_coefficient_first_falls_back_when_pool_has_no_recoding_headroom_yet,
        test_recover_coefficient_first_narrows_via_arc_once_recoded_packets_have_accumulated,
        test_pair_cache_skips_the_search_on_an_unchanged_failed_pair,
        test_pair_cache_reuses_a_successful_repair_without_researching,
        test_pair_cache_miss_when_the_trusted_set_changes,
        test_pair_cache_does_not_change_recovery_output,
    ]
    for test in tests:
        test()
        print(f"{test.__name__} passed")
    print("All segmented recovery tests passed!")
