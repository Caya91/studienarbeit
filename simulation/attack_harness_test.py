"""Tests for simulation/attack_harness.py -- the shared plumbing of the ticket-17 security sims.

If any of these fail, every attack number built on the harness is suspect, so they check
the plumbing independently of any attack:
  - pairing: same seed -> same data rows and same shared-RNG stream in every arm;
  - honest traffic: recodes are valid in every arm, their code row is exactly the linear
    combination of the source, and an honest-only receiver always decodes CORRECTLY;
  - the strict oracle rejects corruption (m=8) and accepts honest packets;
  - injected_status / arrival-stream bookkeeping.

Run (PowerShell, main .venv, from the worktree/repo root); exit code 0 = pass:
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" simulation/attack_harness_test.py
"""
import random

from simulation.attack_harness import (
    ARMS, SEGMENTED_ARMS, N1_ARMS, ReceiverOutcome, arrivals_with_injection, default_cfg, field_for,
    in_row_span, independent_rows, injected_status, paired_setup, passes_oracle, random_row, recode,
    row_outside_span, row_rank, run_receiver,
)
from simulation.integrity_schemes import AdmitConfig


GEN, DATA = 4, 12


def _arm_ns(arm):
    return (1,) if arm in N1_ARMS else (2, 3, 5)


def _source_combination(field, data_rows, coeffs):
    """sum_i coeffs[i] * data_rows[i] computed independently of recode."""
    out = [0] * len(data_rows[0])
    for c, row in zip(coeffs, data_rows):
        out = [field.add(o, field.mul(c, b)) for o, b in zip(out, row)]
    return out


def test_field_cache_is_shared():
    assert field_for(4) is field_for(4)
    assert field_for(8).max_value == 255 and field_for(2).max_value == 3
    print("  field_for caches one TableField per m")


def test_default_cfg_only_changes_min_pool_size():
    cfg, base = default_cfg(GEN), AdmitConfig()
    assert cfg.min_pool_size == GEN
    for name in ("verify_count", "min_trust_count", "decode_verify_count", "hamming_distance", "pair_budget", "mode"):
        assert getattr(cfg, name) == getattr(base, name), name
    print(f"  cfg: min_pool_size={cfg.min_pool_size}, rest = production defaults")


def test_row_helpers():
    f = field_for(4)
    rng = random.Random(1)
    for count in range(1, GEN + 1):
        rows = independent_rows(rng, f, GEN, count)
        assert row_rank(f, rows) == count
    rows = independent_rows(rng, f, GEN, GEN - 1)
    combo = bytearray(f.add(f.mul(3, a), f.mul(7, b)) for a, b in zip(rows[0], rows[1]))
    assert in_row_span(f, combo, rows)
    for _ in range(50):
        out = row_outside_span(rng, f, GEN, rows, exclude=[rows[0]])
        assert not in_row_span(f, out, rows) and out != rows[0]
    print("  rank / span / outside-span helpers consistent")


def test_pairing_same_source_every_arm():
    checked = 0
    for m in (2, 4, 8):
        f = field_for(m)
        for n in (1, 2, 3, 5):
            arms = N1_ARMS if n == 1 else SEGMENTED_ARMS
            for seed in range(8):
                streams, datas = [], []
                for arm in arms:
                    shared, setup = paired_setup(seed, f, GEN, DATA, n, arm)
                    datas.append([bytes(r) for r in setup.data_rows])
                    streams.append([shared.getrandbits(32) for _ in range(6)])
                assert datas[0] == datas[1], (m, n, seed)
                assert streams[0] == streams[1], (m, n, seed)
                checked += 1
    print(f"  {checked} (m, n, seed) cells: identical data rows + shared stream across arms")


def test_honest_recodes_valid_and_linear():
    rng = random.Random(3)
    checked = 0
    for m in (2, 4, 8):
        f = field_for(m)
        for arm in ARMS:
            for n in _arm_ns(arm):
                _, setup = paired_setup(11, f, GEN, DATA, n, arm)
                rows = [random_row(rng, f, GEN) for _ in range(5)]
                pkts = [recode(setup, r) for r in rows]
                for r, p in zip(rows, pkts):
                    code = setup.code(p)
                    assert list(code[:GEN]) == list(r), "coefficient block must be the recoding row"
                    assert list(code[GEN:]) == _source_combination(f, setup.data_rows, r), "data = combo"
                    others = [q for q in pkts if q is not p]
                    assert passes_oracle(setup, p, others), f"honest recode rejected ({arm}, n={n}, m={m})"
                checked += 1
    print(f"  {checked} arm/n/m cells: recodes are exact source combinations and pass the oracle")


def test_honest_only_receiver_decodes_correctly():
    checked = 0
    for m in (2, 4, 8):
        f = field_for(m)
        for arm in ARMS:
            for n in _arm_ns(arm):
                for seed in range(6):
                    shared, setup = paired_setup(seed, f, GEN, DATA, n, arm)
                    rows = independent_rows(shared, f, GEN, GEN)
                    rows += [random_row(shared, f, GEN) for _ in range(3 * GEN)]
                    honest = [recode(setup, r) for r in rows]
                    out = run_receiver(setup, iter(honest), default_cfg(GEN), 4 * GEN)
                    assert out.decoded and out.correct, f"honest-only decode failed ({arm}, n={n}, m={m}, seed={seed})"
                    adm, _ = injected_status(setup, out, bytearray(len(honest[0])), honest)
                    assert not adm
                    checked += 1
    print(f"  {checked} honest-only receiver runs: all decoded CORRECTLY (0 silent, 0 timeouts)")


def test_oracle_rejects_single_symbol_corruption():
    f = field_for(8)
    rng = random.Random(5)
    for arm in ARMS:
        for n in _arm_ns(arm):
            shared, setup = paired_setup(2, f, GEN, DATA, n, arm)
            pool = [recode(setup, r) for r in independent_rows(shared, f, GEN, GEN - 1)]
            victim = recode(setup, random_row(shared, f, GEN))
            rejected = 0
            for start, length in setup.data_regions() + [setup.coeff_region()]:
                for _ in range(10):
                    bad = bytearray(victim)
                    pos = start + rng.randrange(length)
                    bad[pos] ^= rng.randint(1, 255)
                    rejected += not passes_oracle(setup, bad, pool)
            total = 10 * (len(setup.data_regions()) + 1)
            assert rejected == total, f"{arm} n={n}: {total - rejected} single-symbol corruptions passed"
    print("  single-symbol corruption in any region is rejected by every arm (m=8)")


def test_injected_status_semantics():
    f = field_for(4)
    shared, setup = paired_setup(0, f, GEN, DATA, 2, "keyless")
    honest = [recode(setup, r) for r in independent_rows(shared, f, GEN, GEN)]
    injected = recode(setup, random_row(shared, f, GEN))
    codes = [setup.code(h) for h in honest]

    def outcome(admitted):
        return ReceiverOutcome(decoded=True, correct=True, admitted=admitted, packets_received=0, admit_calls=1)

    assert injected_status(setup, outcome(codes), injected, honest) == (False, False)
    assert injected_status(setup, outcome(codes + [setup.code(injected)]), injected, honest) == (True, False)
    modified = setup.code(injected)
    modified[0] ^= 1
    assert injected_status(setup, outcome(codes + [modified]), injected, honest) == (True, True)
    print("  injected_status: honest-only / as-sent / modified distinguished")


def test_arrival_stream_order():
    f = field_for(4)
    shared, setup = paired_setup(0, f, GEN, DATA, 2, "keyed")
    head = independent_rows(shared, f, GEN, GEN - 1)
    marker = bytearray(b"\xff") * len(recode(setup, head[0]))
    for strike in range(len(head) + 1):
        log: list = []
        stream = arrivals_with_injection(setup, head, marker, strike, random.Random(1), log)
        got = [next(stream) for _ in range(len(head) + 3)]
        assert got[strike] is marker
        honest_seen = [p for p in got if p is not marker]
        assert [bytes(p) for p in honest_seen[:len(head)]] == [bytes(recode(setup, r)) for r in head]
        assert len(log) == len(honest_seen)
    print("  injection lands at strike index; head order preserved; honest_log complete")


if __name__ == "__main__":
    tests = [
        test_field_cache_is_shared,
        test_default_cfg_only_changes_min_pool_size,
        test_row_helpers,
        test_pairing_same_source_every_arm,
        test_honest_recodes_valid_and_linear,
        test_honest_only_receiver_decodes_correctly,
        test_oracle_rejects_single_symbol_corruption,
        test_injected_status_semantics,
        test_arrival_stream_order,
    ]
    for test in tests:
        print(f"\n=== {test.__name__} ===")
        test()
        print(f"{test.__name__} passed")
    print("\nAll attack-harness tests passed!")
