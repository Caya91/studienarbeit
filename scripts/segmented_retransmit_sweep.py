"""Retransmit-vs-segment-count sweep for the keyless segmented scheme.

Question (thesis #2): as the number of segments N grows, how many extra packets
must be sent to decode? "Retransmits" = packets_to_decode - gen_size (packets
beyond the strict minimum). The overlap gate (a packet must be trusted in EVERY
segment at once) should make this climb with N.

Rank floor is DELIBERATELY IGNORED here (per request): with a fixed 48-byte
payload, large N drives each data-segment below the gen_size-1 rank floor, so
make_source gives up (RuntimeError). We catch that and mark the N "build-failed"
rather than crash -- the N at which construction dies is itself a data point.

Reuses run_recovery_trial unchanged (same admit/decode loop as the real sweeps).

Run (repo root, main venv):
    # smoke: fast, proves it runs + build-failure handling
    LOG_FOLDER=./logs PYTHONPATH=. python scripts/segmented_retransmit_sweep.py --smoke
    # full sweep + plot
    LOG_FOLDER=./logs PYTHONPATH=. python scripts/segmented_retransmit_sweep.py --trials 100
"""

import argparse
import statistics

import matplotlib.pyplot as plt

from binary_ext_fields.custom_field import create_field
from simulation.integrity_schemes import SegmentedScheme, AdmitConfig
from simulation.scheme_comparison_sim import run_recovery_trial
from utils.log_helpers import get_run_log_dir


def run_cell(base_field, n_segments, data_fields, gen_size, ber, cfg, trials, strategy):
    """One (N) cell: `trials` receiver lifetimes. Returns a summary dict. A
    RuntimeError from make_source (rank-floor give-up) aborts the whole cell as
    build-failed -- it fires on the first trial and would fire on every trial."""
    scheme = SegmentedScheme(num_data_segments=n_segments - 1, data_fields=data_fields,
                             strategy=strategy, name=f"seg_n{n_segments}")
    retransmits, decoded, timeouts, silent = [], 0, 0, 0
    for _ in range(trials):
        try:
            r = run_recovery_trial(base_field, scheme, data_fields, gen_size, ber, cfg)
        except RuntimeError as e:
            return {"n": n_segments, "build_failed": True, "reason": str(e).split("--")[0].strip()}
        retransmits.append(r.packets_to_decode - gen_size)
        decoded += r.correct
        timeouts += (r.status == "timeout")
        silent += r.silent_decode
    return {
        "n": n_segments, "build_failed": False, "trials": trials,
        "mean_retransmits": statistics.mean(retransmits),
        "median_retransmits": statistics.median(retransmits),
        "max_retransmits": max(retransmits),
        "decode_rate": decoded / trials, "timeout_rate": timeouts / trials,
        "silent_rate": silent / trials,
    }


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Retransmits vs segment count (keyless segmented).")
    p.add_argument("--payload", type=int, default=48)
    p.add_argument("--gen-size", type=int, default=15)
    p.add_argument("--ber", type=float, default=1e-4)
    p.add_argument("--segments", default="2,4,8,12,16,24", help="comma list of N")
    p.add_argument("--trials", type=int, default=100)
    p.add_argument("--hd", type=int, default=2)
    p.add_argument("--strategy", choices=["uniform_hd", "coefficient_first"], default="uniform_hd")
    p.add_argument("--smoke", action="store_true", help="2 trials, N in {2,4}, no plot")
    p.add_argument("--no-plot", action="store_true")
    args = p.parse_args(argv)

    if args.smoke:
        args.trials, args.segments, args.no_plot = 2, "2,4", True

    segments = [int(x) for x in args.segments.split(",")]
    base_field = create_field(8)
    cfg = AdmitConfig(hamming_distance=args.hd)

    print("=" * 70)
    print(f"retransmit sweep  payload={args.payload}B  g={args.gen_size}  BER={args.ber:g}  "
          f"HD={args.hd}  strategy={args.strategy}  trials={args.trials}")
    print(f"segments: {segments}   (rank floor IGNORED -- expect build-failed at high N)")
    print("=" * 70)
    print(f"{'N':>3} {'built':>6} {'mean_rtx':>9} {'median':>7} {'max':>5} "
          f"{'decode%':>8} {'timeout%':>9} {'silent%':>8}")

    rows = []
    for n in segments:
        s = run_cell(base_field, n, args.payload, args.gen_size, args.ber, cfg,
                     args.trials, args.strategy)
        rows.append(s)
        if s["build_failed"]:
            print(f"{n:>3} {'NO':>6}   <build-failed: rank floor> {s['reason']}")
        else:
            print(f"{n:>3} {'yes':>6} {s['mean_retransmits']:>9.2f} {s['median_retransmits']:>7.1f} "
                  f"{s['max_retransmits']:>5} {100*s['decode_rate']:>7.0f}% "
                  f"{100*s['timeout_rate']:>8.0f}% {100*s['silent_rate']:>7.0f}%")

    built = [r for r in rows if not r["build_failed"]]
    if not args.no_plot and built:
        run_dir = get_run_log_dir("segmented_retransmit_sweep", trials=args.trials,
                                  gen=args.gen_size, m=8)
        xs = [r["n"] for r in built]
        ys = [r["mean_retransmits"] for r in built]
        fig, ax1 = plt.subplots(figsize=(8, 5))
        ax1.plot(xs, ys, "o-", color="tab:blue", label="mean retransmits")
        ax1.set_xlabel("number of segments N")
        ax1.set_ylabel("mean retransmits (packets beyond gen_size)", color="tab:blue")
        ax1.tick_params(axis="y", labelcolor="tab:blue")
        ax2 = ax1.twinx()
        ax2.plot(xs, [100 * r["timeout_rate"] for r in built], "s--", color="tab:red",
                 label="timeout %")
        ax2.set_ylabel("timeout %", color="tab:red")
        ax2.tick_params(axis="y", labelcolor="tab:red")
        ax2.set_ylim(0, 100)
        plt.title(f"Retransmits vs N  (payload={args.payload}B, g={args.gen_size}, BER={args.ber:g})")
        out = run_dir / "retransmits_vs_segments.png"
        fig.tight_layout()
        fig.savefig(out, dpi=120)
        print(f"\nplot -> {out}")


if __name__ == "__main__":
    main()
