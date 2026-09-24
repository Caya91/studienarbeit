"""
Ticket 18: early-exit keyed MAC verification.

`mac_verify_segment(..., early_exit=True)` must return exactly the same bool as the
default (all-W-tags) path -- it only changes the op count. In the isolated harness,
per-target outcomes must be identical with/without early exit and keyed ops never higher.

Judge pass/fail by exit code (0 = pass). Run like the other tests (PYTHONPATH=., LOG_FOLDER set).
"""
import random

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.segmented_mac_tagging import mac_verify_segment
from simulation.isolated_recovery_sim import build_paired_pools, run_config, kd_slice


def _banner(name):
    print(f"\n=== {name} ===")


def test_early_exit_same_bool_all_W():
    _banner("mac_verify_segment: early_exit returns the same bool as the full path, every W")
    rng = random.Random(18)
    pools = build_paired_pools(CountingField(create_field(8)), 6, 18, 3, 6, seed=3)
    field = pools.field
    checked = accepted = 0
    for s, seg in enumerate(pools.kd_segments):
        keys = pools.keyset[s]
        for t in pools.target_idx:
            clean = bytearray(kd_slice(pools.kd_clean[t], seg))
            for trial in range(300):
                cand = bytearray(clean)
                for _ in range(rng.randint(0, 2)):          # 0 flips -> valid, else usually invalid
                    cand[rng.randrange(len(cand))] ^= 1 << rng.randrange(8)
                for W in range(0, seg.num_keys + 1):
                    a = mac_verify_segment(field, keys, cand, seg, W=W)
                    b = mac_verify_segment(field, keys, cand, seg, W=W, early_exit=True)
                    assert a == b, f"seg {seg.name} t{t} W={W}: full={a} early={b}"
                    checked += 1
                    accepted += a
    print(f"  {checked} (candidate, W) checks agree ({accepted} accepted)")


def test_early_exit_fewer_ops_on_reject():
    _banner("early_exit: a candidate failing tag 0 costs 1 inner product instead of W")
    pools = build_paired_pools(CountingField(create_field(8)), 6, 18, 3, 6, seed=3)
    field, seg, keys = pools.field, pools.kd_segments[1], pools.keyset[1]
    cand = bytearray(kd_slice(pools.kd_clean[pools.target_idx[0]], seg))
    cand[seg.payload_length] ^= 0x01                         # tag 0 wrong -> reject at the first tag
    ops = {}
    for early in (False, True):
        field.reset()
        assert not mac_verify_segment(field, keys, cand, seg, W=6, early_exit=early)
        ops[early] = field.mul_count + field.add_count
    print(f"  W=6 reject: full {ops[False]} ops, early-exit {ops[True]} ops")
    assert ops[True] * 6 == ops[False], "early exit should cost exactly 1/W of the full verify here"


def test_harness_outcomes_identical_keyed_ops_not_higher():
    _banner("harness: outcomes identical with/without keyed early exit; keyed ops <= ")
    for seed in (1, 2, 3):
        pools = build_paired_pools(CountingField(create_field(8)), 6, 18, 3, 6, seed)
        for config in ("coefficient_first", "arc_only_a", "arc_only_b"):
            for W in (1, 3, 6):
                a = run_config(pools, config, 0.006, W, seed, keyed_early_exit=False)
                b = run_config(pools, config, 0.006, W, seed, keyed_early_exit=True)
                assert a.keyed.outcomes == b.keyed.outcomes, f"{config} W={W} seed {seed}: keyed outcomes differ"
                assert a.keyless.outcomes == b.keyless.outcomes and a.keyless.ops == b.keyless.ops, \
                    "keyless arm must be untouched by the keyed flag"
                assert b.keyed.ops <= a.keyed.ops, f"{config} W={W}: early exit used MORE ops"
        print(f"  seed {seed}: 3 configs x W in (1,3,6) identical outcomes, keyed ops <=")


if __name__ == "__main__":
    tests = [
        test_early_exit_same_bool_all_W,
        test_early_exit_fewer_ops_on_reject,
        test_harness_outcomes_identical_keyed_ops_not_higher,
    ]
    for test in tests:
        test()
        print(f"{test.__name__} passed")
    print("\nAll keyed early-exit tests passed!")
