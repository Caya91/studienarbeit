"""
Tests for the production ACR-only strategy (2026-09-29) and the restricted channel-error
scopes that go with it. ACR = algebraic consistency check (the step the code calls "ARC").

Meant to be read, not just run:
  - WAIT, don't search blind: with only gen_size packets in the pool, a broken data
    segment cannot be ACR-localized (ACR needs gen_size trusted rows PLUS the broken one),
    so recover_acr_only leaves the packet untouched (counted in `dropped`, still in the
    pool) instead of running a blind whole-segment search; one more clean arrival makes
    it localizable and it is repaired byte-for-byte -- in each arm;
  - no coeff repair: a coefficient flip is never touched;
  - N = 2 structural fact: with ONE data segment, "gen_size packets trusted in that
    segment" (what ACR needs) already means gen_size decodable packets, so end-to-end
    ACR-only never repairs anything at N = 2 -- the scheme admit short-circuits first;
  - error scopes: data_payload hits only data-segment payload bytes, data_segment also
    their salt/tag bytes, never the coeff segment.

Judge pass/fail by exit code (0 = pass).
"""
import random

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import generate_identity_coefficients, recode_rlnc_without_coeffs
from binary_ext_fields.segmented_tagging import tag_generation_segmented
from binary_ext_fields.segmented_recovery import recover_acr_only, segment_slice
from binary_ext_fields.segmented_mac_tagging import layout_mac_segments, generate_keyset, tag_generation_mac
from binary_ext_fields.segmented_mac_recovery import recover_acr_only_mac

FIELD = create_field(8)
GEN_SIZE = 4
DATA_FIELDS = 24
NUM_DATA_SEGMENTS = 2


def _plain(seed):
    rng = random.Random(seed)
    rows = [bytearray(rng.randint(0, FIELD.max_value) for _ in range(DATA_FIELDS)) for _ in range(GEN_SIZE)]
    return generate_identity_coefficients(FIELD, rows)


def _keyless(seed, extra):
    random.seed(seed)
    res = tag_generation_segmented(FIELD, _plain(seed), GEN_SIZE, NUM_DATA_SEGMENTS)
    assert res.ok
    rec = recode_rlnc_without_coeffs(FIELD, res.packets, GEN_SIZE, count=extra)
    return [bytearray(p) for p in res.packets] + [bytearray(p) for p in rec], res.segments


def _keyed(seed, extra):
    segs = layout_mac_segments(GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, GEN_SIZE)
    keyset = generate_keyset(FIELD, segs, random.Random(seed))
    pk = tag_generation_mac(FIELD, _plain(seed), GEN_SIZE, NUM_DATA_SEGMENTS, keyset, GEN_SIZE)
    random.seed(seed)
    rec = recode_rlnc_without_coeffs(FIELD, pk, GEN_SIZE, count=extra)
    return [bytearray(p) for p in pk] + [bytearray(p) for p in rec], segs, keyset


def _flip(packet, seg, col, bit):
    packet[seg.start + col] ^= (1 << bit)


def _check_wait_then_repair(run, pool, segs):
    data0 = next(s for s in segs if s.kind == "data")
    clean = [bytearray(p) for p in pool]
    broken = [bytearray(p) for p in pool]
    _flip(broken[1], data0, 3, 5)                                # one payload bit, packet 1, data segment 0
    # pool = gen_size packets, one broken in data0 -> only gen_size-1 trusted there: cannot localize
    rep = run(broken[:GEN_SIZE])
    assert rep.packets[1] == broken[1], "unlocalizable packet must be left untouched (no blind search)"
    assert sum(o.dropped for o in rep.per_segment) == 1 and sum(o.unpaired_recovered for o in rep.per_segment) == 0
    # one more clean arrival -> gen_size trusted in data0 + the broken one -> ACR localizes, repair
    rep = run(broken[:GEN_SIZE + 1])
    assert rep.packets[1] == clean[1], "ACR-localized packet must be repaired back to the original"
    assert sum(o.unpaired_recovered for o in rep.per_segment) == 1


def test_keyless_waits_then_repairs():
    pool, segs = _keyless(3, extra=2)
    _check_wait_then_repair(lambda p: recover_acr_only(CountingField(FIELD), p, segs, GEN_SIZE, max_combined_hd=2),
                            pool, segs)
    print("  keyless: unlocalizable -> untouched (no blind search); +1 packet -> repaired")


def test_keyed_waits_then_repairs():
    pool, segs, keyset = _keyed(3, extra=2)
    _check_wait_then_repair(lambda p: recover_acr_only_mac(CountingField(FIELD), keyset, p, segs, GEN_SIZE,
                                                           max_combined_hd=2), pool, segs)
    print("  keyed:   unlocalizable -> untouched (no blind search); +1 packet -> repaired")


def test_repair_method_switch():
    """Default bit-flip (HD 2) cannot undo a 3-bit error in ONE byte; the switchable ADR-0002 exact
    solve (bitflip_only=False) solves that byte value directly -- same ACR column, other method."""
    pool, segs = _keyless(7, extra=2)
    data0 = next(s for s in segs if s.kind == "data")
    clean = [bytearray(p) for p in pool]
    broken = [bytearray(p) for p in pool]
    for bit in (0, 3, 6):
        _flip(broken[GEN_SIZE], data0, 5, bit)
    flip = recover_acr_only(CountingField(FIELD), broken, segs, GEN_SIZE, max_combined_hd=2)
    exact = recover_acr_only(CountingField(FIELD), broken, segs, GEN_SIZE, max_combined_hd=2, bitflip_only=False)
    assert flip.packets[GEN_SIZE] == broken[GEN_SIZE], "bit-flip HD 2 must fail on a 3-bit byte error"
    assert exact.packets[GEN_SIZE] == clean[GEN_SIZE], "exact solve must recover the byte"
    from simulation.integrity_schemes import AdmitConfig
    assert AdmitConfig().acr_bitflip_only is True, "bit-flip is the default repair"
    print("  repair switch: default bit-flip fails a 3-bit byte error, exact solve (switch) recovers it")


def test_coeff_segment_never_repaired():
    pool, segs = _keyless(5, extra=3)
    coeff = next(s for s in segs if s.kind == "coeff")
    broken = [bytearray(p) for p in pool]
    _flip(broken[GEN_SIZE], coeff, 1, 2)
    rep = recover_acr_only(CountingField(FIELD), broken, segs, GEN_SIZE, max_combined_hd=2)
    assert segment_slice(rep.packets[GEN_SIZE], coeff) == segment_slice(broken[GEN_SIZE], coeff)
    assert rep.ok is False
    print("  coeff flip left as is (ACR-only never repairs coefficients)")


def test_n2_end_to_end_never_repairs():
    """N=2: the admit short-circuits (>= gen_size already good) before ACR could ever run."""
    import numpy as np
    from simulation.integrity_schemes import AdmitConfig, SegmentedScheme
    from simulation.scheme_comparison_sim import run_recovery_trial
    for seed in range(4):
        random.seed(seed)
        np.random.seed(seed)
        sch = SegmentedScheme(num_data_segments=1, data_fields=60, strategy="acr_only", name="n2")
        r = run_recovery_trial(FIELD, sch, 60, 6, 4e-3, AdmitConfig(hamming_distance=2, min_pool_size=6),
                               max_packets_factor=8, error_scope="data_payload")
        assert r.pairs_recovered == r.unpaired_recovered == r.pairs_failed == r.unpaired_failed == 0, r
    print("  N=2: no repair ever attempted end-to-end (decode needs exactly what ACR needs)")


def test_error_scopes():
    from simulation.integrity_schemes import SegmentedScheme, SegmentedMacScheme
    from simulation.scheme_comparison_sim import _pollute_positions
    for cls in (SegmentedScheme, SegmentedMacScheme):
        sch = cls(num_data_segments=NUM_DATA_SEGMENTS, data_fields=DATA_FIELDS, strategy="acr_only", name="s")
        pay = set(sch.error_positions(GEN_SIZE, "data_payload"))
        seg = set(sch.error_positions(GEN_SIZE, "data_segment"))
        assert len(pay) == DATA_FIELDS and pay < seg
        from binary_ext_fields.segmented_tagging import layout_segments
        segs = (layout_segments(GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS) if cls is SegmentedScheme
                else layout_mac_segments(GEN_SIZE, DATA_FIELDS, NUM_DATA_SEGMENTS, GEN_SIZE))
        coeff = next(s for s in segs if s.kind == "coeff")
        assert not (seg & set(range(coeff.start, coeff.start + coeff.total_length))), "coeff segment must never be hit"
        wire = bytearray(sum(s.total_length for s in segs))
        hit = _pollute_positions(FIELD, wire, 1.0, sorted(pay))     # BER 1 -> every allowed bit flips
        assert {i for i, b in enumerate(hit) if b} == pay and all(b == 0xFF for i, b in enumerate(hit) if i in pay)
    print("  scopes: data_payload = data payload bytes only; data_segment adds data salt/tags; coeff never hit")


if __name__ == "__main__":
    from icecream import ic
    ic.disable()
    test_keyless_waits_then_repairs()
    test_keyed_waits_then_repairs()
    test_repair_method_switch()
    test_coeff_segment_never_repaired()
    test_n2_end_to_end_never_repairs()
    test_error_scopes()
    print("\nAll ACR-only production tests passed!")
