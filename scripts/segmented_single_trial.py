"""One-trial harness for the segmented orthogonal scheme (ADR-0012).

Play-around loop: edit segmented_tagging.py / segmented_recovery.py / the
SegmentedScheme in integrity_schemes.py, then rerun this to see wall clock,
recovery, overhead, ops for a single receiver lifetime -- no full N x BER sweep,
no plotting.

    LOG_FOLDER="./logs" PYTHONPATH=. \
      "E:/projects/studienarbeit/.venv/Scripts/python.exe" \
      scripts/segmented_single_trial.py [--ber 5e-4] [--scheme segmented_uniform_hd_n2] [--repeat 1]

Same field/gen_size/data_fields/cfg as run_segmented_n_sweep so numbers are comparable.
"""
import argparse
from dataclasses import asdict

from binary_ext_fields.generate_symbols import create_field
from simulation.integrity_schemes import SCHEMES, AdmitConfig, SEGMENTED_DATA_FIELDS
from simulation.scheme_comparison_sim import (
    run_recovery_trial, FIELD_M, GEN_SIZE, SEGMENTED_MAX_PACKETS_FACTOR,
)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scheme", default="segmented_uniform_hd_n2",
                   help=f"one of: {', '.join(k for k in SCHEMES if 'segmented' in k)} (or orthogonal baseline)")
    p.add_argument("--ber", type=float, default=5e-4)
    p.add_argument("--repeat", type=int, default=1, help="run N trials and show each + a mean")
    args = p.parse_args()

    base_field = create_field(FIELD_M)
    cfg = AdmitConfig(hamming_distance=2)  # matches run_segmented_n_sweep; <2 disables combined recovery
    scheme = SCHEMES[args.scheme]

    keys = ("wall_time_s", "correct", "decoded", "silent_decode", "overhead",
            "packets_to_decode", "scheme_ops", "pairs_recovered", "pairs_failed", "status")
    rows = []
    for i in range(args.repeat):
        r = run_recovery_trial(base_field, scheme, SEGMENTED_DATA_FIELDS, GEN_SIZE, args.ber, cfg,
                               max_packets_factor=SEGMENTED_MAX_PACKETS_FACTOR)
        d = asdict(r)
        rows.append(d)
        print(f"\n--- trial {i} (scheme={args.scheme} BER={args.ber:g} "
              f"gen_size={GEN_SIZE} data_fields={SEGMENTED_DATA_FIELDS}) ---")
        for k in keys:
            print(f"  {k:18} {d[k]}")

    if args.repeat > 1:
        n = len(rows)
        print(f"\n=== mean over {n} trials ===")
        print(f"  wall_time_s        {sum(x['wall_time_s'] for x in rows)/n:.4f}")
        print(f"  recovery (correct) {sum(x['correct'] for x in rows)/n:.3f}")
        print(f"  overhead           {sum(x['overhead'] for x in rows)/n:.3f}")
        print(f"  scheme_ops         {sum(x['scheme_ops'] for x in rows)/n:.0f}")


if __name__ == "__main__":
    main()
