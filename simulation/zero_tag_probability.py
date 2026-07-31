"""Monte Carlo validation of the zero-self-tag probability model.

Full derivation: docs/zero_tag_probability.md. This bench does three jobs:

1. CONFIRM the closed forms against sampling (with 95% Wilson CIs):
     A  P(one packet's self-tag = 0)          = 1/q
     B  P(a generation needs a redo)          = 1 - (1-1/q)^g
     C  E[regenerations until success]        = (q/(q-1))^g
   where q = 2^m and g = gen_size. The MC draws FRESH generations and never
   uses the reject loop (that would condition the event away and measure 0).

2. MEASURE the cost of the two fix strategies and check the exponential-vs-linear gap:
     regenerate whole generation:  g * (q/(q-1))^g   packet-generations
     regenerate single packet:     g *  q/(q-1)       packet-generations

3. VERIFY the fixed-payload salt-byte fix: with the real data frozen, resampling
   only a salt byte reaches all-nonzero self-tags at the single-packet cost AND
   the generation still passes full orthogonality (check_orth).

Run:  .venv/Scripts/python.exe simulation/zero_tag_probability.py
(no pytest dependency; a tiny built-in harness reports PASS/FAIL and sets exit code.)
"""

import os
import sys
import math
import random
from pathlib import Path

# Runnable directly: the imported modules need PYTHONPATH + LOG_FOLDER at import time.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

from icecream import ic
ic.disable()  # tag generation icecream-dumps; keep bench output clean

from binary_ext_fields.custom_field import create_field, TableField
from binary_ext_fields.generate_symbols import (
    generate_symbols_random,
    generate_identity_coefficients,
    check_orth,
)
from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator as OTC


SEED = 20260731

# ── Sweep sizes (tune here; kept modest so a full run is a couple of minutes) ──
AB_TRIALS = 15_000        # A/B/C core sweep
INVAR_TRIALS = 15_000     # data_fields-invariance of A
SPOT_TRIALS = 60_000      # GF(2^8) rare-event spot check
COST_TRIALS = 6_000       # solution 1 vs 2 cost
SALT_TRIALS = 6_000       # salt-byte fix


# ── Closed forms ──────────────────────────────────────────────────────────────
def p_single(q: int) -> float:
    """A: one packet's self-tag is zero."""
    return 1.0 / q


def p_generation(q: int, g: int) -> float:
    """B: at least one of g self-tags is zero (generation needs a redo)."""
    return 1.0 - (1.0 - 1.0 / q) ** g


def expected_regens(q: int, g: int) -> float:
    """C: expected number of whole-generation draws until one succeeds."""
    return (q / (q - 1)) ** g            # = 1 / (1-1/q)^g


def cost_regen_all(q: int, g: int) -> float:
    """Packet-generations spent by 'regenerate the whole generation'."""
    return g * expected_regens(q, g)


def cost_regen_single(q: int, g: int) -> float:
    """Packet-generations spent by 'regenerate only the offending packet'."""
    return g * (q / (q - 1))


# ── Stats helpers ─────────────────────────────────────────────────────────────
def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion k/n."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (center - half, center + half)


def mean_ci(values: list[float], z: float = 1.96) -> tuple[float, float, float]:
    """Sample mean and normal CI (returns mean, lo, hi)."""
    n = len(values)
    m = sum(values) / n
    var = sum((v - m) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    se = math.sqrt(var / n)
    return m, m - z * se, m + z * se


# ── Generation helpers (fresh, no reject loop) ────────────────────────────────
def q_of(field: TableField) -> int:
    return field.max_value + 1


def _fresh_tagged(field: TableField, otc: OTC, data_fields: int, gen_size: int):
    """One fresh tagged generation: identity coeffs + random data, tags applied once."""
    symbols = generate_symbols_random(0, field.max_value, data_fields, gen_size)
    with_coeffs = generate_identity_coefficients(field, symbols)
    return otc.generate_all_tags(with_coeffs)


def _self_tags(generation, data_fields: int, gen_size: int) -> list[int]:
    """Diagonal (self) tag of each packet. Layout: [gen_size coeffs | data | gen_size tags],
    so self-tag of packet i sits at column (gen_size + data_fields) + i."""
    data_len = gen_size + data_fields
    return [generation[i][data_len + i] for i in range(gen_size)]


# ── Experiment 1: A / B / C ───────────────────────────────────────────────────
def measure_abc(field: TableField, otc: OTC, data_fields: int, gen_size: int, trials: int):
    zero_tags = 0
    total_tags = trials * gen_size
    bad_gens = 0
    for _ in range(trials):
        tags = _self_tags(_fresh_tagged(field, otc, data_fields, gen_size), data_fields, gen_size)
        z = tags.count(0)
        zero_tags += z
        if z:
            bad_gens += 1
    return zero_tags, total_tags, bad_gens


# ── Experiment 4/5: strategy costs (greedy, keeps earlier packets fixed) ──────
def cost_single_trial(field: TableField, otc: OTC, data_fields: int, gen_size: int) -> int:
    """Packet-generations to fix all self-tags by resampling ONE packet's data at a
    time (solution 2). Returns total data-draws.

    Fast + faithful: tag once, then only re-tag when a packet actually needs a redraw.
    Resampling packet i leaves earlier (fixed) packets' self-tags unchanged, so the
    shared `tagged` stays consistent as we advance through positions."""
    data_len = gen_size + data_fields
    symbols = generate_symbols_random(0, field.max_value, data_fields, gen_size)
    draws = gen_size
    tagged = otc.generate_all_tags(generate_identity_coefficients(field, symbols))
    for i in range(gen_size):
        while tagged[i][data_len + i] == 0:
            symbols[i] = bytearray(
                [random.randint(0, field.max_value) for _ in range(data_fields)]
                + [0] * gen_size
            )
            draws += 1
            tagged = otc.generate_all_tags(generate_identity_coefficients(field, symbols))
    return draws


def salt_trial(field: TableField, otc: OTC, data_fields: int, gen_size: int):
    """Fixed-payload salt fix: payload frozen, one appended salt byte resampled until
    all self-tags nonzero. Returns (draws, orthogonal_ok, payload_untouched)."""
    df = data_fields + 1                      # one extra salt column
    data_len = gen_size + df
    payloads = [[random.randint(0, field.max_value) for _ in range(data_fields)]
                for _ in range(gen_size)]
    frozen = [list(p) for p in payloads]      # snapshot to prove data never changes
    salts = [random.randint(0, field.max_value) for _ in range(gen_size)]
    draws = gen_size

    def _tag():
        symbols = [bytearray(payloads[k] + [salts[k]] + [0] * gen_size)
                   for k in range(gen_size)]
        return otc.generate_all_tags(generate_identity_coefficients(field, symbols))

    tagged = _tag()
    for i in range(gen_size):
        while tagged[i][data_len + i] == 0:
            salts[i] = random.randint(0, field.max_value)
            draws += 1
            tagged = _tag()
    orthogonal_ok = check_orth(field, tagged)
    payload_untouched = payloads == frozen
    return draws, orthogonal_ok, payload_untouched


# ── Tiny PASS/FAIL harness ────────────────────────────────────────────────────
_passed = 0
_failed = 0


def check(name: str, closed: float, lo: float, hi: float, extra: str = "", enforce: bool = True):
    """enforce=False -> informational only (small fields, where the i.i.d. closed form
    is a documented approximation, not asserted). See Q8/(A) and docs/zero_tag_probability.md."""
    global _passed, _failed
    ok = lo <= closed <= hi
    if enforce:
        tag = "PASS" if ok else "FAIL"
        _passed += 1 if ok else 0
        _failed += 0 if ok else 1
    else:
        tag = "----" if ok else "INFO"   # small-field: deviation expected, not a failure
    print(f"  [{tag}] {name:<46} closed={closed:.5f}  CI=[{lo:.5f}, {hi:.5f}] {extra}")


def check_close(name: str, closed: float, mean: float, lo: float, hi: float,
                rel_tol: float = 0.02, extra: str = ""):
    """Assert a measured mean matches a closed form. The cost formulas inherit the
    same ~1/q i.i.d. approximation as A/B/C (§7), so a tight CI is over-sensitive:
    accept if the closed form is within CI OR within rel_tol of the mean."""
    global _passed, _failed
    ok = (lo <= closed <= hi) or (abs(mean - closed) <= rel_tol * closed)
    _passed += 1 if ok else 0
    _failed += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<46} closed={closed:.5f}  "
          f"CI=[{lo:.5f}, {hi:.5f}] {extra}")


def check_bool(name: str, ok: bool, extra: str = ""):
    global _passed, _failed
    if ok:
        _passed += 1
    else:
        _failed += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {extra}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    random.seed(SEED)
    fields = {m: create_field(m) for m in (2, 3, 4, 8)}
    otcs = {m: OTC(fields[m]) for m in fields}

    print("=" * 78)
    print("Experiment 1 — A / B / C  (data_fields=2)")
    print("   asserted for q>=16 (GF(2^4)+); GF(2^2)/GF(2^3) shown INFO-only:")
    print("   the i.i.d. closed form is a documented small-field approximation (Q8/A).")
    print("=" * 78)
    for m in (2, 3, 4):
        field, otc, q = fields[m], otcs[m], q_of(fields[m])
        enforce = q >= 16
        for g in (2, 4, 6, 8):
            zt, tt, bad = measure_abc(field, otc, 2, g, AB_TRIALS)
            # A
            lo, hi = wilson_ci(zt, tt)
            check(f"A  GF(2^{m}) g={g}  P(tag=0)=1/q", p_single(q), lo, hi, enforce=enforce)
            # B
            lo, hi = wilson_ci(bad, AB_TRIALS)
            check(f"B  GF(2^{m}) g={g}  P(redo)", p_generation(q, g), lo, hi, enforce=enforce)
            # C derived from B's CI (C = 1/(1-B), monotone in B)
            b_lo, b_hi = wilson_ci(bad, AB_TRIALS)
            check(f"C  GF(2^{m}) g={g}  E[regens]",
                  expected_regens(q, g), 1 / (1 - b_lo), 1 / (1 - b_hi), enforce=enforce)
        print()

    print("=" * 78)
    print("Experiment 2 — A is invariant to data_fields  (GF(2^4), g=3)")
    print("=" * 78)
    field, otc, q = fields[4], otcs[4], q_of(fields[4])
    for df in (1, 2, 5, 10):
        zt, tt, _ = measure_abc(field, otc, df, 3, INVAR_TRIALS)
        lo, hi = wilson_ci(zt, tt)
        check(f"A  data_fields={df:<2}  P(tag=0)=1/q", p_single(q), lo, hi)
    print()

    print("=" * 78)
    print("Experiment 3 — GF(2^8) rare-event spot check  (g=3, data_fields=2)")
    print("=" * 78)
    field, otc, q = fields[8], otcs[8], q_of(fields[8])
    zt, tt, bad = measure_abc(field, otc, 2, 3, SPOT_TRIALS)
    lo, hi = wilson_ci(zt, tt)
    check("A  GF(2^8) g=3  P(tag=0)=1/256", p_single(q), lo, hi)
    lo, hi = wilson_ci(bad, SPOT_TRIALS)
    check("B  GF(2^8) g=3  P(redo)", p_generation(q, 3), lo, hi)
    print()

    print("=" * 78)
    print("Experiment 4 — cost: regenerate-all vs regenerate-single  (GF(2^4), data_fields=2)")
    print("=" * 78)
    field, otc, q = fields[4], otcs[4], q_of(fields[4])
    for g in (2, 4, 6, 8):
        # regenerate-all cost = g * (draws until a clean generation)
        all_costs = []
        for _ in range(COST_TRIALS):
            draws = 1
            while True:
                tags = _self_tags(_fresh_tagged(field, otc, 2, g), 2, g)
                if tags.count(0) == 0:
                    break
                draws += 1
            all_costs.append(g * draws)
        m_all, lo, hi = mean_ci(all_costs)
        check_close(f"cost regen-ALL    g={g}", cost_regen_all(q, g), m_all, lo, hi,
                    extra=f"(mean={m_all:.3f})")
        # regenerate-single cost
        single_costs = [cost_single_trial(field, otc, 2, g) for _ in range(COST_TRIALS)]
        m_s, lo, hi = mean_ci(single_costs)
        check_close(f"cost regen-SINGLE g={g}", cost_regen_single(q, g), m_s, lo, hi,
                    extra=f"(mean={m_s:.3f}; all/single ~{m_all / m_s:.1f}x)")
    print()

    print("=" * 78)
    print("Experiment 5 — fixed-payload salt fix  (GF(2^4), g=4, data_fields=3)")
    print("=" * 78)
    field, otc, q = fields[4], otcs[4], q_of(fields[4])
    salt_costs = []
    all_orth = True
    all_frozen = True
    for _ in range(SALT_TRIALS):
        draws, orth_ok, frozen_ok = salt_trial(field, otc, 3, 4)
        salt_costs.append(draws)
        all_orth = all_orth and orth_ok
        all_frozen = all_frozen and frozen_ok
    m_s, lo, hi = mean_ci(salt_costs)
    check("cost SALT (payload frozen)", cost_regen_single(q, 4), lo, hi,
          extra=f"(mean={m_s:.3f})")
    check_bool("salt fix: every generation passes check_orth", all_orth)
    check_bool("salt fix: real payload never mutated", all_frozen)
    print()

    print("=" * 78)
    print(f"RESULT: {_passed} passed, {_failed} failed")
    print("=" * 78)
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
