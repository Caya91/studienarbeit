"""Test bench for simulation/crc_recovery.py (ADR-0011).

No pytest dependency -- a tiny built-in harness reports PASS/FAIL and sets the
exit code, same convention as simulation/recovery_decode_test.py.

Run:  .venv/Scripts/python.exe simulation/crc_recovery_test.py
"""

import os
import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

from simulation.crc_recovery import (
    CrcInstrument, analytic_false_repair, attach, candidates_up_to, crc,
    recover, tag_overhead_bits, _flip_bits,
)


# ══ CRC primitive: known-answer vectors ("123456789") ════════════════════════

def test_crc8_known_answer():
    # CRC-8/SMBUS (poly 0x07, init 0, xorout 0) check value = 0xF4.
    assert crc(b"123456789", 8) == 0xF4


def test_crc16_known_answer():
    # CRC-16/XMODEM (poly 0x1021, init 0, xorout 0) check value = 0x31C3.
    assert crc(b"123456789", 16) == 0x31C3


def test_crc_widths_bounded():
    for w in (8, 16, 32):
        assert 0 <= crc(b"hello world", w) < (1 << w)


def test_crc_detects_every_single_bit_error():
    # A real CRC never collides on a 1-bit change (HD-1 is always detected).
    data = bytearray(b"orthogonal")
    ref = crc(bytes(data), 32)
    n = 8 * len(data)
    for p in range(n):
        assert crc(bytes(_flip_bits(data, [p])), 32) != ref


# ══ recover(): outcomes ══════════════════════════════════════════════════════

def _corrupt(original: bytearray, hd: int, rng) -> bytearray:
    n = 8 * len(original)
    return _flip_bits(original, rng.sample(range(n), hd))


def test_recover_correct_hd1():
    rng = random.Random(1)
    original = bytearray(rng.randrange(256) for _ in range(8))
    ref = crc(bytes(original), 32)
    received = _corrupt(original, 1, rng)
    inst = CrcInstrument()
    repaired, exhausted = recover(inst, received, ref, 32, max_hd=3)
    assert not exhausted
    assert repaired == original          # wide CRC -> no HD-1 collision -> correct
    assert inst.correction_trials >= 1


def test_recover_correct_hd3():
    rng = random.Random(2)
    original = bytearray(rng.randrange(256) for _ in range(6))
    ref = crc(bytes(original), 32)
    received = _corrupt(original, 3, rng)
    inst = CrcInstrument()
    repaired, exhausted = recover(inst, received, ref, 32, max_hd=3)
    assert not exhausted
    assert repaired == original


def test_recover_no_repair_when_hd_exceeds_budget_of_search():
    # 4 bits flipped but search only goes to HD 3 -> nothing within reach, and a
    # 32-bit CRC won't collide on a small packet, so: no-repair (not exhausted).
    rng = random.Random(3)
    original = bytearray(rng.randrange(256) for _ in range(6))
    ref = crc(bytes(original), 32)
    received = _corrupt(original, 4, rng)
    inst = CrcInstrument()
    repaired, exhausted = recover(inst, received, ref, 32, max_hd=3)
    assert repaired is None
    assert not exhausted


def test_recover_budget_exhaustion():
    rng = random.Random(4)
    original = bytearray(rng.randrange(256) for _ in range(32))   # n = 256 bits
    ref = crc(bytes(original), 32)
    received = _corrupt(original, 3, rng)
    inst = CrcInstrument()
    repaired, exhausted = recover(inst, received, ref, 32, max_hd=3, budget=100)
    assert repaired is None
    assert exhausted
    assert inst.correction_trials == 100


def test_recover_false_repair_with_narrow_crc():
    # CRC-8 over a biggish packet: a wrong single-bit flip collides long before
    # the true fix, so we expect at least one silent false-repair across seeds.
    saw_false = False
    for seed in range(50):
        rng = random.Random(seed)
        original = bytearray(rng.randrange(256) for _ in range(32))
        ref = crc(bytes(original), 8)
        received = _corrupt(original, 3, rng)
        inst = CrcInstrument()
        repaired, exhausted = recover(inst, received, ref, 8, max_hd=3)
        if repaired is not None and repaired != original:
            saw_false = True
            break
    assert saw_false, "expected a CRC-8 collision (false-repair) within 50 seeds"


def test_localization_hint_shrinks_search():
    # Passing the true corrupted bits as the suspect set makes recovery trivial
    # and cheap -- the comparison's "CRC with ACR localization" path.
    rng = random.Random(5)
    original = bytearray(rng.randrange(256) for _ in range(16))
    ref = crc(bytes(original), 32)
    n = 8 * len(original)
    bad = rng.sample(range(n), 2)
    received = _flip_bits(original, bad)
    inst = CrcInstrument()
    repaired, exhausted = recover(inst, received, ref, 32, max_hd=3, suspect_bits=set(bad))
    assert repaired == original
    assert inst.correction_trials <= candidates_up_to(len(bad), 2)   # tiny vs whole-packet


# ══ analytic helpers ═════════════════════════════════════════════════════════

def test_candidates_up_to():
    assert candidates_up_to(8, 1) == 8
    assert candidates_up_to(8, 2) == 8 + 28
    assert candidates_up_to(8, 3) == 8 + 28 + 56


def test_analytic_false_repair_scales():
    # Wider CRC -> exponentially fewer expected collisions; larger packet -> more.
    assert analytic_false_repair(256, 3, 8) > analytic_false_repair(256, 3, 32)
    assert analytic_false_repair(512, 3, 16) > analytic_false_repair(64, 3, 16)


def test_tag_overhead_bits():
    assert tag_overhead_bits(16) == 16


# ══ harness ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"crc_recovery_test  ({len(tests)} cases)")
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
