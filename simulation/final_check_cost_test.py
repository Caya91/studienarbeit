"""
Ticket 20: the post-repair whole-pool check (report.ok) is excluded from the harness
recovery cost and reported separately.

- entries with final_check=False: same repaired packets, ok=None, fewer ops;
- harness: recovery_ops (repair only) + final_check_ops == ops of the old full call
  (final_check=True), per arm, same seed; outcomes unchanged.

Judge pass/fail by exit code (0 = pass).
"""
from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.segmented_recovery import recover_arc_only
from binary_ext_fields.segmented_mac_recovery import recover_arc_only_mac
from simulation.isolated_recovery_sim import (
    build_paired_pools, run_config, inject_paired, injected_trust_map, coeff_clean_targets,
)


def _banner(name):
    print(f"\n=== {name} ===")


def _entry_ops(pools, inj, arm, final_check):
    f = pools.field
    f.reset()
    if arm == "keyless":
        tr = injected_trust_map(pools.kl_clean, inj.kl, pools.kl_segments, pools.helper_idx, pools.target_idx)
        ccl = coeff_clean_targets(pools.kl_clean, inj.kl, pools.kl_segments, pools.target_idx)
        rep = recover_arc_only(f, inj.kl, pools.kl_segments, pools.gen_size, basis_idx=pools.helper_idx,
                               coeff_clean_target_idx=ccl, max_combined_hd=2, candidates_budget=20000, W=2,
                               injected_trust_by_segment=tr, bitflip_only=True, final_check=final_check)
    else:
        tr = injected_trust_map(pools.kd_clean, inj.kd, pools.kd_segments, pools.helper_idx, pools.target_idx)
        ccl = coeff_clean_targets(pools.kd_clean, inj.kd, pools.kd_segments, pools.target_idx)
        rep = recover_arc_only_mac(f, pools.keyset, inj.kd, pools.kd_segments, pools.gen_size,
                                   basis_idx=pools.helper_idx, coeff_clean_target_idx=ccl, max_combined_hd=2,
                                   candidates_budget=20000, W=2, injected_trust_by_segment=tr,
                                   early_exit=True, final_check=final_check)
    return rep, f.mul_count + f.add_count


def test_entry_final_check_off_same_packets():
    _banner("entries: final_check=False -> same repaired packets, ok=None, fewer ops")
    for seed in (1, 2):
        pools = build_paired_pools(CountingField(create_field(8)), 6, 18, 3, 6, seed)
        inj = inject_paired(pools, 0.006, "data_only", seed=seed * 131 + 7)
        for arm in ("keyless", "keyed"):
            on, ops_on = _entry_ops(pools, inj, arm, True)
            off, ops_off = _entry_ops(pools, inj, arm, False)
            assert on.packets == off.packets, f"{arm}: final_check must not change the repair"
            assert off.ok is None and on.ok in (True, False)
            assert ops_off < ops_on, f"{arm}: skipping the pool check must save ops"
            print(f"  seed {seed} {arm}: ops {ops_on} -> {ops_off} (pool check {ops_on - ops_off})")


def test_harness_repair_plus_final_check_equals_old_total():
    _banner("harness: recovery_ops + final_check_ops == old full-call ops; outcomes unchanged")
    for seed in (1, 2, 3):
        pools = build_paired_pools(CountingField(create_field(8)), 6, 18, 3, 6, seed)
        for config in ("arc_only_a", "arc_only_b"):
            res = run_config(pools, config, 0.006, 2, seed)
            inj = res.inj
            for arm, ar in (("keyless", res.keyless), ("keyed", res.keyed)):
                _, old_total = _entry_ops(pools, inj, arm, True)
                assert ar.ops + ar.final_check_ops == old_total, \
                    f"seed {seed} {config} {arm}: {ar.ops}+{ar.final_check_ops} != {old_total}"
                assert ar.final_check_ops > 0 and ar.final_check_time_s > 0
        print(f"  seed {seed}: ARC a/b both arms: repair + final check == old total")


if __name__ == "__main__":
    tests = [test_entry_final_check_off_same_packets, test_harness_repair_plus_final_check_equals_old_total]
    for test in tests:
        test()
        print(f"{test.__name__} passed")
    print("\nAll final-check-cost tests passed!")
