r"""Microbenchmark: the keyless acceptance check (GF(2^8) inner products) per field backend, with
zlib.crc32 as the reference (ticket 21, ADR-0014).

Vector = one data-segment slice of the ADR-0014 layout: 50 B payload + 1 salt + 4 tags = 55 B
(gen_size 4, df 100, 2 data segments). A "check" = the keyless oracle on a CLEAN slice (worst case,
nothing short-circuits): self-check + the first W helper checks, W = 0..4.

Variants (library = what does the GF arithmetic):
  table              TableField loop, pure Python (today's path)
  galois_public      galois FieldArray public API per call: np.dot on two GF views (GF._view = no
                     per-call value verification; the verifying public .view(GF) is timed apart)
  galois_ufunc       galois' compiled lookup-multiply ufunc called directly + numpy XOR-reduce
                     (= the harness backend `--field-backend galois`)
  galois_public_batched / galois_ufunc_batched
                     self + W helpers as ONE call: (W+1) x 55 GF matrix times the candidate
                     (public: M @ c; ufunc: broadcast multiply + XOR-reduce along rows)
  pyerasure          pyerasure 1.3.0 Binary8 per-element ops -- pure Python as installed
  numba              own 4-line numba kernel over our mul table: compiled reference, NOT a library
  zlib               zlib.crc32 on the 50 B payload (raw) and the harness's crc_verify_segment

Checks first that every backend gives identical results (full multiplication tables, random
vectors of many lengths, real tagged slices + bit-flipped candidates through the real oracle);
then times each variant: warm-up (numba JIT excluded), min (and median) of >= 7 repeats -- min is
robust to background load. Single process; NUMBA_NUM_THREADS=1 keeps galois' numba-parallel matmul
on one core.

Output (--out, default E:/projects/studienarbeit/logs/crc32_vs_keyless_galois/bench):
  inner_product_bench.csv   measure, variant, library, in_harness, W, bytes, us_min, us_median, repeats, number
  inner_product_bench.png/.pdf

Run (PowerShell):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/inner_product_backend_bench.py
"""
import os

os.environ.setdefault("NUMBA_NUM_THREADS", "1")  # before numba/galois import (compute budget)

import argparse
import csv
import random
import statistics
import sys
import timeit
import zlib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from icecream import ic

ic.disable()  # playground/arc_pl.py debug prints

import numpy as np

from binary_ext_fields.custom_field import TableField, create_field
from binary_ext_fields.field_backends import make_counting_field, galois_field
from binary_ext_fields.operations import inner_product_bytes
from playground.new_recovery import is_orthogonal_to_trusted
from simulation.isolated_recovery_sim import build_paired_pools
from simulation.segmented_crc import Crc32Instrument, crc_verify_segment, segment_slice as crc_slice
from binary_ext_fields.segmented_recovery import segment_slice as kl_slice

W_MAX = 4
OUT_DEFAULT = Path("E:/projects/studienarbeit/logs/crc32_vs_keyless_galois/bench")


# ── the variants ────────────────────────────────────────────────────────────────

def make_variants(table: TableField):
    """name -> (library, per-call inner product fn(x, y) -> int)."""
    GF = galois_field(8, table.prime)
    gf_mul = GF._multiply.ufunc
    xor_reduce = np.bitwise_xor.reduce
    u8 = np.uint8
    pe_field = make_counting_field("pyerasure")
    nb_field = make_counting_field("numba")

    def galois_public(x, y):
        return int(np.dot(GF._view(np.frombuffer(x, dtype=u8)), GF._view(np.frombuffer(y, dtype=u8))))

    def galois_ufunc(x, y):
        return int(xor_reduce(gf_mul(np.frombuffer(x, dtype=u8), np.frombuffer(y, dtype=u8))))

    return {
        "table": ("none (pure Python)", lambda x, y: TableField.inner_product(table, x, y)),
        "galois_public": ("galois", galois_public),
        "galois_ufunc": ("galois", galois_ufunc),
        "pyerasure": ("pyerasure (pure Python)", pe_field._backend_inner_product),
        "numba": ("numba (own kernel)", nb_field._backend_inner_product),
    }


def make_batched(table: TableField, helpers, W: int):
    """name -> check fn(c) -> bool computing self + W helper products in ONE library call."""
    GF = galois_field(8, table.prime)
    gf_mul = GF._multiply.ufunc
    raw = np.empty((W + 1, len(helpers[0])), dtype=np.uint8)   # row 0 = candidate, rows 1.. = helpers
    for j in range(W):
        raw[j + 1] = np.frombuffer(helpers[j], dtype=np.uint8)
    M = GF._view(raw)   # shares memory with `raw`: writing raw[0] updates M

    def public(c):
        cn = np.frombuffer(c, dtype=np.uint8)
        raw[0] = cn
        return not (M @ GF._view(cn)).view(np.ndarray).any()

    def ufunc(c):
        cn = np.frombuffer(c, dtype=np.uint8)
        raw[0] = cn
        return not np.bitwise_xor.reduce(gf_mul(cn, raw), axis=1).any()

    def values(c, which):
        cn = np.frombuffer(c, dtype=np.uint8)
        raw[0] = cn
        if which == "public":
            return [int(v) for v in (M @ GF._view(cn)).view(np.ndarray)]
        return [int(v) for v in np.bitwise_xor.reduce(gf_mul(cn, raw), axis=1)]

    return {"galois_public_batched": public, "galois_ufunc_batched": ufunc}, values


# ── correctness first ───────────────────────────────────────────────────────────

def assert_identical(table, variants, kl_ref, helpers, rng: random.Random) -> int:
    GF = galois_field(8, table.prime)
    g_tab = np.asarray(GF.Range(0, 256)[:, None] * GF.Range(0, 256)[None, :]).astype(int)
    assert (g_tab == np.array(table._mul)).all(), "galois multiplication table != ours (modulus?)"
    pe = make_counting_field("pyerasure")._pe
    assert all(pe._table.multiply(a, b) == table._mul[a][b] for a in range(256) for b in range(256)), \
        "pyerasure multiplication table != ours"
    n_checked = 0
    lengths = [rng.randrange(0, 81) for _ in range(3000)] + [55] * 2000
    for n in lengths:
        x = bytearray(rng.randrange(256) for _ in range(n))
        y = bytearray(rng.randrange(256) for _ in range(n))
        want = TableField.inner_product(table, x, y)
        for name, (_, fn) in variants.items():
            assert fn(x, y) == want, f"{name}: <x,y> differs from table at n={n}"
        n_checked += 1
    # batched products, random candidates vs the real helpers
    for W in range(W_MAX + 1):
        _, values = make_batched(table, helpers, W)
        for _ in range(300):
            c = bytearray(rng.randrange(256) for _ in range(len(helpers[0])))
            want = [TableField.inner_product(table, c, v) for v in [c] + helpers[:W]]
            assert values(c, "public") == want and values(c, "ufunc") == want, f"batched W={W} differs"
            n_checked += 1
    # the real oracle on the clean slice + bit-flipped candidates, every backend field
    fields = {b: make_counting_field(b) for b in ("table", "galois", "pyerasure", "numba")}
    ref = make_counting_field("table")
    cands = [kl_ref] + [_flip(kl_ref, rng.sample(range(8 * len(kl_ref)), rng.randint(1, 3))) for _ in range(1500)]
    for c in cands:
        for W in range(W_MAX + 1):
            want = is_orthogonal_to_trusted(ref, c, helpers, W=W)
            for b, f in fields.items():
                assert is_orthogonal_to_trusted(f, c, helpers, W=W) == want, f"oracle differs: backend {b}, W={W}"
            for name, fn in make_batched(table, helpers, W)[0].items():
                assert fn(c) == want, f"oracle differs: {name}, W={W}"
            n_checked += 1
    counts = {b: (f.mul_count, f.add_count) for b, f in fields.items()}
    assert len(set(counts.values())) == 1, f"op counts differ across backends: {counts}"
    return n_checked


def _flip(v: bytearray, bits) -> bytearray:
    out = bytearray(v)
    for p in bits:
        out[p >> 3] ^= 1 << (p & 7)
    return out


# ── timing ──────────────────────────────────────────────────────────────────────

def bench(stmt: str, g: dict, repeat: int, target_s: float = 0.15) -> dict:
    """Warm up, pick `number` so one repeat takes ~target_s, return min/median us per call."""
    t = timeit.Timer(stmt, globals=g)
    t.timeit(number=50)                                   # warm-up (JIT paths already compiled)
    one = t.timeit(number=200) / 200
    number = max(20, int(target_s / max(one, 1e-8)))
    ts = [x / number * 1e6 for x in t.repeat(repeat=repeat, number=number)]
    return {"us_min": min(ts), "us_median": statistics.median(ts), "repeats": repeat, "number": number}


def run(out: Path, repeat: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    table = create_field(8)
    pools = build_paired_pools(make_counting_field("table"), gen_size=4, data_fields=100,
                               num_data_segments=2, T=4, seed=seed)
    kl = next(s for s in pools.kl_segments if s.kind == "data")
    cs = next(s for s in pools.crc_segments if s.kind == "data")
    t0 = pools.target_idx[0]
    kl_ref = kl_slice(pools.kl_clean[t0], kl)                       # clean: passes every check
    helpers = [kl_slice(pools.kl_clean[h], kl) for h in pools.helper_idx]
    cr = crc_slice(pools.crc_clean[t0], cs)
    payload = bytes(cr[:cs.payload_length])
    assert len(kl_ref) == 55 and len(payload) == 50, (len(kl_ref), len(payload))

    variants = make_variants(table)
    n_ok = assert_identical(table, variants, kl_ref, helpers, rng)
    print(f"all backends agree: {n_ok} vectors / candidates (full mul tables equal: galois, pyerasure)")

    rows = []

    def add(measure, variant, library, in_harness, W, nbytes, res):
        rows.append(dict(measure=measure, variant=variant, library=library, in_harness=in_harness, W=W,
                         bytes=nbytes, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in res.items()}))
        print(f"  {measure:<22} {variant:<24} W={W:>2}  {res['us_min']:9.3f} us (median {res['us_median']:.3f})")

    x = bytearray(rng.randrange(256) for _ in range(55))
    y = bytearray(rng.randrange(256) for _ in range(55))
    GF = galois_field(8, table.prime)
    print("per inner product, 55 B:")
    for name, (lib, fn) in variants.items():
        add("inner_product", name, lib, int(name in ("table", "galois_ufunc", "pyerasure", "numba")), -1, 55,
            bench("fn(x, y)", {"fn": fn, "x": x, "y": y}, repeat))
    g = {"np": np, "GF": GF, "x": x, "xg": GF._view(np.frombuffer(x, dtype=np.uint8)),
         "yg": GF._view(np.frombuffer(y, dtype=np.uint8))}
    add("conversion", "np.frombuffer", "numpy", 0, -1, 55, bench("np.frombuffer(x, dtype=np.uint8)", g, repeat))
    add("conversion", "frombuffer+view(GF)", "galois", 0, -1, 55,
        bench("np.frombuffer(x, dtype=np.uint8).view(GF)", g, repeat))
    add("conversion", "frombuffer+GF._view", "galois", 0, -1, 55,
        bench("GF._view(np.frombuffer(x, dtype=np.uint8))", g, repeat))
    for stmt, name in (("np.dot(xg, yg)", "np.dot (GF arrays ready)"), ("xg @ yg", "@ (GF arrays ready)"),
                       ("(xg * yg).sum()", "(x*y).sum() (GF ready)")):
        add("galois_public_op", name, "galois", 0, -1, 55, bench(stmt, g, repeat))

    print("one keyless check of a clean 55 B slice (self + W helpers):")
    fields = {b: make_counting_field(b) for b in ("table", "galois", "pyerasure", "numba")}
    harness_name = {"table": "table", "galois": "galois_ufunc", "pyerasure": "pyerasure", "numba": "numba"}
    for W in range(W_MAX + 1):
        H = helpers[:W]
        for b, f in fields.items():   # the harness oracle with the backend CountingField (= sweep path)
            add("check", harness_name[b], variants[harness_name[b]][0], 1, W, 55,
                bench("orth(f, c, H, W=W)", {"orth": is_orthogonal_to_trusted, "f": f, "c": kl_ref, "H": H, "W": W},
                      repeat))
        fn = variants["galois_public"][1]   # public galois per call, same early-exit order, no harness wrapper
        add("check", "galois_public", "galois", 0, W, 55,
            bench("fn(c, c) == 0 and all(fn(c, h) == 0 for h in H)", {"fn": fn, "c": kl_ref, "H": H}, repeat))
        for name, chk in make_batched(table, helpers, W)[0].items():
            add("check", name, "galois", 0, W, 55, bench("chk(c)", {"chk": chk, "c": kl_ref}, repeat))
    print("CRC-32 reference (50 B payload):")
    add("crc", "zlib.crc32 raw", "zlib (C)", 0, -1, 50, bench("crc32(p)", {"crc32": zlib.crc32, "p": payload}, repeat))
    add("crc", "crc_verify_segment", "zlib (C)", 1, -1, 54,
        bench("v(i, s, seg)", {"v": crc_verify_segment, "i": Crc32Instrument(), "s": cr, "seg": cs}, repeat))
    for f in fields.values():
        f.reset()

    out.mkdir(parents=True, exist_ok=True)
    with open(out / "inner_product_bench.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out / 'inner_product_bench.csv'}")
    return rows


# ── summary + chart ─────────────────────────────────────────────────────────────

LABEL = {
    "table": "table loop, pure Python (today)",
    "galois_public": "galois public API, per call (np.dot)",
    "galois_public_batched": "galois public API, batched (M @ c)",
    "galois_ufunc": "galois compiled ufunc, per call  [harness 'galois']",
    "galois_ufunc_batched": "galois compiled ufunc, batched",
    "pyerasure": "pyerasure 1.3.0 (pure Python)",
    "numba": "numba, own kernel (compiled; not a library)",
}


def summarize(rows: list[dict]) -> None:
    def us(measure, variant, W=-1):
        r = [x for x in rows if x["measure"] == measure and x["variant"] == variant and x["W"] == W]
        return r[0]["us_min"] if r else float("nan")
    z_raw, z_seg = us("crc", "zlib.crc32 raw"), us("crc", "crc_verify_segment")
    print(f"\nsummary (us, min of repeats)   zlib.crc32 raw {z_raw:.3f}, crc_verify_segment {z_seg:.3f}")
    print(f"  {'variant':<24} {'IP 55B':>8} {'chk W0':>8} {'chk W4':>8} {'W4/table':>9} {'W0/crc_seg':>10} {'W4/crc_seg':>10}")
    t4 = us("check", "table", 4)
    for v in LABEL:
        ip, c0, c4 = us("inner_product", v), us("check", v, 0), us("check", v, 4)
        print(f"  {v:<24} {ip:8.2f} {c0:8.2f} {c4:8.2f} {c4 / t4:9.2f} {c0 / z_seg:10.1f} {c4 / z_seg:10.1f}")


def plot(rows: list[dict], out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scripts.scaling_plots_from_csv import GRID, INK, INK_MUTED, _shade

    keyless, crc = "#588157", "#4a3aa7"
    w0_col, w4_col = _shade(keyless, 0.55), keyless

    def us(measure, variant, W=-1):
        return next(x["us_min"] for x in rows if x["measure"] == measure and x["variant"] == variant and x["W"] == W)

    order = ["table", "galois_public", "galois_public_batched", "galois_ufunc", "galois_ufunc_batched",
             "pyerasure", "numba"]

    def fmt(v):
        return f"{v:.0f}" if v >= 100 else f"{v:.3g}"

    def label(x_, y_, left):   # W=0 value left of its marker, W=4 value right -> no collisions
        ax.annotate(fmt(x_), (x_, y_), textcoords="offset points", xytext=(-8 if left else 8, 0),
                    ha="right" if left else "left", va="center", fontsize=7, color=INK)

    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    ys = np.arange(len(order) + 2)[::-1]
    for y, v in zip(ys, order):
        a, b = us("check", v, 0), us("check", v, W_MAX)
        ax.plot([a, b], [y, y], color=GRID, linewidth=3, zorder=1, solid_capstyle="round")
        ax.plot(a, y, "o", color=w0_col, markersize=8, markeredgecolor=keyless, markeredgewidth=1.2, zorder=3,
                label="keyless, self-check only (W=0)" if v == order[0] else None)
        ax.plot(b, y, "o", color=w4_col, markersize=8, zorder=3,
                label=f"keyless, self + {W_MAX} helpers (W={W_MAX})" if v == order[0] else None)
        label(a, y, left=True)
        label(b, y, left=False)
    crc_rows = [("crc_verify_segment", "CRC-32 zlib, harness check (crc_verify_segment)"),
                ("zlib.crc32 raw", "CRC-32 zlib.crc32 alone (50 B)")]
    for (v, _), y in zip(crc_rows, ys[len(order):]):
        c = us("crc", v)
        ax.plot(c, y, "^", color=crc, markersize=9, zorder=3, label="CRC-32 (zlib, C)" if v == crc_rows[0][0] else None)
        label(c, y, left=False)
    ax.set_yticks(ys, [LABEL[v] for v in order] + [lab for _, lab in crc_rows], fontsize=7.5)
    ax.set_xscale("log")
    ax.set_xlabel("µs per accept/reject check of one 50 B data segment (+ salt + 4 tags; log scale)",
                  color=INK, fontsize=9)
    ax.set_title("Keyless check per field backend vs CRC-32 (min of repeats, one process, loaded machine)",
                 color=INK, fontsize=10)
    ax.grid(True, axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED, labelcolor=INK, labelsize=8)
    ax.legend(fontsize=7.5, frameon=False, labelcolor=INK, loc="lower right")
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(out / f"inner_product_bench.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out / 'inner_product_bench.png'}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--repeat", type=int, default=7, help="timing repeats (min reported), >= 5")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--replot", action="store_true", help="re-read the CSV and redraw, no timing")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if a.replot:
        with open(out / "inner_product_bench.csv") as fh:
            rows = [dict(r, W=int(r["W"]), us_min=float(r["us_min"]), us_median=float(r["us_median"]))
                    for r in csv.DictReader(fh)]
    else:
        assert a.repeat >= 5, "--repeat must be >= 5 (min of repeats is the load-robust statistic)"
        rows = run(out, a.repeat, a.seed)
    summarize(rows)
    plot(rows, out)


if __name__ == "__main__":
    main()
