r"""Wall-clock benchmark for the S2 / S3 security sims (2026-10-09): how long do the
receiver's checks and the attackers' forgeries take, keyless vs keyed?

The S2 (verify_width_attack_sim) and S3 (tag_pollution_attack_sim) runs logged op counts only
(receiver_mul, attacker_mul). This script times the SAME production functions those sims call,
single process, on the same paired setups (attack_harness.paired_plan), so the two arms see
identical data and coefficient rows. Nothing else runs in the process while timing; gc is off
inside the timed loops. Field = CountingField (as in every sim), so the numbers include the same
op-counting overhead the recovery wall-clock (isolated_recovery_sim recovery_time_s) has.

Measures (one CSV row per measure x arm x cell x seed; time = mean over `reps` calls):
  verify    one HONEST packet's admission check at width W, all segments (accept path = full
            cost; a forged packet exits at its first failing check). keyless: self-check +
            W witness inner products per segment (check_orth_packet, inner_product_bytes);
            keyed: W MAC tags per segment (mac_verify_key_subset). The checked witnesses / keys
            are a random subset drawn outside the timing. x = checks per packet:
            keyless W = 1..g-1 (core witnesses), keyed W = 1..g (tags).
  admit     the production receiver step as S2/S3 run it: scheme.admit on an all-honest pool of
            g+1 packets, S2/S3 config (random witness policy, width W, sticky, hd 0 -> no repair).
            Includes trust classification (keyless: full pairwise agreement matrix, independent
            of W -- the incremental O(m*W) build is a deferred optimisation) and the per-packet
            secret witness/key ranking (blake2b) of the random policy.
  forge_s2  S2 forger, coeff segment (knowledge_attack_sim.forge_coeff_keyless / _keyed):
            keyless knowledge r = observed packets 0..g-1 (null-space solve), keyed k = leaked
            keys 0..g (k tag inner products).
  forge_s3  S3 tag polluter (tag_pollution_attack_sim.pollute_keyless / pollute_keyed):
            keyless r = 0..g-1 observed packets, keyed t = 1..g polluted tags.

Grid: the S2/S3 settings (df 12, N 2, g 4 and 6, GF(2^2/4/8)) plus realistic payloads
(df 100 / 1000, N 2, g 6, GF(2^8)) for the receiver measures; the forgers only touch the coeff
segment / one tag block, so their cost does not depend on df (measured at df 12 only).

Run (PowerShell, main .venv, repo root; keep the machine otherwise idle):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"
  & "E:/projects/studienarbeit/.venv/Scripts/python.exe" simulation/security_wallclock_bench.py --smoke
  ... --out logs/wallclock/security_bench
Plots: scripts/wallclock_plots_from_csv.py

FROZEN CSV SCHEMA (raw_timings.csv, CSV_SCHEMA_VERSION = 1)
  schema_version, measure, arm, field_bits, gen_size, data_fields, n_segments
  x_kind     str    checks (verify/admit) | observed_packets | leaked_keys | polluted_tags
  x          int    W (checks per packet) or knowledge level
  seed       int
  reps       int    timed calls averaged into time_us
  time_us    float  mean wall-clock microseconds per call
  mul_per_call int  field multiplications per call (CountingField)
  ok         int    1 = every call returned the expected verdict (honest accepted / forgery built)
"""
import argparse
import gc
import os
import platform
import random
import sys
import time
from pathlib import Path

from binary_ext_fields.custom_field import CountingField
from binary_ext_fields.generate_symbols import check_orth_packet
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.segmented_mac_tagging import mac_verify_key_subset
from simulation.attack_harness import default_cfg, field_for, random_row, recode
from simulation.knowledge_attack_sim import forge_coeff_keyed, forge_coeff_keyless, paired_plan, write_rows
from simulation.tag_pollution_attack_sim import pollute_keyed, pollute_keyless
from simulation.verify_width_attack_sim import _secret

CSV_SCHEMA_VERSION = 1
CSV_COLUMNS = ["schema_version", "measure", "arm", "field_bits", "gen_size", "data_fields", "n_segments",
               "x_kind", "x", "seed", "reps", "time_us", "mul_per_call", "ok"]
ARMS = ("keyless", "keyed")
N_SEGMENTS = 2
S23_SETTINGS = [(m, g, 12) for g in (4, 6) for m in (2, 4, 8)]     # (field_bits, g, df)
SIZE_SETTINGS = [(8, 6, 100), (8, 6, 1000)]
REPS = {"verify": 100, "admit": 10, "forge_s2": 100, "forge_s3": 100}


def _timed(fn, reps: int) -> tuple[float, bool]:
    """(mean microseconds per call, all calls returned truthy)."""
    gc.collect()
    gc.disable()
    try:
        ok = True
        t0 = time.perf_counter_ns()
        for _ in range(reps):
            ok &= bool(fn())
        dt = time.perf_counter_ns() - t0
    finally:
        gc.enable()
    return dt / reps / 1000.0, ok


def _ops(fn, cnt: CountingField) -> int:
    before = cnt.mul_count
    fn()
    return cnt.mul_count - before


# ── the timed calls ───────────────────────────────────────────────────────────

def verify_keyless(field, segments, pkt, witnesses) -> bool:
    for seg in segments:
        a, b = seg.start, seg.start + seg.total_length
        sl = pkt[a:b]
        if not check_orth_packet(field, sl):
            return False
        for w in witnesses:
            if inner_product_bytes(field, sl, w[a:b]) != 0:
                return False
    return True


def verify_keyed(field, segments, keyset, pkt, key_idx) -> bool:
    return all(mac_verify_key_subset(field, keyset[s], pkt[seg.start:seg.start + seg.total_length], seg, key_idx[s])
               for s, seg in enumerate(segments))


def _cfg(g: int, arm: str, width, seed: int):
    cfg = default_cfg(g)
    cfg.hamming_distance = 0
    cfg.witness_policy = "random"
    cfg.witness_secret = _secret(seed)
    cfg.witness_sticky = True
    if arm == "keyless":
        cfg.verify_count = width
    else:
        cfg.mac_verify_count = width
    return cfg


def bench_cell(arm: str, m: int, g: int, df: int, seed: int, measures, reps=REPS) -> list[dict]:
    base = field_for(m)
    setup, plan = paired_plan(seed, base, g, df, N_SEGMENTS, arm)
    head = [recode(setup, r) for r in plan.head]                  # g-1 honest packets
    target = recode(setup, plan.forged_row)                       # honest, innovative
    extra_row = random_row(random.Random(f"{seed}/extra"), base, g)
    extra = recode(setup, extra_row)
    rng = random.Random(f"{seed}/{arm}/bench")
    common = dict(schema_version=CSV_SCHEMA_VERSION, arm=arm, field_bits=m, gen_size=g, data_fields=df,
                  n_segments=N_SEGMENTS, seed=seed)
    rows = []

    def add(measure, x_kind, x, fn, cnt):
        r = reps[measure]
        t_us, ok = _timed(fn, r)
        rows.append(dict(common, measure=measure, x_kind=x_kind, x=x, reps=r, time_us=t_us,
                         mul_per_call=_ops(fn, cnt), ok=int(ok)))

    if "verify" in measures:
        cnt = CountingField(base)
        top = g - 1 if arm == "keyless" else g
        for w in range(1, top + 1):
            if arm == "keyless":
                wit = head[:w]
                fn = lambda wit=wit: verify_keyless(cnt, setup.segments, target, wit)  # noqa: E731
            else:
                idx = [sorted(rng.sample(range(g), w)) for _ in setup.segments]
                fn = lambda idx=idx: verify_keyed(cnt, setup.segments, setup.keyset, target, idx)  # noqa: E731
            add("verify", "checks", w, fn, cnt)

    if "admit" in measures:
        pool = head + [target, extra]                             # g+1 honest packets
        top = g - 1 if arm == "keyless" else g
        for w in range(1, top + 1):
            cfg = _cfg(g, arm, w, seed)
            insts = [setup.new_instrument() for _ in range(reps["admit"] + 1)]
            it = iter(insts)

            def fn(cfg=cfg, it=it):
                res = setup.scheme.admit(next(it), [bytearray(p) for p in pool], g, cfg)
                return res is not None and len(res) == len(pool)
            r = reps["admit"]
            t_us, ok = _timed(fn, r)
            last = insts[-1]
            fn(cfg, iter([last]))
            rows.append(dict(common, measure="admit", x_kind="checks", x=w, reps=r, time_us=t_us,
                             mul_per_call=last.field.mul_count, ok=int(ok)))

    if "forge_s2" in measures:
        cnt = CountingField(base)
        if arm == "keyless":
            for r_obs in range(g):
                obs = head[:r_obs]
                fn = lambda obs=obs: forge_coeff_keyless(setup, obs, plan.forged_row, rng, cnt)[0] is not None  # noqa: E731
                add("forge_s2", "observed_packets", r_obs, fn, cnt)
        else:
            for k in range(g + 1):
                fn = lambda k=k: forge_coeff_keyed(setup, k, plan.forged_row, rng, cnt) is not None  # noqa: E731
                add("forge_s2", "leaked_keys", k, fn, cnt)

    if "forge_s3" in measures:
        cnt = CountingField(base)
        s = random.Random(f"{seed}/segment").randrange(len(setup.segments))
        if arm == "keyless":
            for r_obs in range(g):
                obs = head[:r_obs]
                fn = lambda obs=obs: pollute_keyless(setup, target, s, obs, rng, cnt) != target  # noqa: E731
                add("forge_s3", "observed_packets", r_obs, fn, cnt)
        else:
            for t in range(1, g + 1):
                fn = lambda t=t: pollute_keyed(setup, target, s, t, rng, cnt) != target  # noqa: E731
                add("forge_s3", "polluted_tags", t, fn, cnt)
    return rows


def run(seeds: int, out_dir: Path | None, settings=None, reps=REPS, seed_start=0) -> list[dict]:
    settings = settings or ([(s, ("verify", "admit", "forge_s2", "forge_s3")) for s in S23_SETTINGS]
                            + [(s, ("verify", "admit")) for s in SIZE_SETTINGS])
    rows, t_start = [], time.perf_counter()
    for (m, g, df), measures in settings:
        t0 = time.perf_counter()
        for seed in range(seed_start, seed_start + seeds):
            for arm in ARMS:                                     # arms interleaved per seed (same machine state)
                rows += bench_cell(arm, m, g, df, seed, measures, reps)
        print(f"  GF(2^{m}) g={g} df={df} {','.join(measures)}: {time.perf_counter() - t0:.1f} s", flush=True)
        if out_dir is not None:
            write_rows(out_dir / "raw_timings.csv", rows, CSV_COLUMNS)
    print(f"total {time.perf_counter() - t_start:.1f} s, {len(rows)} rows, "
          f"{sum(1 - r['ok'] for r in rows)} rows with unexpected verdicts")
    if out_dir is not None:
        (out_dir / "machine.txt").write_text(
            f"{platform.platform()}\n{platform.processor()}\npython {sys.version}\ncpu_count {os.cpu_count()}\n"
            f"seeds {seeds} (from {seed_start}), reps {reps}\n", encoding="utf-8")
    return rows


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--smoke", action="store_true", help="2 seeds, few reps, no files")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--out", type=Path, default=Path("logs/wallclock/security_bench"))
    args = ap.parse_args(argv)
    if args.smoke:
        run(2, None, reps={k: max(2, v // 10) for k, v in REPS.items()})
        return
    run(args.seeds, args.out, seed_start=args.seed_start)


if __name__ == "__main__":
    main()
