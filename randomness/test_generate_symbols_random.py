"""
Randomness test suite for generate_symbols_random().

Compares three RNG sources and prints a metrics table.
Only the data-byte portion of each packet is analysed
(the trailing gen_size zeros are tag placeholders and are excluded).
"""

import sys
import os
import math
import secrets
import statistics
import collections
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import chi2

from binary_ext_fields.generate_symbols import generate_symbols_random

# ── Configuration ─────────────────────────────────────────────────────────────

MIN_INT     = 0
MAX_INT     = 15
DATA_FIELDS = 16    # random bytes per packet
GEN_SIZE    = 8     # packets per generation (trailing GEN_SIZE bytes are always 0)
N_TRIALS    = 50_000  # number of generations to run

OUT_DIR = Path(__file__).resolve().parent.parent / "logs" / "randomness_quality"

# ── RNG sources ───────────────────────────────────────────────────────────────
# Each callable matches the (min_int, max_int) -> int interface of random.randint.
# os.urandom masking is safe here because MAX_INT = 2^m - 1 (bitmask property).

import random as _random

_rng_mt = _random.Random()   # seeded from OS entropy at import time

def _rng_urandom(lo: int, hi: int) -> int:
    return int.from_bytes(os.urandom(1), "little") & hi

def _rng_secrets(lo: int, hi: int) -> int:
    return secrets.randbelow(hi - lo + 1) + lo

SOURCES = {
    "random.randint": _rng_mt.randint,
    "os.urandom":     _rng_urandom,
    "secrets":        _rng_secrets,
}

# ── Data collection ───────────────────────────────────────────────────────────

def collect_values(rng_fn) -> list[int]:
    """Run N_TRIALS generations and return all data-byte values as a flat list."""
    values = []
    for _ in range(N_TRIALS):
        generation = generate_symbols_random(MIN_INT, MAX_INT, DATA_FIELDS, GEN_SIZE, rng=rng_fn)
        for packet in generation:
            # only the first DATA_FIELDS bytes are random; rest are zero tag placeholders
            values.extend(packet[:DATA_FIELDS])
    return values

# ── Metrics ───────────────────────────────────────────────────────────────────

def _entropy(values: list[int]) -> float:
    """Shannon entropy in bits. Ideal = log2(16) = 4.0"""
    counts = collections.Counter(values)
    total  = len(values)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def _chi_square(values: list[int]) -> tuple[float, float]:
    """Chi-square goodness-of-fit for uniform distribution over [MIN_INT, MAX_INT].
    df = MAX_INT - MIN_INT = 15.  Returns (chi_sq, p_value)."""
    n_bins   = MAX_INT - MIN_INT + 1
    counts   = collections.Counter(values)
    expected = len(values) / n_bins
    chi_sq   = sum((counts.get(v, 0) - expected) ** 2 / expected
                   for v in range(MIN_INT, MAX_INT + 1))
    p_value  = chi2.sf(chi_sq, df=n_bins - 1)
    return chi_sq, p_value


def _freq_table(all_values: dict[str, list[int]]) -> pd.DataFrame:
    """Returns a DataFrame of per-value counts for each source."""
    rows = {}
    for name, values in all_values.items():
        counts = collections.Counter(values)
        rows[name] = [counts.get(v, 0) for v in range(MIN_INT, MAX_INT + 1)]
    return pd.DataFrame(rows, index=range(MIN_INT, MAX_INT + 1))


# ── Visualisation ─────────────────────────────────────────────────────────────

COLORS = ["#4C72B0", "#DD8452", "#55A868"]   # one per source

def plot_freq_distribution(freq_df: pd.DataFrame, expected: int, out_dir: Path) -> None:
    """
    Grouped bar chart: x = field value (0-15), bar groups = sources.
    A dashed red line marks the expected count for a perfectly uniform distribution.
    """
    sources = freq_df.columns.tolist()
    values  = freq_df.index.tolist()
    n_vals  = len(values)
    n_src   = len(sources)

    bar_width = 0.25
    x = np.arange(n_vals)
    offsets = np.linspace(-(n_src - 1) / 2, (n_src - 1) / 2, n_src) * bar_width

    fig, ax = plt.subplots(figsize=(14, 5))

    for i, (src, color) in enumerate(zip(sources, COLORS)):
        ax.bar(x + offsets[i], freq_df[src], width=bar_width,
               label=src, color=color, edgecolor="white", linewidth=0.4, alpha=0.88)

    ax.axhline(expected, color="red", linewidth=1.5, linestyle="--",
               label=f"expected (uniform) = {expected:,}")

    ax.set_xticks(x)
    ax.set_xticklabels(values, fontsize=9)
    ax.set_xlabel("Field value  (0 to 15)", fontsize=11)
    ax.set_ylabel("Count", fontsize=11)
    ax.set_title("Value frequency distribution  —  generate_symbols_random()", fontsize=12, fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)
    ax.legend(fontsize=9)

    plt.tight_layout()
    path = out_dir / "freq_distribution.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  freq_distribution.png")


def plot_metrics_comparison(df: pd.DataFrame, out_dir: Path) -> None:
    """
    One subplot per numeric metric; bars = sources; red dashed line = ideal value.
    """
    numeric_cols = [
        ("Mean [7.500]",    7.5,   (7.0,  8.0),  "Mean"),
        ("Std [4.610]",     4.610, (4.0,  5.2),  "Std dev"),
        ("Entropy [4.000]", 4.0,   (3.9,  4.01), "Entropy (bits)"),
        ("Chi-sq [~15]",    15.0,  (0,    40),   "Chi-square  (df=15)"),
        ("p-value [>0.05]", None,  (0,    1.0),  "p-value"),
    ]

    n = len(numeric_cols)
    fig, axes = plt.subplots(1, n, figsize=(4.2 * n, 4.5))
    fig.suptitle("Metrics comparison  —  generate_symbols_random()", fontsize=12, fontweight="bold")

    sources = df.index.tolist()
    x = np.arange(len(sources))

    for ax, (col, ideal, ylim, label) in zip(axes, numeric_cols):
        vals = df[col].astype(float).tolist()
        bars = ax.bar(x, vals, color=COLORS[:len(sources)],
                      edgecolor="white", linewidth=0.5, alpha=0.88)
        if ideal is not None:
            ax.axhline(ideal, color="red", linewidth=1.5, linestyle="--",
                       label=f"ideal = {ideal}")
            ax.legend(fontsize=8)
        elif col.startswith("p-value"):
            ax.axhline(0.05, color="red", linewidth=1.5, linestyle="--",
                       label="threshold = 0.05")
            ax.legend(fontsize=8)

        ax.set_xticks(x)
        ax.set_xticklabels(sources, rotation=20, ha="right", fontsize=8)
        ax.set_title(label, fontsize=9, fontweight="bold")
        ax.set_ylim(ylim)
        ax.yaxis.grid(True, linestyle="--", alpha=0.35)
        ax.set_axisbelow(True)

        for bar, val in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + (ylim[1] - ylim[0]) * 0.015,
                    f"{val:.4f}", ha="center", va="bottom", fontsize=7, fontweight="bold")

    plt.tight_layout()
    path = out_dir / "metrics_comparison.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  metrics_comparison.png")


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    total_per_source = N_TRIALS * GEN_SIZE * DATA_FIELDS
    print(f"generate_symbols_random() — randomness test")
    print(f"  min={MIN_INT}  max={MAX_INT}  data_fields={DATA_FIELDS}  gen_size={GEN_SIZE}")
    print(f"  trials={N_TRIALS:,}  values per source={total_per_source:,}\n")

    all_values: dict[str, list[int]] = {}
    rows = []

    for name, rng_fn in SOURCES.items():
        print(f"  collecting {name} ...", flush=True)
        values = collect_values(rng_fn)
        all_values[name] = values

        in_range    = all(MIN_INT <= v <= MAX_INT for v in values)
        all_seen    = set(values) == set(range(MIN_INT, MAX_INT + 1))
        mean        = statistics.mean(values)
        std         = statistics.stdev(values)
        entropy     = _entropy(values)
        chi_sq, pv  = _chi_square(values)
        passes_chi  = pv > 0.05

        rows.append({
            "Source":         name,
            "Range OK":       in_range,
            "All vals seen":  all_seen,
            "Mean [7.500]":   round(mean, 4),
            "Std [4.610]":    round(std, 4),
            "Entropy [4.000]": round(entropy, 4),
            "Chi-sq [~15]":   round(chi_sq, 2),
            "p-value [>0.05]": round(pv, 4),
            "Passes chi2":    passes_chi,
        })

    df = pd.DataFrame(rows).set_index("Source")

    print("\n-- Summary table ----------------------------------------------------------------")
    pd.set_option("display.float_format", "{:.4f}".format)
    pd.set_option("display.max_columns", 15)
    pd.set_option("display.width", 160)
    print(df.to_string())

    freq_df = _freq_table(all_values)
    freq_df.index.name = "Value"
    print("\n-- Per-value frequencies --------------------------------------------------------")
    expected = total_per_source // (MAX_INT - MIN_INT + 1)
    print(f"  Expected per value: {expected:,}")
    print(freq_df.to_string())

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\nGenerating plots ...")
    plot_freq_distribution(freq_df, expected, OUT_DIR)
    plot_metrics_comparison(df, OUT_DIR)

    try:
        df.to_csv(OUT_DIR / "generate_symbols_random_results.csv")
        freq_df.to_csv(OUT_DIR / "generate_symbols_random_freq.csv")
    except PermissionError:
        print("  (CSV save skipped — file open elsewhere)")

    print(f"\nAll outputs in: {OUT_DIR}")


if __name__ == "__main__":
    run()
