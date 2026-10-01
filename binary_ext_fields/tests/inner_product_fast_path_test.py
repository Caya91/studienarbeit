"""
Equivalence test for the inner-product fast path (2026-09-29).

operations.inner_product_bytes hands TableField / CountingField to their own
`inner_product` (direct table lookups) instead of the generic per-element loop
(vector_multiply_into + add). The fast path must be a pure speedup:
  - the SAME field value for every input, every field size;
  - the SAME op accounting on a CountingField: len(x) muls + len(x) adds on the
    running totals AND on the active phase bucket (nothing, not even an empty
    bucket key, for a length-0 product);
  - the SAME end-to-end simulation output: one isolated-harness seed and one
    production ACR-only trial give identical results AND identical op counts with
    and without the fast path.

Judge pass/fail by exit code (0 = pass).
"""
import random
from contextlib import contextmanager

from binary_ext_fields.custom_field import CountingField, TableField, create_field
from binary_ext_fields.operations import inner_product_bytes


@contextmanager
def generic_loop_only():
    """Temporarily remove the fast path so inner_product_bytes falls back to the loop."""
    saved = {cls: cls.__dict__["inner_product"] for cls in (TableField, CountingField)}
    try:
        for cls in saved:
            delattr(cls, "inner_product")
        yield
    finally:
        for cls, fn in saved.items():
            setattr(cls, "inner_product", fn)


def _counts(cf: CountingField):
    return cf.mul_count, cf.add_count, dict(cf.phase_mul), dict(cf.phase_add)


def test_value_and_counts_match_generic_loop():
    rng = random.Random(0)
    for m in (2, 4, 8):
        base = create_field(m)
        for length in (0, 1, 2, 7, 50):
            for _ in range(20):
                x = bytearray(rng.randint(0, base.max_value) for _ in range(length))
                y = bytearray(rng.randint(0, base.max_value) for _ in range(length))
                fast_cf, loop_cf = CountingField(base), CountingField(base)
                with fast_cf.phase("recovery"):
                    fast_val = inner_product_bytes(fast_cf, x, y)
                with generic_loop_only():
                    with loop_cf.phase("recovery"):
                        loop_val = inner_product_bytes(loop_cf, x, y)
                    plain_loop = inner_product_bytes(base, x, y)
                assert fast_val == loop_val == plain_loop == inner_product_bytes(base, x, y), \
                    f"value differs GF(2^{m}) len {length}"
                assert _counts(fast_cf) == _counts(loop_cf), \
                    f"op accounting differs GF(2^{m}) len {length}: {_counts(fast_cf)} vs {_counts(loop_cf)}"
    print("  fast path == generic loop: values, totals, phase buckets (GF(2^2/4/8), len 0..50)")


def _isolated_rows():
    from simulation.isolated_recovery_sim import sweep_seed
    rows = sweep_seed(3, gen_size=6, T=6, data_fields=60, num_data_segments=3, field_bits=8, Ws=(1, 3),
                      bers=(3e-3,), spans=("payload", "segment"), configs=("arc_only_a", "acr_only_data_tags"),
                      hds=(2,), budgets=(20000,))
    return [{k: v for k, v in r.items() if not k.endswith("time_s")} for r in rows]


def _production_trial():
    import numpy as np
    from simulation.integrity_schemes import AdmitConfig, SegmentedScheme
    from simulation.scheme_comparison_sim import run_recovery_trial
    random.seed(11)
    np.random.seed(11)
    scheme = SegmentedScheme(num_data_segments=3, data_fields=60, strategy="acr_only", name="t")
    cfg = AdmitConfig(hamming_distance=2, pair_budget=None, min_pool_size=6)
    r = run_recovery_trial(create_field(8), scheme, 60, 6, 3e-3, cfg, max_packets_factor=8,
                           error_scope="data_payload")
    d = dict(r.__dict__)
    d.pop("wall_time_s"), d.pop("time_per_packet_s")
    return d


def test_simulations_identical_with_and_without_fast_path():
    fast_iso, fast_prod = _isolated_rows(), _production_trial()
    with generic_loop_only():
        loop_iso, loop_prod = _isolated_rows(), _production_trial()
    assert fast_iso == loop_iso, "isolated-harness rows differ with the fast path"
    assert fast_prod == loop_prod, f"production trial differs: {fast_prod} vs {loop_prod}"
    assert any(r["recovery_ops"] > 0 for r in fast_iso), "probe did no repair work -- pick a harder cell"
    print(f"  isolated sweep_seed ({len(fast_iso)} rows) + production acr_only trial identical incl. op counts")


if __name__ == "__main__":
    from icecream import ic
    ic.disable()
    test_value_and_counts_match_generic_loop()
    test_simulations_identical_with_and_without_fast_path()
    print("\nAll inner-product fast-path tests passed!")
