"""Test bench for the segmented N-sweep runner plumbing (ticket 02): the per-cell
runtime cap and the empty-legend plot guard. Deliberately does NOT re-test the
recovery mechanics -- those are covered by segmented_recovery_test.py; here we only
pin the sweep-driver behaviour the ticket added.

Run:  .venv/Scripts/python.exe simulation/scheme_comparison_test.py
(no pytest dependency; a tiny built-in harness reports PASS/FAIL and sets the exit code.)
"""

import os
import sys
import time
import warnings
from pathlib import Path

# Make the file runnable directly without pre-exporting PYTHONPATH / LOG_FOLDER,
# which the imported modules require at import time.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

import matplotlib
matplotlib.use("Agg")  # headless: never pop a window during tests

from simulation.scheme_comparison_sim import _run_capped_cell, _plot_by_n_strategy


# ══ Per-cell runtime cap ═════════════════════════════════════════════════════

def test_cap_none_runs_all_trials():
    """No budget -> every requested trial runs."""
    calls = []
    results = _run_capped_cell(lambda: calls.append(1), num_trials=5, time_budget_s=None)
    assert len(results) == 5, len(results)
    assert len(calls) == 5, len(calls)


def test_cap_large_budget_runs_all_trials():
    """A budget far larger than the work never trips -> all trials run."""
    results = _run_capped_cell(lambda: None, num_trials=4, time_budget_s=1000.0)
    assert len(results) == 4, len(results)


def test_cap_small_budget_stops_early():
    """A budget smaller than num_trials * per-trial-time stops before the full count
    and records fewer trials than requested."""
    def slow_trial():
        time.sleep(0.03)
        return "r"
    results = _run_capped_cell(slow_trial, num_trials=100, time_budget_s=0.12)
    assert 1 <= len(results) < 100, len(results)


def test_cap_always_runs_at_least_one_trial():
    """Even a zero/negative budget must run one trial -- an empty cell is useless and
    would divide-by-zero downstream."""
    results = _run_capped_cell(lambda: "r", num_trials=10, time_budget_s=0.0)
    assert len(results) == 1, len(results)


def test_cap_returns_trial_return_values_in_order():
    """The returned list is exactly the trial_fn outputs, in call order."""
    seq = iter(range(5))
    results = _run_capped_cell(lambda: next(seq), num_trials=5, time_budget_s=None)
    assert results == [0, 1, 2, 3, 4], results


# ══ Empty-legend plot guard ══════════════════════════════════════════════════

def _all_nan_summary_rows():
    """A summary where every plotted metric is NaN and there is no N=1 baseline row --
    the ic-refinement plot's 'no pair ever attempted' case that used to warn."""
    return [
        {"scheme": "segmented_uniform_hd_n2", "n": 2, "strategy": "uniform_hd",
         "bit_error_rate": 1e-4, "ic_refinement_failure_rate": float("nan")},
        {"scheme": "segmented_uniform_hd_n2", "n": 2, "strategy": "uniform_hd",
         "bit_error_rate": 1e-3, "ic_refinement_failure_rate": float("nan")},
    ]


def test_empty_legend_emits_no_warning(tmp_path=None):
    """Plotting an all-NaN metric with no baseline and no hline must not trip
    matplotlib's 'No artists with labels found to put in legend' warning."""
    out = Path(os.environ["LOG_FOLDER"]) / "_test_empty_legend.png"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _plot_by_n_strategy(_all_nan_summary_rows(), n_values=(2,), strategies=("uniform_hd",),
                            metric="ic_refinement_failure_rate", ylabel="test",
                            output_path=out, ylim=(-0.02, 1.02), hline=None)
    legend_warnings = [w for w in caught if "legend" in str(w.message).lower()]
    assert not legend_warnings, [str(w.message) for w in legend_warnings]
    out.unlink(missing_ok=True)


def test_populated_plot_still_saves(tmp_path=None):
    """A plot that DOES have data still renders and writes its file (guard didn't
    suppress a real legend)."""
    rows = [
        {"scheme": "orthogonal", "n": 1, "strategy": "orthogonal",
         "bit_error_rate": 1e-4, "correct_rate": 0.9},
        {"scheme": "orthogonal", "n": 1, "strategy": "orthogonal",
         "bit_error_rate": 1e-3, "correct_rate": 0.5},
    ]
    out = Path(os.environ["LOG_FOLDER"]) / "_test_populated.png"
    out.unlink(missing_ok=True)
    _plot_by_n_strategy(rows, n_values=(1,), strategies=(), metric="correct_rate",
                        ylabel="test", output_path=out, ylim=(-0.02, 1.02))
    assert out.exists(), out
    out.unlink(missing_ok=True)


# ══ Tiny harness ═════════════════════════════════════════════════════════════

def _run() -> int:
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    print("=" * 78)
    print(f"TESTS  ({len(tests)} cases)")
    print("=" * 78)
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS   {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL   {name}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001 -- report, don't abort the suite
            print(f"  ERROR  {name}: {type(e).__name__}: {e}")
            failed += 1
    print("-" * 78)
    print(f"  {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
