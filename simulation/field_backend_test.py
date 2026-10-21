"""Test bench for the GF inner-product backends (binary_ext_fields/field_backends.py, ticket 21) and
the isolated harness's `--field-backend` switch.

A backend may only change wall-clock: every outcome (target_outcomes, recovered/silent/failed) and
every op count (recovery_ops/mul/add, final_check_ops, phase buckets) must equal the table path's.

No pytest dependency -- same built-in PASS/FAIL harness as segmented_crc_test.py.

Run (PowerShell):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; .\\.venv\\Scripts\\python.exe simulation\\field_backend_test.py
"""
import contextlib
import io
import os
import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

from icecream import ic

from binary_ext_fields.custom_field import CountingField, create_field
from binary_ext_fields.field_backends import FIELD_BACKENDS, make_counting_field
from binary_ext_fields.operations import inner_product_bytes
from simulation.isolated_recovery_sim import CSV_COLUMNS, main, run_smoke, sweep_seed

ic.disable()  # playground/arc_pl.py debug prints

LIBRARY_BACKENDS = tuple(b for b in FIELD_BACKENDS if b != "table")
TIME_COLUMNS = {"recovery_time_s", "final_check_time_s"}   # the only columns a backend may change


def test_table_backend_is_the_plain_counting_field():
    f = make_counting_field("table", 8)
    assert type(f) is CountingField, f"default backend must stay CountingField, got {type(f).__name__}"
    assert f.prime == create_field(8).prime


def test_inner_product_and_counters_identical_to_counting_field():
    rng = random.Random(5)
    for m in (4, 8):
        ref = CountingField(create_field(m))
        fields = {b: make_counting_field(b, m) for b in LIBRARY_BACKENDS if not (b == "pyerasure" and m != 8)}
        for i in range(400):
            n = rng.choice((0, 1, 2, 55, rng.randrange(0, 90)))
            x = bytearray(rng.randrange(1 << m) for _ in range(n))
            y = bytearray(rng.randrange(1 << m) for _ in range(n))
            if i % 3 == 0:
                x, y = bytes(x), list(y)          # other input types take the same path
            phase = ("recovery", "detection", None)[i % 3]
            got = {}
            for b, f in [("table", ref), *fields.items()]:
                if phase is None:
                    got[b] = inner_product_bytes(f, x, y)
                else:
                    with f.phase(phase):
                        got[b] = inner_product_bytes(f, x, y)
            for b in fields:
                assert got[b] == got["table"], f"{b} m={m}: <x,y>={got[b]}, table {got['table']} (n={n})"
        for b, f in fields.items():
            got = (f.mul_count, f.add_count, f.phase_mul, f.phase_add)
            want = (ref.mul_count, ref.add_count, ref.phase_mul, ref.phase_add)
            assert got == want, f"{b} m={m}: counters {got} != table {want}"


def test_tables_untouched_by_backends():
    """mul/add (ACR's row ops, tagging) stay the table's in every backend."""
    base = create_field(8)
    for b in LIBRARY_BACKENDS:
        f = make_counting_field(b, 8)
        assert f._mul == base._mul and f._add == base._add, f"{b}: field tables changed"
        assert f.mul(7, 9) == base.mul(7, 9) and f.mul_count == 1, f"{b}: mul() broken"


def _sweep(backend: str, seed: int) -> list[dict]:
    return sweep_seed(seed, gen_size=4, T=4, data_fields=100, num_data_segments=2, field_bits=8,
                      Ws=(0, 1, 4), bers=(1e-3, 1e-2, 3e-2), spans=("payload",), configs=("arc_only_a",),
                      hds=(2,), budgets=(1500,), arms=("keyless", "keyed", "crc_acr", "crc_blind"),
                      field_backend=backend)


def test_sweep_outcomes_and_ops_identical_across_backends():
    """Small multi-seed sweep incl. high BER (3e-2) and W = 0 (silent decodes): every non-time
    column -- target_outcomes, recovered/silent/failed, recovery_ops/mul/add, final_check_ops, CRC
    bytes -- identical row for row in every backend, all four arms."""
    seen = {"R": 0, "S": 0, "F": 0}
    for seed in range(3):
        ref = _sweep("table", seed)
        for row in ref:
            for k in seen:
                seen[k] += row["target_outcomes"].count(k)
        for b in LIBRARY_BACKENDS:
            rows = _sweep(b, seed)
            assert len(rows) == len(ref), f"{b} seed {seed}: {len(rows)} rows vs {len(ref)}"
            for r, w in zip(rows, ref):
                diff = {c for c in CSV_COLUMNS if c not in TIME_COLUMNS and r[c] != w[c]}
                assert not diff, f"{b} seed {seed} {w['arm']} W={w['W']} ber={w['bit_error_rate']}: " \
                                 f"{ {c: (r[c], w[c]) for c in diff} }"
    assert all(seen.values()), f"sweep must exercise recovered, silent and failed outcomes: {seen}"


def test_smoke_identical_across_backends():
    def smoke(b):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = run_smoke(field_backend=b, arms=("keyless", "keyed", "crc_acr"))
        return buf.getvalue(), [(r.config, a, ar.outcomes, ar.mul, ar.add, ar.final_check_ops)
                                for r in res for a, ar in r.arm_results().items()]
    ref_txt, ref_res = smoke("table")
    for b in LIBRARY_BACKENDS:
        txt, res = smoke(b)
        assert res == ref_res, f"{b}: smoke outcomes/ops differ"
        assert txt == ref_txt, f"{b}: smoke text differs"


def test_cli_choice():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        try:
            main(["--smoke", "--field-backend", "nope"])
            raise AssertionError("an unknown backend must be rejected")
        except SystemExit as e:
            assert e.code != 0


# ══ harness ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"field_backend_test  ({len(tests)} cases)")
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"{'ALL PASS' if not failed else f'{failed} FAILED'}")
    sys.exit(1 if failed else 0)
