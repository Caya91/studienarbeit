"""Test bench for simulation/segmented_crc.py and the CRC-32 arms of the isolated harness
(ADR-0014).

No pytest dependency -- same built-in PASS/FAIL harness as crc_recovery_test.py.

Run (PowerShell):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; .\\.venv\\Scripts\\python.exe simulation\\segmented_crc_test.py
"""
import os
import random
import sys
import zlib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

from icecream import ic

from binary_ext_fields.custom_field import CountingField, create_field
from binary_ext_fields.segmented_recovery import SegmentTrust
from binary_ext_fields.segmented_tagging import layout_segments
from simulation.isolated_recovery_sim import (
    ARMS, CRC_ARMS, CSV_COLUMNS, build_paired_pools, info_columns, inject_paired,
    assert_identical_info_corruption, result_rows, run_config,
)
from simulation.segmented_crc import (
    CRC_BYTES, Crc32Instrument, check_crc_segmented, crc_tag_overhead_bytes, crc_verify_combined,
    crc_verify_segment, layout_crc_segments, zero_crc,
    recover_arc_only_crc, repair_segment_crc, segment_slice, tag_packets_crc,
)

ic.disable()  # playground/arc_pl.py debug prints

G = 4                    # gen_size: 4 tag bytes/segment keyless = one CRC-32 (ADR-0014)
DATA_FIELDS, NUM_DATA_SEGMENTS, T = 40, 4, 6


def _pools(seed=3, T_=T):
    return build_paired_pools(CountingField(create_field(8)), G, DATA_FIELDS, NUM_DATA_SEGMENTS, T_, seed)


def _flip(packet, seg, col, bit):
    packet[seg.start + col] ^= 1 << bit


# ══ CRC primitive + layout ════════════════════════════════════════════════════

def test_zlib_crc32_is_affine_over_gf2():
    # standard CRC-32: crc(a ^ b) == crc(a) ^ crc(b) ^ crc(0^n) -- what makes the combined filter sound
    rng = random.Random(1)
    for n in (1, 7, 40):
        a = bytes(rng.randrange(256) for _ in range(n))
        b = bytes(rng.randrange(256) for _ in range(n))
        assert zlib.crc32(bytes(x ^ y for x, y in zip(a, b))) == zlib.crc32(a) ^ zlib.crc32(b) ^ zero_crc(n)
    assert zlib.crc32(b"123456789") == 0xCBF43926   # IEEE CRC-32 check value


def test_combined_filter_passes_two_valid_slices_and_rejects_one_bad():
    pools = _pools()
    seg = pools.crc_segments[2]
    a, b = (segment_slice(pools.crc_clean[t], seg) for t in pools.target_idx[:2])
    inst = Crc32Instrument()
    assert crc_verify_combined(inst, bytearray(x ^ y for x, y in zip(a, b)), seg)
    a[3] ^= 0x10
    assert not crc_verify_combined(inst, bytearray(x ^ y for x, y in zip(a, b)), seg)


def test_layout_mirrors_keyless_payloads_with_one_crc_per_segment():
    kl = layout_segments(G, DATA_FIELDS, NUM_DATA_SEGMENTS)
    cs = layout_crc_segments(kl)
    assert [(s.name, s.kind, s.payload_length) for s in cs] == [(s.name, s.kind, s.payload_length) for s in kl]
    assert cs[0].start == 0
    for prev, nxt in zip(cs, cs[1:]):
        assert nxt.start == prev.start + prev.payload_length + CRC_BYTES
    # tag-byte parity (ADR-0014 point 2): keyless gen_size tag bytes (salt not counted) == CRC-32 bytes
    for k, c in zip(kl, cs):
        keyless_tag_bytes = k.total_length - k.payload_length - 1   # minus the salt byte
        assert keyless_tag_bytes == c.total_length - c.payload_length == 4
    assert crc_tag_overhead_bytes(cs) == 4 * len(kl)


def test_clean_pool_passes_and_carries_identical_info_columns():
    pools = _pools()
    inst = Crc32Instrument()
    assert all(check_crc_segmented(inst, pools.crc_clean, pools.crc_segments).values())
    for i in range(len(pools.kl_clean)):
        assert info_columns(pools.crc_clean[i], pools.crc_segments) == info_columns(pools.kl_clean[i], pools.kl_segments)


def test_single_bit_flip_is_detected():
    pools = _pools()
    seg = pools.crc_segments[1]
    s = segment_slice(pools.crc_clean[pools.target_idx[0]], seg)
    for col in range(seg.payload_length):
        for bit in range(8):
            bad = bytearray(s)
            bad[col] ^= 1 << bit
            assert not crc_verify_segment(Crc32Instrument(), bad, seg)


# ══ Repair ════════════════════════════════════════════════════════════════════

def _repair(pools, corrupt, localization, budget=None, hd=2):
    trust = {}
    for seg in pools.crc_segments:
        broken = [t for t in pools.target_idx if segment_slice(corrupt[t], seg) != segment_slice(pools.crc_clean[t], seg)]
        trust[seg.name] = SegmentTrust(seg.name, broken=broken,
                                       trusted=[i for i in range(len(corrupt)) if i not in set(broken)])
    return recover_arc_only_crc(pools.field, Crc32Instrument(), corrupt, pools.crc_segments, G,
                                basis_idx=pools.helper_idx, coeff_clean_target_idx=pools.target_idx,
                                localization=localization, max_combined_hd=hd, candidates_budget=budget,
                                injected_trust_by_segment=trust)


def test_unpaired_single_error_recovered_both_localizations():
    pools = _pools()
    seg = pools.crc_segments[2]
    for loc in ("acr", "blind"):
        corrupt = [bytearray(p) for p in pools.crc_clean]
        _flip(corrupt[pools.target_idx[0]], seg, 5, 3)
        rep = _repair(pools, corrupt, loc)
        assert rep.ok, loc
        assert rep.packets == pools.crc_clean, f"{loc}: repaired pool != clean"


def test_pair_disjoint_and_same_position_errors_recovered():
    pools = _pools()
    seg = pools.crc_segments[1]
    t0, t1 = pools.target_idx[:2]
    for loc in ("acr", "blind"):
        for (c0, b0), (c1, b1) in (((2, 1), (7, 6)),     # disjoint -> combined search
                                   ((4, 2), (4, 2))):    # same bit -> cancels in Sc -> IC-refinement
            corrupt = [bytearray(p) for p in pools.crc_clean]
            _flip(corrupt[t0], seg, c0, b0)
            _flip(corrupt[t1], seg, c1, b1)
            rep = _repair(pools, corrupt, loc)
            assert rep.packets == pools.crc_clean, f"{loc} {(c0, b0)}/{(c1, b1)} not recovered"
            assert rep.per_segment[0].pairs_recovered == 1


def test_blind_searches_more_than_acr():
    pools = _pools()
    seg = pools.crc_segments[1]
    corrupt = [bytearray(p) for p in pools.crc_clean]
    _flip(corrupt[pools.target_idx[0]], seg, seg.payload_length - 1, 7)   # last bit of the payload
    tried = {}
    for loc in ("acr", "blind"):
        inst = Crc32Instrument()
        trust = SegmentTrust(seg.name, broken=[pools.target_idx[0]],
                             trusted=[i for i in range(len(corrupt)) if i != pools.target_idx[0]])
        tmp = [bytearray(p) for p in corrupt]
        localizer = (lambda i: [seg.payload_length - 1]) if loc == "acr" else (lambda i: list(range(seg.payload_length)))
        repair_segment_crc(inst, tmp, seg, localizer, max_combined_hd=2, injected_trust=trust)
        assert tmp == pools.crc_clean
        tried[loc] = inst.correction_trials
    assert tried["acr"] < tried["blind"], tried


def test_budget_exhaustion_is_an_honest_failure():
    pools = _pools()
    seg = pools.crc_segments[1]
    corrupt = [bytearray(p) for p in pools.crc_clean]
    _flip(corrupt[pools.target_idx[0]], seg, seg.payload_length - 1, 7)
    rep = _repair(pools, corrupt, "blind", budget=5)
    assert rep.packets[pools.target_idx[0]] == corrupt[pools.target_idx[0]], "budget-out must leave the packet untouched"
    assert rep.per_segment[0].unpaired_failed == 1


# ══ Harness wiring ═══════════════════════════════════════════════════════════

def test_injection_identical_across_all_three_pools():
    pools = _pools(seed=5)
    for model in ("data_only", "whole_packet", "info_only", "data_segment"):
        inj = inject_paired(pools, 0.01, model, seed=11)
        assert inj.crc is not None
        assert_identical_info_corruption(pools, inj)   # asserts keyless == keyed == CRC info columns
        if model in ("data_only", "info_only"):        # no redundancy flips -> CRC bytes untouched
            for t in pools.target_idx:
                for seg in pools.crc_segments:
                    a, b = segment_slice(inj.crc[t], seg), segment_slice(pools.crc_clean[t], seg)
                    assert a[seg.payload_length:] == b[seg.payload_length:]


def test_crc_arms_do_not_perturb_keyless_keyed():
    # adding the CRC arms must leave the keyless/keyed outcomes AND op counts unchanged
    pools = _pools(seed=9)
    base = run_config(pools, "arc_only_a", 0.008, 2, 9)
    full = run_config(pools, "arc_only_a", 0.008, 2, 9, arms=ARMS)
    for a, b in ((base.keyless, full.keyless), (base.keyed, full.keyed)):
        assert a.outcomes == b.outcomes and a.ops == b.ops
    assert set(full.crc) == set(CRC_ARMS)


def test_crc_only_run_and_rows():
    pools = _pools(seed=4)
    res = run_config(pools, "arc_only_a", 0.006, None, 4, arms=CRC_ARMS)
    assert res.keyless is None and res.keyed is None
    rows = result_rows(pools, res, W=None, ber=0.006, seed=4, repair_span="payload", data_fields=DATA_FIELDS,
                       num_data_segments=NUM_DATA_SEGMENTS, max_combined_hd=2, candidates_budget=20000)
    assert [r["arm"] for r in rows] == list(CRC_ARMS)
    for r in rows:
        assert set(r) == set(CSV_COLUMNS) and r["W"] == -1 and r["h2h_both"] == -1
        assert len(r["target_outcomes"]) == len(pools.target_idx)
        assert r["recovery_crc_bytes"] > 0 or r["n_arm_corrupted"] == 0
    assert rows[1]["recovery_ops"] == 0, "blind CRC does no field ops (no ACR)"


def test_crc_arms_refuse_coefficient_first():
    pools = _pools()
    try:
        run_config(pools, "coefficient_first", 0.006, None, 1, arms=("crc_acr",))
    except AssertionError as e:
        assert "ARC-only" in str(e)
    else:
        raise AssertionError("coefficient_first must be refused for CRC arms")


def test_low_ber_data_only_crc_arms_recover_everything_without_silent():
    # light corruption, both localizations, no budget: every target recovered, 0 silent
    for seed in range(4):
        pools = _pools(seed=seed)
        res = run_config(pools, "arc_only_a", 0.003, None, seed, arms=CRC_ARMS, candidates_budget=None)
        for arm, ar in res.crc.items():
            assert ar.silent == 0, f"seed {seed} {arm}: silent decode"


# ══ harness ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"segmented_crc_test  ({len(tests)} cases)")
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"{'ALL PASS' if not failed else f'{failed} FAILED'}")
    sys.exit(1 if failed else 0)
