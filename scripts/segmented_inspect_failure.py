"""Inspect what FAILED in a segmented recovery trial (ADR-0012).

pairs_failed>0 in the single-trial harness means the combined search couldn't
split some broken pair -- almost always OVERLAPPING errors (same byte column hit
in both packets, so they cancel in the XOR-combined row the search works on) or a
search-budget give-up. This script reproduces a failing trial deterministically
and dumps the real packet bytes of each failed pair so you can SEE it.

    LOG_FOLDER="./logs" PYTHONPATH=. \
      "E:/projects/studienarbeit/.venv/Scripts/python.exe" \
      scripts/segmented_inspect_failure.py [--ber 5e-4] [--seed N] [--max-seeds 200]

No --seed: scans seeds 0.. until one yields a failed pair (reproducible run).
Uses the same field/gen_size/data_fields/cfg as run_segmented_n_sweep.
"""
import argparse
import random

from binary_ext_fields.generate_symbols import create_field
import binary_ext_fields.segmented_recovery as sr
from binary_ext_fields.segmented_tagging import layout_segments
from simulation.integrity_schemes import SCHEMES, AdmitConfig, SEGMENTED_DATA_FIELDS
import simulation.scheme_comparison_sim as scs
from simulation.scheme_comparison_sim import (
    run_recovery_trial, FIELD_M, GEN_SIZE, SEGMENTED_MAX_PACKETS_FACTOR,
)

# ── capture: wrap the two recovery fns so a failed pair records its real bytes ──
_ctx = {"segment": None, "pairs": [], "idx": 0}
_captured = []  # one dict per failed pair
_pool_log = []  # (clean_wire, polluted_wire) per received packet, in pool order
_orig_repair = sr.repair_segment
_orig_search = sr.recover_pair_by_combined_search
_orig_pollute = scs.pollute_generation


def _pollute_wrap(base_field, wires, ber, mode):
    # run_recovery_trial pollutes one fresh wire at a time; log clean+polluted so a
    # failed pair can be diffed against ground truth to locate every injected flip.
    out = _orig_pollute(base_field, wires, ber, mode)
    for clean, polluted in zip(wires, out):
        _pool_log.append((bytes(clean), bytes(polluted)))
    return out


def _classify_flip(offset, segs):
    """(segment_name, region, local_index) for a global byte offset. region in
    {'payload','salt','tag'} -- the three parts of a segment's [payload|salt|tags]."""
    for s in segs:
        if s.start <= offset < s.start + s.total_length:
            local = offset - s.start
            if local < s.payload_length:
                return s.name, "payload", local
            if local == s.payload_length:
                return s.name, "salt", 0
            return s.name, "tag", local - s.payload_length - 1
    return "?", "?", offset


def _flips_for(index, segs):
    """Byte-level diff of pool packet `index`: clean vs polluted, classified."""
    clean, polluted = _pool_log[index]
    flips = []
    for off in range(min(len(clean), len(polluted))):
        if clean[off] != polluted[off]:
            name, region, local = _classify_flip(off, segs)
            flips.append((off, name, region, local, clean[off], polluted[off]))
    return flips


def _repair_wrap(field, packets, segment, candidate_columns_for, **kw):
    # repair_segment recomputes trust+plan from these exact packets; mirror it so we
    # know which (packet_a, packet_b) each subsequent search call corresponds to.
    plan = sr.plan_pairing(sr.classify_segment_trust(field, packets, segment))
    _ctx.update(segment=segment, pairs=list(plan.pairs), idx=0)
    return _orig_repair(field, packets, segment, candidate_columns_for, **kw)


def _search_wrap(field, slice_a, slice_b, trusted_slices, candidate_columns, max_combined_hd, **kw):
    res = _orig_search(field, slice_a, slice_b, trusted_slices, candidate_columns, max_combined_hd, **kw)
    i = _ctx["idx"]
    _ctx["idx"] += 1
    if not res.ok and i < len(_ctx["pairs"]):
        pair = _ctx["pairs"][i]
        _captured.append({
            "segment": _ctx["segment"], "pair": pair,
            "slice_a": bytes(slice_a), "slice_b": bytes(slice_b),
            "columns": list(candidate_columns), "trusted_n": len(trusted_slices),
            "hd_found": res.combined_hd_found, "candidates_tried": res.candidates_tried,
        })
    return res


def _render_pair(field, rec, payload_len, segs):
    seg = rec["segment"]
    pa, pb = rec["pair"].packet_a, rec["pair"].packet_b
    print(f"\n  FAILED pair: segment={seg.name!r}  packets ({pa}, {pb})")
    print(f"    columns searched : {rec['columns']}  (payload_len={payload_len}; "
          f"salt+tag columns NOT searched)")
    print(f"    trusted refs      : {rec['trusted_n']}   hd_found={rec['hd_found']}   "
          f"candidates_tried={rec['candidates_tried']}")
    # Ground truth: where did pollution actually flip bytes in each packet?
    for pkt in (pa, pb):
        flips = _flips_for(pkt, segs)
        here = [f for f in flips if f[1] == seg.name]  # flips in THIS (failed) segment
        summary = ", ".join(f"{region}[{local}] {c:02x}->{p:02x}" for _, _, region, local, c, p in here) or "none"
        regions = sorted({f[2] for f in here})
        print(f"    packet {pkt}: flips in '{seg.name}' = {summary}"
              + (f"   <-- regions: {regions}" if here else ""))
        other = [f for f in flips if f[1] != seg.name]
        if other:
            print(f"              (also flipped elsewhere: "
                  + ", ".join(f"{name}.{region}[{local}]" for _, name, region, local, _, _ in other) + ")")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scheme", default="segmented_uniform_hd_n2")
    p.add_argument("--ber", type=float, default=5e-4)
    p.add_argument("--seed", type=int, default=None, help="fix the trial; omit to scan for a failing one")
    p.add_argument("--max-seeds", type=int, default=200)
    args = p.parse_args()

    base_field = create_field(FIELD_M)
    cfg = AdmitConfig(hamming_distance=2)
    scheme = SCHEMES[args.scheme]

    sr.repair_segment = _repair_wrap
    sr.recover_pair_by_combined_search = _search_wrap
    scs.pollute_generation = _pollute_wrap
    try:
        seeds = [args.seed] if args.seed is not None else range(args.max_seeds)
        for seed in seeds:
            _captured.clear()
            _pool_log.clear()
            random.seed(seed)
            r = run_recovery_trial(base_field, scheme, SEGMENTED_DATA_FIELDS, GEN_SIZE, args.ber, cfg,
                                   max_packets_factor=SEGMENTED_MAX_PACKETS_FACTOR)
            if _captured or args.seed is not None:
                break
    finally:
        sr.repair_segment = _orig_repair
        sr.recover_pair_by_combined_search = _orig_search
        scs.pollute_generation = _orig_pollute

    print(f"=== seed={seed} scheme={args.scheme} BER={args.ber:g} "
          f"gen_size={GEN_SIZE} data_fields={SEGMENTED_DATA_FIELDS} ===")
    print(f"  status={r.status} correct={r.correct} overhead={r.overhead} "
          f"pairs_recovered={r.pairs_recovered} pairs_failed={r.pairs_failed}")
    if not _captured:
        print("\nNo failed pair captured (try a higher --ber or --max-seeds).")
        return

    segs = layout_segments(GEN_SIZE, SEGMENTED_DATA_FIELDS, scheme.num_data_segments)
    seg_len = {s.name: s.payload_length for s in segs}
    # Dedup: the same (segment, pair) re-searched across rounds is one distinct failure.
    seen, distinct = set(), []
    for rec in _captured:
        key = (rec["segment"].name, rec["pair"].packet_a, rec["pair"].packet_b)
        if key not in seen:
            seen.add(key)
            distinct.append(rec)
    print(f"\n{len(_captured)} failed-pair search(es), {len(distinct)} DISTINCT stuck pair(s) "
          f"(the rest are per-round re-searches of the same pair):")
    for rec in distinct:
        _render_pair(base_field, rec, seg_len[rec["segment"].name], segs)


if __name__ == "__main__":
    main()
