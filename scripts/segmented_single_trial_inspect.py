"""Single-trial, per-round inspector for the keyless segmented orthogonal scheme
(SegmentedScheme, ADR-0012 -- your "keyless HMAC").

NOT a sweep. One receiver lifetime, one BER, one seed, everything printed so you
can watch admission + recovery happen packet by packet. It re-implements the body
of SegmentedScheme.admit inline (same primitives -- layout_segments,
classify_segment_trust, recover_uniform_hd / recover_coefficient_first) so the
intermediate state that .admit() hides is visible: who is trusted per segment
before repair, what the combined search did, who is trusted after, and which
packets clear the every-segment intersection into the decode basis.

It also diffs each polluted wire packet against its clean form and tells you which
segment/region (payload / salt / tag) each flipped byte lives in, so you can line
up "this error appeared" against "recovery caught / missed it".

Run (from repo root, main venv):
    PYTHONPATH=. python scripts/segmented_single_trial_inspect.py
    PYTHONPATH=. python scripts/segmented_single_trial_inspect.py --n 3 --ber 1e-3 --verify-count 4 --hd 2 --seed 1

Knobs mirror AdmitConfig + the scheme constructor exactly (see integrity_schemes.py):
    --n            total segments N (coeff + N-1 data);      constructor num_data_segments
    --strategy     uniform_hd | coefficient_first;           constructor strategy
    --hd           max_combined_hd (recovery power);         AdmitConfig.hamming_distance
    --verify-count witnesses per cross-check (security/cost); AdmitConfig.verify_count
    --pair-budget  per-pair combined-search candidate cap;   AdmitConfig.pair_budget
    --min-trust    per-segment trusted floor before admit;   AdmitConfig.min_trust_count
    --min-pool     do-not-attempt-admit floor;               AdmitConfig.min_pool_size
"""

import argparse
import random

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import recode_rlnc_without_coeffs
from binary_ext_fields.pollution import pollute_generation, pollute_random
from binary_ext_fields.segmented_tagging import layout_segments
from binary_ext_fields.segmented_recovery import (
    classify_segment_trust, recover_uniform_hd, recover_coefficient_first,
)
from simulation.integrity_schemes import SegmentedScheme, AdmitConfig, _strip_to_code
from simulation.recovery_decode_sim import _try_decode


# ── byte -> "which segment / which region" ────────────────────────────────────
def describe_byte(idx: int, segments) -> str:
    """Locate a wire byte index inside the segment layout: which segment, and
    whether it is a payload / salt / tag byte (the three regions of a TaggedSegment)."""
    for seg in segments:
        if seg.start <= idx < seg.start + seg.total_length:
            off = idx - seg.start
            if off < seg.payload_length:
                return f"{seg.name}.payload[{off}]"
            if off == seg.payload_length:
                return f"{seg.name}.salt"
            return f"{seg.name}.tag[{off - seg.payload_length - 1}]"
    return f"<byte {idx} past layout>"   # tag columns beyond declared segments == bug signal


def diff_regions(clean: bytearray, polluted: bytearray, segments) -> list[str]:
    return [describe_byte(i, segments) for i in range(len(polluted)) if clean[i] != polluted[i]]


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Per-round inspector for the keyless segmented scheme.")
    p.add_argument("--n", type=int, default=3, help="total segments N (default 3)")
    p.add_argument("--strategy", choices=["uniform_hd", "coefficient_first"], default="uniform_hd")
    p.add_argument("--gen-size", type=int, default=10)
    p.add_argument("--data-fields", type=int, default=48, help="must clear the rank floor for this N")
    p.add_argument("--ber", type=float, default=1e-3)
    p.add_argument("--hd", type=int, default=2, help="max_combined_hd; <2 -> combined recovery is a no-op")
    p.add_argument("--verify-count", type=int, default=4, help="witnesses per cross-check; 0 = self-check only")
    p.add_argument("--pair-budget", type=int, default=100_000)
    p.add_argument("--min-trust", type=int, default=4)
    p.add_argument("--min-pool", type=int, default=10)
    p.add_argument("--max-packets-factor", type=int, default=12)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    random.seed(args.seed)
    base_field = create_field(args.gen_size and 8)  # field m=8, gen_size independent

    scheme = SegmentedScheme(num_data_segments=args.n - 1, data_fields=args.data_fields,
                             strategy=args.strategy, name="inspect")
    cfg = AdmitConfig(hamming_distance=args.hd, verify_count=args.verify_count,
                      pair_budget=args.pair_budget, min_trust_count=args.min_trust,
                      min_pool_size=args.min_pool)

    gen_size = args.gen_size
    segments = layout_segments(gen_size, args.data_fields, args.n - 1)

    print("=" * 78)
    print(f"SegmentedScheme (keyless)  N={args.n}  strategy={args.strategy}  seed={args.seed}")
    print(f"gen_size={gen_size}  data_fields={args.data_fields}  BER={args.ber:g}")
    print(f"HD={args.hd}  verify_count={args.verify_count}  pair_budget={args.pair_budget}  "
          f"min_trust={args.min_trust}  min_pool={args.min_pool}")
    print("segment layout (start, payload_len, +1 salt, +gen_size tags):")
    for seg in segments:
        print(f"   {seg.name:8s} start={seg.start:3d} payload={seg.payload_length:3d} "
              f"total={seg.total_length:3d}")
    print("=" * 78)

    source, source_suffix = scheme.make_source(base_field, args.data_fields, gen_size)
    instrument = scheme.new_instrument(base_field)
    field = instrument.field   # CountingField with detection/recovery phase buckets
    cnt_decode = CountingField(base_field)
    max_packets = args.max_packets_factor * gen_size

    pool: list[bytearray] = []
    received = 0
    pollution_log: list[str] = []
    decoded = correct = False

    while received < max_packets:
        clean = bytearray(recode_rlnc_without_coeffs(base_field, source, gen_size, count=1))
        wire = scheme.attach(instrument, clean)              # identity (homomorphic)
        polluted = pollute_generation(base_field, [wire], args.ber, pollute_random)[0]
        flipped = diff_regions(wire, bytearray(polluted), segments)
        pollution_log += flipped
        pool.append(bytearray(polluted))
        received += 1

        hdr = f"[round {received:2d}] pool={len(pool):2d}"
        if flipped:
            hdr += "  NEW ERRORS: " + ", ".join(flipped)
        else:
            hdr += "  (clean packet)"
        print(hdr)

        # gate 1: below gen_size / min_pool -> admit is a no-op ("waiting").
        if len(pool) < max(gen_size, cfg.min_pool_size):
            print(f"          waiting: pool < max(gen_size={gen_size}, min_pool={cfg.min_pool_size})")
            continue

        # pre-check: who is already good in EVERY segment, no repair. (mirrors admit)
        already_good = set(range(len(pool)))
        pre = []
        for seg in segments:
            t = classify_segment_trust(field, pool, seg, verify_count=cfg.verify_count)
            pre.append((seg.name, len(t.trusted), len(t.broken)))
            already_good &= set(t.trusted)
        print("          pre-check trust  " +
              "  ".join(f"{n}:trust={tr},brk={br}" for n, tr, br in pre))

        if len(already_good) >= gen_size:
            print(f"          -> {len(already_good)} packets clean in all segments, "
                  f"NO repair search needed")
            accepted = [_strip_to_code(pool[i], segments) for i in sorted(already_good)]
        else:
            # repair: pairing + combined search across every segment
            mul_before = field.mul_count
            if args.strategy == "uniform_hd":
                report = recover_uniform_hd(field, pool, segments, max_combined_hd=cfg.hamming_distance,
                                            candidates_budget=cfg.pair_budget,
                                            pair_cache=instrument.pair_cache, verify_count=cfg.verify_count)
            else:
                report = recover_coefficient_first(field, pool, segments, gen_size,
                                                   max_combined_hd=cfg.hamming_distance,
                                                   candidates_budget=cfg.pair_budget,
                                                   pair_cache=instrument.pair_cache, verify_count=cfg.verify_count)
            for o in report.per_segment:
                # accumulate into the instrument exactly like SegmentedScheme.admit does,
                # so the end-of-run totals match the per-round lines.
                instrument.pairs_recovered += o.pairs_recovered
                instrument.pairs_failed += o.pairs_failed
                instrument.unpaired_recovered += o.unpaired_recovered
                instrument.unpaired_failed += o.unpaired_failed
                if o.pairs_recovered or o.pairs_failed or o.unpaired_recovered or o.unpaired_failed:
                    print(f"          repair {o.segment_name:8s} "
                          f"pairs +{o.pairs_recovered}/-{o.pairs_failed}  "
                          f"unpaired +{o.unpaired_recovered}/-{o.unpaired_failed}")
            print(f"          repair muls this round: {field.mul_count - mul_before}")

            # post-repair: a packet is admitted only if EVERY segment trusts it (intersection)
            good = set(range(len(report.packets)))
            waiting = False
            post = []
            for seg in segments:
                t = classify_segment_trust(field, report.packets, seg, verify_count=cfg.verify_count)
                post.append((seg.name, len(t.trusted)))
                if len(t.trusted) < cfg.min_trust_count:
                    waiting = True
                good &= set(t.trusted)
            print("          post-repair trust " +
                  "  ".join(f"{n}:trust={tr}" for n, tr in post))
            if waiting:
                print(f"          waiting: a segment has < min_trust={cfg.min_trust}")
                continue
            print(f"          -> {len(good)} packets trusted in ALL segments (intersection)")
            accepted = [_strip_to_code(report.packets[i], segments) for i in sorted(good)]

        decoded, correct = _try_decode(cnt_decode, accepted, gen_size, source_suffix)
        print(f"          decode: admitted={len(accepted)}  decoded={decoded}  correct={correct}")
        if decoded:
            break

    # ── summary ────────────────────────────────────────────────────────────
    status = "decoded" if correct else ("SILENT_DECODE" if decoded else "timeout")
    print("=" * 78)
    print(f"RESULT: {status}   packets_to_decode={received}   overhead={received / gen_size:.2f}x")
    print(f"pairs recovered={instrument.pairs_recovered} failed={instrument.pairs_failed}   "
          f"unpaired recovered={instrument.unpaired_recovered} failed={instrument.unpaired_failed}")
    pm = field.phase_mul
    print(f"field muls: total={field.mul_count}  detection={pm.get('detection', 0)}  "
          f"recovery={pm.get('recovery', 0)}")
    print(f"decode muls (separate counter): {cnt_decode.mul_count}")
    if pollution_log:
        from collections import Counter
        by_region = Counter(r.split(".")[1].split("[")[0] for r in pollution_log)
        by_seg = Counter(r.split(".")[0] for r in pollution_log)
        print(f"total byte errors injected: {len(pollution_log)}  "
              f"by region={dict(by_region)}  by segment={dict(by_seg)}")
    print("=" * 78)


if __name__ == "__main__":
    main()
