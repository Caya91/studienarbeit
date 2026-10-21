"""
Tests for S3 (tag pollution, 2026-10-03).

  - theory: width all keyless = (q-1)/(q^(u+1)-1) (nonzero delta), r = g-1 always passes;
    keyed random W=1 = 1 - t/g, all = 0, first = step at t = g-W;
  - the polluters touch ONLY the chosen segment's tag block (code row unchanged), change
    something, and the keyless one stays valid against every observed packet;
  - a polluted packet never causes a wrong decode (silent = 0) -- it carries honest content.

Judge pass/fail by exit code (0 = pass).
"""
import random

from binary_ext_fields.custom_field import CountingField
from simulation.attack_harness import default_cfg, field_for, passes_oracle, recode
from simulation.knowledge_attack_sim import paired_plan
from simulation.tag_pollution_attack_sim import (
    _tag_block, pollute_keyed, pollute_keyless, run_trial, sweep_cells, theory_admit,
)


def test_theory():
    g = 4
    for q in (4, 16, 256):
        for r in range(g):
            u = g - 1 - r
            assert abs(theory_admit("keyless", "first", r, None, g, q) - (q - 1) / (q ** (u + 1) - 1)) < 1e-12
        for t in range(1, g + 1):
            assert abs(theory_admit("keyed", "random", t, 1, g, q) - (1 - t / g)) < 1e-12
            assert theory_admit("keyed", "first", t, None, g, q) == 0.0
            for W in range(1, g):
                assert theory_admit("keyed", "first", t, W, g, q) == (1.0 if t <= g - W else 0.0)
    print("  theory ok")


def test_polluters_only_touch_tags():
    g, m = 4, 4
    base = field_for(m)
    for arm in ("keyless", "keyed"):
        for seed in range(20):
            setup, plan = paired_plan(seed, base, g, 12, 2, arm)
            head = [recode(setup, r) for r in plan.head]
            target = recode(setup, plan.forged_row)
            for s in range(len(setup.segments)):
                rng, cnt = random.Random(seed), CountingField(base)
                for k in (range(g) if arm == "keyless" else range(1, g + 1)):
                    p = (pollute_keyless(setup, target, s, head[:k], rng, cnt) if arm == "keyless"
                         else pollute_keyed(setup, target, s, k, rng, cnt))
                    off, width = _tag_block(setup, s)
                    diff = [i for i, (a, b) in enumerate(zip(p, target)) if a != b]
                    assert diff and all(off <= i < off + width for i in diff), (arm, seed, s, k, diff)
                    assert setup.code(p) == setup.code(target)
                    if arm == "keyless":
                        assert passes_oracle(setup, p, head[:k]), (seed, s, k)
                        if k == g - 1:
                            assert passes_oracle(setup, p, head)
                    else:
                        assert len(diff) == k
    print("  polluters: tag block only, keyless valid vs observed")


def test_keyless_support():
    """support e: only e tag-block bytes may change; e = 1 always breaks the self-check; e >= r + 2 stays valid
    against the observed packets."""
    g, base = 6, field_for(4)
    for seed in range(15):
        setup, plan = paired_plan(seed, base, g, 12, 2, "keyless")
        head = [recode(setup, r) for r in plan.head]
        target = recode(setup, plan.forged_row)
        rng, cnt = random.Random(seed), CountingField(base)
        p = pollute_keyless(setup, target, 1, [], rng, cnt, support=1)
        assert sum(a != b for a, b in zip(p, target)) == 1 and not passes_oracle(setup, p, [])
        for r in range(g - 1):
            for e in range(r + 2, g + 2):
                p = pollute_keyless(setup, target, 0, head[:r], rng, cnt, support=e)
                assert 1 <= sum(a != b for a, b in zip(p, target)) <= e
                assert passes_oracle(setup, p, head[:r]), (seed, r, e)
    print("  keyless support: e = 1 caught by self-check, e >= r + 2 valid vs observed")


def test_never_silent():
    for cell in sweep_cells(ms=(2,), g=4):
        for seed in range(15):
            row = run_trial(cell, seed)
            assert row["silent"] == 0 and row["decoded"] == 1, (cell, seed, row)
    print("  no silent decode, every trial decodes")


if __name__ == "__main__":
    test_theory()
    test_polluters_only_touch_tags()
    test_keyless_support()
    test_never_silent()
    print("all S3 tests passed")
