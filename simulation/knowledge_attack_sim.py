r"""Ticket 17 Part B -- partial-knowledge forgery, keyless vs keyed (plan attack A5).

Question: how often does ONE forged packet produce a silent decode, as a function of how
much the attacker knows?
  keyless (SegmentedScheme):   the attacker has OBSERVED r honest packets (r = 0..g-1)
  keyed   (SegmentedMacScheme): k of the coeff segment's g key vectors have LEAKED (k = 0..g)
Both are put on one axis, u = verification constraints the attacker cannot compute:
  keyed   u = g - k        (the receiver verifies all g tags)
  keyless u = g - 1 - r    (at its first decode attempt the receiver holds g-1 honest
                            witnesses; the self-check is free -- it is linear in char 2)
Theory (written before any run): P(forgery passes the strict oracle) = q^-u in both arms.

The forger is SPLICE-FREE by construction (Part A's zero-work splice is a separate result):
it copies an intercepted honest victim V (its data segments stay genuine and verify for
free) and replaces ONLY the coeff segment with a coefficient row c' OUTSIDE the span of
every honest row the receiver holds at its first decode attempt -- so c' is innovative
("forced innovation": the attacker's best case; an unconditioned random c' would be
dependent ~1/q of the time) and outside the attacker's own observed span.
  keyless: coeff-segment tags solved so the slice is self-orthogonal and orthogonal to all
           r observed coeff slices (free tag variables randomised, not zeroed).
  keyed:   tags exact for the k leaked keys, uniform random for the other g-k.

Arrival schedule (paired across arms: same data, same honest rows H_0.., same V, same c'):
  keyless early: H_0..H_{r-1} (observed), F, then unobserved honest     (strike index r)
  keyed   early: F, then honest                                          (strike index 0)
  late (both):   H_0..H_{g-2}, F, then honest                            (strike index g-1)
The keyed tag check does not depend on arrival order ("late" = insensitivity check). For
keyless, "late" exposes the greedy-peel tie-break in classify_segment_trust: a forger that
disagrees with exactly one honest packet ties with it, and the LOWER pool index is peeled
first -- early, that is the forger; late, the honest packet.

Recorded per trial (no channel noise): oracle_pass (strict: every check vs the g-1 honest
head packets, no repair -- the q^-u event), forged_admitted / forged_modified (production
admit, incl. the keyed repair machinery "repairing" a forgery into a valid-but-wrong
packet), decoded / correct / silent, attacker field-ops.

Run (PowerShell, main .venv, from the worktree/repo root):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" simulation/knowledge_attack_sim.py --smoke
  ... simulation/knowledge_attack_sim.py --sweep --trials 4000 --workers 6 --out <dir>
Replot without re-running: scripts/knowledge_attack_plots_from_csv.py (pools run dirs).

FROZEN CSV SCHEMA (raw_trials.csv, CSV_SCHEMA_VERSION = 1; CSV_COLUMNS enforces it)
One row per trial. Pool across runs by summing counts per cell, never by averaging rates.
  schema_version   int   = CSV_SCHEMA_VERSION
  arm              str   keyless | keyed
  strike           str   early | late
  field_bits       int   m of GF(2^m);  q = 2^m
  q                int
  gen_size         int   g
  data_fields      int
  n_segments       int   N (1 coeff + N-1 data segments)
  knowledge_kind   str   observed_packets (keyless) | leaked_keys (keyed)
  knowledge        int   r (keyless) or k (keyed)
  u                int   unknown constraints (see above)
  seed             int   paired: same seed -> same data / honest rows / victim / c' in every cell
  strike_index     int   pool position of the forged packet
  oracle_pass      int   0/1 forged packet passes every check vs the g-1 honest head (strict)
  forged_admitted  int   0/1 forged packet (any form) in the admitted set when the receiver stopped
  forged_modified  int   0/1 ... admitted only in a MODIFIED form (repair changed it)
  decoded          int   0/1 receiver reached full rank
  correct          int   0/1 decoded == source
  silent           int   0/1 decoded AND wrong -- the safety number
  packets_received int   pool size when the receiver stopped (cap = 4*g)
  forge_failed     int   0/1 attacker could not build a forgery (keyless solve inconsistent every retry)
  forge_attempts   int   keyless solve attempts; each retry redraws c' (still innovative) (keyed: 1)
  attacker_mul     int   field muls on the forging path
  attacker_add     int   field adds on the forging path
  receiver_mul     int   field muls of the receiver's admit calls (detection + repair)
  verify_count     int   AdmitConfig (logged so runs with other cfgs never pool silently)
  min_trust_count  int
  min_pool_size    int
  hamming_distance int
"""

import argparse
import csv
import os
import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path

from binary_ext_fields.custom_field import CountingField
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.pollution import _gf_solve
from simulation.attack_harness import (
    arrivals_with_injection, default_cfg, field_for, independent_rows, injected_status,
    paired_setup, passes_oracle, random_row, recode, row_outside_span, run_receiver,
)


CSV_SCHEMA_VERSION = 1
CSV_COLUMNS = [
    "schema_version", "arm", "strike", "field_bits", "q", "gen_size", "data_fields", "n_segments",
    "knowledge_kind", "knowledge", "u", "seed", "strike_index",
    "oracle_pass", "forged_admitted", "forged_modified", "decoded", "correct", "silent",
    "packets_received", "forge_failed", "forge_attempts", "attacker_mul", "attacker_add", "receiver_mul",
    "verify_count", "min_trust_count", "min_pool_size", "hamming_distance",
]

ARMS = ("keyless", "keyed")
STRIKES = ("early", "late")
GEN_SIZE = 4
DATA_FIELDS = 12
N_SEGMENTS = 2
SWEEP_MS = (2, 4)
MAX_PACKETS_FACTOR = 4
FORGE_RETRIES = 32


# ── Knowledge axis ────────────────────────────────────────────────────────────

def knowledge_levels(arm: str, gen_size: int) -> range:
    return range(gen_size) if arm == "keyless" else range(gen_size + 1)


def unknown_constraints(arm: str, knowledge: int, gen_size: int) -> int:
    return gen_size - 1 - knowledge if arm == "keyless" else gen_size - knowledge


def strike_index(arm: str, strike: str, knowledge: int, gen_size: int) -> int:
    if strike == "late":
        return gen_size - 1
    return knowledge if arm == "keyless" else 0


def theory_pass(q: int, u: int) -> float:
    """P(one forgery passes the strict oracle) = q^-u, both arms."""
    return float(q) ** -u


def theory_keyed_repair(q: int, m: int, u: int, gen_size: int, hd: int) -> float:
    """First-order P(keyed forgery ADMITTED) once the production repair runs (found while
    building ticket 17, not predicted): a forgery failing its MAC is 'broken', and the
    unpaired coeff-segment repair bit-flips up to `hd` bits over the WHOLE segment
    (payload + tags) until the MAC verifies -- so the receiver itself corrects a guessed
    tag that is one bit off. For hd = 1:
      a = q^-u                 all u guessed tags right (the oracle event)
      b = u * m * q^-u         exactly one guessed tag off by exactly one bit (m of q values)
      c = g * m * q^-g         otherwise, a payload bit flip lands on a c'' whose g tags all match
      P = a + b + (1 - a - b) * c
    hd = 0 -> q^-u (no repair). hd >= 2 is not modelled (nan)."""
    a = float(q) ** -u
    if hd == 0:
        return a
    if hd == 1:
        b = u * m * a
        return a + b + (1 - a - b) * gen_size * m * float(q) ** -gen_size
    return float("nan")


def theory_keyless_late(q: int, u: int) -> float:
    """First-order P(keyless forgery ADMITTED) with a LATE strike (also found while building
    ticket 17): classify_segment_trust's greedy peel breaks a disagreement-count tie by
    peeling the LOWER pool index. A forger that disagrees with exactly one honest packet j
    (prob u (1-1/q) q^-(u-1)) is injected after j, so j is peeled instead of the forger;
    the forger then survives if the next honest arrival agrees with it (1/q) and c' is
    still innovative against the reshuffled honest set (~1-1/q):
      q^-u + u (1-1/q)^2 q^-u  =  q^-u (1 + u (1-1/q)^2).
    Early strike: the forger has the lower index, is peeled on the tie -> plain q^-u."""
    return float(q) ** -u * (1 + u * (1 - 1 / q) ** 2)


def theory_admit(arm: str, strike: str, q: int, m: int, u: int, gen_size: int, hd: int) -> float:
    """Expected production ADMIT rate per arm/strike (see the two functions above)."""
    if arm == "keyed":
        return theory_keyed_repair(q, m, u, gen_size, hd)
    return theory_keyless_late(q, u) if strike == "late" else theory_pass(q, u)


# ── Paired per-seed plan ──────────────────────────────────────────────────────

@dataclass
class Plan:
    head: list          # g-1 honest rows (rank g-1) the receiver holds at its first decode attempt
    victim_row: bytearray
    forged_row: bytearray   # c': outside span(head) (innovative) and != victim_row
    tail_seed: int


def paired_plan(seed, field, gen_size, data_fields, n, arm):
    """(setup, plan). Every draw here comes from the arm-independent shared RNG, so the
    same seed gives the same plan in both arms and at every knowledge level."""
    shared, setup = paired_setup(seed, field, gen_size, data_fields, n, arm)
    head = independent_rows(shared, field, gen_size, gen_size - 1)
    victim_row = random_row(shared, field, gen_size)
    while not any(victim_row):
        victim_row = random_row(shared, field, gen_size)
    forged_row = row_outside_span(shared, field, gen_size, head, exclude=[victim_row])
    return setup, Plan(head=head, victim_row=victim_row, forged_row=forged_row, tail_seed=shared.getrandbits(64))


# ── The two forgers (coeff segment only) ──────────────────────────────────────

def forge_coeff_keyless(setup, observed_packets, forged_row, atk_rng, cnt, new_row=None):
    """Keyless coeff-segment slice [c' | salt | g tags]: self-orthogonal (in char 2 that is
    the linear constraint XOR-of-all-bytes = 0) and orthogonal to every observed coeff
    slice. Unknowns = salt + g tags (g+1), constraints = len(observed)+1 <= g. Free
    variables are RANDOMISED (x = x0 + y, A y = b + A x0) so the forgery is uniform over the
    solution space rather than biased to zeros. All arithmetic through cnt (attacker work).

    The system can only be inconsistent when the observed (salt|tags) rows plus the all-ones
    row are linearly dependent AND c' violates the matching condition -- a property of c'
    alone (salt and tags are unknowns), so retrying the same c' is pointless: each retry
    draws a fresh c' from new_row() (None = give up after the first attempt).
    Returns (slice | None, attempts); slice[:g] is the c' actually used."""
    seg = setup.coeff_segment()
    g = setup.gen_size
    assert seg.payload_length == g
    obs = [p[seg.start:seg.start + seg.total_length] for p in observed_packets]
    A = [list(o[g:]) for o in obs] + [[1] * (g + 1)]          # columns: salt, tag_1..tag_g
    row = list(forged_row)
    for attempt in range(1, FORGE_RETRIES + 1):
        if attempt > 1:
            if new_row is None:
                break
            row = list(new_row())
        b = []
        for o in obs:
            acc = 0
            for x, y in zip(row, o[:g]):
                acc = cnt.add(acc, cnt.mul(x, y))
            b.append(acc)
        acc = 0
        for x in row:
            acc = cnt.add(acc, x)
        b.append(acc)
        x0 = [atk_rng.randint(0, cnt.max_value) for _ in range(g + 1)]
        b_shift = []
        for a_row, bj in zip(A, b):
            acc = bj
            for a, x in zip(a_row, x0):
                acc = cnt.add(acc, cnt.mul(a, x))
            b_shift.append(acc)
        y = _gf_solve(cnt, A, b_shift)
        if y is None:
            continue
        rest = [cnt.add(a, c) for a, c in zip(x0, y)]
        return bytearray(row + rest), attempt
    return None, attempt


def forge_coeff_keyed(setup, leaked_keys: int, forged_row, atk_rng, cnt):
    """Keyed coeff-segment slice [c' | g tags]: exact MAC for the first `leaked_keys` key
    vectors (i.i.d. keys, so which subset leaks is immaterial), uniform guesses for the rest."""
    s = next(i for i, seg in enumerate(setup.segments) if seg.kind == "coeff")
    keys = setup.keyset[s]
    tags = [inner_product_bytes(cnt, forged_row, keys[j]) for j in range(leaked_keys)]
    tags += [atk_rng.randint(0, cnt.max_value) for _ in range(len(keys) - leaked_keys)]
    return bytearray(forged_row) + bytearray(tags)


def splice_coeff(setup, victim, coeff_slice) -> bytearray:
    seg = setup.coeff_segment()
    assert len(coeff_slice) == seg.total_length
    out = bytearray(victim)
    out[seg.start:seg.start + seg.total_length] = coeff_slice
    return out


# ── One trial ─────────────────────────────────────────────────────────────────

@dataclass
class KnowledgeTrial:
    schema_version: int
    arm: str
    strike: str
    field_bits: int
    q: int
    gen_size: int
    data_fields: int
    n_segments: int
    knowledge_kind: str
    knowledge: int
    u: int
    seed: int
    strike_index: int
    oracle_pass: int
    forged_admitted: int
    forged_modified: int
    decoded: int
    correct: int
    silent: int
    packets_received: int
    forge_failed: int
    forge_attempts: int
    attacker_mul: int
    attacker_add: int
    receiver_mul: int
    verify_count: int
    min_trust_count: int
    min_pool_size: int
    hamming_distance: int


def run_knowledge_trial(arm, knowledge, seed, field_bits=2, strike="early", gen_size=GEN_SIZE,
                        data_fields=DATA_FIELDS, n=N_SEGMENTS, cfg=None,
                        max_packets_factor=MAX_PACKETS_FACTOR, receiver=True) -> KnowledgeTrial:
    """One forged packet against one receiver lifetime. receiver=False skips the receiver
    (oracle_pass and attacker work only -- the fast path for q^-u Monte Carlo); the
    receiver-side fields are then 0."""
    assert arm in ARMS and strike in STRIKES and knowledge in knowledge_levels(arm, gen_size)
    base = field_for(field_bits)
    cfg = cfg or default_cfg(gen_size)
    setup, plan = paired_plan(seed, base, gen_size, data_fields, n, arm)
    honest_head = [recode(setup, r) for r in plan.head]
    victim = recode(setup, plan.victim_row)
    cnt = CountingField(base)
    # strike deliberately NOT in the seed: early and late get the identical forged packet,
    # so any early/late difference is the receiver's, paired per trial.
    atk_rng = random.Random(f"{seed}/{arm}/{knowledge}/attacker")

    if arm == "keyless":
        # a redrawn c' stays forced-innovative (outside the receiver's honest head span)
        redraw = lambda: row_outside_span(atk_rng, base, gen_size, plan.head, exclude=[plan.victim_row])  # noqa: E731
        coeff_slice, attempts = forge_coeff_keyless(setup, honest_head[:knowledge], plan.forged_row, atk_rng, cnt,
                                                    new_row=redraw)
    else:
        coeff_slice, attempts = forge_coeff_keyed(setup, knowledge, plan.forged_row, atk_rng, cnt), 1

    s_idx = strike_index(arm, strike, knowledge, gen_size)
    instrument = setup.new_instrument()
    honest_log: list = []
    tail = random.Random(plan.tail_seed)
    forged = None if coeff_slice is None else splice_coeff(setup, victim, coeff_slice)
    oracle = forged is not None and passes_oracle(setup, forged, honest_head)
    if receiver:
        # attacker could not forge -> it injects a harmless duplicate; the receiver just sees honest traffic
        injected = forged if forged is not None else recode(setup, plan.head[0])
        arrivals = arrivals_with_injection(setup, plan.head, injected, s_idx, tail, honest_log)
        outcome = run_receiver(setup, arrivals, cfg, max_packets_factor * gen_size, instrument=instrument)
        admitted, modified = (False, False) if forged is None else injected_status(setup, outcome, forged, honest_log)
        decoded, correct, pkts = outcome.decoded, outcome.correct, outcome.packets_received
    else:
        admitted = modified = decoded = correct = False
        pkts = 0

    return KnowledgeTrial(
        schema_version=CSV_SCHEMA_VERSION, arm=arm, strike=strike, field_bits=field_bits, q=2 ** field_bits,
        gen_size=gen_size, data_fields=data_fields, n_segments=n,
        knowledge_kind="observed_packets" if arm == "keyless" else "leaked_keys", knowledge=knowledge,
        u=unknown_constraints(arm, knowledge, gen_size), seed=seed, strike_index=s_idx,
        oracle_pass=int(oracle), forged_admitted=int(admitted), forged_modified=int(modified),
        decoded=int(decoded), correct=int(correct), silent=int(decoded and not correct), packets_received=pkts,
        forge_failed=int(coeff_slice is None), forge_attempts=attempts,
        attacker_mul=cnt.mul_count, attacker_add=cnt.add_count, receiver_mul=instrument.field.mul_count,
        verify_count=-1 if cfg.verify_count is None else cfg.verify_count, min_trust_count=cfg.min_trust_count,
        min_pool_size=cfg.min_pool_size, hamming_distance=cfg.hamming_distance,
    )


# ── Cells, aggregation, sweep ─────────────────────────────────────────────────

def sweep_cells(ms=SWEEP_MS, ns=(N_SEGMENTS,), arms=ARMS, strikes=STRIKES, gen_size=GEN_SIZE, hds=(1,)):
    """hd = the receiver's repair Hamming distance (AdmitConfig.hamming_distance; production
    default 1). 0 switches the repair search off -- the control for the keyed repair effect."""
    return [dict(arm=arm, knowledge=k, field_bits=m, strike=strike, n=n, gen_size=gen_size, hd=hd)
            for m in ms for n in ns for hd in hds for arm in arms for strike in strikes
            for k in knowledge_levels(arm, gen_size)]


def run_cell(cell, seeds, data_fields=DATA_FIELDS, receiver=True) -> list[KnowledgeTrial]:
    cfg = default_cfg(cell["gen_size"])
    cfg.hamming_distance = cell.get("hd", cfg.hamming_distance)
    return [run_knowledge_trial(cell["arm"], cell["knowledge"], s, field_bits=cell["field_bits"],
                                strike=cell["strike"], gen_size=cell["gen_size"], data_fields=data_fields,
                                n=cell["n"], cfg=cfg, receiver=receiver) for s in seeds]


def _run_chunk(args):
    cell, seeds, data_fields = args
    return [asdict(t) for t in run_cell(cell, seeds, data_fields)]


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval (lo, hi) for a proportion."""
    if total <= 0:
        return float("nan"), float("nan")
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def summarize(rows: list[dict]) -> list[dict]:
    """Per (arm, strike, m, n, g, knowledge) cell: counts, rates, Wilson CIs, theory."""
    cells: dict = {}
    for r in rows:
        key = (r["arm"], r["strike"], int(r["field_bits"]), int(r["n_segments"]), int(r["gen_size"]),
               int(r["hamming_distance"]), int(r["knowledge"]))
        cells.setdefault(key, []).append(r)
    out = []
    for (arm, strike, m, n, g, hd, k), rs in sorted(cells.items()):
        t = len(rs)
        u = int(rs[0]["u"])
        c = {f: sum(int(r[f]) for r in rs) for f in
             ("oracle_pass", "forged_admitted", "forged_modified", "silent", "decoded", "forge_failed")}
        lo, hi = wilson(c["silent"], t)
        olo, ohi = wilson(c["oracle_pass"], t)
        out.append({
            "arm": arm, "strike": strike, "field_bits": m, "q": 2 ** m, "n_segments": n, "gen_size": g,
            "hd": hd, "knowledge": k, "u": u, "trials": t,
            **c,
            "oracle_rate": c["oracle_pass"] / t, "oracle_lo": olo, "oracle_hi": ohi,
            "admit_rate": c["forged_admitted"] / t,
            "silent_rate": c["silent"] / t, "silent_lo": lo, "silent_hi": hi,
            "decode_rate": c["decoded"] / t,
            "theory": theory_pass(2 ** m, u),
            # expected ADMIT rate: keyed = oracle + repair correction; keyless = the oracle (its
            # forger always self-passes, so it is never 'broken' and never enters the repair
            # search), plus the greedy-peel tie-break term for a late strike
            "theory_admit": theory_admit(arm, strike, 2 ** m, m, u, g, hd),
            "attacker_mul_mean": sum(int(r["attacker_mul"]) for r in rs) / t,
            "receiver_mul_mean": sum(int(r["receiver_mul"]) for r in rs) / t,
        })
    return out


def write_rows(path: Path, rows: list[dict], columns=None) -> None:
    columns = columns or list(rows[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def run_sweep(trials=4000, ms=SWEEP_MS, ns=(N_SEGMENTS,), strikes=STRIKES, gen_size=GEN_SIZE,
              data_fields=DATA_FIELDS, seed_start=0, workers=1, out_dir=None, chunk=250, plot=True,
              hds=(1,)) -> Path:
    """Every cell x `trials` paired seeds -> raw_trials.csv (+ summary.csv + plots)."""
    if out_dir is None:
        from utils.log_helpers import get_run_log_dir
        out_dir = get_run_log_dir("knowledge_attack", trials=trials, gen=gen_size, m="".join(map(str, ms)))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = list(range(seed_start, seed_start + trials))
    jobs = [(cell, seeds[i:i + chunk], data_fields)
            for cell in sweep_cells(ms, ns, ARMS, strikes, gen_size, hds) for i in range(0, len(seeds), chunk)]
    rows: list[dict] = []
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for i, part in enumerate(ex.map(_run_chunk, jobs), 1):
                rows.extend(part)
                if i % 20 == 0 or i == len(jobs):
                    print(f"  {i}/{len(jobs)} chunks", flush=True)
    else:
        for i, job in enumerate(jobs, 1):
            rows.extend(_run_chunk(job))
            print(f"  {i}/{len(jobs)} chunks", flush=True)
    assert all(list(r.keys()) == CSV_COLUMNS for r in rows), "trial record drifted from the frozen schema"
    write_rows(out_dir / "raw_trials.csv", rows, CSV_COLUMNS)
    summary = summarize(rows)
    write_rows(out_dir / "summary.csv", summary)
    print(format_summary(summary))
    if plot:
        from scripts.knowledge_attack_plots_from_csv import plot_all
        plot_all([out_dir / "raw_trials.csv"], out_dir)
    print(f"\nwrote {out_dir}")
    return out_dir


# ── Readable output ───────────────────────────────────────────────────────────

def format_summary(summary: list[dict]) -> str:
    head = (f"{'arm':<8} {'strike':<6} {'m':>2} {'N':>2} {'hd':>2} {'know':>4} {'u':>2} {'trials':>6} | "
            f"{'oracle':>7} {'q^-u':>7} | {'admit':>7} {'thAdmit':>7} {'modif':>6} | {'silent':>7} [95% CI]"
            f"          {'atkMul':>7}")
    lines = [head, "-" * len(head)]
    for s in summary:
        lines.append(
            f"{s['arm']:<8} {s['strike']:<6} {s['field_bits']:>2} {s['n_segments']:>2} {s['hd']:>2} "
            f"{s['knowledge']:>4} {s['u']:>2} {s['trials']:>6} | {s['oracle_rate']:>7.4f} {s['theory']:>7.4f} | "
            f"{s['admit_rate']:>7.4f} {s['theory_admit']:>7.4f} {s['forged_modified']:>6} | {s['silent_rate']:>7.4f} "
            f"[{s['silent_lo']:.4f},{s['silent_hi']:.4f}] {s['attacker_mul_mean']:>7.1f}")
    return "\n".join(lines)


def run_smoke(seed=0, field_bits=2, mc_trials=150) -> str:
    """(1) one readable line per (arm, knowledge) for a single seed; (2) a quick Monte Carlo
    table (mc_trials per cell, early strike) with the q^-u theory column beside it."""
    lines = [f"Partial-knowledge forgery (ticket 17 B)  GF(2^{field_bits}) g={GEN_SIZE} N={N_SEGMENTS} "
             f"data={DATA_FIELDS}  seed={seed}",
             "one forged packet per trial; splice-free forger; c' forced innovative; no channel noise",
             "",
             f"{'arm':<8} {'know':>4} {'u':>2} {'idx':>3} | {'oracle':>6} {'admit':>5} {'modif':>5} "
             f"{'dec':>3} {'ok':>3} {'SILENT':>6} {'pkts':>4} {'atkMul':>6} {'tries':>5}"]
    for arm in ARMS:
        for k in knowledge_levels(arm, GEN_SIZE):
            t = run_knowledge_trial(arm, k, seed, field_bits=field_bits)
            lines.append(f"{arm:<8} {k:>4} {t.u:>2} {t.strike_index:>3} | {t.oracle_pass:>6} {t.forged_admitted:>5} "
                         f"{t.forged_modified:>5} {t.decoded:>3} {t.correct:>3} {t.silent:>6} "
                         f"{t.packets_received:>4} {t.attacker_mul:>6} {t.forge_attempts:>5}")
    rows = []
    for cell in sweep_cells(ms=(field_bits,), strikes=("early",)):
        rows.extend(asdict(t) for t in run_cell(cell, range(mc_trials)))
    lines += ["", f"Monte Carlo, {mc_trials} paired seeds/cell, early strike:", format_summary(summarize(rows))]
    return "\n".join(lines)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Ticket 17 Part B: partial-knowledge forgery sweep.")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--trials", type=int, default=4000, help="paired seeds per cell")
    p.add_argument("--seed-start", type=int, default=0)
    p.add_argument("--ms", default=",".join(map(str, SWEEP_MS)))
    p.add_argument("--ns", default=str(N_SEGMENTS), help="comma list of N (segments per packet)")
    p.add_argument("--strikes", default=",".join(STRIKES))
    p.add_argument("--gen-size", type=int, default=GEN_SIZE)
    p.add_argument("--data-fields", type=int, default=DATA_FIELDS)
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p.add_argument("--out", default=None)
    p.add_argument("--hds", default="1", help="comma list of receiver repair Hamming distances (0 = repair off)")
    p.add_argument("--no-plot", action="store_true")
    a = p.parse_args(argv)
    if a.smoke:
        print(run_smoke())
    if a.sweep:
        run_sweep(trials=a.trials, ms=tuple(int(x) for x in a.ms.split(",")),
                  ns=tuple(int(x) for x in a.ns.split(",")), strikes=tuple(a.strikes.split(",")),
                  gen_size=a.gen_size, data_fields=a.data_fields, seed_start=a.seed_start,
                  workers=a.workers, out_dir=a.out, plot=not a.no_plot,
                  hds=tuple(int(x) for x in a.hds.split(",")))
    if not (a.smoke or a.sweep):
        p.print_help()


if __name__ == "__main__":
    main()
