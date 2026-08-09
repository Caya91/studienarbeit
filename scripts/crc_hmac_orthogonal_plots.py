"""Three comparison plots across four recovery arms:

  * Orthogonal (per-column)   -- keyless-HMAC self-tag, per-column bitflip oracle (mode B)
  * Orthogonal (arc-linear)   -- same self-tag, ARC-localize then linear solve (mode D)
  * CRC (localized)           -- CRC-16 + ARC-localized bit-flip repair (fair fight)
  * CRC (whole-packet)        -- CRC-16 + budget-capped whole-packet search (bare floor)

The two orthogonal arms share ONE scheme (`OrthogonalScheme`) and differ only by
`AdmitConfig.mode`; the two CRC arms are the two `CrcScheme` variants. So an "arm"
= (scheme, admit-config), and each arm carries its own config here.

Plots (all vs bit error rate):
  1. completion_time_boxplots.png -- per-trial wall-clock to decode a generation,
     one box per arm x BER at BER 1e-5 and 1e-3.
  2. recovery_success_vs_ber.png -- correct-recovery rate over the extended sweep.
  3. overhead_bytes_vs_ber.png   -- mean transmission overhead in BYTES (the extra
     packets beyond gen_size, each a full scheme-specific wire packet).

CAVEAT (completion time): orthogonal runs pure-Python finite-field arithmetic,
CRC is table-driven Python search -- absolute wall-clock is implementation-level
end-to-end time, not primitive cost. Op counts live in scheme_comparison_sim.py.
"""

import csv
from dataclasses import asdict

import matplotlib.pyplot as plt
import numpy as np
from icecream import ic

ic.disable()

from binary_ext_fields.custom_field import create_field
from binary_ext_fields.generate_symbols import recode_rlnc_without_coeffs
from simulation.integrity_schemes import SCHEMES, AdmitConfig
from simulation.scheme_comparison_sim import run_recovery_trial
from utils.log_helpers import get_run_log_dir


# ── Configuration ─────────────────────────────────────────────────────────────
FIELD_M = 8
GEN_SIZE = 10
DATA_FIELDS = 10
NUM_TRIALS = 100                           # overridable with --trials
HAMMING_DISTANCE = 2                       # user: "1 or 2" -> 2

BER_BOX = [1e-5, 1e-3]                      # the two box-plot BERs
# line-graph sweep extended past 1e-3 so the arms actually diverge (below ~1e-3
# send-until-decodable pins them all at ~100%).
BER_LINE = [1e-5, 1e-4, 5e-4, 1e-3, 5e-3, 1e-2, 2e-2, 5e-2]
ALL_BERS = sorted(set(BER_BOX) | set(BER_LINE))

# One entry per arm. `scheme` indexes SCHEMES; `mode` overrides AdmitConfig.mode
# (only the orthogonal scheme reads it -- CRC ignores mode, uses its own flag).
ARMS = [
    {"id": "orth_per_column", "label": "Orthogonal (per-column)", "scheme": "orthogonal",
     "mode": "per_column", "color": "#2a6f97", "style": "-",  "marker": "o"},
    {"id": "orth_arc_linear", "label": "Orthogonal (arc-linear)", "scheme": "orthogonal",
     "mode": "arc_linear",  "color": "#5fa8d3", "style": "-.", "marker": "v"},
    {"id": "crc_localized",   "label": "CRC (localized)",         "scheme": "crc_localized",
     "mode": "per_column",  "color": "#e07a5f", "style": "--", "marker": "^"},
    {"id": "crc_whole",       "label": "CRC (whole-packet)",      "scheme": "crc_whole",
     "mode": "per_column",  "color": "#f2a65a", "style": ":",  "marker": "D"},
]
ARM_BY_ID = {a["id"]: a for a in ARMS}
ARM_IDS = [a["id"] for a in ARMS]
BER_COLOR = {1e-5: "#81b29a", 1e-3: "#e07a5f"}


def _cfg_for(arm) -> AdmitConfig:
    return AdmitConfig(hamming_distance=HAMMING_DISTANCE, mode=arm["mode"])


def wire_bytes_for(base_field, scheme, data_fields, gen_size) -> int:
    """On-wire packet size in bytes (coeffs + data + tag), measured by attaching
    one real recoded packet -- captures each scheme's tag layout exactly."""
    source, _ = scheme.make_source(base_field, data_fields, gen_size)
    clean = recode_rlnc_without_coeffs(base_field, source, gen_size, count=1)
    instrument = scheme.new_instrument(base_field)
    return len(scheme.attach(instrument, bytearray(clean)))


def collect(base_field):
    """Run every (arm, BER) cell and return raw per-trial rows + per-arm wire size.
    Each arm supplies its own AdmitConfig (mode); overhead in bytes is derived from
    packets_to_decode and the arm's scheme wire size."""
    wire = {a["id"]: wire_bytes_for(base_field, SCHEMES[a["scheme"]], DATA_FIELDS, GEN_SIZE)
            for a in ARMS}
    rows = []
    for arm in ARMS:
        scheme = SCHEMES[arm["scheme"]]
        cfg = _cfg_for(arm)
        for ber in ALL_BERS:
            print(f"=== {arm['label']:24} BER={ber:g} ===")
            for trial_id in range(NUM_TRIALS):
                r = run_recovery_trial(base_field, scheme, DATA_FIELDS, GEN_SIZE, ber, cfg)
                extra_pkts = max(0, r.packets_to_decode - GEN_SIZE)
                rows.append({
                    "arm": arm["id"], "scheme": arm["scheme"], "mode": arm["mode"],
                    "bit_error_rate": ber, "trial_id": trial_id,
                    "wire_bytes": wire[arm["id"]],
                    "extra_packets": extra_pkts,
                    "overhead_bytes": extra_pkts * wire[arm["id"]],
                    "completion_time_ms": r.wall_time_s * 1e3,
                    **asdict(r),
                })
    return rows, wire


def _samples(rows, arm_id, ber, field):
    return [row[field] for row in rows if row["arm"] == arm_id and row["bit_error_rate"] == ber]


def _rate(rows, arm_id, ber, field):
    vals = _samples(rows, arm_id, ber, field)
    return float(np.mean(vals)) if vals else float("nan")


# ── Plot 1: completion-time box plots ─────────────────────────────────────────
def plot_boxplots(rows, out_path):
    fig, ax = plt.subplots(figsize=(12, 6))
    positions, data, box_colors, xticks, xticklabels = [], [], [], [], []
    n_ber = len(BER_BOX)
    for gi, arm in enumerate(ARMS):
        base = gi * (n_ber + 0.8)
        for bi, ber in enumerate(BER_BOX):
            positions.append(base + bi)
            data.append(_samples(rows, arm["id"], ber, "completion_time_ms"))
            box_colors.append(BER_COLOR[ber])
        xticks.append(base + (n_ber - 1) / 2)
        xticklabels.append(arm["label"])

    bp = ax.boxplot(data, positions=positions, widths=0.7, patch_artist=True,
                    showfliers=False, medianprops=dict(color="black", linewidth=1.5))
    for patch, c in zip(bp["boxes"], box_colors):
        patch.set_facecolor(c)
        patch.set_alpha(0.85)

    ax.set_yscale("log")
    ax.set_xticks(xticks)
    ax.set_xticklabels(xticklabels, fontsize=11, fontweight="bold")
    ax.set_ylabel("Completion time per generation (ms, log scale)", fontsize=12, fontweight="bold")
    ax.set_title(f"Completion time by arm (HD={HAMMING_DISTANCE}, gen={GEN_SIZE}, "
                 f"{NUM_TRIALS} trials)", fontsize=13, fontweight="bold")
    ax.yaxis.grid(True, which="both", linestyle="--", alpha=0.3)
    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=BER_COLOR[b], alpha=0.85) for b in BER_BOX]
    ax.legend(handles, [f"BER = {b:g}" for b in BER_BOX], fontsize=10, title="Bit error rate")
    fig.text(0.01, 0.01, "Wall-clock: pure-Python field ops (orthogonal) vs table-driven "
             "CRC search -- implementation-level, not primitive cost.",
             fontsize=7, style="italic", color="grey")
    plt.tight_layout(rect=(0, 0.03, 1, 1))
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {out_path}")
    plt.close(fig)


# ── Plot 2: recovery-success line graph ───────────────────────────────────────
def plot_recovery(rows, out_path):
    fig, ax = plt.subplots(figsize=(9, 6))
    for arm in ARMS:
        ys = [_rate(rows, arm["id"], ber, "correct") for ber in BER_LINE]
        ax.plot(BER_LINE, ys, arm["style"], marker=arm["marker"], color=arm["color"],
                linewidth=2, markersize=7, markerfacecolor="none", markeredgewidth=1.8,
                label=arm["label"])
    ax.set_xscale("log")
    ax.set_ylim(-0.02, 1.02)
    ax.set_xlabel("Bit error rate", fontsize=12, fontweight="bold")
    ax.set_ylabel("Successful recovery rate (decoded to correct source)", fontsize=12, fontweight="bold")
    ax.set_title(f"Successful recovery vs BER (HD={HAMMING_DISTANCE}, gen={GEN_SIZE}, "
                 f"{NUM_TRIALS} trials)", fontsize=13, fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=10)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {out_path}")
    plt.close(fig)


# ── Plot 3: overhead-in-bytes line graph ──────────────────────────────────────
def plot_overhead_bytes(rows, out_path):
    fig, ax = plt.subplots(figsize=(9, 6))
    for arm in ARMS:
        ys = [_rate(rows, arm["id"], ber, "overhead_bytes") for ber in BER_LINE]
        ax.plot(BER_LINE, ys, arm["style"], marker=arm["marker"], color=arm["color"],
                linewidth=2, markersize=7, label=arm["label"])
    ax.set_xscale("log")
    ax.set_xlabel("Bit error rate", fontsize=12, fontweight="bold")
    ax.set_ylabel("Mean transmission overhead (bytes of extra packets)", fontsize=12, fontweight="bold")
    ax.set_title(f"Overhead in bytes vs BER (HD={HAMMING_DISTANCE}, gen={GEN_SIZE}, "
                 f"{NUM_TRIALS} trials)", fontsize=13, fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=10)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved: {out_path}")
    plt.close(fig)


def _write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Written: {path}")


def main(num_trials=NUM_TRIALS):
    global NUM_TRIALS
    NUM_TRIALS = num_trials
    run_dir = get_run_log_dir("crc_hmac_orthogonal_plots", trials=NUM_TRIALS,
                              gen=GEN_SIZE, hd=HAMMING_DISTANCE, m=FIELD_M)
    base_field = create_field(FIELD_M)

    rows, wire = collect(base_field)
    print("\nWire packet sizes (bytes): " +
          ", ".join(f"{a['label']}={wire[a['id']]}" for a in ARMS))
    _write_csv(run_dir / "raw_results.csv", rows)

    plot_boxplots(rows, run_dir / "completion_time_boxplots.png")
    plot_recovery(rows, run_dir / "recovery_success_vs_ber.png")
    plot_overhead_bytes(rows, run_dir / "overhead_bytes_vs_ber.png")

    print(f"\nDone. Results written to: {run_dir}")
    return run_dir


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=NUM_TRIALS,
                    help="trials per (arm, BER) cell")
    args = ap.parse_args()
    main(num_trials=args.trials)
