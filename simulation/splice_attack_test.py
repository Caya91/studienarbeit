"""Ticket 17 Part A tests -- segment splice / scale attack (simulation/splice_attack_sim.py).

Asserts the OBSERVED outcome (hypothesis confirmed 2026-09-23): on both segmented arms
(keyless SegmentedScheme, keyed SegmentedMacScheme) a splice / scale / zero forgery is
admitted by the production admit path and silently decodes wrong, for every N; the N=1
controls (one tag over [coeff|data]) reject every modification. Plus the checks that make
that claim trustworthy:
  - sanity + negative controls: the unmodified victim decodes correctly, a random
    modification is rejected (the oracles work);
  - mechanism: each forged segment is individually valid while the packet's code row is
    inconsistent with the source (coefficients untouched, data from elsewhere);
  - cost: no key is read and the attacker spends 0 field muls (scale: one per byte);
  - field-size independence (m=2,4): the attack is not a q^-u collision;
  - the all-ones parity rule (char-2 self-check == orthogonality to the all-ones vector);
  - N=1 controls still reach a CORRECT decode after rejecting the forgery;
  - determinism, smoke shape, CSV.

Run (PowerShell, main .venv, from the worktree/repo root); exit code 0 = pass:
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" simulation/splice_attack_test.py
"""
import copy
import csv
import random
import tempfile
from pathlib import Path

from binary_ext_fields.custom_field import CountingField
from simulation.attack_harness import (
    field_for, independent_rows, paired_setup, passes_oracle, recode, row_outside_span,
)
from simulation.splice_attack_sim import (
    VARIANTS, cells, expected, forge, format_table, run_smoke, run_splice_trial, run_table,
    summarize, write_csv,
)


def _victim_and_pool(seed, m, n, arm, gen_size=4, data_fields=12):
    f = field_for(m)
    shared, setup = paired_setup(seed, f, gen_size, data_fields, n, arm)
    head = independent_rows(shared, f, gen_size, gen_size - 1)
    victim_row = row_outside_span(shared, f, gen_size, head)
    return setup, [recode(setup, r) for r in head], recode(setup, victim_row), victim_row


def test_full_table_matches_prediction():
    trials = run_table(range(10))
    rows = summarize(trials)
    print(format_table(rows))
    bad = [t for t in trials if not t.matches]
    assert not bad, f"{len(bad)} trials deviate, first: {bad[0]}"
    # the headline, spelled out: every segmented splice/scale/zero trial is a silent decode
    seg = [t for t in trials if t.n > 1 and t.variant in ("splice", "scale", "zero")]
    assert seg and all(t.silent and t.forged_admitted and t.oracle_pass for t in seg)
    n1 = [t for t in trials if t.n == 1 and t.variant != "none"]
    assert n1 and not any(t.forged_admitted or t.silent for t in n1)
    print(f"  {len(seg)} segmented splice/scale/zero trials: all silent; {len(n1)} N=1 control trials: none admitted")


def test_sanity_and_negative_controls():
    for arm, n in cells():
        for seed in range(5):
            none = run_splice_trial(arm, n, "none", seed)
            assert none.forged_admitted and none.decoded and none.correct and not none.silent, (arm, n, seed)
            rnd = run_splice_trial(arm, n, "random", seed)
            assert not rnd.oracle_pass and not rnd.forged_admitted and not rnd.silent, (arm, n, seed)
            assert rnd.decoded and rnd.correct, "receiver must still decode correctly after rejecting"
    print("  unmodified victim decodes correctly; random modification rejected, decode still correct")


def test_mechanism_segments_valid_code_inconsistent():
    for arm in ("keyless", "keyed"):
        for n in (2, 3, 5):
            for seed in range(4):
                setup, pool, victim, victim_row = _victim_and_pool(seed, 8, n, arm)
                f = setup.base_field
                for variant in ("splice", "scale", "zero"):
                    forged = forge(setup, variant, victim, pool[0], random.Random(seed), CountingField(f))
                    assert passes_oracle(setup, forged, pool), f"{arm} n={n} {variant}: a segment check failed"
                    code = setup.code(forged)
                    assert list(code[:setup.gen_size]) == list(victim_row), "coefficients must be the victim's"
                    truth = [0] * setup.data_fields
                    for c, row in zip(victim_row, setup.data_rows):
                        truth = [f.add(t, f.mul(c, b)) for t, b in zip(truth, row)]
                    assert list(code[setup.gen_size:]) != truth, f"{variant}: data happens to be consistent"
    print("  every forged segment valid on its own; coeff row = victim's; data inconsistent with it")


def test_attack_needs_no_key_and_no_work():
    for arm in ("keyless", "keyed"):
        for n in (2, 5):
            setup, pool, victim, _ = _victim_and_pool(1, 8, n, arm)
            blind = copy.copy(setup)
            blind.keyset = None           # attacker never holds a key
            blind.gen_packets = None      # ... nor the source
            for variant in ("splice", "scale", "zero", "ones"):
                c1, c2 = CountingField(setup.base_field), CountingField(setup.base_field)
                a = forge(setup, variant, victim, pool[0], random.Random(9), c1)
                b = forge(blind, variant, victim, pool[0], random.Random(9), c2)
                assert a == b, f"{arm} {variant}: forgery depends on secret/source state"
                want = setup.data_regions()[0][1] if variant == "scale" else 0
                assert c1.mul_count == want, f"{arm} {variant}: {c1.mul_count} muls, expected {want}"
    print("  forgery identical without keys/source; muls: splice/zero/ones = 0, scale = 1 per byte")


def test_field_size_independent():
    for m in (2, 4):
        for arm in ("keyless", "keyed"):
            for n in (2, 5):
                for variant in ("splice", "scale", "zero"):
                    for seed in range(4):
                        t = run_splice_trial(arm, n, variant, seed, field_bits=m)
                        assert t.silent and t.forged_admitted, (m, arm, n, variant, seed)
    print("  GF(2^2) and GF(2^4): splice/scale/zero still silent every time (not a collision event)")


def test_ones_parity_rule():
    # (gen_size, data_fields, n) -> data-slice lengths (payload + 1 salt + gen_size tags)
    layouts = [(4, 12, 5), (4, 12, 2), (4, 12, 3), (4, 13, 2), (4, 13, 3), (3, 10, 3), (3, 8, 3)]
    seen = set()
    for g, d, n in layouts:
        for seed in range(3):
            t = run_splice_trial("keyless", n, "ones", seed, gen_size=g, data_fields=d)
            _, setup = paired_setup(seed, field_for(8), g, d, n, "keyless")
            lengths = [length for _, length in setup.data_regions()]
            all_even = all(x % 2 == 0 for x in lengths)
            assert t.forged_admitted == all_even and t.silent == all_even, (g, d, n, lengths, t)
            seen.add(all_even)
            k = run_splice_trial("keyed", n, "ones", seed, gen_size=g, data_fields=d)
            assert not k.forged_admitted and not k.silent, (g, d, n)
    assert seen == {True, False}, "layouts must cover both parities"
    print("  keyless admits beta*1 iff every data slice has even length; keyed always rejects")


def test_n1_controls_recover_correct_decode():
    for arm, n in [("keyless_n1", 1), ("keyed_n1", 1)]:
        for variant in VARIANTS:
            if variant == "none":
                continue
            for seed in range(5):
                t = run_splice_trial(arm, n, variant, seed)
                assert not t.forged_admitted and t.decoded and t.correct, (arm, variant, seed)
                assert t.packets_received > t.gen_size, "must have needed a further honest packet"
    print("  N=1 controls: forgery rejected, generation still decodes correctly from honest packets")


def test_expected_table_is_exhaustive():
    f = field_for(8)
    for arm, n in cells():
        _, setup = paired_setup(0, f, 4, 12, n, arm)
        for variant in VARIANTS:
            adm, silent = expected(setup, variant)
            assert not (silent and not adm), "a silent decode needs an admitted forgery"
    print(f"  prediction defined and consistent for {len(cells()) * len(VARIANTS)} (arm, N, variant) cells")


def test_determinism():
    for arm, n in [("keyless", 3), ("keyed", 5), ("keyless_n1", 1)]:
        for variant in ("splice", "random"):
            assert run_splice_trial(arm, n, variant, 4) == run_splice_trial(arm, n, variant, 4)
    print("  identical inputs -> identical trial records")


def test_smoke_shape_and_csv():
    text = run_smoke(seeds=range(2))
    assert "Splice/scale test" in text and "ALL CELLS MATCH THE PREDICTION" in text
    assert text.count("\n") > len(cells()) * len(VARIANTS)
    trials = run_table(range(1), segmented_ns=(2,), variants=("splice", "none"))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.csv"
        write_csv(trials, path)
        with path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    assert len(rows) == len(trials) and {"arm", "variant", "silent", "matches"} <= set(rows[0])
    print(f"  smoke readable ({text.count(chr(10))} lines, verdict line present); CSV {len(rows)} rows")


if __name__ == "__main__":
    tests = [
        test_full_table_matches_prediction,
        test_sanity_and_negative_controls,
        test_mechanism_segments_valid_code_inconsistent,
        test_attack_needs_no_key_and_no_work,
        test_field_size_independent,
        test_ones_parity_rule,
        test_n1_controls_recover_correct_decode,
        test_expected_table_is_exhaustive,
        test_determinism,
        test_smoke_shape_and_csv,
    ]
    for test in tests:
        print(f"\n=== {test.__name__} ===")
        test()
        print(f"{test.__name__} passed")
    print("\nAll splice-attack tests passed!")
