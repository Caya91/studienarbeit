"""
Randomness quality comparison for RLNC packet generation.

Levels
──────
L1  Bit / byte statistics   entropy · chi-square · bit balance
L2  Sequential patterns     runs test · autocorrelation · Hamming distance
L3  Structural              compressibility · birthday collision
L4  GF(2^m) domain          inner-product acceptance rate vs. theoretical 1/|F|
L5  Performance             generation throughput (MB/s)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
import random
import secrets
import time
import math
import zlib
import collections

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from binary_ext_fields.custom_field import create_field
from binary_ext_fields.operations import inner_product_bytes


# ── Configuration ─────────────────────────────────────────────────────────────

PACKET_LEN = 16       # bytes (= field elements per packet)
N_PACKETS  = 20_000
FIELD_M    = 4        # GF(2^4); ideal acceptance = 1/16 = 0.0625

OUT_DIR    = Path(__file__).resolve().parent.parent / "logs" / "randomness_quality"


# ── Sources ───────────────────────────────────────────────────────────────────
#
# Returns list[bytes] of length n, each packet being `packet_len` bytes.
# Fixed-seed MT is intentionally weak — gives a visible reference point.

def _make_sources(packet_len: int) -> dict[str, callable]:
    _rng_numpy = np.random.default_rng()
    _rng_mt    = random.Random()          # seeded from OS entropy
    _rng_fixed = random.Random(0xDEAD)   # fixed seed — control / worst case

    return {
        "os.urandom":    lambda n: [os.urandom(packet_len) for _ in range(n)],
        "secrets":       lambda n: [secrets.token_bytes(packet_len) for _ in range(n)],
        "random.Random": lambda n: [bytes(_rng_mt.getrandbits(8) for _ in range(packet_len)) for _ in range(n)],
        "numpy PCG64":   lambda n: [bytes(_rng_numpy.integers(0, 256, packet_len, dtype=np.uint8).tolist()) for _ in range(n)],
        "MT fixed-seed": lambda n: [bytes(_rng_fixed.getrandbits(8) for _ in range(packet_len)) for _ in range(n)],
    }


# ── L1: Bit / byte statistics ─────────────────────────────────────────────────

def l1_entropy(packets: list[bytes]) -> float:
    """Shannon entropy in bits/byte. Ideal: 8.0"""
    counts = collections.Counter(b for p in packets for b in p)
    total  = sum(counts.values())
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def l1_chi_square(packets: list[bytes]) -> float:
    """Chi-square statistic for uniform byte distribution.
    Ideal ≈ 255 (the median of χ²(255)); well below ~293 (p=0.05 threshold)."""
    counts   = collections.Counter(b for p in packets for b in p)
    total    = sum(counts.values())
    expected = total / 256
    return sum(((counts.get(i, 0) - expected) ** 2) / expected for i in range(256))


def l1_bit_balance(packets: list[bytes]) -> float:
    """Fraction of 1-bits across all bytes. Ideal: 0.5"""
    ones = total = 0
    for p in packets:
        for b in p:
            ones  += bin(b).count("1")
            total += 8
    return ones / total


# ── L2: Sequential patterns ───────────────────────────────────────────────────

def l2_runs_z(packets: list[bytes], sample: int = 300) -> float:
    """Wald–Wolfowitz runs test on a bit stream.
    |z| < 1.96 passes at α = 0.05 (two-tailed). Ideal: z ≈ 0."""
    bits = []
    for p in packets[:sample]:
        for b in p:
            for shift in range(7, -1, -1):
                bits.append((b >> shift) & 1)

    n1, n0 = bits.count(1), bits.count(0)
    n = n1 + n0
    if n0 == 0 or n1 == 0:
        return float("inf")

    runs = 1 + sum(1 for i in range(1, n) if bits[i] != bits[i - 1])
    mu   = 2 * n1 * n0 / n + 1
    var  = 2 * n1 * n0 * (2 * n1 * n0 - n) / (n ** 2 * (n - 1))
    return (runs - mu) / math.sqrt(var) if var > 0 else float("inf")


def l2_autocorr(packets: list[bytes], lag: int = 1, sample: int = 500) -> float:
    """Byte-level Pearson autocorrelation at given lag. Ideal: 0.0"""
    flat = [b for p in packets[:sample] for b in p]
    n    = len(flat)
    mean = sum(flat) / n
    num  = sum((flat[i] - mean) * (flat[i + lag] - mean) for i in range(n - lag))
    den  = sum((x - mean) ** 2 for x in flat)
    return num / den if den != 0 else 0.0


def l2_avg_hamming(packets: list[bytes]) -> float:
    """Average Hamming distance between consecutive packets (in bits).
    Ideal: 4 × packet_len (= 50 % of bits differ)."""
    n = min(len(packets) - 1, 10_000)
    total = sum(
        sum(bin(a ^ b).count("1") for a, b in zip(packets[i], packets[i + 1]))
        for i in range(n)
    )
    return total / n


# ── L3: Structural tests ──────────────────────────────────────────────────────

def l3_compression(packets: list[bytes], sample: int = 2_000) -> float:
    """zlib compression ratio on raw concatenated packets.
    Truly random data is incompressible → ratio ≥ 1.0."""
    data       = b"".join(packets[:sample])
    compressed = zlib.compress(data, level=9)
    return len(compressed) / len(data)


def l3_birthday(packets: list[bytes]) -> int:
    """Index of first duplicate packet. No collision → returns N_PACKETS.
    Random sequences of 16 bytes have ~2^64 birthday threshold → collisions never expected."""
    seen = set()
    for i, p in enumerate(packets):
        if p in seen:
            return i
        seen.add(p)
    return len(packets)


# ── L4: GF(2^m) domain fitness ────────────────────────────────────────────────

def _to_field_packets(packets: list[bytes], max_val: int) -> list[bytes]:
    """Reduce each byte to a valid field element via bitmasking (works for 2^m fields)."""
    return [bytes(b & max_val for b in p) for p in packets]


def l4_gf_acceptance(packets: list[bytes], field, sample: int = 5_000) -> float:
    """Fraction of consecutive pairs whose GF inner product == 0.
    Theoretical ideal for uniform random field elements: 1 / |F| = 1 / (max_val + 1)."""
    field_pkts = _to_field_packets(packets, field.max_value)
    n = min(sample, len(field_pkts) - 1)
    accepted = sum(
        1 for i in range(n)
        if inner_product_bytes(field, field_pkts[i], field_pkts[i + 1]) == 0
    )
    return accepted / n


def l4_field_uniformity(packets: list[bytes], field) -> float:
    """Chi-square of field element distribution after masking.
    Ideal ≈ field.max_value (df = max_value, median of chi²)."""
    field_pkts = _to_field_packets(packets, field.max_value)
    counts   = collections.Counter(b for p in field_pkts for b in p)
    total    = sum(counts.values())
    fsize    = field.max_value + 1
    expected = total / fsize
    return sum(((counts.get(i, 0) - expected) ** 2) / expected for i in range(fsize))


# ── L5: Performance ───────────────────────────────────────────────────────────

def l5_throughput(gen_fn, n: int, packet_len: int) -> float:
    """Generation throughput in MB/s."""
    t0 = time.perf_counter()
    gen_fn(n)
    elapsed = time.perf_counter() - t0
    return (n * packet_len) / (1024 ** 2) / elapsed


# ── Runner ────────────────────────────────────────────────────────────────────

def run_all(packet_len: int = PACKET_LEN, n: int = N_PACKETS, field_m: int = FIELD_M) -> pd.DataFrame:
    field   = create_field(field_m)
    sources = _make_sources(packet_len)
    ideal_gf = 1 / (field.max_value + 1)

    print(f"Packets: {n:,}  ×  {packet_len} bytes  |  GF(2^{field_m})  ideal acceptance = {ideal_gf:.4f}\n")

    rows = []
    for name, gen_fn in sources.items():
        print(f"  {name} ...", flush=True)
        packets = gen_fn(n)

        row = {
            "Source":                   name,
            # L1
            "L1 Entropy [8.0]":         l1_entropy(packets),
            "L1 Chi-sq [≈255]":         l1_chi_square(packets),
            "L1 Bit balance [0.500]":   l1_bit_balance(packets),
            # L2
            "L2 Runs |z| [<1.96]":      abs(l2_runs_z(packets)),
            "L2 Autocorr [0.000]":      l2_autocorr(packets),
            f"L2 Hamming [{4*packet_len}]": l2_avg_hamming(packets),
            # L3
            "L3 Compress [≥1.00]":      l3_compression(packets),
            "L3 Birthday [no coll.]":   l3_birthday(packets),
            # L4
            f"L4 GF accept [{ideal_gf:.4f}]":  l4_gf_acceptance(packets, field),
            f"L4 GF chi-sq [≈{field.max_value}]": l4_field_uniformity(packets, field),
            # L5
            "L5 Throughput (MB/s)":     l5_throughput(gen_fn, n, packet_len),
        }
        rows.append(row)

    return pd.DataFrame(rows).set_index("Source")


# ── Visualization ─────────────────────────────────────────────────────────────

# For each metric: (ideal_value, direction)
#   "high"   → higher is better   (normalize: val → 1 when at upper bound)
#   "low"    → lower is better
#   "center" → closeness to ideal is best
_METRIC_META = {
    "L1 Entropy [8.0]":       (8.0,  "high",   (6.0,   8.0)),
    "L1 Chi-sq [≈255]":       (255,  "center", (150,   450)),
    "L1 Bit balance [0.500]": (0.5,  "center", (0.45,  0.55)),
    "L2 Runs |z| [<1.96]":   (0.0,  "low",    (0.0,   6.0)),
    "L2 Autocorr [0.000]":   (0.0,  "center", (-0.05, 0.05)),
    "L3 Compress [≥1.00]":   (1.0,  "high",   (0.90,  1.05)),
    "L3 Birthday [no coll.]": (None, "high",   (0,     N_PACKETS)),
}


def _normalize(series: pd.Series, col: str, packet_len: int) -> pd.Series:
    """Map raw metric values to [0, 1] where 1 = ideal."""
    hamming_col = f"L2 Hamming [{4*packet_len}]"
    if col == hamming_col:
        ideal = 4 * packet_len
        span  = ideal * 0.5
        return 1 - (series - ideal).abs().clip(0, span) / span

    gf_accept_cols = [c for c in [col] if c.startswith("L4 GF accept")]
    if gf_accept_cols or col.startswith("L4 GF accept"):
        ideal = float(col.split("[")[1].rstrip("]"))
        span  = ideal
        return 1 - (series - ideal).abs().clip(0, span) / span

    gf_chi_cols = [c for c in [col] if c.startswith("L4 GF chi-sq")]
    if gf_chi_cols or col.startswith("L4 GF chi-sq"):
        meta  = col.split("[≈")[1].rstrip("]")
        ideal = float(meta)
        lo, hi = 0, ideal * 3
        return 1 - (series - ideal).abs().clip(0, hi) / hi

    meta = _METRIC_META.get(col)
    if meta is None:
        lo, hi = series.min(), series.max()
        return (series - lo) / (hi - lo + 1e-12)

    ideal, direction, (lo, hi) = meta
    span = hi - lo or 1.0

    if direction == "high":
        return (series.clip(lo, hi) - lo) / span
    if direction == "low":
        return 1 - (series.clip(lo, hi) - lo) / span
    # center
    return 1 - (series - ideal).abs().clip(0, span / 2) / (span / 2)


def plot_heatmap(df: pd.DataFrame, out_dir: Path, packet_len: int) -> None:
    metrics = [c for c in df.columns if not c.startswith("L5")]
    score   = pd.DataFrame({col: _normalize(df[col].astype(float), col, packet_len) for col in metrics})

    fig, ax = plt.subplots(figsize=(len(metrics) * 1.5 + 1, len(df) * 0.7 + 2))
    im = ax.imshow(score.values, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(metrics)))
    ax.set_xticklabels(metrics, rotation=40, ha="right", fontsize=8)
    ax.set_yticks(range(len(df)))
    ax.set_yticklabels(df.index, fontsize=9)
    ax.set_title("Randomness quality heatmap  (green = closer to ideal)", pad=12)
    plt.colorbar(im, ax=ax, label="Normalized score  (1 = ideal)")

    for r, src in enumerate(df.index):
        for c, col in enumerate(metrics):
            ax.text(c, r, f"{float(df.loc[src, col]):.3f}",
                    ha="center", va="center", fontsize=6.5, color="black")

    plt.tight_layout()
    fig.savefig(out_dir / "heatmap.png", dpi=150)
    plt.close(fig)
    print(f"  heatmap.png")


def plot_per_level(df: pd.DataFrame, out_dir: Path) -> None:
    level_groups = {
        "L1 — Byte statistics": [c for c in df.columns if c.startswith("L1")],
        "L2 — Sequential":      [c for c in df.columns if c.startswith("L2")],
        "L3 — Structural":      [c for c in df.columns if c.startswith("L3")],
        "L4 — GF domain":       [c for c in df.columns if c.startswith("L4")],
        "L5 — Throughput":      [c for c in df.columns if c.startswith("L5")],
    }

    colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B2"]

    for group, cols in level_groups.items():
        if not cols:
            continue
        ncols = len(cols)
        fig, axes = plt.subplots(1, ncols, figsize=(4.5 * ncols, 4), squeeze=False)
        fig.suptitle(group, fontsize=11, weight="bold")

        for ax, col in zip(axes[0], cols):
            vals = df[col].astype(float)
            bars = ax.bar(range(len(vals)), vals,
                          color=[colors[i % len(colors)] for i in range(len(vals))],
                          edgecolor="white", linewidth=0.5)
            ax.set_xticks(range(len(vals)))
            ax.set_xticklabels(df.index, rotation=30, ha="right", fontsize=8)
            ax.set_title(col, fontsize=8)

            # draw ideal reference line if known
            meta = _METRIC_META.get(col)
            if meta and meta[0] is not None:
                ax.axhline(meta[0], color="red", linewidth=1.2, linestyle="--",
                           label=f"ideal = {meta[0]}")
                ax.legend(fontsize=7)

        plt.tight_layout()
        fname = group.split("—")[0].strip().lower().replace(" ", "_") + ".png"
        fig.savefig(out_dir / fname, dpi=150)
        plt.close(fig)
        print(f"  {fname}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = run_all()

    print("\n── Results ──────────────────────────────────────────────────────────")
    pd.set_option("display.float_format", "{:.4f}".format)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.width", 160)
    print(df.to_string())

    csv_path = OUT_DIR / "results.csv"
    df.to_csv(csv_path)
    print(f"\nResults → {csv_path}")

    print("\nGenerating plots ...")
    plot_heatmap(df, OUT_DIR, PACKET_LEN)
    plot_per_level(df, OUT_DIR)
    print(f"\nAll outputs in: {OUT_DIR}")
