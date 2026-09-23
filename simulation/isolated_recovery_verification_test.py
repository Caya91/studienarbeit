"""
Elaborate verification for the isolated recovery comparison (ADR-0013, ticket 15 B/C)
plus the ticket-14 sweep's frozen CSV schema + replot.

Complements simulation/isolated_recovery_test.py (paired invariant, data-only strong-W
self-check, symmetric drop, helpers untouched). Here:
  - W semantics: empirical oracle wrong-accept rate vs q^-W (keyed exact; keyless a
    floor, gap reported), Monte Carlo in GF(2^4) (W=1..3) and GF(2^8) (W=1);
  - the keyless coeff-segment blind spot behind the measured coefficient_first silent
    decodes (identity-coeff helpers are sparse there) -- mechanism pinned, not "fixed";
  - silent-decode scoring is measured correctly (constructed recovered/silent/failed);
  - edge cases: W=0, W=gen_size, odd broken count (unpaired path), helper set = gen_size;
  - readable smoke is deterministic and has the ticket-15 shape;
  - sweep CSV matches CSV_COLUMNS, counts are consistent, replot-from-CSV works.

Silent-decode is a MEASURED output; nothing here bounds it except W=gen_size, where a
q^-gen_size collision is ~2^-48 and a silent decode would mean broken wiring.
Judge pass/fail by exit code (0 = pass). Run like isolated_recovery_sim.py's header.
"""
import contextlib
import csv
import io
import math
import random
import tempfile
from pathlib import Path

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import check_orth_packet
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.segmented_mac_tagging import mac_verify_segment

from simulation.isolated_recovery_sim import (
    build_paired_pools, run_config, run_smoke, run_sweep, InjectedErrors,
    score_keyless, score_keyed, info_columns, kl_slice, kd_slice,
    CONFIGS, CSV_COLUMNS, RECOVERED, SILENT, FAILED,
)


def _banner(name):
    print(f"\n=== {name} ===")


def _pools(seed=7, gen_size=6, T=6, data_fields=18, num_data_segments=3, bits=8):
    return build_paired_pools(CountingField(create_field(bits)), gen_size, data_fields, num_data_segments, T, seed)


def _keyless_accepts(field, sl, helper_slices, W):
    return check_orth_packet(field, sl) and all(inner_product_bytes(field, sl, h) == 0 for h in helper_slices[:W])


# ── B1: W semantics vs q^-W ───────────────────────────────────────────────────

def _mc_wrong_accept(pools, W, n, rng, seg_pos=1):
    """Uniform random nonzero error on one full segment slice of a clean target; rate at
    which each arm's W-oracle still accepts (= wrong-accept, the candidate is wrong)."""
    field = pools.field
    kl_seg, kd_seg = pools.kl_segments[seg_pos], pools.kd_segments[seg_pos]
    t = pools.target_idx[0]
    kl_c, kd_c = bytearray(kl_slice(pools.kl_clean[t], kl_seg)), bytearray(kd_slice(pools.kd_clean[t], kd_seg))
    helpers = [kl_slice(pools.kl_clean[h], kl_seg) for h in pools.helper_idx]
    keys = pools.keyset[seg_pos]
    acc_kl = acc_kd = 0
    for _ in range(n):
        e = bytearray(rng.randint(0, field.max_value) for _ in kl_c)
        if any(e):
            acc_kl += _keyless_accepts(field, bytearray(a ^ b for a, b in zip(kl_c, e)), helpers, W)
        e = bytearray(rng.randint(0, field.max_value) for _ in kd_c)
        if any(e):
            acc_kd += mac_verify_segment(field, keys, bytearray(a ^ b for a, b in zip(kd_c, e)), kd_seg, W=W)
    return acc_kl / n, acc_kd / n


def _within(p_hat, p, n, k=4.5):
    return abs(p_hat - p) <= k * math.sqrt(p * (1 - p) / n) + 1.0 / n


def test_w_semantics_wrong_accept_tracks_q_pow_minus_W():
    _banner("W semantics: random-error wrong-accept vs q^-W (keyed exact, keyless floor)")
    rng = random.Random(2026)
    cases = [(4, 1, 8000), (4, 2, 40000), (4, 3, 150000), (8, 1, 40000)]
    for bits, W, n in cases:
        pools = _pools(seed=3, gen_size=6, data_fields=12, num_data_segments=2, bits=bits)
        q = 1 << bits
        p_kl, p_kd = _mc_wrong_accept(pools, W, n, rng)
        print(f"  GF(2^{bits}) W={W} n={n}: keyed {p_kd:.2e} vs q^-W {q**-W:.2e} | "
              f"keyless {p_kl:.2e} vs q^-(W+1) {q**-(W+1):.2e} (free self-check); ratio kl/q^-W = {p_kl * q**W:.3f}")
        assert _within(p_kd, q ** -W, n), "keyed wrong-accept must track q^-W (i.i.d. keys -> exact)"
        # keyless: a floor at least as strong as nominal q^-W on random errors (self-check extra)
        assert p_kl <= q ** -W + 4.5 * math.sqrt(q ** -W / n) + 1.0 / n, "keyless wrong-accept above nominal q^-W"


# ── B1b: the structural keyless gap (explains coefficient_first silent decodes) ─

def test_keyless_coeff_segment_blind_spot_mechanism():
    _banner("keyless coeff-segment blind spot: sparse identity helpers leave coeff col W unconstrained")
    pools = _pools()
    field, G = pools.field, pools.gen_size
    seg = next(s for s in pools.kl_segments if s.kind == "coeff")
    kd_seg = next(s for s in pools.kd_segments if s.kind == "coeff")
    t = pools.target_idx[0]
    for W in (1, 2, 3):
        helpers = [kl_slice(pools.kl_clean[h], seg) for h in pools.helper_idx]
        # a redundancy column (salt/tag) where the first W helpers are all zero
        red = [c for c in range(seg.payload_length, seg.total_length) if all(h[c] == 0 for h in helpers[:W])]
        assert red, "expected a sparse redundancy column in the identity-helper coeff segment"
        c = red[0]
        sl = bytearray(kl_slice(pools.kl_clean[t], seg))
        sl[W] ^= 0x10     # WRONG coefficient (info column W) ...
        sl[c] ^= 0x10     # ... compensated in the redundancy region (self-sum stays 0)
        assert _keyless_accepts(field, sl, helpers, W), f"W={W}: blind-spot candidate should pass keyless oracle"
        assert not _keyless_accepts(field, sl, helpers, G), "W=gen_size must close the blind spot"
        # keyed: same wrong coefficient (+ a tag byte flip) is rejected at the same W
        kd = bytearray(kd_slice(pools.kd_clean[t], kd_seg))
        kd[W] ^= 0x10
        kd[kd_seg.payload_length] ^= 0x10
        assert not mac_verify_segment(field, pools.keyset[0], kd, kd_seg, W=W), "keyed MAC should reject"
        print(f"  W={W}: keyless ACCEPTS wrong coeff[{W}] + redundancy col {c} (helpers[:W] zero there); "
              f"rejected at W={G}; keyed rejects")


# ── B2: silent-decode scoring is measured correctly ───────────────────────────

def test_scoring_buckets_constructed_outcomes():
    _banner("scoring: constructed recovered / SILENT (valid-but-wrong packet) / failed, both arms")
    pools = _pools()
    W = 2
    t_ok, t_swap, t_bad = pools.target_idx[:3]
    for arm, clean, segs, score in (("keyless", pools.kl_clean, pools.kl_segments, score_keyless),
                                    ("keyed", pools.kd_clean, pools.kd_segments, score_keyed)):
        pool = [bytearray(p) for p in clean]
        pool[t_swap] = bytearray(clean[pools.target_idx[-1]])   # a DIFFERENT valid packet: passes oracle, wrong bytes
        data = next(s for s in segs if s.kind == "data")
        pool[t_bad][data.start] ^= 0x01                           # payload flip, not repaired
        out = score(pools, pool, W)
        assert out[t_ok] == RECOVERED, f"{arm}: untouched target must score recovered"
        assert out[t_swap] == SILENT, f"{arm}: valid-but-wrong packet must score SILENT"
        assert out[t_bad] == FAILED, f"{arm}: corrupted unrepaired packet must score failed"
        print(f"  {arm}: recovered / SILENT / failed buckets as constructed")


# ── B3: edge cases ────────────────────────────────────────────────────────────

def test_edge_W0_self_check_only():
    _banner("edge W=0: keyless = self-check only, keyed = no tag checked")
    pools = _pools()
    T = len(pools.target_idx)
    for config in CONFIGS:
        res = run_config(pools, config, ber=0.004, W=0, seed=7)
        for arm in (res.keyless, res.keyed):
            assert arm.recovered + arm.silent + arm.failed == T
        # keyed W=0 verifies nothing -> nothing can be rejected
        assert res.keyed.failed == 0, "keyed W=0 accepts every candidate (no tags verified)"
        # keyless W=0 failures are exactly the self-check failures
        for t in pools.target_idx:
            selfok = all(check_orth_packet(pools.field, kl_slice(res.kl_packets[t], s)) for s in pools.kl_segments)
            assert (res.keyless.outcomes[t] == FAILED) == (not selfok)
        print(f"  {config}: keyless rec {res.keyless.recovered} sil {res.keyless.silent} fail {res.keyless.failed} | "
              f"keyed rec {res.keyed.recovered} sil {res.keyed.silent} fail 0")


def test_edge_W_gen_size_no_silent_any_config():
    _banner("edge W=gen_size: every config, both arms -> 0 silent (q^-gen_size collision)")
    for seed in (1, 2, 3):
        pools = _pools(seed=seed)
        for config in CONFIGS:
            res = run_config(pools, config, ber=0.006, W=pools.gen_size, seed=seed)
            assert res.keyless.silent == 0 and res.keyed.silent == 0, \
                f"seed {seed} {config}: silent at W=gen_size ({res.keyless.silent}/{res.keyed.silent})"
        print(f"  seed {seed}: 0 silent in all 3 configs, both arms")


def _hand_injection(pools, flips):
    """flips: [(target, data_segment_pos, col, bit)] applied identically to both arms."""
    kl = [bytearray(p) for p in pools.kl_clean]
    kd = [bytearray(p) for p in pools.kd_clean]
    per_target = {t: [] for t in pools.target_idx}
    data_kl = [s for s in pools.kl_segments if s.kind == "data"]
    data_kd = [s for s in pools.kd_segments if s.kind == "data"]
    for t, d, col, bit in flips:
        assert col < data_kl[d].payload_length, "hand flips must hit payload (info) columns"
        kl[t][data_kl[d].start + col] ^= 1 << bit
        kd[t][data_kd[d].start + col] ^= 1 << bit
        per_target[t].append((data_kl[d].name, col, bit))
    return InjectedErrors(kl=kl, kd=kd, per_target=per_target)


def test_edge_odd_broken_count_unpaired_path():
    _banner("edge odd broken count: 1 broken (data-0) and 3 broken (data-1) -> unpaired path, recovered")
    pools = _pools()
    t = pools.target_idx
    flips = [(t[0], 0, 2, 5),                                   # data-0: ONE broken target
             (t[1], 1, 0, 1), (t[2], 1, 4, 7), (t[3], 1, 5, 3)]  # data-1: THREE broken (1 pair + 1 unpaired)
    inj = _hand_injection(pools, flips)
    res = run_config(pools, "arc_only_a", ber=0.0, W=pools.gen_size, seed=7, inj=inj)
    for name, rep in (("keyless", res.kl_report), ("keyed", res.kd_report)):
        by = {o.segment_name: o for o in rep.per_segment}
        d0, d1 = pools.kl_segments[1].name, pools.kl_segments[2].name
        unp0 = by[d0].unpaired_recovered + by[d0].unpaired_failed
        unp1 = by[d1].unpaired_recovered + by[d1].unpaired_failed
        assert unp0 == 1 and unp1 == 1, f"{name}: expected exactly one unpaired packet per odd segment, got {unp0}/{unp1}"
        print(f"  {name}: {d0} unpaired={unp0}, {d1} pairs={by[d1].pairs_recovered + by[d1].pairs_failed} unpaired={unp1}")
    for t_ in t[:4]:
        assert res.keyless.outcomes[t_] == RECOVERED and res.keyed.outcomes[t_] == RECOVERED, \
            f"single-bit error on target {t_} must be recovered in both arms"
    print("  all 4 broken targets recovered in both arms")


def test_edge_helper_set_exactly_gen_size():
    _banner("edge helper set = gen_size: minimal full-rank ARC basis (identity coeffs), recovery works")
    pools = _pools()
    G = pools.gen_size
    assert len(pools.helper_idx) == G
    for arm_clean, segs in ((pools.kl_clean, pools.kl_segments), (pools.kd_clean, pools.kd_segments)):
        coeff = next(s for s in segs if s.kind == "coeff")
        rows = [list(arm_clean[h][coeff.start:coeff.start + coeff.payload_length]) for h in pools.helper_idx]
        assert rows == [[1 if i == j else 0 for j in range(G)] for i in range(G)], "helpers must be the identity basis"
    res = run_config(pools, "arc_only_a", ber=0.004, W=2, seed=7)
    assert res.keyless.recovered > 0 and res.keyed.recovered > 0
    print(f"  G={G} identity helpers in both arms; ARC-only (a) recovers {res.keyless.recovered}/{res.keyed.recovered}")


# ── C: readable smoke ─────────────────────────────────────────────────────────

def _smoke_text(**kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_smoke(**kw)
    return buf.getvalue()


def test_smoke_deterministic_and_shaped():
    _banner("smoke: deterministic for a fixed seed; legend once; 3 config blocks; overall tally")
    a, b = _smoke_text(seed=7), _smoke_text(seed=7)
    assert a == b, "smoke output must be byte-identical across re-runs"
    assert a.count("Legend:") == 1
    assert a.count("=== config:") == 3
    assert a.count(" summary  keyless:") == 3 and a.count("head-to-head    keyless-only-win") == 3
    assert "overall head-to-head" in a
    print("  two runs byte-identical; shape as ticket 15 C")


# ── Ticket 14: frozen CSV + replot ────────────────────────────────────────────

def test_sweep_csv_frozen_schema_and_replot():
    _banner("sweep: CSV == frozen CSV_COLUMNS, counts consistent, paired rows agree, replot works")
    from scripts.isolated_recovery_plots_from_csv import load, plot_all
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "run"
        seeds, bers, Ws, spans = [0, 1], (2e-3, 6e-3), (1, 2), ("payload", "segment")
        run_sweep(seeds=seeds, bers=bers, Ws=Ws, spans=spans, out_dir=run_dir, workers=1)
        with open(run_dir / "raw_trials.csv", newline="") as fh:
            reader = csv.DictReader(fh)
            assert tuple(reader.fieldnames) == CSV_COLUMNS, "CSV header drifted from frozen schema"
            rows = list(reader)
        assert len(rows) == len(seeds) * len(bers) * len(CONFIGS) * len(spans) * len(Ws) * 2
        cells = {}
        for r in rows:
            T = int(r["T"])
            assert int(r["recovered"]) + int(r["silent"]) + int(r["failed"]) == T
            assert sum(int(r[k]) for k in ("h2h_keyless_only", "h2h_keyed_only", "h2h_both", "h2h_neither")) == T
            key = (r["config"], r["repair_span"], r["W"], r["bit_error_rate"], r["seed"])
            cells.setdefault(key, {})[r["arm"]] = r
        for key, arms in cells.items():
            kl, kd = arms["keyless"], arms["keyed"]
            for col in ("n_info_corrupted", "n_coeff_corrupted", "h2h_both", "h2h_keyless_only"):
                assert kl[col] == kd[col], f"{key}: paired column {col} differs across arm rows"
            assert int(kl["h2h_both"]) + int(kl["h2h_keyless_only"]) == int(kl["recovered"])
            assert int(kd["h2h_both"]) + int(kd["h2h_keyed_only"]) == int(kd["recovered"])
        s = load(str(run_dir), min_trials=2)
        out = plot_all(s, Path(tmp) / "plots")
        made = {p.name for p in Path(out).glob("*.png")}
        for span in spans:
            for key in ("recovery", "silent", "ops"):
                assert f"{key}_vs_ber_{span}.png" in made
            assert f"coeff_repair_isolation_{span}.png" in made
        print(f"  {len(rows)} rows, header frozen, counts/pairing consistent; replot wrote {len(made)} png")


if __name__ == "__main__":
    tests = [
        test_w_semantics_wrong_accept_tracks_q_pow_minus_W,
        test_keyless_coeff_segment_blind_spot_mechanism,
        test_scoring_buckets_constructed_outcomes,
        test_edge_W0_self_check_only,
        test_edge_W_gen_size_no_silent_any_config,
        test_edge_odd_broken_count_unpaired_path,
        test_edge_helper_set_exactly_gen_size,
        test_smoke_deterministic_and_shaped,
        test_sweep_csv_frozen_schema_and_replot,
    ]
    for test in tests:
        test()
        print(f"{test.__name__} passed")
    print("\nAll isolated-recovery verification tests passed!")
