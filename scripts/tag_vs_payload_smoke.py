"""
EXPERIMENT (branch exp/tag-vs-payload-recovery, throwaway): does it matter WHAT the recovered
span contains, at equal length L?

  A  "payload+tags": per data segment payload p_A + redundancy (keyed: g tags, keyless: salt + g
     tags), errors hit the WHOLE data segment (error scope data_segment), |span| = L.
  B  "payload only": per data segment payload L, errors hit ONLY the payload (data_payload),
     tags/salt clean, |span| = L.

gen_size g and segment count fixed in both, so tag count and ACR's "g trusted" need are equal;
only the CONTENT of the error span differs. A is run with three repair spans:
  payload      -- ACR on payload columns only (production default); tag/salt errors unrepairable
  segment      -- + blind bit-flip over the whole salt/tag span (ADR-0013 ticket 16)
  acr_segment  -- ACR also re-derives salt/tag columns (added on this branch)

Level 1 (mechanism): exactly e bit errors in ONE target packet's span of data-0, one
recover_acr_only(_mac) call, outcome repaired / failed / silent + field muls.
Level 2 (end-to-end): run_recovery_trial at fixed BER, overhead / correct / silent.

Run (PowerShell, from the worktree):
  $env:LOG_FOLDER="./logs"; $env:PYTHONPATH="."; E:/projects/studienarbeit/.venv/Scripts/python.exe scripts/tag_vs_payload_smoke.py
"""
import random
import statistics
import sys

import numpy as np
from icecream import ic

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import generate_identity_coefficients, recode_rlnc_without_coeffs
from binary_ext_fields.segmented_tagging import tag_generation_segmented
from binary_ext_fields.segmented_recovery import recover_acr_only, segment_slice
from binary_ext_fields.segmented_mac_tagging import layout_mac_segments, generate_keyset, tag_generation_mac
from binary_ext_fields.segmented_mac_recovery import recover_acr_only_mac
from simulation.integrity_schemes import AdmitConfig, SegmentedScheme, SegmentedMacScheme
from simulation.scheme_comparison_sim import run_recovery_trial

ic.disable()
FIELD = create_field(8)
G = 5
L = 10                 # recovered span length (symbols)
NSEG = 2               # data segments (N = 3; N = 2 never repairs under ACR-only)
EXTRA = 3              # recoded packets on top of the g source packets (level 1 pool)
HD = 2


def layouts(arm):
    """(payload per data segment) for A and B so the error span is L in both."""
    redundancy = G if arm == "keyed" else G + 1          # keyless: salt + g tags
    return {"A": L - redundancy, "B": L}


def build_pool(arm, payload, seed):
    data_fields = payload * NSEG
    rng = random.Random(seed)
    rows = [bytearray(rng.randint(0, FIELD.max_value) for _ in range(data_fields)) for _ in range(G)]
    plain = generate_identity_coefficients(FIELD, rows)
    random.seed(seed)
    if arm == "keyless":
        res = tag_generation_segmented(FIELD, plain, G, NSEG)
        if not res.ok:
            return None
        src, segs, keyset = res.packets, res.segments, None
    else:
        segs = layout_mac_segments(G, data_fields, NSEG, G)
        keyset = generate_keyset(FIELD, segs, random.Random(seed))
        src = tag_generation_mac(FIELD, plain, G, NSEG, keyset, G)
    rec = recode_rlnc_without_coeffs(FIELD, src, G, count=EXTRA)
    return [bytearray(p) for p in src] + [bytearray(p) for p in rec], segs, keyset


def level1(arm, case, span, e, trials):
    payload = layouts(arm)[case]
    out = {"repaired": 0, "failed": 0, "silent": 0, "undetected": 0}
    muls = []
    seed = 0
    done = 0
    while done < trials:
        seed += 1
        built = build_pool(arm, payload, seed)
        if built is None:
            continue
        pool, segs, keyset = built
        data0 = next(s for s in segs if s.kind == "data")
        width = data0.total_length if case == "A" else data0.payload_length
        assert width == L, (arm, case, width)
        target = len(pool) - 1                              # a recoded packet (dense coeffs)
        clean = bytearray(pool[target])

        def repair(p):
            cf = CountingField(FIELD)
            if arm == "keyless":
                r = recover_acr_only(cf, p, segs, G, max_combined_hd=HD, repair_span=span)
            else:
                r = recover_acr_only_mac(cf, keyset, p, segs, G, max_combined_hd=HD, repair_span=span)
            return r, cf.mul_count

        _, base_muls = repair([bytearray(p) for p in pool])  # same pool, no error: detection baseline
        rng = random.Random(10_000 + seed)
        for pos in rng.sample(range(L * 8), e):             # e distinct bit positions in the span
            pool[target][data0.start + pos // 8] ^= 1 << (pos % 8)
        broken = bytearray(pool[target])
        rep, m = repair(pool)
        got = rep.packets[target]
        o = rep.per_segment[0]                               # data-0 outcome
        noticed = o.dropped + o.unpaired_failed + o.pairs_failed + o.unpaired_recovered + o.pairs_recovered
        if got == clean:
            out["repaired"] += 1
        elif got != broken:
            out["silent"] += 1
        else:                                                # untouched: detected-but-unfixed vs never seen
            out["failed" if noticed else "undetected"] += 1
        muls.append(m - base_muls)                           # muls caused by the error
        done += 1
    return out, statistics.mean(muls)


def level2(arm, case, span, ber, trials):
    payload = layouts(arm)[case]
    cls = SegmentedScheme if arm == "keyless" else SegmentedMacScheme
    scope = "data_segment" if case == "A" else "data_payload"
    cfg = AdmitConfig(hamming_distance=HD, repair_span=span, min_pool_size=G)
    rs = []
    for seed in range(trials):
        random.seed(seed)
        np.random.seed(seed)
        sch = cls(num_data_segments=NSEG, data_fields=payload * NSEG, strategy="acr_only", name=f"{arm}{case}")
        rs.append(run_recovery_trial(FIELD, sch, payload * NSEG, G, ber, cfg, max_packets_factor=8,
                                     error_scope=scope))
    return {
        "correct": sum(r.correct for r in rs) / trials,
        "silent": sum(r.silent_decode for r in rs),
        "overhead": statistics.mean(r.overhead for r in rs),
        "rep": sum(r.unpaired_recovered + r.pairs_recovered for r in rs),
        "fail": sum(r.unpaired_failed + r.pairs_failed for r in rs),
        "ops": statistics.mean(r.scheme_ops for r in rs),
        "wall": statistics.mean(r.wall_time_s for r in rs),
    }


CONFIGS = [("A", "payload"), ("A", "segment"), ("A", "acr_segment"), ("B", "payload")]

if __name__ == "__main__":
    t1 = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    t2 = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    bers = [float(b) for b in sys.argv[3].split(",")] if len(sys.argv) > 3 else [3e-3]
    print(f"g={G} L={L} N={1 + NSEG} HD={HD} GF(2^8); A payload/seg: keyed {layouts('keyed')['A']}, "
          f"keyless {layouts('keyless')['A']}; B payload/seg {L}")
    print(f"\nLEVEL 1: exactly e bit errors in target's span, one repair call ({t1} trials/cell)")
    print(f"{'arm':8}{'case':5}{'span':13}{'e':>2}  {'repaired':>8}{'failed':>8}{'silent':>8}{'undet':>8}{'d_muls':>10}")
    for arm in ("keyless", "keyed"):
        for case, span in CONFIGS:
            for e in (1, 2, 3):
                o, m = level1(arm, case, span, e, t1)
                print(f"{arm:8}{case:5}{span:13}{e:>2}  {o['repaired']/t1:8.2f}{o['failed']/t1:8.2f}"
                      f"{o['silent']/t1:8.2f}{o['undetected']/t1:8.2f}{m:10.0f}", flush=True)
    print(f"\nLEVEL 2: end-to-end ({t2} trials/cell)")
    print(f"{'arm':8}{'case':5}{'span':13}{'BER':>7}  {'correct':>7}{'silent':>7}{'overhd':>7}"
          f"{'rep':>5}{'fail':>5}{'ops':>10}{'wall_s':>7}")
    for ber in bers:
        for arm in ("keyless", "keyed"):
            for case, span in CONFIGS:
                r = level2(arm, case, span, ber, t2)
                print(f"{arm:8}{case:5}{span:13}{ber:7.0e}  {r['correct']:7.2f}{r['silent']:7d}"
                      f"{r['overhead']:7.2f}{r['rep']:5d}{r['fail']:5d}{r['ops']:10.0f}{r['wall']:7.2f}", flush=True)
