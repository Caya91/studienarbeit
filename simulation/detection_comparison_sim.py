r"""
Error DETECTION, keyless vs CRC-32 (ADR-0014 point 5).

Question: a data segment arrives with channel bit errors in its payload -- how often does
each check fail to notice? Per corrupted segment (data payload only, ADR-0014 point 4):

  keyless_W0      keyless self-check only (the free check, no helper packets needed)
  keyless_W1..Wg  self-check + orthogonality to the first W clean helper packets
  crc32           the segment's own CRC-32

Three views, all on the isolated harness's pools (build_paired_pools: G = gen_size clean
helpers, T targets, identical [coeff | data] columns in every arm):

1. EXACT undetected-pattern counts for exactly k flipped bits, k <= k_max. Both checks are
   linear in the error e (char 2): the corrupted slice passes the keyless self-check iff
   <e,e> = (sum_i e_i)^2 = 0, i.e. iff the XOR of the error bytes is 0, and witness h iff
   <e,h> = 0; the CRC (zlib.crc32, affine) passes iff crc(e) ^ crc(0^L) = 0. So each single-bit error
   has a "syndrome" (keyless: the W+1 byte values (2^b, 2^b*h_1[c], ..., 2^b*h_W[c]);
   CRC: crc of that bit), and a k-bit error is missed iff its k syndromes XOR to 0.
   Counting those k-subsets exactly gives P(miss | k) = count / C(n, k), n = 8 * payload
   bytes -- no sampling noise, also at 2^-32 where Monte Carlo sees nothing.
   Side results: keyless_W0 = per-bit-lane parity -> every odd-weight error is caught and
   the k=2 misses are exactly "same bit in two different bytes"; CRC-32 at these lengths
   has Hamming distance >= 5 -> every error of <= 4 bits is caught.
2. ANALYTIC miss probability vs BER from the exact counts: sum over k of Bin(n, k, BER) *
   P(miss | k), conditioned on >= 1 flip. k <= k_max exact; above that a tail model:
   keyless_W0 exact for every k (closed form: lane-parity generating function), keyless_W
   = keyless_W0(k) * 2^-8W (witnesses as independent byte checks), crc32 = 2^-32.
3. MEASURED (Monte Carlo) with the REAL oracles (check_orth_packet / inner products /
   crc_verify_segment): exact-k flips (validates view 1) and BER injection via the
   harness's own inject_paired("data_only") (validates view 2).

Plus the per-segment VERIFY cost (wall-clock, the user's chosen cost metric) of each level.

Run (PowerShell, project .venv):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; .\.venv\Scripts\python.exe simulation\detection_comparison_sim.py --smoke
  ... --dfs 100,300,1000 --num-data-segments 4 --seeds 20 --out logs\detection_comparison\<run>
Plots: scripts/detection_comparison_plots.py <run dir>.

Outputs (one CSV each, in the run dir):
  exact_counts.csv   df, num_data_segments, seed, segment, payload_bytes, n_bits, level, k,
                     undetected, patterns (= C(n, k)), p_miss
  analytic_ber.csv   df, num_data_segments, seed, segment, n_bits, level, ber, p_miss_given_corrupted
  mc_exact_k.csv     df, num_data_segments, seed, level, k, trials, missed
  mc_ber.csv         df, num_data_segments, seed, level, ber, corrupted_segments, missed
  verify_time.csv    df, num_data_segments, level, payload_bytes, reps, seconds_per_verify
"""
from __future__ import annotations

import csv
import random
import zlib
import time
from math import comb
from pathlib import Path

import numpy as np

from binary_ext_fields.custom_field import CountingField, create_field
from binary_ext_fields.field_backends import FIELD_BACKENDS, make_counting_field
from binary_ext_fields.generate_symbols import check_orth_packet
from binary_ext_fields.operations import inner_product_bytes
from simulation.isolated_recovery_sim import build_paired_pools, inject_paired
from simulation.segmented_crc import (
    CRC_WIDTH, Crc32Instrument, crc_verify_segment, segment_slice as crc_slice, zero_crc,
)
from binary_ext_fields.segmented_recovery import segment_slice as kl_slice
from playground.new_recovery import is_orthogonal_to_trusted

GEN_SIZE = 4            # ADR-0014: 4 keyless tag bytes per segment == one CRC-32
FIELD_BITS = 8
K_MAX = 4
SMOKE_BERS = (1e-4, 1e-3, 1e-2)
DEFAULT_BERS = (1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2)


def levels(gen_size: int) -> tuple[str, ...]:
    return tuple(f"keyless_W{w}" for w in range(gen_size + 1)) + ("crc32",)


# ── 1. syndromes + exact counting ──────────────────────────────────────────────

def keyless_bit_syndromes(field, helper_slices, payload_length: int, W: int) -> np.ndarray:
    """One packed syndrome per payload bit (position = col*8 + bit, the recovery convention):
    byte 0 = 2^bit (self-check: XOR of error bytes), byte j = 2^bit * h_j[col] (witness j)."""
    out = np.empty(payload_length * 8, dtype=np.uint64)
    for col in range(payload_length):
        for bit in range(8):
            v = 1 << bit
            s = v
            for j in range(W):
                s |= field.mul(v, helper_slices[j][col]) << (8 * (j + 1))
            out[col * 8 + bit] = s
    return out


_CRC_SYNDROME_CACHE: dict[int, np.ndarray] = {}


def crc_bit_syndromes(payload_length: int) -> np.ndarray:
    """crc(e) ^ crc(0^L) for every single-bit error e of the payload: the linear part of
    zlib's affine CRC-32, so a k-bit error is missed iff these XOR to 0 (data-independent ->
    cached)."""
    if payload_length not in _CRC_SYNDROME_CACHE:
        out = np.empty(payload_length * 8, dtype=np.uint64)
        for col in range(payload_length):
            for bit in range(8):
                e = bytearray(payload_length)
                e[col] = 1 << bit
                out[col * 8 + bit] = zlib.crc32(bytes(e)) ^ zero_crc(payload_length)
        _CRC_SYNDROME_CACHE[payload_length] = out
    return _CRC_SYNDROME_CACHE[payload_length]


def count_undetected(syn: np.ndarray, k_max: int = K_MAX) -> dict[int, int]:
    """Number of k-subsets of bit positions (1 <= k <= k_max <= 4) whose syndromes XOR to 0
    = undetected k-bit error patterns. Exact. O(n^2) memory/time for k >= 3."""
    assert 1 <= k_max <= 4
    n = len(syn)
    vals, cnts = np.unique(syn, return_counts=True)
    cnts = cnts.astype(object)                       # python ints: no overflow in the sums below
    out = {1: int(cnts[vals == 0].sum()) if (vals == 0).any() else 0}
    if k_max >= 2:
        out[2] = int(sum(c * (c - 1) // 2 for c in cnts))
    if k_max >= 3:
        iu, ju = np.triu_indices(n, k=1)
        pair = syn[iu] ^ syn[ju]
        # #l (l != i, j) with syn[l] == pair; each triple is counted once per choice of l -> /3
        pos = np.searchsorted(vals, pair)
        pos_ok = np.minimum(pos, len(vals) - 1)
        hit = vals[pos_ok] == pair
        c = np.where(hit, cnts[pos_ok].astype(np.int64), 0)
        c = c - (pair == syn[iu]) - (pair == syn[ju])   # l == i iff syn[j] == 0 (and vice versa)
        out[3] = int(c.sum()) // 3
        if k_max >= 4:
            _, m = np.unique(pair, return_counts=True)
            same_xor_pairs = int(sum(int(x) * (int(x) - 1) // 2 for x in m))
            # pairs sharing an element ({a,b},{a,c}) have equal XOR iff syn[b] == syn[c]
            overlap = sum(int(g) * (int(g) - 1) // 2 * (n - int(g)) + int(g) * (int(g) - 1) * (int(g) - 2) // 2
                          for g in cnts)
            out[4] = (same_xor_pairs - overlap) // 3   # each zero-XOR 4-set splits 3 ways
    return out


# ── 2. analytic miss probability vs BER ───────────────────────────────────────

def self_check_miss_table(payload_length: int) -> list[float]:
    """keyless_W0 closed form for every k: P(all 8 bit-lane parities even | k distinct random
    flips) = [x^k] (((1+x)^L + (1-x)^L) / 2)^8 / C(8L, k). Index = k."""
    L = payload_length
    even = [comb(L, i) if i % 2 == 0 else 0 for i in range(L + 1)]
    poly = [1]
    for _ in range(8):
        nxt = [0] * (len(poly) + L)
        for i, a in enumerate(poly):
            if a:
                for j, b in enumerate(even):
                    if b:
                        nxt[i + j] += a * b
        poly = nxt
    n = 8 * L
    return [poly[k] / comb(n, k) for k in range(n + 1)]


def analytic_miss_given_corrupted(level: str, n_bits: int, exact: dict[int, float], self_table: list[float],
                                  ber: float, k_cut: int | None = None) -> float:
    """P(miss | >= 1 flip) = sum_k Bin(n,k,ber) P(miss|k) / (1 - (1-ber)^n). exact[k] for
    k <= K_MAX, tail model above it (module docstring). Terms beyond k_cut (default: mean +
    12 sd + 20) are negligible and skipped."""
    mean = n_bits * ber
    k_cut = min(n_bits, k_cut if k_cut is not None else int(mean + 12 * (mean ** 0.5) + 20))
    p_any = 1.0 - (1.0 - ber) ** n_bits
    W = None if level == "crc32" else int(level.rsplit("W", 1)[1])
    total = 0.0
    log_q, log_p = np.log1p(-ber), np.log(ber)
    for k in range(1, k_cut + 1):
        if k in exact:
            pm = exact[k]
        elif W is None:
            pm = 2.0 ** -CRC_WIDTH
        else:
            pm = self_table[k] * 2.0 ** (-8 * W)
        if pm == 0.0:
            continue
        log_b = _log_comb(n_bits, k) + k * log_p + (n_bits - k) * log_q
        total += float(np.exp(log_b)) * pm
    return total / p_any


def _log_comb(n: int, k: int) -> float:
    from math import lgamma
    return lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)


# ── 3. Monte Carlo with the real oracles ──────────────────────────────────────

def _keyless_levels_passed(field, slice_, helper_slices, gen_size: int) -> int:
    """Highest W such that the slice passes self + first W witnesses; -1 = fails self-check.
    Level W misses the error iff the returned value >= W."""
    if not check_orth_packet(field, slice_):
        return -1
    for j in range(gen_size):
        if inner_product_bytes(field, slice_, helper_slices[j]) != 0:
            return j
    return gen_size


def mc_exact_k(pools, field, ks, trials: int, rng: random.Random) -> dict[tuple[str, int], int]:
    """Flip exactly k random distinct payload bits of a random (target, data segment) of the
    CLEAN pool; count misses per level with the real oracles."""
    g = pools.gen_size
    lv = levels(g)
    missed = {(l, k): 0 for l in lv for k in ks}
    data = [(kl, cs) for kl, cs in zip(pools.kl_segments, pools.crc_segments) if kl.kind == "data"]
    helpers = {kl.name: [kl_slice(pools.kl_clean[h], kl) for h in pools.helper_idx] for kl, _ in data}
    inst = Crc32Instrument()
    for k in ks:
        for _ in range(trials):
            t = rng.choice(pools.target_idx)
            kl, cs = rng.choice(data)
            bits = rng.sample(range(8 * kl.payload_length), k)
            ks_ = kl_slice(pools.kl_clean[t], kl)
            cr = crc_slice(pools.crc_clean[t], cs)
            for p in bits:
                ks_[p >> 3] ^= 1 << (p & 7)
                cr[p >> 3] ^= 1 << (p & 7)
            top = _keyless_levels_passed(field, ks_, helpers[kl.name], g)
            for w in range(g + 1):
                if top >= w:
                    missed[(f"keyless_W{w}", k)] += 1
            if crc_verify_segment(inst, cr, cs):
                missed[("crc32", k)] += 1
    return missed


def mc_ber(pools, field, ber: float, rounds: int, seed: int) -> tuple[int, dict[str, int]]:
    """The harness's own data-only injection (identical flips in every arm), `rounds` times;
    per corrupted (target, data segment) count misses per level."""
    g = pools.gen_size
    missed = {l: 0 for l in levels(g)}
    corrupted = 0
    data = [(kl, cs) for kl, cs in zip(pools.kl_segments, pools.crc_segments) if kl.kind == "data"]
    helpers = {kl.name: [kl_slice(pools.kl_clean[h], kl) for h in pools.helper_idx] for kl, _ in data}
    inst = Crc32Instrument()
    for r in range(rounds):
        inj = inject_paired(pools, ber, "data_only", seed=seed * 100_003 + r)
        for t in pools.target_idx:
            for kl, cs in data:
                ks_ = kl_slice(inj.kl[t], kl)
                if ks_ == kl_slice(pools.kl_clean[t], kl):
                    continue
                corrupted += 1
                top = _keyless_levels_passed(field, ks_, helpers[kl.name], g)
                for w in range(g + 1):
                    if top >= w:
                        missed[f"keyless_W{w}"] += 1
                if crc_verify_segment(inst, crc_slice(inj.crc[t], cs), cs):
                    missed["crc32"] += 1
    return corrupted, missed


def verify_time(pools, field, reps: int) -> dict[str, tuple[int, float]]:
    """Wall-clock of ONE accept/reject check of a clean data segment per level (worst case:
    every check runs to the end). Returns level -> (payload_bytes, seconds per verify).
    A `field` with a fused check (field backend numba_check, 2026-10-29) is timed through the
    harness oracle is_orthogonal_to_trusted -- one compiled call per verify; any other field runs
    the original per-product loop (a clean slice passes everything, so the work is the same)."""
    g = pools.gen_size
    kl = next(s for s in pools.kl_segments if s.kind == "data")
    cs = next(s for s in pools.crc_segments if s.kind == "data")
    t = pools.target_idx[0]
    ks_, cr = kl_slice(pools.kl_clean[t], kl), crc_slice(pools.crc_clean[t], cs)
    helpers = [kl_slice(pools.kl_clean[h], kl) for h in pools.helper_idx]
    out = {}
    fused = hasattr(field, "orthogonal_to_trusted")
    for w in range(g + 1):
        t0 = time.perf_counter()
        if fused:
            for _ in range(reps):
                is_orthogonal_to_trusted(field, ks_, helpers, W=w)
        else:
            for _ in range(reps):
                check_orth_packet(field, ks_)
                for j in range(w):
                    inner_product_bytes(field, ks_, helpers[j])
        out[f"keyless_W{w}"] = (kl.payload_length, (time.perf_counter() - t0) / reps)
    inst = Crc32Instrument()
    t0 = time.perf_counter()
    for _ in range(reps):
        crc_verify_segment(inst, cr, cs)
    out["crc32"] = (cs.payload_length, (time.perf_counter() - t0) / reps)
    return out


# ── driver ────────────────────────────────────────────────────────────────────

def _write(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def run(dfs=(100, 300, 1000), num_data_segments: int = 4, seeds=range(5), gen_size: int = GEN_SIZE,
        T: int | None = None, k_max: int = K_MAX, bers=DEFAULT_BERS, mc_k_trials: int = 2000,
        mc_ber_rounds: int = 20, verify_reps: int = 2000, out_dir=None, exact_segments: int | None = None,
        seg_bytes: int | None = None, field_backend: str = "table") -> Path:
    """Every view for each df x seed. exact_segments caps how many data segments per seed get
    the exact count (None = all; the O(n^2) k>=3 count dominates at large df). seg_bytes = data
    bytes per segment (num_data_segments = df // seg_bytes per df, the 50 B layout of the
    earlier wall-clock/scaling plots); None = num_data_segments for every df."""
    from icecream import ic
    ic.disable()
    T = gen_size if T is None else T
    if out_dir is None:
        from utils.log_helpers import get_run_log_dir
        out_dir = get_run_log_dir("detection_comparison", gen=gen_size, N=num_data_segments, seeds=len(list(seeds)))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    field = create_field(FIELD_BITS)
    lv = levels(gen_size)
    exact_rows, analytic_rows, mck_rows, mcb_rows, time_rows = [], [], [], [], []

    for df in dfs:
        nds = df // seg_bytes if seg_bytes else num_data_segments
        for seed in seeds:
            t_start = time.perf_counter()
            pools = build_paired_pools(CountingField(field), gen_size, df, nds, T, seed)
            data = [(kl, cs) for kl, cs in zip(pools.kl_segments, pools.crc_segments) if kl.kind == "data"]
            for kl, cs in data[:exact_segments]:
                L, n = kl.payload_length, 8 * kl.payload_length
                helpers = [kl_slice(pools.kl_clean[h], kl) for h in pools.helper_idx]
                self_table = self_check_miss_table(L)
                for level in lv:
                    syn = crc_bit_syndromes(L) if level == "crc32" else \
                        keyless_bit_syndromes(field, helpers, L, int(level.rsplit("W", 1)[1]))
                    counts = count_undetected(syn, k_max)
                    exact = {}
                    for k, c in counts.items():
                        exact[k] = c / comb(n, k)
                        exact_rows.append(dict(df=df, num_data_segments=nds, seed=seed, segment=kl.name,
                                               payload_bytes=L, n_bits=n, level=level, k=k, undetected=c,
                                               patterns=comb(n, k), p_miss=exact[k]))
                    for ber in bers:
                        analytic_rows.append(dict(df=df, num_data_segments=nds, seed=seed,
                                                  segment=kl.name, n_bits=n, level=level, ber=ber,
                                                  p_miss_given_corrupted=analytic_miss_given_corrupted(
                                                      level, n, exact, self_table, ber)))
            rng = random.Random(seed * 7919 + df)
            ks = tuple(range(1, k_max + 3))
            for (level, k), m in mc_exact_k(pools, field, ks, mc_k_trials, rng).items():
                mck_rows.append(dict(df=df, num_data_segments=nds, seed=seed, level=level, k=k,
                                     trials=mc_k_trials, missed=m))
            for ber in bers:
                corrupted, missed = mc_ber(pools, field, ber, mc_ber_rounds, seed)
                for level, m in missed.items():
                    mcb_rows.append(dict(df=df, num_data_segments=nds, seed=seed, level=level,
                                         ber=ber, corrupted_segments=corrupted, missed=m))
            print(f"  df={df} seed={seed} done in {time.perf_counter() - t_start:.1f}s", flush=True)
        vfield = field if field_backend == "table" else make_counting_field(field_backend, FIELD_BITS)
        for level, (L, s) in verify_time(pools, vfield, verify_reps).items():
            time_rows.append(dict(df=df, num_data_segments=nds, level=level, payload_bytes=L,
                                  reps=verify_reps, seconds_per_verify=s))
        # land each df as it completes (replot-able part-way)
        for name, rows in (("exact_counts", exact_rows), ("analytic_ber", analytic_rows), ("mc_exact_k", mck_rows),
                           ("mc_ber", mcb_rows), ("verify_time", time_rows)):
            _write(out_dir / f"{name}.csv", rows)
    return out_dir


def print_summary(out_dir: Path) -> None:
    """Compact console table: exact P(miss | k) pooled over seeds/segments, and MC vs analytic."""
    import pandas as pd
    ex = pd.read_csv(out_dir / "exact_counts.csv")
    pooled = ex.groupby(["df", "level", "k"])[["undetected", "patterns"]].sum()
    pooled["p_miss"] = pooled.undetected / pooled.patterns
    print("\nexact P(miss | k flips), pooled:")
    print(pooled["p_miss"].unstack("k").to_string(float_format=lambda v: f"{v:.3g}"))
    mk = pd.read_csv(out_dir / "mc_exact_k.csv").groupby(["df", "level", "k"])[["missed", "trials"]].sum()
    mk["rate"] = mk.missed / mk.trials
    print("\nMC (real oracles) miss rate | k flips:")
    print(mk["rate"].unstack("k").to_string(float_format=lambda v: f"{v:.3g}"))
    mb = pd.read_csv(out_dir / "mc_ber.csv").groupby(["df", "level", "ber"])[["missed", "corrupted_segments"]].sum()
    an = pd.read_csv(out_dir / "analytic_ber.csv").groupby(["df", "level", "ber"]).p_miss_given_corrupted.mean()
    both = mb.join(an)
    both["mc"] = both.missed / both.corrupted_segments
    print("\nmiss | corrupted segment vs BER: MC (missed/corrupted) vs analytic")
    print(both[["missed", "corrupted_segments", "mc", "p_miss_given_corrupted"]]
          .to_string(float_format=lambda v: f"{v:.3g}"))
    vt = pd.read_csv(out_dir / "verify_time.csv")
    print("\nverify time per data segment (us):")
    print(vt.assign(us=vt.seconds_per_verify * 1e6).pivot(index="level", columns="df", values="us")
          .to_string(float_format=lambda v: f"{v:.3g}"))


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Detection: keyless vs CRC-32 (ADR-0014).")
    ap.add_argument("--smoke", action="store_true", help="tiny run (df 40, 2 seeds) + console summary")
    ap.add_argument("--dfs", default="100,300,1000")
    ap.add_argument("--num-data-segments", type=int, default=4)
    ap.add_argument("--seg-bytes", type=int, default=None,
                    help="data bytes per segment -> num_data_segments = df // seg_bytes (overrides --num-data-segments)")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--k-max", type=int, default=K_MAX, help="exact counts up to k (<= 4)")
    ap.add_argument("--bers", default=",".join(repr(b) for b in DEFAULT_BERS))
    ap.add_argument("--mc-k-trials", type=int, default=2000, help="MC exact-k trials per (seed, k)")
    ap.add_argument("--mc-ber-rounds", type=int, default=20, help="MC BER injections per (seed, BER)")
    ap.add_argument("--exact-segments", type=int, default=None, help="data segments per seed for exact counts")
    ap.add_argument("--out", default=None)
    ap.add_argument("--field-backend", choices=FIELD_BACKENDS, default="table",
                    help="keyless field for the verify-time measurement ONLY (counts are backend-free)")
    a = ap.parse_args(argv)
    if a.smoke:
        d = run(dfs=(40,), num_data_segments=a.num_data_segments, seeds=range(2), bers=SMOKE_BERS,
                mc_k_trials=500, mc_ber_rounds=5, verify_reps=500, out_dir=a.out, field_backend=a.field_backend)
    else:
        d = run(dfs=tuple(int(x) for x in a.dfs.split(",")), num_data_segments=a.num_data_segments,
                seeds=range(a.seed_start, a.seed_start + a.seeds), k_max=a.k_max,
                bers=tuple(float(b) for b in a.bers.split(",")), mc_k_trials=a.mc_k_trials,
                mc_ber_rounds=a.mc_ber_rounds, exact_segments=a.exact_segments, out_dir=a.out,
                seg_bytes=a.seg_bytes, field_backend=a.field_backend)
    print_summary(d)
    print(f"\ndone -> {d}")


if __name__ == "__main__":
    main()
