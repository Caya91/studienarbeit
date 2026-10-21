"""Tests for simulation/two_hop_sim.py (ADR-0015 task 2).

Covers: the GF / channel helpers, IncrementalSegmentTrust == classify_segment_trust, the CRC blind
relay giving a corrupted input a fresh valid CRC (passes at the sink -> silent decode), the CRC verify
relay dropping it, a keyless recoded mixture of a corrupted input failing the sink check (no silent
decode), keyed blind / verify, clean-channel timing, pairing across schemes, sweep resume.

No pytest -- same PASS/FAIL harness as segmented_crc_test.py.

Run (PowerShell):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" simulation/two_hop_test.py
"""
import csv
import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

from icecream import ic

from binary_ext_fields.custom_field import CountingField, create_field
from binary_ext_fields.generate_symbols import recode_rlnc_without_coeffs
from binary_ext_fields.segmented_recovery import classify_segment_trust, segment_slice
from binary_ext_fields.segmented_tagging import layout_segments
from simulation.integrity_schemes import SegmentedScheme, _strip_to_code
from simulation.two_hop_sim import (
    POLICIES, SCHEMES, IncrementalSegmentTrust, combine, make_sink_scheme, pollute, run_sweep,
    run_two_hop_trial, wire_segments_for,
)

ic.disable()  # playground/arc_pl.py debug prints

FIELD = create_field(8)
G, DF, N = 4, 100, 3


def _corrupt_tick(tick_to_hit, byte_offset=13, bit=2, extra=None):
    """hop1_hook planting ONE data-payload error into the packet the source sends at `tick_to_hit`
    (positions = the scheme's data-payload bytes, so the same logical byte in every layout).
    `extra` = a second (byte_offset, bit) in the same packet."""
    def make(scheme):
        sink = make_sink_scheme(scheme, N, DF)
        positions = sink.error_positions(G, "data_payload")

        def hook(tick, wire):
            if tick == tick_to_hit:
                wire = bytearray(wire)
                wire[positions[byte_offset]] ^= 1 << bit
                if extra is not None:
                    wire[positions[extra[0]]] ^= 1 << extra[1]
            return wire
        return hook
    return make


# ══ helpers ═══════════════════════════════════════════════════════════════════

def test_combine_matches_the_field_recode():
    rng = random.Random(1)
    packets = [bytearray(rng.randrange(256) for _ in range(30)) for _ in range(5)]
    coeffs = [rng.randrange(256) for _ in range(5)] + []
    coeffs[2] = 0
    ref = bytearray(30)
    for c, p in zip(coeffs, packets):
        ref = FIELD.vector_multiply_add_into(ref, p, c)
    assert combine(FIELD, packets, coeffs) == ref


def test_pollute_only_touches_positions_and_matches_ber():
    pkt = bytearray(200)
    positions = list(range(50, 150))
    assert pollute(pkt, 0.0, positions, random.Random(3)) == pkt
    a = pollute(pkt, 0.05, positions, random.Random(3))
    assert a == pollute(pkt, 0.05, positions, random.Random(3))           # reproducible
    assert all(a[i] == 0 for i in range(200) if i not in positions)
    flips = 0
    for s in range(200):
        flips += sum(bin(b).count("1") for b in pollute(pkt, 0.05, positions, random.Random(s)))
    mean = flips / 200
    assert 36 < mean < 44, f"mean flips {mean} vs 800 bits x 0.05 = 40"


def test_incremental_trust_equals_classify_segment_trust():
    for seed in range(8):
        random.seed(seed)
        scheme = SegmentedScheme(6, 300, "acr_only", "kl")
        source, _ = scheme.make_source(FIELD, 300, G)
        segs = layout_segments(G, 300, 6)
        rng = random.Random(seed)
        for vc in (4, None, 1):
            inc = [IncrementalSegmentTrust(CountingField(FIELD), s, vc) for s in segs]
            pool = []
            for k in range(14):
                p = bytearray(recode_rlnc_without_coeffs(FIELD, source, G, count=1))
                kind = rng.random()
                seg = segs[rng.randrange(1, len(segs))]
                if kind < 0.25:      # single bit -> self-check catches it
                    p[seg.start + rng.randrange(seg.payload_length)] ^= 1 << rng.randrange(8)
                elif kind < 0.45:    # two flips, same bit lane -> passes the self-check, cross-check needed
                    c1, c2 = rng.sample(range(seg.payload_length), 2)
                    b = rng.randrange(8)
                    p[seg.start + c1] ^= 1 << b
                    p[seg.start + c2] ^= 1 << b
                pool.append(p)
                for t in inc:
                    t.add(p)
                for s, t in zip(segs, inc):
                    assert t.classify() == classify_segment_trust(FIELD, pool, s, verify_count=vc), \
                        f"seed {seed} vc {vc} k {k} segment {s.name}"


def test_incremental_trust_charges_fewer_field_ops():
    random.seed(4)
    scheme = SegmentedScheme(2, DF, "acr_only", "kl")
    source, _ = scheme.make_source(FIELD, DF, G)
    seg = layout_segments(G, DF, 2)[1]
    inc_field, full_field = CountingField(FIELD), CountingField(FIELD)
    inc = IncrementalSegmentTrust(inc_field, seg, 4)
    pool = []
    for _ in range(12):
        p = bytearray(recode_rlnc_without_coeffs(FIELD, source, G, count=1))
        pool.append(p)
        inc.add(p)
        inc.classify()
        classify_segment_trust(full_field, pool, seg, verify_count=4)
    L = seg.total_length
    assert inc_field.mul_count == L * (12 + 12 * 11 // 2)     # each self-check + each pair once
    assert full_field.mul_count > 3 * inc_field.mul_count


# ══ the three required propagation tests ══════════════════════════════════════

def test_crc_blind_relay_gives_a_corrupted_input_a_valid_crc_and_the_sink_decodes_wrong():
    hook = _corrupt_tick(1)("crc")
    r = run_two_hop_trial(FIELD, "crc", "blind", DF, N, 0.0, 0.0, trial_idx=0, hop1_hook=hook)
    assert r.relay_corrupted_rx == 1 and r.relay_dropped == 0 and r.relay_polluted_inputs == 1
    assert r.hop2_polluted_emitted >= r.hop2_packets - 1          # every mixture carries it (coeff 0: 1/256)
    assert r.status == "silent_decode" and r.silent_decode and r.sink_wrong_used >= 1
    # direct check: a blind CRC relay's output passes every CRC at the sink though its data is wrong
    from simulation.two_hop_sim import CrcRelay
    sink = make_sink_scheme("crc", N, DF)
    random.seed(9)
    source, data = sink.make_source(FIELD, DF, G)
    inst = sink.new_instrument(FIELD)
    relay = CrcRelay(FIELD, "blind", random.Random(1), sink, G)
    for k in range(3):
        wire = sink.attach(inst, bytearray(recode_rlnc_without_coeffs(FIELD, source, G, count=1)))
        if k == 0:
            wire[sink.error_positions(G, "data_payload")[5]] ^= 0x04
        relay.receive(wire, k == 0)
    out, code = relay.emit()
    assert sink.packet_ok(inst.crc, out, sink.wire_segments(G)), "blind relay output must carry valid CRCs"
    assert bytes(code[G:]) != bytes(combine(FIELD, data, code[:G])), "...while its data is polluted"


def test_crc_verify_relay_drops_the_corrupted_input():
    hook = _corrupt_tick(1)("crc")
    r = run_two_hop_trial(FIELD, "crc", "verify", DF, N, 0.0, 0.0, trial_idx=0, hop1_hook=hook)
    assert r.relay_dropped == 1 and r.relay_polluted_inputs == 0 and r.hop2_polluted_emitted == 0
    assert r.status == "decoded" and r.relay_verify_crc_bytes > 0 and r.relay_retag_crc_bytes > 0


def test_keyless_recoded_mixture_of_a_corrupted_input_fails_the_sink_check():
    # unit level: relay mixes 3 packets, one with a data error -> the sink's production trust
    # classification marks the mixture broken in that segment (tags are linear, data is not clean)
    random.seed(11)
    scheme = SegmentedScheme(N - 1, DF, "acr_only", "kl")
    source, data = scheme.make_source(FIELD, DF, G)
    segs = layout_segments(G, DF, N - 1)
    rng = random.Random(5)
    for trial in range(20):
        buf = [bytearray(recode_rlnc_without_coeffs(FIELD, source, G, count=1)) for _ in range(3)]
        seg = segs[1 + trial % 2]
        buf[0][seg.start + rng.randrange(seg.payload_length)] ^= 1 << rng.randrange(8)
        mix = combine(FIELD, buf, [rng.randrange(1, 256) for _ in buf])     # nonzero -> polluted
        code = _strip_to_code(mix, segs)
        assert bytes(code[G:]) != bytes(combine(FIELD, data, code[:G]))
        clean = [bytearray(recode_rlnc_without_coeffs(FIELD, source, G, count=1)) for _ in range(5)]
        trust = classify_segment_trust(FIELD, clean + [mix], seg, verify_count=4)
        assert 5 in trust.broken or 5 not in trust.trusted, f"trial {trial}: polluted mixture trusted"
    # end to end: blind keyless relay -> detected at the sink, never a silent decode
    for tick in (1, 2):
        hook = _corrupt_tick(tick)("keyless")
        r = run_two_hop_trial(FIELD, "keyless", "blind", DF, N, 0.0, 0.0, trial_idx=0, hop1_hook=hook)
        assert r.relay_polluted_inputs == 1 and r.hop2_polluted_emitted >= 1
        assert not r.silent_decode and r.sink_wrong_used == 0, r


def test_keyless_blind_polluted_mixtures_stall_the_sink():
    # one corrupted input in the relay buffer before the sink holds 4 good packets: every later
    # mixture is polluted (multi-bit after scaling) -> nothing decodable within the cap
    stalls = 0
    for t in range(4):
        hook = _corrupt_tick(1, byte_offset=20 + t, bit=t)("keyless")
        r = run_two_hop_trial(FIELD, "keyless", "blind", DF, N, 0.0, 0.0, trial_idx=t, max_ticks=24,
                              hop1_hook=hook)
        assert not r.silent_decode
        stalls += r.status == "timeout"
    assert stalls >= 3, f"only {stalls}/4 stalled"


def test_keyless_verify_relay_never_mixes_a_self_check_detectable_error():
    hook = _corrupt_tick(2)("keyless")            # single bit flip -> the relay's self-check catches it
    r = run_two_hop_trial(FIELD, "keyless", "verify", DF, N, 0.0, 0.0, trial_idx=0, hop1_hook=hook)
    assert r.relay_polluted_inputs == 0 and r.hop2_polluted_emitted == 0
    assert r.status == "decoded" and r.relay_check_mul > 0 and r.relay_dropped == 1


def test_keyed_blind_detects_and_keyed_verify_drops():
    hook = _corrupt_tick(1)("keyed")
    r = run_two_hop_trial(FIELD, "keyed", "blind", DF, N, 0.0, 0.0, trial_idx=0, hop1_hook=hook)
    assert r.relay_polluted_inputs == 1 and not r.silent_decode and r.sink_wrong_used == 0
    r = run_two_hop_trial(FIELD, "keyed", "verify", DF, N, 0.0, 0.0, trial_idx=0, hop1_hook=hook)
    assert r.relay_dropped == 1 and r.status == "decoded" and r.relay_check_mul > 0


# ══ timing, pairing, driver ═══════════════════════════════════════════════════

def test_clean_channel_every_scheme_and_policy_decodes_after_threshold_plus_gen_size():
    for s in SCHEMES:
        for p in POLICIES:
            r = run_two_hop_trial(FIELD, s, p, DF, N, 0.0, 0.0, trial_idx=3)
            assert r.status == "decoded", (s, p, r.status)
            assert r.first_emit_tick == 3 and r.ticks == r.hop2_packets + 2 and r.hop2_packets >= G
            assert r.relay_corrupted_rx == r.sink_corrupted_rx == 0


def test_trials_are_paired_across_schemes_and_policies():
    # same trial -> the relay receives the same [coeff | data] (incl. the same hop-1 bit flips) in
    # every scheme x policy: dedicated RNG streams + the same data-payload bit order in every layout
    seen = {}
    for s in SCHEMES:
        segs = wire_segments_for(s, make_sink_scheme(s, N, DF), G, DF, N)
        for p in POLICIES:
            got = []
            run_two_hop_trial(FIELD, s, p, DF, N, 3e-3, 3e-3, trial_idx=5, max_ticks=12,
                              hop1_hook=lambda tick, w, got=got, segs=segs: got.append(bytes(_strip_to_code(w, segs))) or w)
            seen[(s, p)] = got
    shortest = min(len(v) for v in seen.values())
    assert shortest >= 4
    ref = seen[("crc", "verify")][:shortest]
    assert any(ref) and all(v[:shortest] == ref for v in seen.values()), "hop-1 stream not paired"


def test_skipping_the_unused_final_check_changes_no_outcome():
    from dataclasses import replace
    from simulation.scheme_comparison_sim import run_recovery_trial
    from simulation.integrity_schemes import AdmitConfig, SegmentedMacScheme
    from simulation.two_hop_sim import default_admit_config
    on = replace(default_admit_config(), final_check=True)
    off = default_admit_config()
    assert off.final_check is False and AdmitConfig().final_check is True    # default path unchanged
    for scheme in (SegmentedScheme(6, 300, "acr_only", "kl"), SegmentedMacScheme(6, 300, "acr_only", "kd")):
        for seed in range(3):
            res = []
            for cfg in (on, off):
                random.seed(seed)
                r = run_recovery_trial(FIELD, scheme, 300, G, 2e-3, cfg, max_packets_factor=16,
                                       error_scope="data_payload")
                res.append((r.status, r.packets_to_decode, r.pairs_recovered, r.unpaired_recovered))
            assert res[0] == res[1], (scheme.name, seed, res)
    for s in ("keyless", "keyed"):
        a = run_two_hop_trial(FIELD, s, "blind", DF, N, 1e-3, 1e-3, trial_idx=1, cfg=on, max_ticks=20)
        b = run_two_hop_trial(FIELD, s, "blind", DF, N, 1e-3, 1e-3, trial_idx=1, cfg=off, max_ticks=20)
        assert (a.status, a.ticks, a.sink_accepted_final) == (b.status, b.ticks, b.sink_accepted_final)
        assert b.sink_scheme_mul <= a.sink_scheme_mul


def test_wire_segments_match_the_sink_layouts():
    for s in SCHEMES:
        sink = make_sink_scheme(s, N, DF)
        segs = wire_segments_for(s, sink, G, DF, N)
        random.seed(2)
        src, _ = sink.make_source(FIELD, DF, G)
        wire = sink.attach(sink.new_instrument(FIELD), bytearray(src[0]))
        assert segs[-1].start + segs[-1].total_length == len(wire)


def test_sweep_writes_rows_and_resumes():
    out = Path(tempfile.mkdtemp(prefix="twohop_test_"))
    try:
        run_sweep(out, schemes=("crc", "keyless"), policies=("blind",), configs=((DF, N),), bers=(1e-3,),
                  trials=2, workers=1, cell_budget_s=1e9, max_ticks=16)
        rows = list(csv.DictReader((out / "raw_trials.csv").open(newline="")))
        assert len(rows) == 4 and {r["scheme"] for r in rows} == {"crc", "keyless"}
        run_sweep(out, schemes=("crc", "keyless"), policies=("blind",), configs=((DF, N),), bers=(1e-3,),
                  trials=2, workers=1, cell_budget_s=1e9, max_ticks=16)
        assert len(list(csv.DictReader((out / "raw_trials.csv").open(newline="")))) == 4   # resumed, no dupes
    finally:
        shutil.rmtree(out, ignore_errors=True)


# ══ harness ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"two_hop_test  ({len(tests)} cases)")
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
            import traceback
            traceback.print_exc()
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"{'ALL PASS' if not failed else f'{failed} FAILED'}")
    sys.exit(1 if failed else 0)
