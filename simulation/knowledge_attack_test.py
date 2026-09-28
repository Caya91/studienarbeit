"""Ticket 17 Part B tests -- partial-knowledge forgery (simulation/knowledge_attack_sim.py).

What must hold for the q^-u comparison to be trustworthy, checked independently:
  - pairing: same seed -> same data, honest rows, victim and c' in both arms / every level;
    c' innovative (outside the receiver's honest span) and != the victim row;
  - the forgers do exactly what they claim: keyless slice satisfies self + every observed
    cross constraint with RANDOMISED free tags; keyed tags exact for leaked keys, uniform
    otherwise; the forged packet differs from the victim only in its coeff segment;
  - end points: u = 0 always silent (both arms, all fields, both strikes); max u at GF(2^8)
    never silent;
  - keyless early strike: the production receiver's verdict == the strict oracle, per trial;
  - Monte Carlo: strict-oracle pass rate tracks q^-u in both arms (GF(2^2), GF(2^4));
  - the two measured deviations, pinned by mechanism and by formula:
      keyed repair (hd=1 corrects a guessed tag one bit off; hd=0 control == oracle),
      keyless late-strike greedy-peel tie-break (late admits a superset of early);
  - attacker work (keyed exactly k*g muls), batch invariants (silent => admitted, no
    timeouts, clean decode otherwise), an N=5 spot check;
  - theory functions, Wilson CI, smoke shape, frozen CSV schema + summary + replot, determinism.

Run (PowerShell, main .venv, from the worktree/repo root); exit code 0 = pass (~5 min):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" simulation/knowledge_attack_test.py
"""
import csv
import math
import random
import tempfile
from pathlib import Path

from binary_ext_fields.custom_field import CountingField
from binary_ext_fields.generate_symbols import check_orth_packet
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.segmented_mac_tagging import mac_tag_vector
from simulation.attack_harness import default_cfg, field_for, in_row_span, recode, row_outside_span, row_rank
from simulation.knowledge_attack_sim import (
    ARMS, CSV_COLUMNS, STRIKES, forge_coeff_keyed, forge_coeff_keyless, knowledge_levels, paired_plan,
    run_knowledge_trial, run_smoke, run_sweep, splice_coeff, summarize, theory_admit, theory_keyed_repair,
    theory_keyless_late, theory_pass, unknown_constraints, wilson,
)

G, D, N = 4, 12, 2


def _within(p_hat, p, n, z=4.5):
    """|p_hat - p| within z binomial standard errors (plus a 1/n granularity floor)."""
    return abs(p_hat - p) <= z * math.sqrt(max(p * (1 - p), 1e-12) / n) + 1.0 / n


def _cfg(hd):
    cfg = default_cfg(G)
    cfg.hamming_distance = hd
    return cfg


def _rate(trials, field):
    return sum(getattr(t, field) for t in trials) / len(trials)


def test_theory_functions():
    assert theory_pass(4, 0) == 1.0 and theory_pass(4, 1) == 0.25 and theory_pass(16, 2) == 1 / 256
    assert theory_keyed_repair(4, 2, 1, 4, 0) == 0.25
    assert math.isclose(theory_keyed_repair(4, 2, 1, 4, 1), 0.75 + 0.25 * 4 * 2 / 256)
    assert theory_keyed_repair(4, 2, 0, 4, 1) == 1.0, "u=0 must be exactly 1 (no probability > 1)"
    assert math.isnan(theory_keyed_repair(4, 2, 1, 4, 2))
    assert math.isclose(theory_keyless_late(4, 1), 0.25 * (1 + 0.75 ** 2))
    assert theory_keyless_late(16, 0) == 1.0
    assert theory_admit("keyless", "early", 4, 2, 2, 4, 1) == theory_pass(4, 2)
    assert theory_admit("keyless", "late", 4, 2, 2, 4, 1) == theory_keyless_late(4, 2)
    assert theory_admit("keyed", "late", 4, 2, 2, 4, 1) == theory_keyed_repair(4, 2, 2, 4, 1)
    for arm in ARMS:
        us = [unknown_constraints(arm, k, G) for k in knowledge_levels(arm, G)]
        assert us[-1] == 0 and us == sorted(us, reverse=True)
    lo, hi = wilson(0, 100)
    assert lo == 0 and 0.03 < hi < 0.045
    lo, hi = wilson(100, 100)
    assert math.isclose(hi, 1.0) and 0.95 < lo < 0.97
    print("  q^-u, repair / late-strike formulas, dispatch, u ranges, Wilson CI")


def test_plan_paired_and_innovative():
    for m in (2, 4, 8):
        f = field_for(m)
        for seed in range(8 if m < 8 else 3):
            plans = {arm: paired_plan(seed, f, G, D, N, arm) for arm in ARMS}
            (s0, p0), (s1, p1) = plans["keyless"], plans["keyed"]
            assert [bytes(r) for r in s0.data_rows] == [bytes(r) for r in s1.data_rows]
            assert [bytes(r) for r in p0.head] == [bytes(r) for r in p1.head]
            assert (p0.victim_row, p0.forged_row, p0.tail_seed) == (p1.victim_row, p1.forged_row, p1.tail_seed)
            assert row_rank(f, p0.head) == G - 1
            assert not in_row_span(f, p0.forged_row, p0.head), "c' must be innovative"
            assert p0.forged_row != p0.victim_row and any(p0.victim_row)
    print("  identical plan in both arms; head rank g-1; c' innovative and != victim (m=2,4,8)")


def test_keyless_forgery_satisfies_constraints_and_is_random():
    fails = 0
    zero_bytes = total_bytes = 0
    for m in (2, 4, 8):
        f = field_for(m)
        for seed in range(6 if m < 8 else 2):
            setup, plan = paired_plan(seed, f, G, D, N, "keyless")
            seg = setup.coeff_segment()
            head = [recode(setup, r) for r in plan.head]
            victim = recode(setup, plan.victim_row)
            for r in range(G):
                rng = random.Random(f"{seed}/{r}")
                sl, attempts = forge_coeff_keyless(
                    setup, head[:r], plan.forged_row, rng, CountingField(f),
                    new_row=lambda: row_outside_span(rng, f, G, plan.head, exclude=[plan.victim_row]))
                if sl is None:
                    fails += 1
                    continue
                assert attempts >= 1 and len(sl) == seg.total_length
                if attempts == 1:
                    assert list(sl[:G]) == list(plan.forged_row), "first attempt must use the planned c'"
                else:
                    assert not in_row_span(f, sl[:G], plan.head), "a redrawn c' must stay innovative"
                assert check_orth_packet(f, sl), "forged coeff slice must self-verify"
                for h in head[:r]:
                    assert inner_product_bytes(f, sl, h[seg.start:seg.start + seg.total_length]) == 0
                forged = splice_coeff(setup, victim, sl)
                assert forged[seg.start + seg.total_length:] == victim[seg.start + seg.total_length:]
                assert forged != victim
                if m == 8 and r == 0:
                    zero_bytes += sum(b == 0 for b in sl[seg.payload_length + 1:])
                    total_bytes += G
    assert fails == 0, f"{fails} keyless forgeries failed (solve inconsistent every retry)"
    assert zero_bytes <= total_bytes // 4, f"free tag variables look zeroed ({zero_bytes}/{total_bytes} zero bytes)"
    print(f"  keyless slices: self + every observed cross check hold, data segments untouched, 0 forge failures; "
          f"free tags randomised ({zero_bytes}/{total_bytes} zero bytes at r=0, GF(2^8))")


def test_keyed_forgery_known_exact_unknown_uniform():
    f = field_for(2)
    matches = trials = 0
    for seed in range(100):
        setup, plan = paired_plan(seed, f, G, D, N, "keyed")
        keys = setup.keyset[0]
        truth = mac_tag_vector(f, keys, plan.forged_row)
        for k in range(G + 1):
            sl = forge_coeff_keyed(setup, k, plan.forged_row, random.Random(f"{seed}/{k}"), CountingField(f))
            tags = list(sl[G:])
            assert tags[:k] == truth[:k], "leaked-key tags must be exact"
            matches += sum(a == b for a, b in zip(tags[k:], truth[k:]))
            trials += G - k
    rate = matches / trials
    assert _within(rate, 1 / 4, trials), f"unknown tags hit the true MAC at {rate:.3f}, expected 1/q = 0.25"
    print(f"  leaked tags exact; guessed tags hit the true MAC at {rate:.3f} (1/q = 0.25, n={trials})")


def test_u0_always_silent():
    for m in (2, 4, 8):
        seeds = range(12 if m < 8 else 3)
        for strike in STRIKES:
            for arm, know in (("keyless", G - 1), ("keyed", G)):
                for s in seeds:
                    t = run_knowledge_trial(arm, know, s, field_bits=m, strike=strike)
                    assert t.u == 0 and t.oracle_pass and t.forged_admitted and t.silent, (m, strike, arm, s)
    print("  u=0 (keyless r=g-1 / keyed k=g): every trial silent, GF(2^2,4,8), both strikes")


def test_keyless_full_view_never_fails_to_forge():
    """Regression (first 4000-trial sweep): with the salt fixed, r = g-1 observed slices + the
    all-ones row were occasionally dependent and c' inconsistent -> forge failed 26/4000 at
    GF(2^4), so 'u=0' read 0.9935 instead of 1. Salt is now an unknown and c' is redrawn."""
    for m in (2, 4):
        ts = [run_knowledge_trial("keyless", G - 1, s, field_bits=m, receiver=False) for s in range(1500)]
        failed = sum(t.forge_failed for t in ts)
        redrawn = sum(t.forge_attempts > 1 for t in ts)
        assert failed == 0 and all(t.oracle_pass for t in ts), (m, failed)
        print(f"  GF(2^{m}) r=g-1: 1500/1500 forgeries pass the oracle ({redrawn} needed a c' redraw)")


def test_max_u_gf256_never_silent():
    for arm, know in (("keyless", 0), ("keyed", 0)):
        ts = [run_knowledge_trial(arm, know, s, field_bits=8) for s in range(40)]
        assert not any(t.silent or t.forged_admitted for t in ts), arm
        assert all(t.decoded and t.correct for t in ts)
    print("  max u at GF(2^8): 0/40 silent per arm, every generation decoded correctly")


def test_keyless_early_production_equals_oracle():
    agree = 0
    for r in range(G):
        for s in range(250):
            t = run_knowledge_trial("keyless", r, s, field_bits=2)
            assert t.forged_admitted == t.oracle_pass == t.silent, (r, s, t)
            assert not t.forged_modified
            agree += 1
    print(f"  {agree} keyless early trials: production admit == strict oracle == silent, per trial")


def test_oracle_rate_tracks_q_pow_minus_u():
    report = []
    for m, n in ((2, 1000), (4, 1000)):
        q = 2 ** m
        for arm in ARMS:
            for know in knowledge_levels(arm, G):
                u = unknown_constraints(arm, know, G)
                if u == 0 or q ** -u * n < 2:
                    continue      # u=0 is trivially 1; below ~2 expected events the rate says nothing
                ts = [run_knowledge_trial(arm, know, s, field_bits=m, receiver=False) for s in range(n)]
                rate = _rate(ts, "oracle_pass")
                report.append(f"{arm:<7} m={m} u={u}: {rate:.4f} vs {q ** -u:.4f}")
                assert _within(rate, q ** -u, n), report[-1]
    print("  strict-oracle pass rate within 4.5 SE of q^-u:\n    " + "\n    ".join(report))


def test_keyed_repair_amplification_mechanism():
    f = field_for(2)
    for know in (G - 1, G - 2):
        u = G - know
        off = [run_knowledge_trial("keyed", know, s, field_bits=2, cfg=_cfg(0)) for s in range(500)]
        on = [run_knowledge_trial("keyed", know, s, field_bits=2, cfg=_cfg(1)) for s in range(500)]
        assert all(a.forged_admitted == a.oracle_pass for a in off), "hd=0: admit must equal the oracle"
        for a, b in zip(off, on):
            assert a.oracle_pass == b.oracle_pass
            assert b.forged_admitted >= b.oracle_pass, "repair can only add admits"
        rate = _rate(on, "forged_admitted")
        th = theory_keyed_repair(4, 2, u, G, 1)
        assert _within(rate, th, len(on)), f"k={know}: admit {rate:.3f} vs repair theory {th:.3f}"
        # mechanism: every extra admit whose code is unchanged had exactly one guessed tag one bit off
        extra = [t for t in on if t.forged_admitted and not t.oracle_pass]
        assert extra
        for t in extra:
            setup, plan = paired_plan(t.seed, f, G, D, N, "keyed")
            sl = forge_coeff_keyed(setup, know, plan.forged_row, random.Random(f"{t.seed}/keyed/{know}/attacker"),
                                   CountingField(f))
            truth = mac_tag_vector(f, setup.keyset[0], plan.forged_row)
            bit_dist = sum(bin(a ^ b).count("1") for a, b in zip(sl[G:], truth))
            if not t.forged_modified:
                assert bit_dist == 1, f"seed {t.seed}: tag-only repair but guessed tags {bit_dist} bits off"
        print(f"  k={know} (u={u}): oracle {_rate(on, 'oracle_pass'):.3f}, hd=0 admit == oracle, "
              f"hd=1 admit {rate:.3f} vs theory {th:.3f}; {len(extra)} extra admits = receiver fixed a 1-bit tag guess"
              f" or a payload flip")


def test_late_strike_effects():
    for know in (1, 2):   # keyless u = 2, 1
        u = G - 1 - know
        early = [run_knowledge_trial("keyless", know, s, field_bits=2, strike="early") for s in range(400)]
        late = [run_knowledge_trial("keyless", know, s, field_bits=2, strike="late") for s in range(400)]
        for e, l in zip(early, late):
            assert e.oracle_pass == l.oracle_pass, "same forged packet in both strikes"
            assert l.forged_admitted >= e.forged_admitted, "late must admit everything early admits"
        late_only = [l for e, l in zip(early, late) if l.forged_admitted and not e.forged_admitted]
        assert late_only and not any(l.oracle_pass for l in late_only), "late-only admits must be oracle failures"
        rate = _rate(late, "forged_admitted")
        assert _within(rate, theory_keyless_late(4, u), len(late)), (u, rate)
        print(f"  keyless u={u}: early {_rate(early, 'forged_admitted'):.3f} (q^-u {4 ** -u:.3f}), "
              f"late {rate:.3f} (tie-break theory {theory_keyless_late(4, u):.3f}), {len(late_only)} late-only admits")
    for know in (2, 3):
        e = [run_knowledge_trial("keyed", know, s, field_bits=2, strike="early") for s in range(200)]
        l = [run_knowledge_trial("keyed", know, s, field_bits=2, strike="late") for s in range(200)]
        assert [(a.forged_admitted, a.silent) for a in e] == [(b.forged_admitted, b.silent) for b in l]
    print("  keyed: early and late identical per trial (tag check is order-independent)")


def test_attacker_work():
    for know in knowledge_levels("keyed", G):
        t = run_knowledge_trial("keyed", know, 3, field_bits=4, receiver=False)
        assert t.attacker_mul == know * G, (know, t.attacker_mul)
    means = []
    for r in knowledge_levels("keyless", G):
        ts = [run_knowledge_trial("keyless", r, s, field_bits=4, receiver=False) for s in range(20)]
        means.append(sum(t.attacker_mul for t in ts) / len(ts))
        assert all(t.forge_attempts >= 1 and not t.forge_failed for t in ts)
    assert means[0] > 0 and means == sorted(means), means
    print(f"  keyed muls = k*g exactly; keyless mean muls by r: {[round(x, 1) for x in means]} (increasing)")


def test_batch_invariants():
    n_trials = 0
    for arm in ARMS:
        for strike in STRIKES:
            for hd in (0, 1):
                for know in knowledge_levels(arm, G):
                    for s in range(25):
                        t = run_knowledge_trial(arm, know, s, field_bits=2, strike=strike, cfg=_cfg(hd))
                        n_trials += 1
                        assert t.decoded, f"timeout: {t}"
                        assert not t.silent or t.forged_admitted, "silent decode without an admitted forgery"
                        assert t.forged_admitted or t.correct, "clean pool decoded wrong"
                        assert not t.forged_modified or t.forged_admitted
                        assert t.packets_received <= 4 * G
    print(f"  {n_trials} trials: no timeouts; silent => forgery admitted; no forgery => correct decode")


def test_n5_spot_check():
    for arm, know in (("keyless", G - 1), ("keyed", G)):
        assert all(run_knowledge_trial(arm, know, s, field_bits=2, n=5).silent for s in range(10))
    for arm, know in (("keyless", G - 2), ("keyed", G - 1)):
        ts = [run_knowledge_trial(arm, know, s, field_bits=2, n=5, receiver=False) for s in range(600)]
        assert _within(_rate(ts, "oracle_pass"), 0.25, 600), arm
    print("  N=5: u=0 always silent; u=1 oracle ~ 1/4 in both arms (forgery flat in N)")


def test_determinism():
    for arm, know, strike in (("keyless", 1, "late"), ("keyed", 2, "early")):
        assert run_knowledge_trial(arm, know, 7, field_bits=2, strike=strike) == \
            run_knowledge_trial(arm, know, 7, field_bits=2, strike=strike)
    print("  identical inputs -> identical trial records")


def test_smoke_shape():
    text = run_smoke(mc_trials=4)
    assert "Partial-knowledge forgery" in text and "Monte Carlo" in text
    body = [line for line in text.splitlines() if line.startswith(("keyless ", "keyed "))]
    assert len(body) == 2 * (len(knowledge_levels("keyless", G)) + len(knowledge_levels("keyed", G)))
    print(f"  smoke: {len(body)} readable rows (per-trial + Monte Carlo)")


def test_sweep_csv_summary_and_replot():
    with tempfile.TemporaryDirectory() as tmp:
        out = run_sweep(trials=5, ms=(2,), strikes=STRIKES, hds=(0, 1), workers=1, out_dir=Path(tmp), chunk=5)
        with (out / "raw_trials.csv").open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == CSV_COLUMNS
            rows = list(reader)
        n_cells = 2 * 2 * (len(knowledge_levels("keyless", G)) + len(knowledge_levels("keyed", G)))
        assert len(rows) == 5 * n_cells
        with (out / "summary.csv").open(encoding="utf-8") as fh:
            summary = list(csv.DictReader(fh))
        assert len(summary) == n_cells and all(int(s["trials"]) == 5 for s in summary)
        assert len(summarize(rows)) == n_cells
        pngs = sorted(p.name for p in out.glob("*.png"))
        assert pngs == ["attacker_work_vs_u.png", "oracle_vs_u.png", "repair_effect_keyed.png", "silent_vs_u.png"], pngs
        from scripts.knowledge_attack_plots_from_csv import discover, load, plot_all, plot_silent
        assert discover([str(out)]) == [out / "raw_trials.csv"]
        made = plot_all(discover([str(out)]), Path(tmp) / "replot")
        assert len(made) == 4
        s = load(str(out), n=2)            # manual path: one call -> summary rows -> any single plot
        assert len(s) == n_cells and load(str(out), n=5) == []
        assert plot_silent(s, Path(tmp) / "single").name == "silent_vs_u.png"
    print(f"  frozen schema ({len(CSV_COLUMNS)} cols), {len(rows)} rows = cells x trials, summary per cell, "
          f"4 plots + replot from CSV")


if __name__ == "__main__":
    tests = [
        test_theory_functions,
        test_plan_paired_and_innovative,
        test_keyless_forgery_satisfies_constraints_and_is_random,
        test_keyed_forgery_known_exact_unknown_uniform,
        test_u0_always_silent,
        test_keyless_full_view_never_fails_to_forge,
        test_max_u_gf256_never_silent,
        test_keyless_early_production_equals_oracle,
        test_oracle_rate_tracks_q_pow_minus_u,
        test_keyed_repair_amplification_mechanism,
        test_late_strike_effects,
        test_attacker_work,
        test_batch_invariants,
        test_n5_spot_check,
        test_determinism,
        test_smoke_shape,
        test_sweep_csv_summary_and_replot,
    ]
    for test in tests:
        print(f"\n=== {test.__name__} ===")
        test()
        print(f"{test.__name__} passed")
    print("\nAll knowledge-attack tests passed!")
