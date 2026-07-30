"""Investigation + test bench for the two gate functions of the incremental
recovery/decode sim (recovery_decode_sim.py):

    sniff_pool(field, pool, min_trust_count, min_pool_size)  -> (broken, trusted)
    _try_decode(field, accepted, gen_size, source_suffix)    -> (decoded, correct)

Two things live here, kept deliberately separate:

1. DEMOS (`demo_sniff`, `demo_try_decode`) -- narrated, aligned-table walkthroughs of
   a single hand-built scenario. They print not just the return value but the internal
   reasoning behind it (per-packet self-check result, cross-orthogonality witness
   counts, the RREF/inversion of the decode basis) so the *why* is visible, not just
   the *what*. Run them to understand the functions.

2. TESTS (`test_*`) -- deterministic (seeded) assertions pinning the contract of each
   function across its interesting cases: the warm-up gate, the trust threshold, a
   self-check failure, a self-check *false positive* (the silent-decode source), and
   for decode: too-few / not-full-rank / clean / silently-wrong / redundant inputs.

Run:  .venv/Scripts/python.exe simulation/recovery_decode_test.py
(no pytest dependency; a tiny built-in harness reports PASS/FAIL and sets the exit code.)
Small field/gen sizes (GF(2^8), gen_size=3, 2 data symbols) keep every table readable.
"""

import os
import random
import sys
from pathlib import Path

# Make the file runnable directly (python simulation/recovery_decode_test.py) without
# pre-exporting PYTHONPATH / LOG_FOLDER, which the imported modules require at import time.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

from icecream import ic
ic.disable()  # sniffing/recovery icecream-dump on every call; keep the bench output clean

from binary_ext_fields.custom_field import create_field, TableField
from binary_ext_fields.generate_symbols import (
    generate_symbols_until_nonzero,
    recode_rlnc_without_coeffs,
    check_orth_packet,
    inner_product_bytes,
)
from binary_ext_fields.rref import calculate_rref, invert_pivot_rows
from playground.sniffing import sniff_pool
from playground.new_recovery import _basis_full_rank
from simulation.recovery_decode_sim import _try_decode, _accepted_packets


# ── Readable scenario sizes ──────────────────────────────────────────────────
M = 8            # GF(2^8)
GEN = 3          # coefficient-block width / full-rank basis size
DATA = 2         # data symbols per packet (cols GEN..GEN+DATA-1; then tag cols)


# ══ Builders ═════════════════════════════════════════════════════════════════

def build_pool(seed: int, count: int, gen: int = GEN, data: int = DATA, m: int = M):
    """A clean, pairwise-orthogonal recoded pool of `count` packets, plus its source.
    Seeding `random` makes the whole scenario reproducible."""
    random.seed(seed)
    field = create_field(m)
    source = generate_symbols_until_nonzero(field, data, gen, coefficients=True)
    pool = [bytearray(p) for p in recode_rlnc_without_coeffs(field, source, gen, count=count)]
    return field, source, pool


def break_self_check(field: TableField, pkt: bytearray) -> tuple[bytearray, int, int]:
    """Smallest bit-flip that makes `pkt` FAIL its self-check -> a conclusively broken
    packet. Returns (broken_pkt, col, bit). Most flips break self-orthogonality, so
    this almost always finds a single-bit one immediately."""
    for col in range(len(pkt)):
        for bit in range(field.bit_lenght):
            cand = bytearray(pkt)
            cand[col] ^= (1 << bit)
            if not check_orth_packet(field, cand):
                return cand, col, bit
    raise RuntimeError("no self-check-breaking flip found (unexpected)")


def _witness_count(field: TableField, cand: bytearray, others: list[bytearray]) -> int:
    """How many of `others` (assumed self-passing) `cand` is cross-orthogonal to -- the
    signal sniff_pool thresholds on for trust."""
    return sum(1 for o in others if inner_product_bytes(field, cand, o) == 0)


def find_self_check_false_positive(field: TableField, pool: list[bytearray]):
    """A self-check FALSE POSITIVE: a corrupted packet that still PASSES its self-check
    (so sniffing never flags it broken) yet is cross-orthogonal to NONE of the other
    packets. This is the packet that slips into the decode basis on self-check alone
    and silently poisons the decode -- exactly what the cross-verification gate exists
    to catch.

    Searches single- then double-bit flips of each pool packet and returns the first
    candidate with witness_count == 0 (orthogonal to no one). Returns
    (index_it_replaces, false_positive_pkt, flips) or (None, None, None).
    """
    n_bytes = len(pool[0])
    bits = [(c, b) for c in range(n_bytes) for b in range(field.bit_lenght)]

    for idx, pkt in enumerate(pool):
        others = [pool[j] for j in range(len(pool)) if j != idx]
        # single-bit
        for (c, b) in bits:
            cand = bytearray(pkt)
            cand[c] ^= (1 << b)
            if cand != pkt and check_orth_packet(field, cand) and _witness_count(field, cand, others) == 0:
                return idx, cand, [(c, b)]
        # double-bit fallback
        for i in range(len(bits)):
            for j in range(i + 1, len(bits)):
                (c1, b1), (c2, b2) = bits[i], bits[j]
                cand = bytearray(pkt)
                cand[c1] ^= (1 << b1)
                cand[c2] ^= (1 << b2)
                if cand != pkt and check_orth_packet(field, cand) and _witness_count(field, cand, others) == 0:
                    return idx, cand, [(c1, b1), (c2, b2)]
    return None, None, None


def source_suffix(source: list[bytearray], gen: int = GEN) -> list[bytearray]:
    """The systematic (data+tag) columns of the known source -- decode ground truth."""
    return [bytearray(p[gen:]) for p in source]


def pick_clean_pair_spanning_with(field: TableField, clean: list[bytearray], fp: bytearray,
                                  skip_idx: int, gen: int = GEN):
    """Two clean packets A, B such that {A, B, fp} is full rank (gen_size=3) -- so the
    false positive is *required* to complete the basis and therefore lands in the
    decode's pivot set. Returns (A, B) or (None, None)."""
    others = [k for k in range(len(clean)) if k != skip_idx]
    for a in range(len(others)):
        for b in range(a + 1, len(others)):
            A, B = clean[others[a]], clean[others[b]]
            if _basis_full_rank(field, [A, B, fp], gen):
                return bytearray(A), bytearray(B)
    return None, None


# ══ Pretty printing ══════════════════════════════════════════════════════════

def print_pool(title: str, pool: list[bytearray], gen: int = GEN,
               ref: list[bytearray] | None = None, notes: dict[int, str] | None = None) -> None:
    """Aligned byte table with a '|' at the coeff|data boundary. Cells differing from
    `ref` are wrapped >..<. `notes` maps row -> trailing annotation."""
    notes = notes or {}
    w = 5
    ncols = max(len(p) for p in pool)
    header = "         "
    for c in range(ncols):
        if c == gen:
            header += "  |"
        header += f"{c:>{w}}"
    print(f"\n{title}")
    print(header + f"    (cols 0..{gen - 1} = coeff | rest = data+tag)")
    for i, p in enumerate(pool):
        changed = set()
        if ref is not None:
            changed = {j for j in range(len(p)) if j >= len(ref[i]) or p[j] != ref[i][j]}
        row = f"  P[{i:>2}] "
        for c, v in enumerate(p):
            if c == gen:
                row += "  |"
            cell = f">{v}<" if c in changed else f"{v}"
            row += f"{cell:>{w}}"
        note = notes.get(i, "")
        if note:
            row += f"    {note}"
        print(row)


def _matrix(rows) -> list[list[int]]:
    return [list(r) for r in rows]


# ══ Demo 1: sniff_pool ═══════════════════════════════════════════════════════

def demo_sniff() -> None:
    print("\n" + "=" * 78)
    print("DEMO 1 -- sniff_pool: how a pool is classified into broken / trusted")
    print("=" * 78)

    field, source, clean = build_pool(seed=11, count=6)
    pool = [bytearray(p) for p in clean]

    # One conclusively broken packet (self-check fails) ...
    broken_pkt, bcol, bbit = break_self_check(field, pool[1])
    pool[1] = broken_pkt
    # ... and one self-check false positive (self-check passes, cross-check fails).
    fp_idx, fp_pkt, fp_flips = find_self_check_false_positive(field, clean)
    if fp_pkt is not None:
        pool[fp_idx] = fp_pkt

    notes = {1: f"<- broken by flip col{bcol}/bit{bbit}"}
    if fp_pkt is not None:
        notes[fp_idx] = f"<- self-check FALSE POSITIVE (flips {fp_flips})"
    print_pool("Pool (>v< = changed vs clean original):", pool, ref=clean, notes=notes)

    # Internal reasoning: self-check, then cross-orthogonality witness counts.
    self_pass = [check_orth_packet(field, p) for p in pool]
    passers = [i for i, ok in enumerate(self_pass) if ok]
    print("\nPer-packet signals (what sniff_pool computes internally):")
    print(f"  {'idx':>3} {'self-check':>11} {'witnesses':>10}   meaning")
    for i, p in enumerate(pool):
        if not self_pass[i]:
            print(f"  {i:>3} {'FAIL':>11} {'-':>10}   conclusively BROKEN")
            continue
        w = _witness_count(field, p, [pool[j] for j in passers if j != i])
        tag = "clean-looking" if w >= 3 else "self-passes but few/no witnesses"
        print(f"  {i:>3} {'pass':>11} {w:>10}   {tag}")

    print("\nsniff_pool return at three trust thresholds (min_pool_size=6):")
    for mtc in (1, 3, 5):
        broken, trusted = sniff_pool(field, pool, min_trust_count=mtc, min_pool_size=6)
        print(f"  min_trust_count={mtc}:  broken={broken}   trusted={trusted}")

    print("\nRead it: the broken packet (P[1]) is in `broken` at every threshold -- self-")
    print("check failure is conclusive. The false positive is NEVER in `broken` (it self-")
    print("passes) and is kept OUT of `trusted` by its low witness count -- that gap is")
    print("the whole point of cross-verification before admitting a packet to the basis.")


# ══ Demo 2: _try_decode ══════════════════════════════════════════════════════

def _show_decode(field, accepted, gen, suffix, label) -> None:
    print_pool(f"{label} -- accepted set fed to _try_decode:", accepted, gen=gen)
    full_rank = False
    try:
        full_rank = _basis_full_rank(field, accepted, gen) if len(accepted) >= gen else False
    except Exception as e:  # noqa: BLE001 -- display helper, never fatal
        print(f"  (rank check raised {type(e).__name__})")
    print(f"  len(accepted)={len(accepted)}  gen_size={gen}  full_rank={full_rank}")
    if full_rank:
        try:
            _, cleaned = calculate_rref(_matrix(accepted), field, gen)
            inverted = invert_pivot_rows(cleaned, field, gen)
            print("  after RREF + pivot inversion (coeff block should be the identity;")
            print("  each row's data+tag suffix is a decoded systematic symbol):")
            print_pool("    decoded rows:", [bytearray(r) for r in inverted[:gen]], gen=gen)
            for i in range(gen):
                ok = list(inverted[i][gen:]) == list(suffix[i])
                mark = "== source" if ok else "!= source  <-- WRONG (silent)"
                print(f"      row {i}: {mark}")
        except Exception as e:  # noqa: BLE001
            print(f"  (decode raised {type(e).__name__}: {e})")
    decoded, correct = _try_decode(field, accepted, gen, suffix)
    print(f"  => _try_decode returns (decoded={decoded}, correct={correct})")


def demo_try_decode() -> None:
    print("\n" + "=" * 78)
    print("DEMO 2 -- _try_decode: full-rank check, decode, and correctness compare")
    print("=" * 78)

    field, source, _pool = build_pool(seed=11, count=6)
    suffix = source_suffix(source)

    # (a) clean, full-rank basis == the source itself -> decodes to source.
    _show_decode(field, [bytearray(p) for p in source], GEN, suffix,
                 "\n[a] clean full-rank basis")

    # (b) same basis but one data byte silently corrupted -> full rank, wrong decode.
    silent = [bytearray(p) for p in source]
    silent[1][GEN] ^= 0x01  # flip one bit in packet 1's first data column
    _show_decode(field, silent, GEN, suffix,
                 "\n[b] full rank but one packet silently wrong")

    # (c) underdetermined: gen_size copies of one packet -> rank 1, not decodable.
    dup = [bytearray(source[0]) for _ in range(GEN)]
    _show_decode(field, dup, GEN, suffix,
                 "\n[c] underdetermined (duplicate rows)")

    print("\nRead it: _try_decode only reports decoded=True once the accepted coefficient")
    print("blocks reach full rank. correct=False with decoded=True is a SILENT decode --")
    print("the receiver cannot tell; only this ground-truth compare against the known")
    print("source can. That is why silent_decode_rate is the sim's real safety metric.")


# ══ Demo 3: _accepted_packets -- tying sniff and decode together ═════════════

def demo_accepted() -> None:
    print("\n" + "=" * 78)
    print("DEMO 3 -- _accepted_packets: the V-gate between sniff and decode")
    print("=" * 78)

    field, source, clean = build_pool(seed=11, count=10)
    idx, fp, flips = find_self_check_false_positive(field, clean)
    A, B = pick_clean_pair_spanning_with(field, clean, fp, idx)
    suffix = source_suffix(source)

    # A minimal pool where the false positive is the only way to reach full rank:
    # two clean packets that span the remaining dimension only together with fp.
    pool = [A, B, bytearray(fp)]
    print_pool("A 3-packet pool: two clean (P[0],P[1]) + one false positive (P[2]):",
               pool, notes={2: f"<- false positive (flips {flips})"})

    print("\n_accepted_packets admits different sets depending on the verify count V:")
    for v in (0, 1):
        accepted = _accepted_packets(field, pool, decode_verify_count=v, min_pool_size=3)
        has_fp = any(p == fp for p in accepted)
        decoded, correct = _try_decode(field, accepted, GEN, suffix)
        verdict = ("SILENT WRONG DECODE" if (decoded and not correct)
                   else "correct decode" if decoded else "not decoded (safe wait)")
        print(f"  V={v}: admitted {len(accepted)} packet(s), false_positive_in_basis={has_fp}"
              f"  ->  _try_decode=(decoded={decoded}, correct={correct})  [{verdict}]")

    print("\nRead it: at V=0 the false positive is admitted on self-check alone, completes a")
    print("full-rank basis, and _try_decode succeeds while decoding WRONG. One cross-check")
    print("witness (V=1) is enough to exclude it -- the basis no longer spans, so the")
    print("receiver safely WAITS for a real packet instead of decoding garbage.")


# ══ Tests: sniff_pool ════════════════════════════════════════════════════════

def test_sniff_below_min_pool_size_is_empty():
    field, _src, pool = build_pool(seed=1, count=4)
    broken, trusted = sniff_pool(field, pool, min_trust_count=1, min_pool_size=10)
    assert broken == [] and trusted == [], f"warm-up gate should return ([],[]), got {(broken, trusted)}"


def test_sniff_clean_pool_all_trusted():
    field, _src, pool = build_pool(seed=2, count=10)
    broken, trusted = sniff_pool(field, pool, min_trust_count=3, min_pool_size=10)
    assert broken == [], f"clean pool must have no broken, got {broken}"
    assert trusted == list(range(10)), f"all clean packets must be trusted, got {trusted}"


def test_sniff_trust_threshold_is_exclusive_boundary():
    # 10 clean packets -> each is cross-orthogonal to the other 9 (witness count 9).
    field, _src, pool = build_pool(seed=3, count=10)
    _b, trusted_at_9 = sniff_pool(field, pool, min_trust_count=9, min_pool_size=10)
    _b, trusted_at_10 = sniff_pool(field, pool, min_trust_count=10, min_pool_size=10)
    assert trusted_at_9 == list(range(10)), f"9 witnesses >= 9 should trust all, got {trusted_at_9}"
    assert trusted_at_10 == [], f"9 witnesses < 10 should trust none, got {trusted_at_10}"


def test_sniff_self_check_failure_is_broken():
    field, _src, pool = build_pool(seed=4, count=10)
    pool[0], _c, _bit = break_self_check(field, pool[0])
    broken, trusted = sniff_pool(field, pool, min_trust_count=1, min_pool_size=10)
    assert 0 in broken, f"self-check failure must be flagged broken, got broken={broken}"
    assert 0 not in trusted, f"a broken packet must never be trusted, got trusted={trusted}"


def test_sniff_broken_packets_lower_witness_counts():
    # Break 2 packets -> the 8 survivors each see only 7 other self-passers.
    field, _src, pool = build_pool(seed=5, count=10)
    for i in (0, 1):
        pool[i], _c, _b = break_self_check(field, pool[i])
    _b, trusted_at_7 = sniff_pool(field, pool, min_trust_count=7, min_pool_size=10)
    _b, trusted_at_8 = sniff_pool(field, pool, min_trust_count=8, min_pool_size=10)
    assert set(trusted_at_7) == set(range(2, 10)), f"survivors have 7 witnesses -> trusted at 7, got {trusted_at_7}"
    assert trusted_at_8 == [], f"7 witnesses < 8 -> none trusted at 8, got {trusted_at_8}"


def test_sniff_false_positive_self_passes_but_not_trusted():
    field, _src, clean = build_pool(seed=6, count=10)
    idx, fp, _flips = find_self_check_false_positive(field, clean)
    assert fp is not None, "expected to construct a self-check false positive"
    pool = [bytearray(p) for p in clean]
    pool[idx] = fp

    broken, trusted = sniff_pool(field, pool, min_trust_count=1, min_pool_size=10)
    assert idx not in broken, f"false positive self-passes, so must NOT be broken; broken={broken}"
    assert idx not in trusted, f"cross-check must exclude the false positive from trusted; trusted={trusted}"


# ══ Tests: _try_decode ═══════════════════════════════════════════════════════

def test_decode_too_few_packets_is_undecoded():
    field, source, _pool = build_pool(seed=7, count=6)
    suffix = source_suffix(source)
    decoded, correct = _try_decode(field, [bytearray(source[0]), bytearray(source[1])], GEN, suffix)
    assert (decoded, correct) == (False, False), f"fewer than gen_size rows must be undecoded, got {(decoded, correct)}"


def test_decode_clean_source_basis_is_correct():
    field, source, _pool = build_pool(seed=7, count=6)
    suffix = source_suffix(source)
    decoded, correct = _try_decode(field, [bytearray(p) for p in source], GEN, suffix)
    assert decoded and correct, f"clean identity basis must decode correctly, got {(decoded, correct)}"


def test_decode_recoded_full_rank_is_correct():
    # 8 genuine recoded packets: full rank with overwhelming probability, all correct.
    field, source, pool = build_pool(seed=8, count=8)
    suffix = source_suffix(source)
    decoded, correct = _try_decode(field, [bytearray(p) for p in pool], GEN, suffix)
    assert decoded and correct, f"correct full-rank recoded basis must decode correctly, got {(decoded, correct)}"


def test_decode_underdetermined_is_undecoded():
    field, source, _pool = build_pool(seed=9, count=6)
    suffix = source_suffix(source)
    dup = [bytearray(source[0]) for _ in range(GEN)]  # rank 1
    decoded, correct = _try_decode(field, dup, GEN, suffix)
    assert (decoded, correct) == (False, False), f"rank-deficient basis must be undecoded, got {(decoded, correct)}"


def test_decode_silent_failure_is_decoded_but_wrong():
    field, source, _pool = build_pool(seed=10, count=6)
    suffix = source_suffix(source)
    accepted = [bytearray(p) for p in source]
    accepted[1][GEN] ^= 0x01  # corrupt one data byte; coeff block (identity) untouched -> still full rank
    decoded, correct = _try_decode(field, accepted, GEN, suffix)
    assert decoded and not correct, f"a silently-wrong full-rank basis must decode=True, correct=False, got {(decoded, correct)}"


def test_decode_redundant_rows_still_correct():
    # gen_size correct packets + extra correct rows -> still decodes correctly.
    field, source, pool = build_pool(seed=12, count=6)
    suffix = source_suffix(source)
    accepted = [bytearray(p) for p in source] + [bytearray(pool[0]), bytearray(pool[1])]
    decoded, correct = _try_decode(field, accepted, GEN, suffix)
    assert decoded and correct, f"redundant correct rows must still decode correctly, got {(decoded, correct)}"


# ══ Tests: _accepted_packets (the V-gate wrapper) ════════════════════════════

def test_accepted_v0_includes_self_passers_and_false_positive():
    field, _src, clean = build_pool(seed=22, count=10)
    idx, fp, _f = find_self_check_false_positive(field, clean)
    assert fp is not None
    pool = [bytearray(p) for p in clean]
    pool[idx] = fp
    accepted = _accepted_packets(field, pool, decode_verify_count=0)
    assert len(accepted) == 10, f"V=0 admits every self-passer (fp included), got {len(accepted)}"
    assert any(p == fp for p in accepted), "V=0 must admit the self-check false positive"


def test_accepted_v0_excludes_self_check_failures():
    field, _src, clean = build_pool(seed=23, count=10)
    pool = [bytearray(p) for p in clean]
    pool[0], _c, _b = break_self_check(field, pool[0])
    accepted = _accepted_packets(field, pool, decode_verify_count=0)
    assert len(accepted) == 9, f"the broken packet must be excluded, got {len(accepted)}"
    assert all(check_orth_packet(field, p) for p in accepted), "every admitted packet must self-pass"


def test_accepted_v0_ignores_min_pool_size():
    # The V=0 path is a pure self-check filter -- it has no warm-up (min_pool_size) gate,
    # unlike the V>0 path which delegates to sniff_pool.
    field, _src, pool = build_pool(seed=24, count=4)
    accepted = _accepted_packets(field, pool, decode_verify_count=0, min_pool_size=10)
    assert len(accepted) == 4, f"V=0 must not apply the min_pool_size gate, got {len(accepted)}"


def test_accepted_v_positive_excludes_false_positive():
    field, _src, clean = build_pool(seed=25, count=10)
    idx, fp, _f = find_self_check_false_positive(field, clean)
    assert fp is not None
    pool = [bytearray(p) for p in clean]
    pool[idx] = fp
    accepted = _accepted_packets(field, pool, decode_verify_count=2, min_pool_size=10)
    assert all(p != fp for p in accepted), "V>=1 must exclude the false positive"
    a_clean = clean[(idx + 1) % 10]
    assert any(p == a_clean for p in accepted), "well-witnessed clean packets must still be admitted"


def test_accepted_v_positive_matches_sniff_trusted():
    # Contract: for V>0, _accepted_packets is exactly sniff_pool's trusted set (as packets).
    field, _src, clean = build_pool(seed=26, count=10)
    idx, fp, _f = find_self_check_false_positive(field, clean)
    pool = [bytearray(p) for p in clean]
    pool[idx] = fp
    _broken, trusted = sniff_pool(field, pool, min_trust_count=2, min_pool_size=10)
    expected = [pool[i] for i in trusted]
    accepted = _accepted_packets(field, pool, decode_verify_count=2, min_pool_size=10)
    assert accepted == expected, "V>0 must return exactly sniff_pool's trusted packets"


def test_accepted_v_positive_below_min_pool_size_is_empty():
    field, _src, pool = build_pool(seed=27, count=4)
    accepted = _accepted_packets(field, pool, decode_verify_count=1, min_pool_size=10)
    assert accepted == [], f"V>0 honours the warm-up gate, got {len(accepted)}"


def test_v_gate_turns_silent_decode_into_safe_wait():
    """End-to-end: the same pool that silently decodes wrong at V=0 safely waits at V=1,
    because the cross-check evicts the false positive that was completing the basis."""
    field, source, clean = build_pool(seed=28, count=10)
    idx, fp, _f = find_self_check_false_positive(field, clean)
    assert fp is not None, "expected a constructible false positive"
    A, B = pick_clean_pair_spanning_with(field, clean, fp, idx)
    assert A is not None, "expected a clean pair that spans only together with the fp"
    pool = [A, B, bytearray(fp)]
    suffix = source_suffix(source)

    accepted0 = _accepted_packets(field, pool, decode_verify_count=0, min_pool_size=3)
    assert any(p == fp for p in accepted0), "V=0 admits the fp"
    assert _try_decode(field, accepted0, GEN, suffix) == (True, False), \
        "V=0 must produce a silent (decoded-but-wrong) decode"

    accepted1 = _accepted_packets(field, pool, decode_verify_count=1, min_pool_size=3)
    assert all(p != fp for p in accepted1), "V=1 must evict the fp"
    assert _try_decode(field, accepted1, GEN, suffix) == (False, False), \
        "V=1 must fall back to a safe wait, not a wrong decode"


# ══ Tiny harness ═════════════════════════════════════════════════════════════

def _run(show_demos: bool = True) -> int:
    if show_demos:
        demo_sniff()
        demo_try_decode()
        demo_accepted()

    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    print("\n" + "=" * 78)
    print(f"TESTS  ({len(tests)} cases)")
    print("=" * 78)
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS   {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL   {name}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001 -- report, don't abort the suite
            print(f"  ERROR  {name}: {type(e).__name__}: {e}")
            failed += 1
    print("-" * 78)
    print(f"  {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run(show_demos=True))
