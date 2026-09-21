"""
Tests for the isolated recovery comparison harness (ADR-0013, ticket 13).

These pin the harness's hard invariants (mechanics, not silent-decode levels):
  - the paired ground-truth invariant: [coeff|payload] info columns are byte-identical
    across the two arms, clean AND after corruption;
  - injected trust bypasses sniffing (helpers are the witnesses/basis, never scored,
    never mutated);
  - the wiring self-check: data-only BER at a strong (large) W gives ~0 silent decodes
    in BOTH arms, and -- since data-only makes the two arms face identical corruption
    with identical (bit-flip-only) method -- their per-target outcomes match exactly;
  - symmetric drop under whole-packet BER (b): identical coeff-corrupted (dropped)
    target set across arms.

Judge pass/fail by exit code (0 = pass); banners print "assert"/"error" as prose.
Run: see isolated_recovery_sim.py's header (PowerShell, .venv, LOG_FOLDER set).
"""
from binary_ext_fields.custom_field import create_field, CountingField

from simulation.isolated_recovery_sim import (
    build_paired_pools,
    assert_paired_info_columns,
    inject_paired,
    assert_identical_info_corruption,
    coeff_clean_targets,
    run_config,
    info_columns,
    RECOVERED, SILENT, FAILED,
)


def _banner(name):
    print(f"\n=== {name} ===")


def _pools(seed=7, gen_size=6, T=8, data_fields=18, num_data_segments=3):
    field = CountingField(create_field(8))
    pools = build_paired_pools(field, gen_size, data_fields, num_data_segments, T, seed)
    return pools


def test_paired_info_invariant_clean_and_corrupted():
    _banner("paired invariant: [coeff|payload] identical across arms, clean and corrupted")
    pools = _pools()
    assert_paired_info_columns(pools)  # clean
    print("  clean pools: info columns identical across arms")
    for model in ("data_only", "whole_packet"):
        inj = inject_paired(pools, ber=0.02, model=model, seed=123)
        assert_identical_info_corruption(pools, inj)
        # helpers never corrupted
        for h in pools.helper_idx:
            assert inj.kl[h] == pools.kl_clean[h], "keyless helper must not be corrupted"
            assert inj.kd[h] == pools.kd_clean[h], "keyed helper must not be corrupted"
        print(f"  model={model}: corrupted info columns identical across arms; helpers untouched")


def test_data_only_strong_W_zero_silent_and_symmetric_outcomes():
    _banner("wiring self-check: data-only at large W -> 0 silent, arms match target-for-target")
    pools = _pools()
    W = pools.gen_size  # strong oracle
    res = run_config(pools, "arc_only_a", ber=0.02, W=W, seed=7)
    print(f"  keyless: rec {res.keyless.recovered} silent {res.keyless.silent} fail {res.keyless.failed}")
    print(f"  keyed  : rec {res.keyed.recovered} silent {res.keyed.silent} fail {res.keyed.failed}")
    assert res.keyless.silent == 0, "strong oracle must give ~0 silent decodes (keyless)"
    assert res.keyed.silent == 0, "strong oracle must give ~0 silent decodes (keyed)"
    # Data-only => identical corruption + identical (bit-flip) method + strong oracle
    # => the two arms must reach the SAME per-target verdict.
    for t in pools.target_idx:
        assert res.keyless.outcomes[t] == res.keyed.outcomes[t], \
            f"data-only strong-W: target {t} differs ({res.keyless.outcomes[t]} vs {res.keyed.outcomes[t]})"
    print("  every target's keyless verdict == keyed verdict (data-only, strong W)")


def test_helpers_never_mutated_by_recovery():
    _banner("helpers are never mutated by recovery (any config)")
    for config in ("coefficient_first", "arc_only_a", "arc_only_b"):
        pools = _pools()
        res = run_config(pools, config, ber=0.02, W=2, seed=7)
        for h in pools.helper_idx:
            assert res.kl_packets[h] == pools.kl_clean[h], f"[{config}] keyless helper {h} mutated"
            assert res.kd_packets[h] == pools.kd_clean[h], f"[{config}] keyed helper {h} mutated"
        print(f"  {config}: all {len(pools.helper_idx)} helpers unchanged after recovery, both arms")


def test_symmetric_drop_set_in_whole_packet():
    _banner("symmetric drop (b): coeff-corrupted (dropped) target set identical across arms")
    pools = _pools()
    res = run_config(pools, "arc_only_b", ber=0.03, W=2, seed=7)
    # The drop decision is driven by coeff-corruption ground truth, which is identical
    # across arms (paired info columns) -> the coeff-clean (kept) sets must match, hence
    # the dropped sets match.
    kl_clean = set(coeff_clean_targets(pools.kl_clean, res.inj.kl, pools.kl_segments, pools.target_idx))
    kd_clean = set(coeff_clean_targets(pools.kd_clean, res.inj.kd, pools.kd_segments, pools.target_idx))
    kl_dropped = set(pools.target_idx) - kl_clean
    kd_dropped = set(pools.target_idx) - kd_clean
    print(f"  keyless coeff-dropped targets: {sorted(kl_dropped)}")
    print(f"  keyed   coeff-dropped targets: {sorted(kd_dropped)}")
    assert kl_dropped == kd_dropped, "coeff-corrupted (dropped) target set must be identical across arms"


def test_all_configs_run_and_score_all_targets():
    _banner("all 3 configs x 2 arms run; every target scored into one bucket")
    pools = _pools()
    for config in ("coefficient_first", "arc_only_a", "arc_only_b"):
        res = run_config(pools, config, ber=0.01, W=2, seed=7)
        for arm in (res.keyless, res.keyed):
            assert set(arm.outcomes.values()) <= {RECOVERED, SILENT, FAILED}
            assert arm.recovered + arm.silent + arm.failed == len(pools.target_idx)
            assert arm.ops > 0, "recovery must spend field ops"
        print(f"  {config}: keyless {res.keyless.recovered}/{len(pools.target_idx)} rec, "
              f"keyed {res.keyed.recovered}/{len(pools.target_idx)} rec (both fully bucketed)")


if __name__ == "__main__":
    tests = [
        test_paired_info_invariant_clean_and_corrupted,
        test_data_only_strong_W_zero_silent_and_symmetric_outcomes,
        test_helpers_never_mutated_by_recovery,
        test_symmetric_drop_set_in_whole_packet,
        test_all_configs_run_and_score_all_targets,
    ]
    for test in tests:
        test()
        print(f"{test.__name__} passed")
    print("\nAll isolated-recovery harness tests passed!")
