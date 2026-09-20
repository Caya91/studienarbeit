"""
Tests for the matched recovery-acceptance width W (ADR-0013, ticket 10).

Meant to be read, not just run. W caps how many checks a repaired candidate must
pass before it is accepted, matched across the two arms so their nominal collision
is comparable (~q^-W):
  - keyless (`is_orthogonal_to_trusted`): self-check (always, free, uncounted) AND
    orthogonality to the FIRST W trusted packets.
  - keyed (`mac_verify_segment`): verify the FIRST W MAC tags only.

The cap-semantics tests are exact and deterministic (they construct a candidate that
passes exactly the first k checks and fails the (k+1)-th). The rate tests are light
Monte-Carlo with a fixed seed and loose tolerance: they only assert monotonicity in W
and that one extra check cuts survivors by ~1/q, which is the property W exists to give.
"""
import random

from binary_ext_fields.custom_field import create_field
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.generate_symbols import check_orth_packet
from playground.new_recovery import is_orthogonal_to_trusted
from binary_ext_fields.segmented_mac_tagging import MacSegment, mac_tag_vector, mac_verify_segment


def _banner(name):
    print(f"\n=== {name} ===")


def _rand_vec(rng, field, length):
    return bytearray(rng.randint(0, field.max_value) for _ in range(length))


def _self_orth_vec(rng, field, length):
    """A vector that passes the self-check (self inner product 0). ~1/q of random
    vectors do, so a handful of draws finds one -- no reliance on the field's internals."""
    while True:
        v = _rand_vec(rng, field, length)
        if check_orth_packet(field, v):
            return v


# ── Keyless: W caps the cross-check to the first W trusted packets ────────────

def test_keyless_W_checks_only_the_first_W_trusted_packets():
    _banner("keyless: W checks only the first W trusted witnesses")
    field = create_field(4)
    L = 6
    rng = random.Random(1)

    c = _self_orth_vec(rng, field, L)
    # Two witnesses orthogonal to c, then one that is NOT -- placed in that order so
    # W in {0,1,2} accept and W>=3 (and W=None) reject on the third.
    orth, nonorth = [], []
    while len(orth) < 2 or len(nonorth) < 1:
        w = _rand_vec(rng, field, L)
        (orth if inner_product_bytes(field, c, w) == 0 else nonorth).append(w)
    trusted = [orth[0], orth[1], nonorth[0]]

    accepts = {W: is_orthogonal_to_trusted(field, c, trusted, W=W) for W in (0, 1, 2, 3, None)}
    print(f"  self-orth candidate, trusted=[orth, orth, NON-orth]; accepts={accepts}")
    assert accepts[0] is True, "W=0 is self-check only -> a self-orth candidate passes"
    assert accepts[1] is True, "first trusted is orthogonal"
    assert accepts[2] is True, "first two trusted are orthogonal"
    assert accepts[3] is False, "third trusted is non-orthogonal -> rejected once checked"
    assert accepts[None] is False, "None checks all -> the non-orth third rejects"


def test_keyless_self_check_is_mandatory_even_at_W_zero():
    _banner("keyless: self-check always applies, even at W=0 / empty trusted")
    field = create_field(4)
    L = 6
    rng = random.Random(7)

    bad = _rand_vec(rng, field, L)
    while check_orth_packet(field, bad):        # want a NON-self-orthogonal candidate
        bad = _rand_vec(rng, field, L)
    trusted = [_rand_vec(rng, field, L) for _ in range(3)]

    print("  non-self-orth candidate must be rejected regardless of W")
    assert is_orthogonal_to_trusted(field, bad, trusted, W=0) is False
    assert is_orthogonal_to_trusted(field, bad, [], W=0) is False          # no witnesses, self-check still bites
    assert is_orthogonal_to_trusted(field, bad, trusted, W=None) is False


def test_keyless_wrong_accept_rate_scales_like_one_over_q_per_witness():
    _banner("keyless: each extra witness cuts survivors by ~1/q; W=None == W=len(trusted)")
    field = create_field(4)
    q = field.max_value + 1                     # 16
    L = 6
    rng = random.Random(2)

    trusted = [_rand_vec(rng, field, L) for _ in range(3)]
    N = 20000
    counts = {0: 0, 1: 0, 2: 0, 3: 0, None: 0}
    for _ in range(N):
        cand = _rand_vec(rng, field, L)
        for W in counts:
            if is_orthogonal_to_trusted(field, cand, trusted, W=W):
                counts[W] += 1

    print(f"  q={q}, N={N}, pass counts by W: {counts}")
    # Monotonic: more checks -> no more survivors.
    assert counts[0] >= counts[1] >= counts[2] >= counts[3]
    # "all" is exactly "W = number of trusted".
    assert counts[None] == counts[3], "W=None must equal checking every trusted packet"
    # Self-check alone passes ~1/q of random candidates.
    assert 1 / (q * 1.6) < counts[0] / N < 1.6 / q, "W=0 (self-check) pass rate ~1/q"
    # One added independent witness cuts survivors by ~1/q (loose bounds, fixed seed).
    ratio = counts[1] / counts[0]
    print(f"  counts[1]/counts[0] = {ratio:.4f} (expect ~1/q = {1/q:.4f})")
    assert 1 / (q * 2.5) < ratio < 2.5 / q


# ── Keyed: W verifies only the first W MAC tags ───────────────────────────────

def _mac_setup(rng, field, payload_len, num_keys):
    keys = [_rand_vec(rng, field, payload_len) for _ in range(num_keys)]
    segment = MacSegment("s", "data", start=0, payload_length=payload_len, num_keys=num_keys)
    return keys, segment


def test_keyed_W_verifies_only_the_first_W_tags():
    _banner("keyed: W verifies only the first W tags")
    field = create_field(4)
    rng = random.Random(3)
    payload_len, K, W = 5, 4, 2
    keys, segment = _mac_setup(rng, field, payload_len, K)

    payload = _rand_vec(rng, field, payload_len)
    good_tags = mac_tag_vector(field, keys, payload)

    # Slice whose FIRST W tags are correct for this payload but the rest are wrong:
    # verifies at W (first-W recompute-and-match) but fails once a later tag is checked.
    tags = list(good_tags)
    for j in range(W, K):
        tags[j] = (tags[j] + 1) % (field.max_value + 1)
    partial = bytearray(payload) + bytearray(tags)

    print(f"  first {W} tags correct, tags[{W}:] corrupted")
    assert mac_verify_segment(field, keys, partial, segment, W=W) is True
    assert mac_verify_segment(field, keys, partial, segment, W=W + 1) is False
    assert mac_verify_segment(field, keys, partial, segment, W=K) is False
    assert mac_verify_segment(field, keys, partial, segment, W=None) is False

    # A fully correct slice verifies at every width.
    good = bytearray(payload) + bytearray(good_tags)
    assert mac_verify_segment(field, keys, good, segment, W=None) is True
    for W_ok in range(1, K + 1):
        assert mac_verify_segment(field, keys, good, segment, W=W_ok) is True


def test_keyed_W_beyond_num_keys_raises():
    _banner("keyed: W > num_keys asserts (cannot check more tags than are carried)")
    field = create_field(4)
    rng = random.Random(11)
    payload_len, K = 5, 4
    keys, segment = _mac_setup(rng, field, payload_len, K)
    payload = _rand_vec(rng, field, payload_len)
    good = bytearray(payload) + bytearray(mac_tag_vector(field, keys, payload))

    raised = False
    try:
        mac_verify_segment(field, keys, good, segment, W=K + 1)
    except AssertionError:
        raised = True
    print(f"  W={K+1} on num_keys={K} raised AssertionError: {raised}")
    assert raised, "W beyond num_keys must assert, not silently check fewer/more"


def test_keyed_wrong_accept_rate_scales_like_one_over_q_per_tag():
    _banner("keyed: each extra verified tag cuts survivors by ~1/q")
    field = create_field(4)
    q = field.max_value + 1
    rng = random.Random(4)
    payload_len, K = 5, 4
    keys, segment = _mac_setup(rng, field, payload_len, K)

    N = 20000
    passes = {1: 0, 2: 0}
    for _ in range(N):
        payload = _rand_vec(rng, field, payload_len)
        tags = _rand_vec(rng, field, K)               # random (almost surely wrong) tags
        sl = bytearray(payload) + bytearray(tags)
        for W in passes:
            if mac_verify_segment(field, keys, sl, segment, W=W):
                passes[W] += 1

    print(f"  q={q}, N={N}, pass counts by W: {passes}")
    assert passes[1] > passes[2], "verifying a 2nd tag must reject more"
    assert 1 / (q * 1.6) < passes[1] / N < 1.6 / q, "one tag matches ~1/q of the time"
    ratio = passes[2] / passes[1]
    print(f"  passes[2]/passes[1] = {ratio:.4f} (expect ~1/q = {1/q:.4f})")
    assert 1 / (q * 2.5) < ratio < 2.5 / q


if __name__ == "__main__":
    tests = [
        test_keyless_W_checks_only_the_first_W_trusted_packets,
        test_keyless_self_check_is_mandatory_even_at_W_zero,
        test_keyless_wrong_accept_rate_scales_like_one_over_q_per_witness,
        test_keyed_W_verifies_only_the_first_W_tags,
        test_keyed_W_beyond_num_keys_raises,
        test_keyed_wrong_accept_rate_scales_like_one_over_q_per_tag,
    ]
    for test in tests:
        test()
        print(f"{test.__name__} passed")
    print("\nAll W acceptance-width tests passed!")
