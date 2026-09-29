"""
Tests for S2 (verification width x witness policy) and the isolated harness's
data_segment error model (2026-09-29).

Meant to be read, not just run:
  - theory sanity: the hypergeometric "random" formula reduces to the supervisor's
    k/g + (1-k/g)/q at W=1, "first" is q^-max(0, W-k), and width=all gives q^-u;
  - policy semantics in classify: witness_rank=None is today's first-verify_count choice;
    a secret rank picks, per checked packet, the lowest-rank core members -- deterministic
    for a fixed secret (same subset on every admit call), different across secrets;
  - keyed subset verification checks exactly the chosen tags;
  - the deterministic policy is exploitable exactly as predicted: a keyless forger that
    observed r >= vc packets is admitted EVERY time under "first" (the witnesses are the
    packets it saw), a keyed forger with k >= W leaked keys likewise;
  - isolated data_segment model: same payload flips as data_only for the seed, plus
    data-segment salt/tag flips, coeff segment untouched.

Judge pass/fail by exit code (0 = pass).
"""
from binary_ext_fields.custom_field import create_field
from binary_ext_fields.witness_policy import secret_rank
from simulation.verify_width_attack_sim import theory_admit, run_trial


def test_theory_formulas():
    for q in (4, 16, 256):
        g = 4
        for k in range(g + 1):
            assert abs(theory_admit("keyed", "random", k, 1, g, q) - (k / g + (1 - k / g) / q)) < 1e-12
            for W in range(1, g + 1):
                assert theory_admit("keyed", "first", k, W, g, q) == float(q) ** -max(0, W - k)
            assert theory_admit("keyed", "random", k, None, g, q) == float(q) ** -(g - k)
        for r in range(g):
            core = g - 1
            assert abs(theory_admit("keyless", "random", r, 1, g, q) - (r / core + (1 - r / core) / q)) < 1e-12
            assert theory_admit("keyless", "first", r, None, g, q) == float(q) ** -(g - 1 - r)
    print("  theory: W=1 random == k/g + (1-k/g)/q; first == q^-max(0,W-k); all == q^-u")


def test_classify_witness_rank_semantics():
    """Pool of self-passing, mutually orthogonal packets (all honest): which witnesses are
    consulted is observable by making ONE core member disagree with a checked packet."""
    from binary_ext_fields.segmented_recovery import classify_segment_trust
    import binary_ext_fields.segmented_recovery as sr
    calls = []
    real = sr.inner_product_bytes

    class Seg:  # minimal segment: whole packet
        name, start, total_length = "s", 0, 3

    # packets 0,1,2 agree with everyone; packet 3 disagrees with packets 0 and 1 only, so the
    # greedy peel drops 3 (count 2) and the core is [0, 1, 2]. Orthogonality is faked by index.
    field = create_field(8)
    pk = [bytearray([1, 1, 0]), bytearray([2, 2, 0]), bytearray([3, 3, 0]), bytearray([4, 4, 0])]
    idx = {bytes(p): i for i, p in enumerate(pk)}
    bad = {frozenset((3, 0)), frozenset((3, 1))}

    def fake(f, a, b):
        calls.append(1)
        return 1 if frozenset((idx[bytes(a)], idx[bytes(b)])) in bad else 0
    sr.inner_product_bytes = fake
    sr_check = sr.check_orth_packet
    sr.check_orth_packet = lambda f, s: True
    try:
        first = classify_segment_trust(field, pk, Seg, verify_count=1)
        # deterministic: packet 3 (peeled out of the core) is checked against core[0] = packet 0 -> rejected
        assert 3 not in first.trusted
        # a secret rank that puts packet 2 first for checked packet 3 -> accepted
        rank = lambda a, c: {2: 0, 0: 1, 1: 2}.get(c, 9)
        chosen = classify_segment_trust(field, pk, Seg, verify_count=1, witness_rank=rank)
        assert 3 in chosen.trusted
        # a real secret rank is deterministic per secret and stable across calls
        r1, r2 = secret_rank(7, "witness"), secret_rank(7, "witness")
        assert [r1(3, c) for c in range(3)] == [r2(3, c) for c in range(3)]
        assert [secret_rank(7, "witness")(3, c) for c in range(3)] != [secret_rank(8, "witness")(3, c) for c in range(3)]
    finally:
        sr.inner_product_bytes = real
        sr.check_orth_packet = sr_check
    print("  classify: rank=None -> first core witness; secret rank -> chosen subset, stable per secret")


def test_keyed_subset_verification():
    import random
    from binary_ext_fields.segmented_mac_tagging import layout_mac_segments, generate_keyset, mac_tag_vector, \
        mac_verify_key_subset
    field = create_field(8)
    seg = layout_mac_segments(4, 8, 1, 4)[1]
    keys = generate_keyset(field, [seg], random.Random(1))[0]
    payload = bytearray(range(1, seg.payload_length + 1))
    tags = mac_tag_vector(field, keys, payload)
    sl = payload + bytearray(tags)
    sl[seg.payload_length + 2] ^= 1                                  # corrupt tag 2 only
    assert mac_verify_key_subset(field, keys, sl, seg, [0, 1, 3])
    assert not mac_verify_key_subset(field, keys, sl, seg, [2])
    print("  keyed subset verify checks exactly the chosen tags")


def test_first_policy_is_predictable():
    """r >= vc (keyless) / k >= W (keyed) under "first": admitted in every trial."""
    for seed in range(6):
        t = run_trial(dict(arm="keyless", knowledge=2, field_bits=4, width=2, policy="first", g=4, hd=0), seed)
        assert t["forged_admitted"] == 1 and t["silent"] == 1, t
        t = run_trial(dict(arm="keyed", knowledge=2, field_bits=4, width=2, policy="first", g=4, hd=0), seed)
        assert t["forged_admitted"] == 1 and t["silent"] == 1, t
    print("  deterministic witnesses: forger that saw/stole the checked ones always wins (silent decode)")


def test_isolated_data_segment_model():
    from binary_ext_fields.custom_field import CountingField
    from simulation.isolated_recovery_sim import build_paired_pools, inject_paired, info_columns
    field = CountingField(create_field(8))
    pools = build_paired_pools(field, 4, 24, 2, 4, seed=5)
    a = inject_paired(pools, 0.05, "data_only", seed=11)
    b = inject_paired(pools, 0.05, "data_segment", seed=11)
    for t in pools.target_idx:
        for arm_pool, segs in ((b.kl, pools.kl_segments), (b.kd, pools.kd_segments)):
            coeff = next(s for s in segs if s.kind == "coeff")
            clean = pools.kl_clean if segs is pools.kl_segments else pools.kd_clean
            assert arm_pool[t][coeff.start:coeff.start + coeff.total_length] == \
                clean[t][coeff.start:coeff.start + coeff.total_length], "coeff segment touched"
        assert info_columns(a.kl[t], pools.kl_segments) == info_columns(b.kl[t], pools.kl_segments), \
            "payload flips must equal data_only's for the same seed"
    red = sum(1 for t in pools.target_idx for s in pools.kl_segments if s.kind == "data"
              for c in range(s.payload_length, s.total_length)
              if b.kl[t][s.start + c] != pools.kl_clean[t][s.start + c])
    assert red > 0, "BER 0.05 should hit some data salt/tag byte"
    print("  data_segment model: data_only payload flips + data salt/tag flips, coeff untouched")


if __name__ == "__main__":
    from icecream import ic
    ic.disable()
    test_theory_formulas()
    test_classify_witness_rank_semantics()
    test_keyed_subset_verification()
    test_first_policy_is_predictable()
    test_isolated_data_segment_model()
    print("\nAll verify-width / data_segment tests passed!")
