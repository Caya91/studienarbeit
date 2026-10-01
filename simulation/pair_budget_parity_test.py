"""
Budget parity of the pair repair path, keyless vs keyed (bug fixed 2026-10-01).

A pair of broken packets is repaired in up to three searches: the combined search over
Sc = a XOR b, then (IC-refinement fallback) one search per half. Both arms must give
EVERY search its own candidates_budget. The keyed arm used to share one budget across all
three, so a combined search that used the budget up left nothing for the fallback and
keyed recovered less than keyless at the same W for budget reasons alone.

Fixture: two targets with the SAME bit flipped in the same data column. The flips cancel in
Sc, so the combined search can never find them. Two budgets, each must recover both targets
in both arms:
  - exactly the combined-search size (8 + 28 for HD 2 over one ACR column): the combined
    search completes, only a FRESH budget per half leaves room for the fallback;
  - below it (20): the combined search is cut by the budget, and the fallback must STILL run
    (the keyed arm used to return right there).
Third case -- the fallback searches each half over its OWN ACR columns (keyless rule), not the
union of both halves' columns: A has flips in columns (3, 9), B in (3, 1) (column 3 the same
bit, so the combined search cannot split them). Over the union (1, 3, 9) A's fix comes after
all 156 column-1 pairs; over its own (3, 9) within 136 candidates -> budget 150 separates them.

Judge pass/fail by exit code (0 = pass).
"""
from binary_ext_fields.custom_field import CountingField, create_field
from simulation.isolated_recovery_sim import InjectedErrors, build_paired_pools, run_config

G = 4
COL, BIT = 3, 5
COMBINED_CANDIDATES_HD2_ONE_COLUMN = 8 + 28


def _same_bit_pair_injection(pools):
    kl = [bytearray(p) for p in pools.kl_clean]
    kd = [bytearray(p) for p in pools.kd_clean]
    sl = next(s for s in pools.kl_segments if s.kind == "data")
    sd = next(s for s in pools.kd_segments if s.kind == "data")
    t0, t1 = pools.target_idx[:2]
    for t in (t0, t1):
        kl[t][sl.start + COL] ^= 1 << BIT
        kd[t][sd.start + COL] ^= 1 << BIT
    per_target = {t: ([(sl.name, COL, BIT)] if t in (t0, t1) else []) for t in pools.target_idx}
    return InjectedErrors(kl=kl, kd=kd, per_target=per_target)


def _run(budget):
    pools = build_paired_pools(CountingField(create_field(8)), G, 24, 2, G, seed=3)
    res = run_config(pools, "arc_only_a", 0.0, G, seed=3, max_combined_hd=2,
                     candidates_budget=budget, inj=_same_bit_pair_injection(pools))
    return res, len(pools.target_idx)


def test_fallback_gets_fresh_budget_in_both_arms():
    res, T = _run(COMBINED_CANDIDATES_HD2_ONE_COLUMN)
    assert res.keyless.recovered == T, f"keyless {res.keyless.recovered}/{T}"
    assert res.keyed.recovered == T, (f"keyed {res.keyed.recovered}/{T}: the IC-refinement halves must get a fresh "
                                      "budget, not what the combined search left over")
    print(f"  budget = combined-search size: keyless {T}/{T}, keyed {T}/{T} (fresh budget per step)")


def test_fallback_searches_own_columns():
    pools = build_paired_pools(CountingField(create_field(8)), G, 24, 2, G, seed=3)
    kl = [bytearray(p) for p in pools.kl_clean]
    kd = [bytearray(p) for p in pools.kd_clean]
    sl = next(s for s in pools.kl_segments if s.kind == "data")
    sd = next(s for s in pools.kd_segments if s.kind == "data")
    t0, t1 = pools.target_idx[:2]
    flips = {t0: [(3, BIT), (9, 2)], t1: [(3, BIT), (1, 6)]}
    for t, fl in flips.items():
        for col, bit in fl:
            kl[t][sl.start + col] ^= 1 << bit
            kd[t][sd.start + col] ^= 1 << bit
    per_target = {t: [(sl.name, c, b) for c, b in flips.get(t, [])] for t in pools.target_idx}
    res = run_config(pools, "arc_only_a", 0.0, G, seed=3, max_combined_hd=2, candidates_budget=150,
                     inj=InjectedErrors(kl=kl, kd=kd, per_target=per_target))
    T = len(pools.target_idx)
    assert res.keyless.recovered == T, f"keyless {res.keyless.recovered}/{T}"
    assert res.keyed.recovered == T, (f"keyed {res.keyed.recovered}/{T}: IC-refinement halves must search their own "
                                      "ACR columns, not the union of both halves'")
    print(f"  fallback over each half's own columns: keyless {T}/{T}, keyed {T}/{T}")


def test_fallback_runs_after_budget_cut_combined_search():
    res, T = _run(20)
    assert res.keyless.recovered == T, f"keyless {res.keyless.recovered}/{T}"
    assert res.keyed.recovered == T, (f"keyed {res.keyed.recovered}/{T}: a combined search stopped by the budget "
                                      "must fall through to the IC-refinement fallback")
    print(f"  budget < combined-search size: keyless {T}/{T}, keyed {T}/{T} (fallback still runs)")


if __name__ == "__main__":
    from icecream import ic
    ic.disable()
    test_fallback_gets_fresh_budget_in_both_arms()
    test_fallback_runs_after_budget_cut_combined_search()
    test_fallback_searches_own_columns()
    print("\nAll pair-budget parity tests passed!")
