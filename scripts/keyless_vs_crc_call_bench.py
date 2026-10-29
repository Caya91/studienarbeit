r"""Microbenchmark: one acceptance-check CALL, keyless vs CRC-32, as the repair search makes it
(ADR-0014; 2026-10-29 fused compiled keyless check, field backend `numba_check`).

Slice = one data segment of the ADR-0014 layout (gen_size 4): keyless 50 B payload + salt + 4 tags
= 55 B, CRC 50 B payload + 4 B CRC-32 = 54 B. One call = the harness oracle, unchanged call path:
  keyless  playground.new_recovery.is_orthogonal_to_trusted(field, c, helpers, W) -- self-check +
           the first W helper checks, early exit -- per field backend:
             table        pure-Python table loop (ADR-0014 main run)
             numba        compiled inner product, the loop around it in Python (ticket 21)
             numba_check  the whole check as ONE compiled call (this addendum)
  crc      segmented_crc.crc_verify_segment (zlib.crc32, C) and crc_verify_combined (the pair
           search's combined filter); raw zlib.crc32 on the 50 B payload as the floor.
Two candidates per arm: `clean` (passes: every product computed, keyless worst case) and `flipped`
(1 payload bit flipped: rejected -- keyless at the self-check, i.e. what >= 99 % of repair
candidates cost). CRC cost does not depend on the verdict.

No galois / pyerasure (ticket 21: slower than the table loop at this size).
Timing: warm-up (JIT excluded), min (and median) of `--repeat` repeats, one process.

Output (--out, default E:/projects/studienarbeit/logs/crc32_vs_keyless_compiled/bench):
  call_bench.csv   arm, variant, candidate, W, bytes, us_min, us_median, repeats, number

Run (PowerShell):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/keyless_vs_crc_call_bench.py
"""
import os

os.environ.setdefault("NUMBA_NUM_THREADS", "1")

import argparse
import csv
import statistics
import sys
import timeit
import zlib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from icecream import ic

ic.disable()  # playground/arc_pl.py debug prints

from binary_ext_fields.field_backends import make_counting_field
from binary_ext_fields.segmented_recovery import segment_slice as kl_slice
from playground.new_recovery import is_orthogonal_to_trusted
from simulation.isolated_recovery_sim import build_paired_pools
from simulation.segmented_crc import Crc32Instrument, crc_verify_combined, crc_verify_segment
from simulation.segmented_crc import segment_slice as crc_slice

KEYLESS_BACKENDS = ("table", "numba", "numba_check")
W_MAX = 4
DEFAULT_OUT = Path("E:/projects/studienarbeit/logs/crc32_vs_keyless_compiled/bench")


def bench(stmt: str, g: dict, repeat: int, target_s: float = 0.15) -> dict:
    """Warm up, pick `number` so one repeat takes ~target_s, return min/median us per call."""
    t = timeit.Timer(stmt, globals=g)
    t.timeit(number=50)
    one = t.timeit(number=200) / 200
    number = max(20, int(target_s / max(one, 1e-8)))
    ts = [x / number * 1e6 for x in t.repeat(repeat=repeat, number=number)]
    return {"us_min": min(ts), "us_median": statistics.median(ts), "repeats": repeat, "number": number}


def _flip(v: bytearray, bit: int) -> bytearray:
    out = bytearray(v)
    out[bit // 8] ^= 1 << (bit % 8)
    return out


def run(repeat: int, seed: int) -> list[dict]:
    pools = build_paired_pools(make_counting_field("table"), gen_size=4, data_fields=100,
                               num_data_segments=2, T=4, seed=seed)
    kl = next(s for s in pools.kl_segments if s.kind == "data")
    cs = next(s for s in pools.crc_segments if s.kind == "data")
    t0 = pools.target_idx[0]
    kl_clean = kl_slice(pools.kl_clean[t0], kl)
    helpers = [kl_slice(pools.kl_clean[h], kl) for h in pools.helper_idx]
    cr_clean = crc_slice(pools.crc_clean[t0], cs)
    assert len(kl_clean) == 55 and len(cr_clean) == 54, (len(kl_clean), len(cr_clean))
    kl_cands = {"clean": kl_clean, "flipped": _flip(kl_clean, 3)}
    cr_cands = {"clean": cr_clean, "flipped": _flip(cr_clean, 3)}
    combined = bytearray(a ^ b for a, b in zip(cr_clean, crc_slice(pools.crc_clean[pools.target_idx[1]], cs)))
    inst = Crc32Instrument()

    fields = {b: make_counting_field(b) for b in KEYLESS_BACKENDS}
    for name, c in kl_cands.items():   # every backend gives the same verdict before anything is timed
        for W in range(W_MAX + 1):
            verdicts = {b: is_orthogonal_to_trusted(f, c, helpers, W=W) for b, f in fields.items()}
            assert len(set(verdicts.values())) == 1, (name, W, verdicts)
            assert verdicts["table"] == (name == "clean"), (name, W, verdicts)
    assert crc_verify_segment(inst, cr_cands["clean"], cs) and not crc_verify_segment(inst, cr_cands["flipped"], cs)
    assert crc_verify_combined(inst, combined, cs)

    rows = []

    def add(arm, variant, candidate, W, nbytes, res):
        rows.append(dict(arm=arm, variant=variant, candidate=candidate, W=W, bytes=nbytes,
                         **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in res.items()}))
        print(f"  {arm:<8} {variant:<20} {candidate:<8} W={W:>2}  {res['us_min']:8.3f} us"
              f"  (median {res['us_median']:.3f})", flush=True)

    for name, c in kl_cands.items():
        for W in range(W_MAX + 1):
            for b, f in fields.items():
                add("keyless", b, name, W, 55, bench("orth(f, c, H, W=W)", {"orth": is_orthogonal_to_trusted, "f": f,
                                                                            "c": c, "H": helpers, "W": W}, repeat))
    for name, c in cr_cands.items():
        add("crc", "crc_verify_segment", name, -1, 54,
            bench("v(i, c, s)", {"v": crc_verify_segment, "i": inst, "c": c, "s": cs}, repeat))
    add("crc", "crc_verify_combined", "combined", -1, 54,
        bench("v(i, c, s)", {"v": crc_verify_combined, "i": inst, "c": combined, "s": cs}, repeat))
    add("crc", "zlib.crc32 raw", "clean", -1, 50,
        bench("crc32(p)", {"crc32": zlib.crc32, "p": bytes(cr_clean[:cs.payload_length])}, repeat))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--repeat", type=int, default=15)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    rows = run(a.repeat, a.seed)
    a.out.mkdir(parents=True, exist_ok=True)
    with open(a.out / "call_bench.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {a.out / 'call_bench.csv'}")


if __name__ == "__main__":
    main()
