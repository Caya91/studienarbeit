"""Tests for the ADR-0015 end-to-end throughput pieces: integrity_schemes.SegmentedCrcScheme
(CRC-32 ARQ / CRC-32 + ACR), segmented_crc.recover_acr_only_crc, run_recovery_trial's `trace`,
and the pareto_sweep CRC arms + schema v4 -- plus "default paths unchanged" guards.

No pytest -- same PASS/FAIL harness as segmented_crc_test.py.

Run (PowerShell):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" simulation/e2e_throughput_test.py
"""
import os
import random
import sys
from dataclasses import asdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

from icecream import ic

from binary_ext_fields.custom_field import CountingField, create_field
from binary_ext_fields.generate_symbols import recode_rlnc_without_coeffs
from binary_ext_fields.segmented_tagging import layout_segments
from simulation.integrity_schemes import (
    AdmitConfig, SegmentedCrcScheme, SegmentedMacScheme, SegmentedScheme, _strip_to_code,
)
from simulation.scheme_comparison_sim import run_recovery_trial
from simulation.segmented_crc import (
    Crc32Instrument, crc_verify_segment, layout_crc_segments, recover_acr_only_crc, segment_slice,
    tag_packets_crc,
)

ic.disable()  # playground/arc_pl.py debug prints

FIELD = create_field(8)
G, DF, N = 4, 100, 3          # 50 B data segments (ADR-0014/0015 layout)
CFG = AdmitConfig(hamming_distance=2, pair_budget=20000, repair_span="payload", min_pool_size=4)


def _crc(repair, df=DF, n=N):
    return SegmentedCrcScheme(num_data_segments=n - 1, data_fields=df, repair=repair, name=f"crc_{repair}")


def _wire_pool(scheme, count, seed):
    """`count` clean coded wire packets of one fresh generation (+ the instrument + source suffix)."""
    random.seed(seed)
    source, suffix = scheme.make_source(FIELD, scheme.data_fields, G)
    inst = scheme.new_instrument(FIELD)
    pool = [scheme.attach(inst, bytearray(recode_rlnc_without_coeffs(FIELD, source, G, count=1)))
            for _ in range(count)]
    return pool, inst, suffix


def _flip_data_bit(scheme, packet, seg_idx=1, col=7, bit=3):
    seg = scheme.wire_segments(G)[seg_idx]
    assert seg.kind == "data"
    packet[seg.start + col] ^= 1 << bit


# ══ SegmentedCrcScheme: layout + framing ══════════════════════════════════════

def test_wire_layout_is_adr0014_layout_and_frame_matches_tag_packets_crc():
    scheme = _crc("none")
    ref = layout_segments(G, DF, N - 1)
    assert scheme.wire_segments(G) == layout_crc_segments(ref)
    pool, inst, _ = _wire_pool(scheme, 3, seed=1)
    assert all(len(p) == 116 for p in pool)          # 8 + 2 x 54 (ADR-0015 wire bytes)
    assert inst.sender.crc_ops == 3 * (G + DF)        # source CRCs every coded packet once
    # same bytes as ADR-0014's tag_packets_crc on the [coeff | data] columns
    codes = [_strip_to_code(p, scheme.wire_segments(G)) for p in pool]
    plain_ref = [type(s)(s.name, s.kind, s.start, s.payload_length) for s in scheme._plain_segments(G)]
    assert tag_packets_crc(Crc32Instrument(), codes, plain_ref, scheme.wire_segments(G)) == pool
    assert scheme.tag_overhead_bits(G, 8) == 32 * N


def test_error_positions_are_data_payload_bytes_of_the_wire_layout():
    scheme = _crc("none", df=300, n=7)
    pos = scheme.error_positions(G, "data_payload")
    assert len(pos) == 300
    segs = scheme.wire_segments(G)
    for p in pos:
        seg = next(s for s in segs if s.start <= p < s.start + s.total_length)
        assert seg.kind == "data" and p < seg.start + seg.payload_length   # never a CRC / coeff byte


# ══ CRC-32 ARQ ════════════════════════════════════════════════════════════════

def test_arq_admit_drops_every_corrupted_packet_and_checks_each_arrival_once():
    scheme = _crc("none")
    pool, inst, _ = _wire_pool(scheme, 8, seed=2)
    segs = scheme.wire_segments(G)
    clean_codes = [_strip_to_code(p, segs) for p in pool]
    for i in (1, 4, 5):
        _flip_data_bit(scheme, pool[i], seg_idx=1 + i % 2, col=i, bit=i % 8)
    accepted = scheme.admit(inst, pool[:6], G, CFG)
    assert accepted == [clean_codes[i] for i in (0, 2, 3)]
    before = inst.crc.crc_ops
    accepted = scheme.admit(inst, pool, G, CFG)          # 2 new arrivals: only they are checked
    assert accepted == [clean_codes[i] for i in (0, 2, 3, 6, 7)]
    assert inst.crc.crc_ops - before == 2 * (G + DF)     # two clean packets, every segment once
    assert inst.verdict == [True, False, True, True, False, False, True, True]


def test_arq_end_to_end_pays_one_transmission_per_corrupted_packet():
    # detect-drop-resend: every corrupted arrival is wasted, nothing is repaired or wrongly admitted
    for seed in range(6):
        random.seed(50 + seed)
        tr = {}
        r = run_recovery_trial(FIELD, _crc("none"), DF, G, 2e-3, CFG, max_packets_factor=30,
                               error_scope="data_payload", trace=tr)
        assert r.correct and not r.silent_decode
        assert tr["repaired_used"] == 0 and tr["wrong_used"] == 0
        assert tr["n_accepted_final"] == r.packets_to_decode - tr["n_corrupted_rx"]
        assert tr["n_accepted_final"] >= G
        assert r.pairs_recovered == r.unpaired_recovered == 0 and r.scheme_ops == 0


# ══ CRC-32 + ACR (S-PRAC-like) ════════════════════════════════════════════════

def test_recover_acr_only_crc_repairs_a_single_bit_error_with_a_sniffed_basis():
    scheme = _crc("acr", df=300, n=7)
    pool, _, _ = _wire_pool(scheme, 7, seed=3)
    segs = scheme.wire_segments(G)
    clean = [bytearray(p) for p in pool]
    _flip_data_bit(scheme, pool[5], seg_idx=3, col=11, bit=6)
    inst, field = Crc32Instrument(), CountingField(FIELD)
    rep = recover_acr_only_crc(field, inst, pool, segs, G, max_combined_hd=2, candidates_budget=20000)
    assert rep.ok and rep.packets == clean
    assert sum(o.unpaired_recovered for o in rep.per_segment) == 1
    assert field.mul_count > 0                            # ACR localization ran (field ops)
    assert pool[5] != clean[5]                            # input pool untouched (works on a copy)


def test_recover_acr_only_crc_waits_without_a_basis():
    # fewer than gen_size CRC-clean packets in the segment -> nothing localizable -> untouched
    scheme = _crc("acr")
    pool, _, _ = _wire_pool(scheme, 5, seed=4)
    for i in range(4):
        _flip_data_bit(scheme, pool[i], seg_idx=1, col=3 + i, bit=1)
    rep = recover_acr_only_crc(CountingField(FIELD), Crc32Instrument(), pool, scheme.wire_segments(G), G,
                               candidates_budget=20000)
    assert rep.packets == pool and not rep.ok
    assert sum(o.dropped for o in rep.per_segment) == 4


def test_crc_acr_end_to_end_repairs_packets_into_the_basis_without_silent_decodes():
    used = 0
    for seed in range(6):
        random.seed(80 + seed)
        tr = {}
        r = run_recovery_trial(FIELD, _crc("acr", df=300, n=7), 300, G, 1e-3, CFG, max_packets_factor=16,
                               error_scope="data_payload", trace=tr)
        assert not r.silent_decode and tr["wrong_used"] == 0
        assert r.correct
        used += tr["repaired_used"]
    assert used > 0, "CRC + ACR never put a repaired packet into a decode basis"


def test_repair_pair_cache_returns_identical_outcomes():
    scheme = _crc("acr", df=300, n=7)
    pool, _, _ = _wire_pool(scheme, 9, seed=5)
    for i, (seg, col) in enumerate(((2, 4), (2, 9), (4, 1), (4, 30))):   # two broken PAIRS, no unpaired
        _flip_data_bit(scheme, pool[5 + i], seg_idx=seg, col=col, bit=2 + i)
    segs = scheme.wire_segments(G)
    a = recover_acr_only_crc(CountingField(FIELD), Crc32Instrument(), pool, segs, G, candidates_budget=20000)
    cache = {}
    b = recover_acr_only_crc(CountingField(FIELD), Crc32Instrument(), pool, segs, G, candidates_budget=20000,
                             pair_cache=cache)
    inst_c = Crc32Instrument()
    c = recover_acr_only_crc(CountingField(FIELD), inst_c, pool, segs, G, candidates_budget=20000,
                             pair_cache=cache)
    assert a.packets == b.packets == c.packets and a.per_segment == b.per_segment == c.per_segment
    assert cache and inst_c.correction_trials == 0       # 2nd call: pair search served from the cache


# ══ run_recovery_trial trace: bookkeeping only ════════════════════════════════

def _comparable(res):
    d = asdict(res)
    for k in ("wall_time_s", "time_per_packet_s"):
        d.pop(k)
    return d


def test_trace_does_not_change_the_trial():
    schemes = (SegmentedScheme(N - 1, DF, "acr_only", "kl"), SegmentedMacScheme(N - 1, DF, "acr_only", "kd"),
               _crc("none"), _crc("acr"))
    for scheme in schemes:
        for seed in (1, 2):
            random.seed(seed)
            plain = run_recovery_trial(FIELD, scheme, DF, G, 2e-3, CFG, max_packets_factor=16,
                                       error_scope="data_payload")
            random.seed(seed)
            tr = {}
            traced = run_recovery_trial(FIELD, scheme, DF, G, 2e-3, CFG, max_packets_factor=16,
                                        error_scope="data_payload", trace=tr)
            assert _comparable(plain) == _comparable(traced), f"{scheme.name} seed {seed}: trace changed the trial"
            assert set(tr) == {"n_corrupted_rx", "n_accepted_final", "repaired_used", "wrong_used", "op_counts"}


def test_trace_counts_keyless_repairs():
    used = 0
    for seed in range(5):
        random.seed(200 + seed)
        tr = {}
        r = run_recovery_trial(FIELD, SegmentedScheme(6, 300, "acr_only", "kl"), 300, G, 1e-3, CFG,
                               max_packets_factor=16, error_scope="data_payload", trace=tr)
        assert tr["wrong_used"] == 0 and (r.correct or not r.decoded)
        used += tr["repaired_used"]
    assert used > 0


# ══ pareto_sweep: CRC arms + schema v4, defaults unchanged ════════════════════

def test_pareto_layout_wire_symbols():
    from scripts.pareto_sweep import _layout
    expect = {("keyless", 100, 3): 119, ("keyed", 100, 3): 116, ("crc_arq", 100, 3): 116, ("crc_acr", 100, 3): 116,
              ("keyless", 1000, 21): 1109, ("keyed", 1000, 21): 1088, ("crc_arq", 1000, 21): 1088}
    for (arm, df, n), wire in expect.items():
        assert _layout(arm, n, df, G, FIELD) == (wire, 50, 50), (arm, df, n)


def test_pareto_run_task_rows_for_every_arm():
    from scripts.pareto_sweep import ARMS, RAW_FIELDS, SCHEMA_VERSION, Cell, Task, _layout, _seed, run_task
    assert SCHEMA_VERSION == 4 and ARMS == ("keyless", "keyed", "crc_arq", "crc_acr")
    cfg = dict(hamming_distance=2, pair_budget=20000, repair_span="payload", acr_bitflip_only=True, min_pool_size=4)
    for arm in ARMS:
        cell = Cell(arm, DF, N, 1e-3)
        w, lo, hi = _layout(arm, N, DF, G, FIELD)
        task = Task(cell, 0, _seed(cell, 0, G, 8), G, 8, cfg, 16, None, w, lo, hi,
                    strategy="acr_only", error_scope="data_payload")
        row = run_task(task)
        assert list(row) == RAW_FIELDS or set(row) == set(RAW_FIELDS), f"{arm}: row keys drift"
        assert row["schema_version"] == 4 and row["arm"] == arm
        assert row["wire_bits_sent"] == row["packets_to_decode"] * w * 8
        assert (row["crc_bytes"] > 0) == arm.startswith("crc")
        # the old columns of a row are exactly what a direct run_recovery_trial gives (default path)
        random.seed(task.seed)
        import numpy as np
        np.random.seed(task.seed % 2**32)
        from scripts.pareto_sweep import make_scheme
        direct = run_recovery_trial(FIELD, make_scheme(arm, N, DF, "acr_only"), DF, G, 1e-3, AdmitConfig(**cfg),
                                    max_packets_factor=16, error_scope="data_payload")
        for k in ("status", "packets_to_decode", "scheme_ops", "decode_ops", "pairs_recovered", "unpaired_recovered"):
            assert row[k] == getattr(direct, k), f"{arm}: {k} {row[k]} != {getattr(direct, k)}"


def test_crc_scheme_rejects_unknown_repair():
    try:
        SegmentedCrcScheme(2, DF, "blind", "x")
    except AssertionError:
        return
    raise AssertionError("unknown repair mode accepted")


# ══ 2026-10-17: tag-only channel scope, HD knob, final_check off ══════════════

def _all_arms(df=DF, n=N):
    return (SegmentedScheme(n - 1, df, "acr_only", "kl"), SegmentedMacScheme(n - 1, df, "acr_only", "kd"),
            _crc("none", df, n), _crc("acr", df, n))


def _redundancy_bytes(scheme, gen_size=G):
    """(data-seg redundancy positions, every other position) of the wire layout, from the layout itself."""
    if isinstance(scheme, SegmentedCrcScheme):
        segs = scheme.wire_segments(gen_size)
    elif isinstance(scheme, SegmentedMacScheme):
        from binary_ext_fields.segmented_mac_tagging import layout_mac_segments
        segs = layout_mac_segments(gen_size, scheme.data_fields, scheme.num_data_segments, scheme._num_keys(gen_size))
    else:
        segs = layout_segments(gen_size, scheme.data_fields, scheme.num_data_segments)
    red = {s.start + b for s in segs if s.kind == "data" for b in range(s.payload_length, s.total_length)}
    return red, segs


def test_tags_only_positions_are_the_redundancy_complement_of_data_payload():
    # data_segment == data_payload (disjoint union) data_tags_only, and tags-only = exactly the data segments'
    # salt/tag (keyless), MAC (keyed) or CRC bytes -- the isolated harness's data_tags_only byte set (ADR-0014)
    for df, n, per_seg in ((100, 3, (5, 4, 4, 4)), (1000, 21, (5, 4, 4, 4))):
        for scheme, red_len in zip(_all_arms(df, n), per_seg):
            tags = scheme.error_positions(G, "data_tags_only")
            pay = scheme.error_positions(G, "data_payload")
            seg = scheme.error_positions(G, "data_segment")
            assert not set(tags) & set(pay) and sorted(tags + pay) == sorted(seg), scheme.name
            red, _ = _redundancy_bytes(scheme)
            assert set(tags) == red and len(tags) == red_len * (n - 1), (scheme.name, len(tags))


def test_tags_only_flips_never_touch_coefficients_or_payload():
    from simulation.scheme_comparison_sim import _pollute_positions
    for scheme in _all_arms():
        pool, inst, _ = _wire_pool(scheme, 3, seed=7)
        red, _ = _redundancy_bytes(scheme)
        pos = scheme.error_positions(G, "data_tags_only")
        random.seed(3)
        for wire in pool:
            hit = _pollute_positions(FIELD, wire, 0.5, pos)
            diff = {i for i, (a, b) in enumerate(zip(wire, hit)) if a != b}
            assert diff and diff <= red, scheme.name


def test_tags_only_errors_repaired_with_segment_span_dropped_with_payload_span():
    # payload clean -> every admitted packet carries the right information; a tag error is repaired only
    # when the search may flip tag bytes (repair_span="segment"); with "payload" it cannot be repaired
    for scheme in _all_arms()[0], _all_arms()[1], _all_arms()[3]:
        used = {"segment": 0, "payload": 0}
        for span in used:
            cfg = AdmitConfig(hamming_distance=2, pair_budget=20000, repair_span=span, min_pool_size=4)
            for seed in range(4):
                random.seed(300 + seed)
                tr = {}
                r = run_recovery_trial(FIELD, scheme, DF, G, 2e-2, cfg, max_packets_factor=16,
                                       error_scope="data_tags_only", trace=tr)
                assert not r.silent_decode and tr["wrong_used"] == 0, (scheme.name, span, seed)
                used[span] += tr["repaired_used"]
        assert used["segment"] > 0 and used["payload"] == 0, (scheme.name, used)


def test_final_check_off_changes_no_outcome_only_ops():
    for scope in ("data_payload", "data_tags_only", "data_segment"):
        for scheme in _all_arms()[:2]:
            for seed in (11, 12):
                res = {}
                for fc in (True, False):
                    random.seed(seed)
                    tr = {}
                    cfg = AdmitConfig(hamming_distance=3, pair_budget=20000, repair_span="segment", min_pool_size=4,
                                      final_check=fc)
                    r = run_recovery_trial(FIELD, scheme, DF, G, 3e-3, cfg, max_packets_factor=16,
                                           error_scope=scope, trace=tr)
                    res[fc] = (r, tr)
                (a, ta), (b, tb) = res[True], res[False]
                for k in ("status", "packets_to_decode", "decode_ops", "pairs_recovered", "unpaired_recovered"):
                    assert getattr(a, k) == getattr(b, k), (scheme.name, scope, seed, k)
                for k in ("n_corrupted_rx", "n_accepted_final", "repaired_used", "wrong_used"):
                    assert ta[k] == tb[k], (scheme.name, scope, seed, k)
                assert b.scheme_ops <= a.scheme_ops


def test_pareto_hd_knob_and_final_check_reach_config_and_rows():
    import csv
    import json
    import shutil
    import tempfile
    from scripts.pareto_sweep import HAMMING_DISTANCE, main
    assert HAMMING_DISTANCE == 2                         # default depth unchanged
    tmp = Path(tempfile.mkdtemp())
    try:
        main(["--stage", "smoke", "--arm", "keyless", "--configs", "100:3", "--bers", "1e-3", "--trials", "1",
              "--workers", "1", "--gen-size", "4", "--strategy", "acr_only", "--error-scope", "data_tags_only",
              "--repair-span", "segment", "--min-pool-size", "4", "--pair-budget", "20000",
              "--max-packets-factor", "16", "--hamming-distance", "4", "--no-final-check",
              "--resume", str(tmp / "r")])
        conf = json.loads((tmp / "r" / "run_config.json").read_text())
        assert conf["admit_config"]["hamming_distance"] == 4 and conf["admit_config"]["final_check"] is False
        assert conf["error_scope"] == "data_tags_only"
        rows = list(csv.DictReader((tmp / "r" / "raw_trials.csv").open()))
        assert len(rows) == 1 and rows[0]["hamming_distance"] == "4" and rows[0]["error_scope"] == "data_tags_only"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ══ harness ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"e2e_throughput_test  ({len(tests)} cases)")
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
