"""
Tests for the segmented homomorphic-MAC benchmark arm
(binary_ext_fields/segmented_mac_tagging.py + segmented_mac_recovery.py).

Meant to be read, not just run. The anchor test reproduces Fathi & Pahlevani's
hand-worked Combined Recovery example (teach_me lesson 0002) number for number
over toy GF(2^4) -- keys, T1/T2, Sc, Tc, Sc_corrected, cross-reconstructed
S1'/S2', refined IC, and the final recovered segments. The rest exercise the
homomorphic property (tag survives recoding), Case-1 recovery through the
production pipeline, the honest Case-2 failure this pass deliberately does not
fix (IC-refinement deferred), and that coefficient_first's ARC narrowing engages.
"""
import random

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import (
    generate_identity_coefficients,
    recode_rlnc_without_coeffs,
)
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.segmented_mac_tagging import (
    layout_mac_segments,
    generate_keyset,
    mac_tag_vector,
    tag_generation_mac,
    mac_verify_segment,
    check_mac_segmented,
)
from binary_ext_fields.segmented_mac_recovery import (
    classify_segment_trust_mac,
    recover_pair_by_combined_search_mac,
    recover_uniform_hd_mac,
    recover_coefficient_first_mac,
    _make_arc_localizer_mac,
    segment_slice,
)
from playground.arc_pl import error_into_packet_chosen_bit


def _hex(buf):
    return " ".join(f"{b:02x}" for b in buf)


def _banner(name):
    print(f"\n=== {name} ===")


# Shared config: 4 packets, 3 data-segments of 4 bytes each, V = gen_size tag symbols.
FIELD = create_field(8)
GEN_SIZE = 4
DATA_FIELDS = 12
NUM_DATA_SEGMENTS = 3
NUM_KEYS = GEN_SIZE


def _build_mac_pool(field, gen_size, data_fields, num_data_segments, num_keys, seed):
    """A MAC-tagged generation + its keyset + segment layout, all aligned."""
    rng = random.Random(seed)
    data_rows = [bytearray(rng.randint(0, field.max_value) for _ in range(data_fields))
                 for _ in range(gen_size)]
    plain = generate_identity_coefficients(field, data_rows)
    segments = layout_mac_segments(gen_size, data_fields, num_data_segments, num_keys)
    keyset = generate_keyset(field, segments, rng)
    packets = tag_generation_mac(field, plain, gen_size, num_data_segments, keyset, num_keys)
    return packets, keyset, segments, data_rows


# ── (a) The correctness anchor: the paper's worked example, number for number ──

def test_worked_example_reproduces_every_number_over_gf16():
    '''Fathi & Pahlevani Combined Recovery, toy GF(2^4), lesson 0002. Every value
    below is asserted against the lesson's hand-worked result. The MAC tag itself
    comes from the production primitive mac_tag_vector; the combine / value-search
    Correct / cross-reconstruct / refine / single-position-swap steps are mirrored
    inline here (the production pipeline uses a bit-flip combined search instead,
    and defers the swap-refine -- this test anchors the underlying arithmetic).'''
    _banner("worked example over GF(2^4): reproduce every number")
    field = create_field(4)
    keys = [bytearray([3, 5, 9, 6]), bytearray([2, 0xb, 4, 7])]
    S1_true = bytearray([7, 2, 0xc, 1])
    S2_true = bytearray([0xa, 4, 6, 0xd])

    T1 = mac_tag_vector(field, keys, S1_true)
    T2 = mac_tag_vector(field, keys, S2_true)
    print(f"  T1={[hex(x) for x in T1]} (expect 3,9)   T2={[hex(x) for x in T2]} (expect 1,3)")
    assert T1 == [3, 9]
    assert T2 == [1, 3]

    S1_recv = bytearray([7, 9, 0xc, 1])   # index 1 flipped 2->9
    S2_recv = bytearray([0xa, 4, 6, 0xb]) # index 3 flipped d->b
    IC = [1, 3]

    Sc = bytearray(a ^ b for a, b in zip(S1_recv, S2_recv))
    Tc = [a ^ b for a, b in zip(T1, T2)]
    print(f"  Sc={[hex(x) for x in Sc]} (expect d,d,a,a)   Tc={[hex(x) for x in Tc]} (expect 2,a)")
    assert list(Sc) == [0xd, 0xd, 0xa, 0xa]
    assert Tc == [2, 0xa]

    # Correct(Sc, Tc, IC): brute force field VALUES over IC only -- the paper's
    # (2^q)^|IC| = 16^2 search (this IS the expensive step, done once per pair).
    matches = []
    for x in range(16):
        for y in range(16):
            cand = bytearray(Sc)
            cand[IC[0]], cand[IC[1]] = x, y
            if mac_tag_vector(field, keys, cand) == Tc:
                matches.append(cand)
    print(f"  Correct() matches: {[[hex(z) for z in m] for m in matches]} (expect exactly one: d,6,a,c)")
    assert len(matches) == 1
    Sc_corr = matches[0]
    assert list(Sc_corr) == [0xd, 6, 0xa, 0xc]

    # Cross-reconstruct: pair the corrected combined segment with the OTHER received.
    S1p = bytearray(a ^ b for a, b in zip(S2_recv, Sc_corr))
    S2p = bytearray(a ^ b for a, b in zip(S1_recv, Sc_corr))
    print(f"  S1'={[hex(x) for x in S1p]} (expect 7,2,c,7)   S2'={[hex(x) for x in S2p]} (expect a,f,6,d)")
    assert list(S1p) == [7, 2, 0xc, 7]
    assert list(S2p) == [0xa, 0xf, 6, 0xd]

    # Refine IC: Case 1 (separate locations) -> IC' == IC (unchanged).
    IC_refined = sorted({i for i in range(4) if S1p[i] != S1_recv[i]}
                        | {i for i in range(4) if S2p[i] != S2_recv[i]})
    print(f"  IC_refined={IC_refined} (expect {IC}, unchanged -> Case 1)")
    assert IC_refined == IC

    # Recover each with a cheap single-position swap from its own received value.
    def swap_recover(candidate, recv, tag):
        for pos in IC_refined:
            trial = bytearray(candidate)
            trial[pos] = recv[pos]
            if mac_tag_vector(field, keys, trial) == tag:
                return trial
        return None

    S1_final = swap_recover(S1p, S1_recv, T1)
    S2_final = bytearray(a ^ b for a, b in zip(S1_final, Sc_corr))
    print(f"  S1_final={[hex(x) for x in S1_final]} (expect S1_true)   "
          f"S2_final={[hex(x) for x in S2_final]} (expect S2_true)")
    assert S1_final == S1_true
    assert S2_final == S2_true


# ── (b) Homomorphic property + survival under RLNC recoding ───────────────────

def test_mac_is_homomorphic_and_survives_recoding():
    '''T(A XOR B) == T(A) XOR T(B) per segment, and -- the property the whole
    benchmark relies on -- every segment's tag still verifies after the generation
    is RLNC-recoded WITHOUT the key.'''
    _banner("MAC is homomorphic and survives recoding")
    field = create_field(8)
    rng = random.Random(42)
    keys = [bytearray(rng.randint(0, field.max_value) for _ in range(6)) for _ in range(3)]
    A = bytearray(rng.randint(0, field.max_value) for _ in range(6))
    B = bytearray(rng.randint(0, field.max_value) for _ in range(6))
    lhs = mac_tag_vector(field, keys, bytearray(a ^ b for a, b in zip(A, B)))
    rhs = [ta ^ tb for ta, tb in zip(mac_tag_vector(field, keys, A), mac_tag_vector(field, keys, B))]
    print(f"  T(A^B)={lhs}  ==  T(A)^T(B)={rhs}: {lhs == rhs}")
    assert lhs == rhs

    packets, keyset, segments, _ = _build_mac_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, NUM_KEYS, seed=7)
    assert all(check_mac_segmented(FIELD, keyset, packets, segments).values()), "clean pool must verify"
    recoded = recode_rlnc_without_coeffs(FIELD, packets, GEN_SIZE, count=5)
    pool = packets + [bytearray(p) for p in recoded]
    verified = check_mac_segmented(FIELD, keyset, pool, segments)
    print(f"  every segment verifies on originals + 5 recoded packets: {all(verified.values())} ({verified})")
    assert all(verified.values()), "recoded packets' tags must still verify per segment (homomorphic)"


# ── (c) Case 1 recovers; Case 2 fails honestly and is counted ─────────────────

def test_classify_segment_trust_mac_marks_only_the_corrupted_packet():
    _banner("classify_segment_trust_mac: one corrupt packet, rest trusted")
    packets, keyset, segments, _ = _build_mac_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, NUM_KEYS, seed=8)
    segment = next(s for s in segments if s.name == "data-1")
    keys = keyset[segments.index(segment)]
    broken = [bytearray(p) for p in packets]
    broken[2] = error_into_packet_chosen_bit(broken[2], segment.start, chosen_bit=1)
    trust = classify_segment_trust_mac(FIELD, keys, broken, segment)
    print(f"  broken={trust.broken}, trusted={trust.trusted}")
    assert trust.broken == [2]
    assert trust.trusted == [0, 1, 3]


def test_recover_pair_by_combined_search_mac_fixes_two_disjoint_errors():
    '''The core mechanism directly: two packets broken at different columns of the
    same segment, each one flipped bit. The combined search recovers BOTH exactly.'''
    _banner("recover_pair_by_combined_search_mac: two disjoint single-bit errors")
    packets, keyset, segments, _ = _build_mac_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, NUM_KEYS, seed=9)
    segment = next(s for s in segments if s.name == "data-0")
    keys = keyset[segments.index(segment)]
    original_a = segment_slice(packets[0], segment)
    original_b = segment_slice(packets[1], segment)
    broken_a = error_into_packet_chosen_bit(original_a, 0, chosen_bit=2)
    broken_b = error_into_packet_chosen_bit(original_b, 1, chosen_bit=6)
    columns = list(range(segment.payload_length))
    out = recover_pair_by_combined_search_mac(FIELD, keys, broken_a, broken_b, columns, segment, max_combined_hd=2)
    print(f"  ok={out.ok}, a exact={out.fixed_a == original_a}, b exact={out.fixed_b == original_b}")
    assert out.ok
    assert out.fixed_a == original_a
    assert out.fixed_b == original_b


def test_recover_uniform_hd_mac_repairs_a_data_segment():
    '''Full pipeline (Option 1): two disjoint errors in one data segment, both back
    byte-for-byte, whole pool verifies afterwards.'''
    _banner("recover_uniform_hd_mac: full pipeline repairs a data segment")
    packets, keyset, segments, _ = _build_mac_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, NUM_KEYS, seed=13)
    original = [bytearray(p) for p in packets]
    segment = next(s for s in segments if s.name == "data-1")
    broken = [bytearray(p) for p in packets]
    broken[0] = error_into_packet_chosen_bit(broken[0], segment.start, chosen_bit=2)
    broken[2] = error_into_packet_chosen_bit(broken[2], segment.start + 1, chosen_bit=5)
    report = recover_uniform_hd_mac(FIELD, keyset, broken, segments, max_combined_hd=2)
    outcome = next(o for o in report.per_segment if o.segment_name == "data-1")
    print(f"  ok={report.ok}, restored={report.packets == original}, "
          f"pairs_recovered={outcome.pairs_recovered}, pairs_failed={outcome.pairs_failed}")
    assert report.ok
    assert report.packets == original
    assert outcome.pairs_recovered == 1
    assert outcome.pairs_failed == 0


def test_recover_uniform_hd_mac_repairs_the_coefficient_segment():
    '''The coeff-segment is repaired exactly like any data segment (the gap ADR-0012
    closes), via the same MAC pairing/combined search.'''
    _banner("recover_uniform_hd_mac: repairs the coefficient segment")
    packets, keyset, segments, _ = _build_mac_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, NUM_KEYS, seed=14)
    original = [bytearray(p) for p in packets]
    segment = next(s for s in segments if s.kind == "coeff")
    broken = [bytearray(p) for p in packets]
    broken[1] = error_into_packet_chosen_bit(broken[1], segment.start, chosen_bit=1)
    broken[3] = error_into_packet_chosen_bit(broken[3], segment.start + 2, chosen_bit=4)
    report = recover_uniform_hd_mac(FIELD, keyset, broken, segments, max_combined_hd=2)
    print(f"  ok={report.ok}, coeff restored={report.packets == original}")
    assert report.ok
    assert report.packets == original


def test_recover_uniform_hd_mac_single_broken_packet_uses_unpaired_fallback():
    '''One broken packet, no partner -> unpaired bit-flip fallback recovers it.'''
    _banner("recover_uniform_hd_mac: lone broken packet uses unpaired fallback")
    packets, keyset, segments, _ = _build_mac_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, NUM_KEYS, seed=15)
    original = [bytearray(p) for p in packets]
    segment = next(s for s in segments if s.name == "data-2")
    broken = [bytearray(p) for p in packets]
    broken[0] = error_into_packet_chosen_bit(broken[0], segment.start, chosen_bit=3)
    report = recover_uniform_hd_mac(FIELD, keyset, broken, segments, max_combined_hd=2)
    outcome = next(o for o in report.per_segment if o.segment_name == segment.name)
    print(f"  ok={report.ok}, restored={report.packets == original}, "
          f"unpaired_recovered={outcome.unpaired_recovered}")
    assert report.ok
    assert report.packets == original
    assert outcome.unpaired_recovered == 1


def test_recover_uniform_hd_mac_cannot_split_overlapping_errors():
    '''The deferred limitation (IC-refinement Case 2): two packets flipped at the
    SAME column+bit cancel in the XOR-combine, so no split recovers them. This must
    FAIL honestly -- counted as a failed pair, ok=False -- not silently guess.'''
    _banner("recover_uniform_hd_mac: overlapping errors fail honestly (deferred Case 2)")
    packets, keyset, segments, _ = _build_mac_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, NUM_KEYS, seed=16)
    segment = next(s for s in segments if s.name == "data-1")
    broken = [bytearray(p) for p in packets]
    broken[0] = error_into_packet_chosen_bit(broken[0], segment.start, chosen_bit=2)
    broken[2] = error_into_packet_chosen_bit(broken[2], segment.start, chosen_bit=2)  # identical col+bit
    report = recover_uniform_hd_mac(FIELD, keyset, broken, segments, max_combined_hd=2)
    outcome = next(o for o in report.per_segment if o.segment_name == "data-1")
    print(f"  ok={report.ok} (expect False), pairs_failed={outcome.pairs_failed}, "
          f"pairs_recovered={outcome.pairs_recovered}")
    assert report.ok is False
    assert outcome.pairs_failed == 1
    assert outcome.pairs_recovered == 0


# ── (d) coefficient_first ARC narrowing engages ───────────────────────────────

def test_coefficient_first_mac_narrows_candidate_columns_via_arc():
    '''With recoded spares in the pool (the realistic receiver state), Option 2's
    ARC localizer narrows each broken data packet to its true single corrupted
    column -- strictly fewer candidate columns than Option 1's whole-payload
    search -- and the full pipeline recovers the whole pool.'''
    _banner("recover_coefficient_first_mac: ARC narrowing engages with recoded spares")
    packets, keyset, segments, _ = _build_mac_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, NUM_KEYS, seed=19)
    recoded = recode_rlnc_without_coeffs(FIELD, packets, GEN_SIZE, count=5)
    pool = [bytearray(p) for p in packets] + [bytearray(p) for p in recoded]
    original = [bytearray(p) for p in pool]

    coeff_segment = next(s for s in segments if s.name == "coeff")
    data_segment = next(s for s in segments if s.name == "data-0")

    broken = [bytearray(p) for p in pool]
    broken[0] = error_into_packet_chosen_bit(broken[0], coeff_segment.start, chosen_bit=1)
    broken[1] = error_into_packet_chosen_bit(broken[1], coeff_segment.start + 2, chosen_bit=3)
    broken[2] = error_into_packet_chosen_bit(broken[2], data_segment.start, chosen_bit=5)
    broken[3] = error_into_packet_chosen_bit(broken[3], data_segment.start + 1, chosen_bit=6)

    # Probe: repair the two coeff errors by hand, then confirm the localizer the
    # pipeline would build pins each broken data packet to its true column.
    probe = [bytearray(p) for p in broken]
    for i in (0, 1):
        probe[i][coeff_segment.start:coeff_segment.start + coeff_segment.total_length] = \
            original[i][coeff_segment.start:coeff_segment.start + coeff_segment.total_length]
    coeff_trust = classify_segment_trust_mac(FIELD, keyset[segments.index(coeff_segment)], probe, coeff_segment)
    data_trust = classify_segment_trust_mac(FIELD, keyset[segments.index(data_segment)], probe, data_segment)
    localizer = _make_arc_localizer_mac(FIELD, probe, coeff_segment, data_segment, GEN_SIZE,
                                        coeff_trust.trusted, data_trust.trusted)
    loc2, loc3 = localizer(2), localizer(3)
    print(f"  ARC localizer(2)={loc2} (expect [0]), localizer(3)={loc3} (expect [1]); "
          f"vs uniform_hd whole payload = {list(range(data_segment.payload_length))}")
    assert loc2 == [0]
    assert loc3 == [1]
    assert len(loc2) < data_segment.payload_length  # strictly narrower than the uniform_hd search

    report = recover_coefficient_first_mac(FIELD, keyset, broken, segments, GEN_SIZE, max_combined_hd=2)
    print(f"  ok={report.ok}, whole {len(pool)}-packet pool restored={report.packets == original}")
    assert report.ok
    assert report.packets == original


# ── per-pair cache is a pure speed-up ─────────────────────────────────────────

def test_pair_cache_mac_skips_the_search_on_an_unchanged_pair():
    _banner("pair_cache (MAC): unchanged recovered pair not re-searched")
    packets, keyset, segments, _ = _build_mac_pool(FIELD, GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, NUM_KEYS, seed=21)
    segment = next(s for s in segments if s.name == "data-0")
    keys = keyset[segments.index(segment)]
    original_a = segment_slice(packets[0], segment)
    original_b = segment_slice(packets[1], segment)
    broken_a = error_into_packet_chosen_bit(original_a, 0, chosen_bit=2)
    broken_b = error_into_packet_chosen_bit(original_b, 1, chosen_bit=6)
    columns = list(range(segment.payload_length))

    cnt = CountingField(FIELD)
    cache = {}
    first = recover_pair_by_combined_search_mac(cnt, keys, broken_a, broken_b, columns, segment,
                                                max_combined_hd=2, pair_cache=cache)
    muls_after_first = cnt.mul_count
    assert first.ok and first.fixed_a == original_a and first.fixed_b == original_b
    assert muls_after_first > 0
    second = recover_pair_by_combined_search_mac(cnt, keys, broken_a, broken_b, columns, segment,
                                                 max_combined_hd=2, pair_cache=cache)
    print(f"  first muls={muls_after_first}, after cache hit={cnt.mul_count} (expect equal), same={second == first}")
    assert second == first
    assert cnt.mul_count == muls_after_first, "a cache hit must not re-spend field ops"


if __name__ == "__main__":
    tests = [
        test_worked_example_reproduces_every_number_over_gf16,
        test_mac_is_homomorphic_and_survives_recoding,
        test_classify_segment_trust_mac_marks_only_the_corrupted_packet,
        test_recover_pair_by_combined_search_mac_fixes_two_disjoint_errors,
        test_recover_uniform_hd_mac_repairs_a_data_segment,
        test_recover_uniform_hd_mac_repairs_the_coefficient_segment,
        test_recover_uniform_hd_mac_single_broken_packet_uses_unpaired_fallback,
        test_recover_uniform_hd_mac_cannot_split_overlapping_errors,
        test_coefficient_first_mac_narrows_candidate_columns_via_arc,
        test_pair_cache_mac_skips_the_search_on_an_unchanged_pair,
    ]
    for test in tests:
        test()
        print(f"{test.__name__} passed")
    print("\nAll segmented MAC recovery tests passed!")
