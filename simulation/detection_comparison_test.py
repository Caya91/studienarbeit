"""Test bench for simulation/detection_comparison_sim.py (ADR-0014 point 5).

The exact undetected-pattern counts rest on two claims, both brute-forced here:
  1. the subset-XOR counting (count_undetected) is right -- incl. zero syndromes and
     heavy collisions (the k=3/k=4 overlap corrections);
  2. the syndrome model matches the REAL oracles -- every k <= 4 bit pattern of a tiny
     segment is pushed through check_orth_packet / inner products / crc_verify_segment.

Run (PowerShell):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; .\\.venv\\Scripts\\python.exe simulation\\detection_comparison_test.py
"""
import os
import random
import sys
from functools import reduce
from itertools import combinations
from math import comb
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

import numpy as np
from icecream import ic

from binary_ext_fields.custom_field import CountingField, create_field
from binary_ext_fields.segmented_recovery import segment_slice as kl_slice
from simulation.detection_comparison_sim import (
    _keyless_levels_passed, analytic_miss_given_corrupted, count_undetected, crc_bit_syndromes,
    keyless_bit_syndromes, self_check_miss_table,
)
from simulation.isolated_recovery_sim import build_paired_pools
from simulation.segmented_crc import Crc32Instrument, crc_verify_segment, segment_slice as crc_slice

ic.disable()
G = 4


def _brute(syn, k_max):
    syn = [int(x) for x in syn]
    return {k: sum(1 for c in combinations(range(len(syn)), k) if reduce(lambda a, b: a ^ b, (syn[i] for i in c)) == 0)
            for k in range(1, k_max + 1)}


def test_count_undetected_matches_brute_force_with_collisions_and_zeros():
    rng = random.Random(0)
    for trial in range(40):
        n = rng.randint(4, 16)
        alphabet = rng.choice((2, 4, 8, 16))           # small alphabet -> many collisions
        syn = np.array([rng.randrange(alphabet) for _ in range(n)], dtype=np.uint64)  # zeros included
        assert count_undetected(syn, 4) == _brute(syn, 4), f"trial {trial}: n={n} alphabet={alphabet}"


def test_syndrome_model_matches_real_oracles_exhaustively():
    # tiny data segments (3 B = 24 bits): every pattern of 1..4 flipped bits, real oracles
    field = create_field(8)
    pools = build_paired_pools(CountingField(field), G, 12, 4, 4, seed=2)
    inst = Crc32Instrument()
    for kl, cs in [(k, c) for k, c in zip(pools.kl_segments, pools.crc_segments) if k.kind == "data"][:2]:
        L, n = kl.payload_length, 8 * kl.payload_length
        t = pools.target_idx[0]
        helpers = [kl_slice(pools.kl_clean[h], kl) for h in pools.helper_idx]
        real = {lv: {k: 0 for k in range(1, 5)} for lv in [f"keyless_W{w}" for w in range(G + 1)] + ["crc32"]}
        for k in range(1, 5):
            for combo in combinations(range(n), k):
                ks_, cr = kl_slice(pools.kl_clean[t], kl), crc_slice(pools.crc_clean[t], cs)
                for p in combo:
                    ks_[p >> 3] ^= 1 << (p & 7)
                    cr[p >> 3] ^= 1 << (p & 7)
                top = _keyless_levels_passed(field, ks_, helpers, G)
                for w in range(G + 1):
                    real[f"keyless_W{w}"][k] += top >= w
                real["crc32"][k] += crc_verify_segment(inst, cr, cs)
        for w in range(G + 1):
            assert count_undetected(keyless_bit_syndromes(field, helpers, L, w), 4) == real[f"keyless_W{w}"], \
                f"{kl.name} W={w}: syndrome count != real oracle"
        assert count_undetected(crc_bit_syndromes(L), 4) == real["crc32"] == {1: 0, 2: 0, 3: 0, 4: 0}


def test_self_check_closed_form_matches_counts():
    # keyless_W0 = bit-lane parity: odd k never missed, k=2 misses = same bit in two bytes
    field = create_field(8)
    for L in (3, 10, 25):
        table = self_check_miss_table(L)
        counts = count_undetected(keyless_bit_syndromes(field, [], L, 0), 4)
        n = 8 * L
        for k in range(1, 5):
            assert abs(table[k] - counts[k] / comb(n, k)) < 1e-15, (L, k)
        assert counts[1] == counts[3] == 0 and counts[2] == 8 * comb(L, 2)
        assert all(table[k] == 0 for k in range(1, n + 1, 2))


def test_analytic_ber_limits():
    # NOT monotone in BER: the self-check misses only even-weight errors, and the miss chance
    # per even k falls toward 2^-7 -- so it peaks around a couple of flips, then decays.
    n = 80
    table = self_check_miss_table(10)
    exact = {k: table[k] for k in range(1, 5)}
    for ber in (1e-5, 1e-4, 1e-3, 1e-2, 5e-2, 0.5):
        p = analytic_miss_given_corrupted("keyless_W0", n, exact, table, ber)
        assert 0.0 <= p <= 1.0, (ber, p)
    # low BER: almost every corrupted segment has exactly 1 flip -> always caught
    assert analytic_miss_given_corrupted("keyless_W0", n, exact, table, 1e-7) < 1e-5
    # BER 1/2 = uniform random error: even weight half the time, then 2^-7 -> 2^-8
    assert abs(analytic_miss_given_corrupted("keyless_W0", n, exact, table, 0.5) / 2 ** -8 - 1) < 0.05
    # CRC-32 on uniform random errors -> 2^-32 (k <= 4 exactly 0, tail model above)
    p_crc = analytic_miss_given_corrupted("crc32", n, {1: 0, 2: 0, 3: 0, 4: 0}, table, 0.5)
    assert abs(p_crc / 2 ** -32 - 1) < 0.01


# ══ harness ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"detection_comparison_test  ({len(tests)} cases)")
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
