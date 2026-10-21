r"""S3 -- tag pollution: the attacker changes ONLY the tag bytes of an honest packet.

Question (supervisors, 2026-10-03): rerun S2 (verify_width_attack_sim.py), but the attacker
only pollutes tags. How often does a packet carrying WRONG tags get past a receiver that
checks W witnesses (keyless) / W of the g MAC tags (keyed)? Coefficients and payload stay
honest, so an admitted polluted packet still decodes correctly (silent = 0 by construction,
logged as a sanity column); the success metric is the ADMIT rate.

Target = an honest recode with coefficient row c' (plan.forged_row: outside the span of the
g-1 honest head rows, so innovative, and never sent honestly -- admission is unambiguous).
ONE segment, drawn uniformly per seed (paired across arms and knowledge), gets polluted:
  keyless  tag block = salt + g tags (the salt is check-only redundancy, not payload; without
           it there is no nonzero solution at r = g-1). delta = uniform NONZERO vector with
           <delta, 1> = 0 (char-2 self-check stays valid) and <delta, h> = 0 on the tag block of
           every one of the r observed honest packets. Knowledge axis: r observed packets.
  keyed    a leaked key only reproduces the honest tag, so it buys nothing. Knowledge axis
           instead: t = tags polluted (1..g), the LAST t tags (+ uniform nonzero offsets).
           Under "first" (keys[:W] checked) that is the attacker who knows the policy.

Arrival schedule as S2: keyless H_0..H_{r-1}, polluted, rest of the head, then fresh honest;
keyed polluted first. Repair off (hd = 0), witness rejections remembered (sticky).

Theory (written before the runs):
  keyless  delta uniform over the nonzero vectors of a d-dim space, d = g - r (g+1 unknowns,
           r+1 constraints). j unknown witnesses checked -> j more independent constraints:
             f(j) = (q^(d-j) - 1) / (q^d - 1)          (slightly BELOW S2's q^-j: no zero vector)
           first   f(max(0, n - r)),   random  sum_j Hyp(j; g-1, g-1-r, n) f(j),  n = min(W, g-1)
  keyed    admitted iff no polluted tag is checked:
           first   1 if t <= g - W else 0,   random  C(g-t, W) / C(g, W)     (all: 0)

Run (PowerShell, main .venv, repo root):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"
  & "E:/projects/studienarbeit/.venv/Scripts/python.exe" simulation/tag_pollution_attack_sim.py --smoke
  ... --sweep --trials 4000 --ms 2,4 --workers 5 --out logs/tag_pollution_attack/g4_m24_t4000
Plots: scripts/tag_pollution_plots_from_csv.py

FROZEN CSV SCHEMA (raw_trials.csv, CSV_SCHEMA_VERSION = 1). Pool by summing counts per cell.
  schema_version, arm, field_bits, q, gen_size, data_fields, n_segments
  knowledge_kind   str   observed_packets (keyless) | polluted_tags (keyed)
  knowledge        int   r (keyless) | t (keyed)
  seed, strike_index
  polluted_segment int   segment index (0 = coeff segment)
  polluted_bytes   int   tag-block bytes actually changed
  oracle_pass      int   0/1 passes every check vs the g-1 honest head packets (strict, no repair)
  forged_admitted  int   0/1 polluted packet in the admitted set when the receiver stopped
  decoded, correct, silent, packets_received
  attacker_mul, attacker_add, receiver_mul
  witness_policy, width (-1 = all), witness_secret, witness_sticky
  min_trust_count, min_pool_size, hamming_distance
  theory_admit     float the formula above for this cell
"""
import argparse
import os
import random
from concurrent.futures import ProcessPoolExecutor
from math import comb
from pathlib import Path

from binary_ext_fields.custom_field import CountingField
from binary_ext_fields.generate_symbols import check_orth_packet
from binary_ext_fields.pollution import _gf_row_reduce
from simulation.attack_harness import (
    default_cfg, field_for, passes_oracle, random_row, recode, run_receiver,
)
from simulation.knowledge_attack_sim import MAX_PACKETS_FACTOR, paired_plan, wilson, write_rows
from simulation.verify_width_attack_sim import (
    DATA_FIELDS, GEN_SIZE, N_SEGMENTS, POLICIES, STICKY, _hyp, _secret, widths,
)

CSV_SCHEMA_VERSION = 3   # v2 (2026-10-05): + support (keyless footprint sweep); v3 (2026-10-08): + ber, flipped_bits, selfcheck_pass
CSV_COLUMNS = [
    "schema_version", "arm", "field_bits", "q", "gen_size", "data_fields", "n_segments",
    "knowledge_kind", "knowledge", "seed", "strike_index", "polluted_segment", "polluted_bytes",
    "oracle_pass", "forged_admitted", "decoded", "correct", "silent", "packets_received",
    "attacker_mul", "attacker_add", "receiver_mul",
    "witness_policy", "width", "witness_secret", "witness_sticky",
    "min_trust_count", "min_pool_size", "hamming_distance", "theory_admit", "support", "ber", "flipped_bits",
    "selfcheck_pass",
]


# ── Theory ────────────────────────────────────────────────────────────────────

def knowledge_levels(arm: str, g: int) -> range:
    return range(g) if arm == "keyless" else range(1, g + 1)


def theory_admit(arm: str, policy: str, knowledge: int, width: int | None, g: int, q: int, support=None) -> float:
    """support (keyless only) = tag-block bytes the attacker may change; None = the whole block (salt + g tags).
    The pass probability does not depend on it: a witness with coefficient row c passes iff c.v = 0, v = the
    change's inner products with the g source tag blocks; independent witness rows make that f(j) for ANY
    v != 0. Exception: support 1 breaks the char-2 self-check (sum of bytes) -> never admitted. Needs
    support >= knowledge + 2 (r observed + self-check constraints) for a nonzero solution."""
    if arm == "keyless":
        if support == 1:
            return 0.0
        pop, unknown, d = g - 1, g - 1 - knowledge, g - knowledge
        n = pop if width is None else min(width, pop)
        f = lambda j: (float(q) ** (d - j) - 1) / (float(q) ** d - 1)  # noqa: E731
        if policy == "first" or n == pop:
            return f(n - min(n, pop - unknown))
        return sum(_hyp(j, pop, unknown, n) * f(j) for j in range(n + 1))
    t = knowledge
    n = g if width is None else min(width, g)
    if policy == "first" or n == g:
        return 1.0 if t <= g - n else 0.0
    return comb(g - t, n) / comb(g, n)


# ── The two tag polluters ─────────────────────────────────────────────────────

def _tag_block(setup, s: int) -> tuple[int, int]:
    """(offset, length) of segment s's tag block: salt + tags (keyless) / tags (keyed)."""
    seg = setup.segments[s]
    return seg.start + seg.payload_length, seg.total_length - seg.payload_length


def pollute_keyless(setup, target, s: int, observed, atk_rng, cnt, support=None) -> bytearray:
    """target with delta added on segment s's tag block; delta uniform over the NONZERO
    solutions of [observed tag blocks; all-ones] delta = 0 (RREF, free variables random).
    support = number of tag-block bytes delta may touch (a random subset; None = all). If no nonzero
    solution fits the support (e.g. support 1: the self-check alone forces delta = 0), the attacker
    changes the support bytes by random nonzero values anyway (naive pollution)."""
    off, width = _tag_block(setup, s)
    cols = list(range(width)) if support is None else sorted(atk_rng.sample(range(width), support))
    A = [[o[off + c] for c in cols] for o in observed] + [[1] * len(cols)]
    piv = _gf_row_reduce(cnt, A)
    pcols = {c for c, _ in piv}
    free = [c for c in range(len(cols)) if c not in pcols]
    out = bytearray(target)
    if not free:
        assert support is not None, "null space is empty -- tag block too short for the constraints"
        for c in cols:
            out[off + c] = cnt.add(out[off + c], atk_rng.randint(1, cnt.max_value))
        return out
    width = len(cols)
    while True:
        x = [0] * width
        for c in free:
            x[c] = atk_rng.randint(0, cnt.max_value)
        # _gf_row_reduce rows are echelon (zeros left of the pivot, but NOT reduced above later
        # pivots) -> back-substitute from the last pivot; char 2: x_c = sum_{k > c} row[k] x_k
        for c, row in reversed(piv):
            acc = 0
            for k in range(c + 1, width):
                acc = cnt.add(acc, cnt.mul(row[k], x[k]))
            x[c] = acc
        if any(x):
            break
    for c, v in zip(cols, x):
        out[off + c] = cnt.add(out[off + c], v)
    return out


def pollute_keyed(setup, target, s: int, t: int, atk_rng, cnt) -> bytearray:
    """target with uniform nonzero offsets on the LAST t MAC tags of segment s."""
    off, width = _tag_block(setup, s)
    out = bytearray(target)
    for i in range(width - t, width):
        out[off + i] = cnt.add(out[off + i], atk_rng.randint(1, cnt.max_value))
    return out


def _tag_regions(setup) -> list[tuple[int, int]]:
    """(offset, length) of every segment's tag block -- the whole tag region of a packet."""
    return [_tag_block(setup, s) for s in range(len(setup.segments))]


def pollute_noise(setup, target, ber: float, rng, cnt, m: int) -> tuple[bytearray, int]:
    """Channel noise instead of an attacker (supervisor request 2026-10-08): every bit of the tag region (all
    segments; keyless salt + tags, keyed MAC tags) flips independently with probability ber, CONDITIONED on at
    least one flip (only corrupted packets are simulated). Returns (packet, number of flipped bits)."""
    regions = _tag_regions(setup)
    n_bits = m * sum(length for _, length in regions)
    # k ~ Binomial(n_bits, ber) | k >= 1, by inverse CDF
    u = rng.random() * (1 - (1 - ber) ** n_bits)
    k, acc = 0, 0.0
    while acc < u and k < n_bits:
        k += 1
        acc += comb(n_bits, k) * ber ** k * (1 - ber) ** (n_bits - k)
    out = bytearray(target)
    symbols = [off + i for off, length in regions for i in range(length)]
    for pos in rng.sample(range(n_bits), k):
        sym, bit = divmod(pos, m)
        out[symbols[sym]] = cnt.add(out[symbols[sym]], 1 << bit)   # flipping a bit = adding it (char 2)
    return out, k


def _pass_witnesses(q: int, g: int, k: int, j: int) -> float:
    """P(j independent random witness rows all pass) when passing = lying in a codimension-k subspace of
    GF(q)^g (k corrupted segments that survived the self-check, i.e. k independent constraints c.v_s = 0).
    Rows are drawn one by one outside the span of the earlier ones: prod_i (q^(g-k) - q^i) / (q^g - q^i)."""
    p = 1.0
    for i in range(j):
        p *= max(0.0, float(q) ** (g - k) - float(q) ** i) / (float(q) ** g - float(q) ** i)
    return p


def _noise_segment_probs(g: int, m: int, ber: float) -> tuple[float, float]:
    """Keyless segment tag block (salt + g tags, B = g+1 symbols of m bits) under bit noise:
    (z, s1) = P(no flip), P(>= 1 flip AND the char-2 self-check still holds = even flips in every bit position)."""
    B = g + 1
    z = (1 - ber) ** (m * B)
    return z, ((1 + (1 - 2 * ber) ** B) / 2) ** m - z


def theory_noise_selfcheck(g: int, m: int, n_seg: int, ber: float) -> float:
    """P(a corrupted keyless packet passes the self-check in every segment) = ((s1+z)^N - z^N) / (1 - z^N)."""
    z, s1 = _noise_segment_probs(g, m, ber)
    return ((s1 + z) ** n_seg - z ** n_seg) / (1 - z ** n_seg)


def theory_noise(arm: str, width: int | None, g: int, m: int, n_seg: int, ber: float) -> float:
    """P(a packet whose tag region got >= 1 bit flip is admitted), random W-subset checks, repair off.
    keyed   the same W key indices are checked in every segment; index j is bad if its tag is hit in ANY
            segment: b = 1 - (1-ber)^(m N).  P = ((1-b)^W - (1-b)^g) / (1 - (1-b)^g).
    keyless per segment (salt + g tags = B = g+1 symbols): unhurt z = (1-ber)^(mB); hurt but passing the char-2
            self-check (even number of flips in every bit position) s1 = ((1+(1-2ber)^B)/2)^m - z. k hurt-but-
            self-valid segments then need every checked witness (j = min(W, g-1), none seen by the noise) in
            a codim-k subspace: P = sum_k C(N,k) s1^k z^(N-k) pass(k, j) / (1 - z^N)."""
    q = 2 ** m
    if arm == "keyed":
        w = g if width is None else min(width, g)
        good = (1 - ber) ** (m * n_seg)                  # 1 - b
        return (good ** w - good ** g) / (1 - good ** g)
    z, s1 = _noise_segment_probs(g, m, ber)
    j = g - 1 if width is None else min(width, g - 1)
    num = sum(comb(n_seg, k) * s1 ** k * z ** (n_seg - k) * _pass_witnesses(q, g, k, j) for k in range(1, n_seg + 1))
    return num / (1 - z ** n_seg)


# ── One trial ─────────────────────────────────────────────────────────────────

def _arrivals(setup, head_rows, injected, strike_index, tail_rng, skip_row, honest_log):
    """S2's schedule; fresh honest rows equal to skip_row (the target's c') are redrawn so the
    polluted packet's code row never also arrives honestly."""
    for i, row in enumerate(head_rows):
        if i == strike_index:
            yield injected
        honest_log.append(recode(setup, row))
        yield honest_log[-1]
    if strike_index == len(head_rows):
        yield injected
    while True:
        row = random_row(tail_rng, setup.base_field, setup.gen_size)
        if bytes(row) == bytes(skip_row):
            continue
        honest_log.append(recode(setup, row))
        yield honest_log[-1]


def sweep_cells(ms=(2, 4), g=GEN_SIZE, arms=("keyless", "keyed"), policies=POLICIES, hd=0):
    return [dict(arm=arm, knowledge=k, field_bits=m, width=w, policy=pol, g=g, hd=hd)
            for m in ms for arm in arms for w in widths(arm, g)
            for pol in (("first",) if w is None else policies)       # width all: policy irrelevant
            for k in knowledge_levels(arm, g)]


def support_sweep_cells(ms=(2, 4, 8), g=GEN_SIZE, ws=(1, 2, None)):
    """Keyless footprint sweep: support e = tag-block bytes changed (1..g+1, block = salt + g tags) x observed r,
    random witness policy. Only feasible pairs (e >= r + 2) plus the naive e = 1 attacker (r = 0)."""
    return [dict(arm="keyless", knowledge=r, field_bits=m, width=w, policy="first" if w is None else "random",
                 g=g, hd=0, support=e)
            for m in ms for w in ws for e in range(1, g + 2) for r in range(g)
            if (e >= r + 2) or (e == 1 and r == 0)]


def noise_sweep_cells(ms=(2, 4, 8), g=GEN_SIZE, bers=(1e-5, 1e-4, 1e-3, 1e-2)):
    """Random tag-region bit flips (both arms), every verification width, receiver-secret random subsets."""
    return [dict(arm=arm, knowledge=0, field_bits=m, width=w, policy="first" if w is None else "random",
                 g=g, hd=0, ber=ber)
            for m in ms for ber in bers for arm in ("keyless", "keyed") for w in widths(arm, g)]


def run_trial(cell: dict, seed: int, data_fields=DATA_FIELDS, n=N_SEGMENTS) -> dict:
    arm, k, g, m = cell["arm"], cell["knowledge"], cell["g"], cell["field_bits"]
    base = field_for(m)
    cfg = default_cfg(g)
    cfg.hamming_distance = cell["hd"]
    cfg.witness_policy = cell["policy"]
    cfg.witness_secret = _secret(seed)          # receiver-side only; the polluters never read cfg
    cfg.witness_sticky = STICKY
    if arm == "keyless":
        cfg.verify_count = cell["width"]
    else:
        cfg.mac_verify_count = cell["width"]

    setup, plan = paired_plan(seed, base, g, data_fields, n, arm)
    honest_head = [recode(setup, r) for r in plan.head]
    target = recode(setup, plan.forged_row)
    cnt = CountingField(base)
    s = random.Random(f"{seed}/segment").randrange(len(setup.segments))
    atk_rng = random.Random(f"{seed}/{arm}/{k}/tag-pollution")
    ber, flips = cell.get("ber"), 0
    if ber is not None:     # channel noise on the whole tag region; nobody observed anything -> strike first
        polluted, flips = pollute_noise(setup, target, ber, random.Random(f"{seed}/{arm}/noise/{ber}"), cnt, m)
        s, s_idx = -1, 0
    elif arm == "keyless":
        polluted, s_idx = pollute_keyless(setup, target, s, honest_head[:k], atk_rng, cnt, cell.get("support")), k
    else:
        polluted, s_idx = pollute_keyed(setup, target, s, k, atk_rng, cnt), 0

    honest_log: list = []
    arrivals = _arrivals(setup, plan.head, polluted, s_idx, random.Random(plan.tail_seed), plan.forged_row,
                         honest_log)
    out = run_receiver(setup, arrivals, cfg, MAX_PACKETS_FACTOR * g, instrument=(inst := setup.new_instrument()))
    target_code = bytes(setup.code(target))
    return dict(
        schema_version=CSV_SCHEMA_VERSION, arm=arm, field_bits=m, q=2 ** m, gen_size=g, data_fields=data_fields,
        n_segments=n,
        knowledge_kind=("noise" if ber is not None else "observed_packets" if arm == "keyless" else "polluted_tags"),
        knowledge=k,
        seed=seed, strike_index=s_idx, polluted_segment=s,
        polluted_bytes=sum(a != b for a, b in zip(polluted, target)),
        oracle_pass=int(passes_oracle(setup, polluted, honest_head)),
        forged_admitted=int(any(bytes(c) == target_code for c in out.admitted)),
        decoded=int(out.decoded), correct=int(out.correct), silent=int(out.decoded and not out.correct),
        packets_received=out.packets_received, attacker_mul=cnt.mul_count, attacker_add=cnt.add_count,
        receiver_mul=inst.field.mul_count, witness_policy=cell["policy"],
        width=-1 if cell["width"] is None else cell["width"], witness_secret=cfg.witness_secret,
        witness_sticky=int(cfg.witness_sticky), min_trust_count=cfg.min_trust_count,
        min_pool_size=cfg.min_pool_size, hamming_distance=cfg.hamming_distance,
        theory_admit=(theory_noise(arm, cell["width"], g, m, n, ber) if ber is not None else
                      theory_admit(arm, cell["policy"], k, cell["width"], g, 2 ** m, cell.get("support"))),
        support=-1 if cell.get("support") is None else cell["support"],
        ber=0.0 if ber is None else ber, flipped_bits=flips,
        # keyless only: did the corrupted packet survive the char-2 self-check in EVERY segment? (-1 = keyed)
        selfcheck_pass=(int(all(check_orth_packet(base, polluted[seg.start:seg.start + seg.total_length])
                                for seg in setup.segments)) if arm == "keyless" else -1),
    )


def _run_chunk(args):
    cell, seeds = args
    return [run_trial(cell, s) for s in seeds]


# ── Aggregation + sweep ───────────────────────────────────────────────────────

def summarize(rows: list[dict]) -> list[dict]:
    cells: dict = {}
    for r in rows:
        key = (r["arm"], int(r["field_bits"]), int(r["gen_size"]), int(r["hamming_distance"]), r["witness_policy"],
               int(r["width"]), int(r["knowledge"]), int(r.get("support", -1)),   # v1 CSVs: no support = -1
               float(r.get("ber", 0.0)))                                         # < v3: no noise = 0
        cells.setdefault(key, []).append(r)
    out = []
    for (arm, m, g, hd, pol, w, k, sup, ber), rs in sorted(cells.items()):
        t = len(rs)
        adm = sum(int(r["forged_admitted"]) for r in rs)
        lo, hi = wilson(adm, t)
        th = float(rs[0]["theory_admit"])
        coeff = [r for r in rs if int(r["polluted_segment"]) == 0]
        out.append({"arm": arm, "field_bits": m, "q": 2 ** m, "gen_size": g, "n_segments": int(rs[0]["n_segments"]),
                    "data_fields": int(rs[0]["data_fields"]), "hd": hd, "policy": pol, "width": w, "support": sup, "ber": ber,
                    "knowledge": k, "trials": t, "admitted": adm, "admit_rate": adm / t, "admit_lo": lo,
                    "admit_hi": hi, "theory_admit": th,
                    "z_vs_theory": (adm / t - th) / max((th * (1 - th) / t) ** 0.5, 1e-12),
                    "oracle_rate": sum(int(r["oracle_pass"]) for r in rs) / t,
                    "coeff_seg_trials": len(coeff),
                    "coeff_seg_admitted": sum(int(r["forged_admitted"]) for r in coeff),
                    "silent": sum(int(r["silent"]) for r in rs), "decoded": sum(int(r["decoded"]) for r in rs),
                    "packets_mean": sum(int(r["packets_received"]) for r in rs) / t,
                    "attacker_mul_mean": sum(int(r["attacker_mul"]) for r in rs) / t,
                    "receiver_mul_mean": sum(int(r["receiver_mul"]) for r in rs) / t,
                    # noise mode, keyless: measured vs theory share of corrupted packets passing every self-check
                    "selfcheck_rate": (sum(int(r.get("selfcheck_pass", -1)) for r in rs) / t
                                       if ber > 0 and arm == "keyless" else float("nan")),
                    "theory_selfcheck": (theory_noise_selfcheck(g, m, int(rs[0]["n_segments"]), ber)
                                         if ber > 0 and arm == "keyless" else float("nan"))})
    return out


def format_summary(summary: list[dict]) -> str:
    head = (f"{'arm':<8} {'m':>2} {'pol':<6} {'wid':>3} {'know':>4} {'trials':>6} | {'admit':>7} "
            f"[{'95% CI':^15}] {'theory':>7} {'z':>6} | {'silent':>6} {'dec':>6} {'pkts':>5}")
    lines = [head, "-" * len(head)]
    for s in summary:
        w = "all" if s["width"] < 0 else str(s["width"])
        lines.append(f"{s['arm']:<8} {s['field_bits']:>2} {s['policy']:<6} {w:>3} {s['knowledge']:>3}/{s['support']:<2} {s['trials']:>6} | "
                     f"{s['admit_rate']:>7.4f} [{s['admit_lo']:.4f},{s['admit_hi']:.4f}] {s['theory_admit']:>7.4f} "
                     f"{s['z_vs_theory']:>6.2f} | {s['silent']:>6} {s['decoded']:>6} {s['packets_mean']:>5.2f}")
    return "\n".join(lines)


def run_sweep(trials=4000, ms=(2, 4), g=GEN_SIZE, hd=0, seed_start=0, workers=1, out_dir=None, chunk=250,
              cells=None) -> Path:
    """cells: None = the S3 main sweep (sweep_cells); else e.g. support_sweep_cells(...)."""
    if out_dir is None:
        out_dir = Path("logs") / "tag_pollution_attack" / f"g{g}_m{''.join(map(str, ms))}_t{trials}_hd{hd}"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = list(range(seed_start, seed_start + trials))
    jobs = [(cell, seeds[i:i + chunk]) for cell in (cells or sweep_cells(ms, g, hd=hd))
            for i in range(0, len(seeds), chunk)]
    rows: list[dict] = []
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for i, part in enumerate(ex.map(_run_chunk, jobs), 1):
                rows.extend(part)
                if i % 25 == 0 or i == len(jobs):
                    print(f"  {i}/{len(jobs)} chunks", flush=True)
    else:
        for job in jobs:
            rows.extend(_run_chunk(job))
    write_rows(out_dir / "raw_trials.csv", rows, CSV_COLUMNS)
    summary = summarize(rows)
    write_rows(out_dir / "summary.csv", summary)
    print(format_summary(summary))
    print(f"\nwrote {out_dir}")
    return out_dir


def run_smoke(trials=60, ms=(2,), g=GEN_SIZE, seed_start=0, cells=None) -> str:
    rows = [run_trial(cell, s) for cell in (cells or sweep_cells(ms, g)) for s in range(seed_start, seed_start + trials)]
    return format_summary(summarize(rows))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="S3: tag pollution vs verification width.")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--noise-sweep", action="store_true",
                   help="random tag-region bit flips at --bers (corrupted packets only) instead of an attacker")
    p.add_argument("--bers", default="1e-5,1e-4,1e-3,1e-2")
    p.add_argument("--support-sweep", action="store_true",
                   help="keyless footprint sweep (tag-block bytes changed) instead of the main sweep")
    p.add_argument("--trials", type=int, default=4000)
    p.add_argument("--seed-start", type=int, default=0)
    p.add_argument("--ms", default="2,4")
    p.add_argument("--gen-size", type=int, default=GEN_SIZE)
    p.add_argument("--hd", type=int, default=0, help="receiver repair Hamming distance (0 = off)")
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)
    ms = tuple(int(x) for x in a.ms.split(","))
    cells = (noise_sweep_cells(ms, a.gen_size, tuple(float(x) for x in a.bers.split(","))) if a.noise_sweep
             else support_sweep_cells(ms, a.gen_size) if a.support_sweep else None)
    if a.smoke:
        print(run_smoke(ms=ms, g=a.gen_size, cells=cells))
    if a.sweep:
        run_sweep(trials=a.trials, ms=ms, g=a.gen_size, hd=a.hd, seed_start=a.seed_start, workers=a.workers,
                  out_dir=a.out, cells=cells)
    if not (a.smoke or a.sweep):
        p.print_help()


if __name__ == "__main__":
    main()
