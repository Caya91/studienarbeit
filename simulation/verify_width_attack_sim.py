r"""S2 -- verification width vs forgery success, deterministic vs receiver-secret witnesses.

Question (supervisor, 2026-09-29): the receiver caps verification work -- keyed checks W of
the g MAC tags, keyless cross-checks verify_count (vc) witnesses. How often is ONE forged
packet admitted, as a function of the width and of how much the attacker knows?
Supervisor hypothesis (keyed, W = 1, checked key unpredictable):  P ~ k/g + (1 - k/g)/q.

Two witness policies (binary_ext_fields/witness_policy.py, AdmitConfig.witness_policy):
  first   deterministic: first vc core members by arrival (keyless) / keys[:W] (keyed)
  random  per-packet subset from a receiver secret the attacker never sees

Attacker = the ticket-17 splice-free forgers (knowledge_attack_sim.py), EARLY strike:
  keyless  observed the first r honest arrivals, forged coeff slice orthogonal to them
  keyed    k leaked keys = keys[:k] (exact tags), the other g-k tags guessed uniformly
With policy "first" the leaked keys ARE the checked ones (worst case: an attacker who
knows the policy steals/targets exactly those); with "random" which keys leaked is
immaterial. Repair is OFF by default (hd = 0): the admit rate isolates verification.

Theory (first admit decides; written before the runs):
  keyless  core at the first admit = the g-1 honest head packets; unknown witnesses among
           the checked n = min(vc, g-1):
             first   q^-max(0, n - r)
             random  sum_j Hyp(j; g-1, g-1-r, n) q^-j      (n=1: r/(g-1) + (1 - r/(g-1))/q)
  keyed    first   q^-max(0, W - k)
           random  sum_j Hyp(j; g, g-k, W) q^-j            (W=1: k/g + (1 - k/g)/q)
  width None (= all) gives the ticket-17 q^-u in both policies.

Run (PowerShell, main .venv, from the worktree):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"
  & "E:/projects/studienarbeit/.venv/Scripts/python.exe" simulation/verify_width_attack_sim.py --smoke
  ... --sweep --trials 4000 --ms 2,4 --workers 5 --out <dir>

FROZEN CSV SCHEMA (raw_trials.csv, CSV_SCHEMA_VERSION = 1)
  the knowledge_attack_sim v1 columns (see that module) EXCEPT verify_count, plus:
  witness_policy   str   first | random
  width            int   keyless vc / keyed W; -1 = all (no cap)
  witness_secret   int   receiver secret of this trial (derived from seed; never given to the attacker)
  theory_admit     float the formula above for this cell
"""
import argparse
import csv
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from math import comb
from pathlib import Path

from simulation.attack_harness import default_cfg
from simulation.knowledge_attack_sim import (
    CSV_COLUMNS as KNOWLEDGE_COLUMNS, knowledge_levels, run_knowledge_trial, wilson, write_rows,
)

CSV_SCHEMA_VERSION = 1
GEN_SIZE = 4
DATA_FIELDS = 12
N_SEGMENTS = 2
POLICIES = ("first", "random")
CSV_COLUMNS = ([c for c in KNOWLEDGE_COLUMNS if c not in ("schema_version", "verify_count")]
               + ["schema_version", "witness_policy", "width", "witness_secret", "theory_admit"])


# ── Theory ────────────────────────────────────────────────────────────────────

def _hyp(j: int, pop: int, succ: int, draws: int) -> float:
    """P(j successes) drawing `draws` without replacement from `pop` holding `succ` successes."""
    if j < 0 or j > succ or draws - j < 0 or draws - j > pop - succ:
        return 0.0
    return comb(succ, j) * comb(pop - succ, draws - j) / comb(pop, draws)


def theory_admit(arm: str, policy: str, knowledge: int, width: int | None, g: int, q: int) -> float:
    if arm == "keyless":
        pop, unknown = g - 1, g - 1 - knowledge          # core = g-1 honest; r of them observed
    else:
        pop, unknown = g, g - knowledge                  # g keys; k leaked
    n = pop if width is None else min(width, pop)
    if policy == "first" or n == pop:
        known_checked = min(n, pop - unknown)            # "first": the known ones are checked first
        return float(q) ** -(n - known_checked)
    return sum(_hyp(j, pop, unknown, n) * float(q) ** -j for j in range(n + 1))


def theory_admit_reeval(arm: str, policy: str, knowledge: int, width: int | None, g: int, q: int) -> float:
    """theory_admit + the RE-EVALUATION term (found in the first S2 run, 2026-09-29): the receiver is
    stateless -- every arrival re-classifies the whole pool. Keyless + "random" only: a forger
    rejected at the first admit (pool g) is re-checked at pool g+1, where the new honest packet
    joins the core and lands among the forger's n lowest-rank witnesses with prob n/g, replacing the
    highest-rank old witness d (uniform in the old set). The forger now passes iff d was its only
    disagreeing witness (d unknown, prob j/n; the other j-1 unknowns agreed, q^-(j-1); d disagreed,
    1-1/q) and it agrees with the newcomer (1/q). At pool g+1 the g honest packets decode, so there
    is exactly one extra chance:
      P2 = (n/g)(1/q) sum_j Hyp(j; g-1, g-1-r, n) (j/n) q^-(j-1) (1 - 1/q).
    "first" never changes the witnesses (the newcomer has the highest index) and the keyed key subset
    of a packet is fixed, so both get P2 = 0."""
    p1 = theory_admit(arm, policy, knowledge, width, g, q)
    if arm != "keyless" or policy != "random" or width is None or width >= g - 1:
        return p1
    pop, unknown, n = g - 1, g - 1 - knowledge, width
    p2 = (n / g) / q * sum(_hyp(j, pop, unknown, n) * (j / n) * float(q) ** -(j - 1) * (1 - 1 / q)
                           for j in range(1, n + 1))
    return p1 + p2


# ── Cells + one trial ─────────────────────────────────────────────────────────

def widths(arm: str, g: int) -> list:
    """Capped widths 1..(max-1) and None (= all): keyless max = g-1 core witnesses, keyed = g keys."""
    top = g - 1 if arm == "keyless" else g
    return list(range(1, top)) + [None]


def sweep_cells(ms=(2, 4), g=GEN_SIZE, arms=("keyless", "keyed"), policies=POLICIES, hd=0):
    cells = []
    for m in ms:
        for arm in arms:
            for w in widths(arm, g):
                # width None checks everything -> the policy is irrelevant; run it once
                for pol in (("first",) if w is None else policies):
                    for k in knowledge_levels(arm, g):
                        cells.append(dict(arm=arm, knowledge=k, field_bits=m, width=w, policy=pol, g=g, hd=hd))
    return cells


def _secret(seed: int) -> int:
    return (seed * 0x9E3779B1 + 0x5DEECE66D) & 0xFFFFFFFF


def run_trial(cell: dict, seed: int, data_fields=DATA_FIELDS, n=N_SEGMENTS) -> dict:
    g = cell["g"]
    cfg = default_cfg(g)
    cfg.hamming_distance = cell["hd"]
    cfg.witness_policy = cell["policy"]
    cfg.witness_secret = _secret(seed)          # receiver-side only; the forgers never read cfg
    if cell["arm"] == "keyless":
        cfg.verify_count = cell["width"]
    else:
        cfg.mac_verify_count = cell["width"]
    t = asdict(run_knowledge_trial(cell["arm"], cell["knowledge"], seed, field_bits=cell["field_bits"],
                                   strike="early", gen_size=g, data_fields=data_fields, n=n, cfg=cfg))
    t.pop("verify_count")
    t.update(schema_version=CSV_SCHEMA_VERSION, witness_policy=cell["policy"],
             width=-1 if cell["width"] is None else cell["width"], witness_secret=cfg.witness_secret,
             theory_admit=theory_admit(cell["arm"], cell["policy"], cell["knowledge"], cell["width"], g,
                                       2 ** cell["field_bits"]))
    return {c: t[c] for c in CSV_COLUMNS}


def _run_chunk(args):
    cell, seeds = args
    return [run_trial(cell, s) for s in seeds]


# ── Aggregation + sweep ───────────────────────────────────────────────────────

def summarize(rows: list[dict]) -> list[dict]:
    cells: dict = {}
    for r in rows:
        key = (r["arm"], int(r["field_bits"]), int(r["gen_size"]), int(r["hamming_distance"]), r["witness_policy"],
               int(r["width"]), int(r["knowledge"]))
        cells.setdefault(key, []).append(r)
    out = []
    for (arm, m, g, hd, pol, w, k), rs in sorted(cells.items()):
        t = len(rs)
        adm = sum(int(r["forged_admitted"]) for r in rs)
        sil = sum(int(r["silent"]) for r in rs)
        lo, hi = wilson(adm, t)
        th = float(rs[0]["theory_admit"])
        th2 = theory_admit_reeval(arm, pol, k, None if w < 0 else w, g, 2 ** m)
        z = (adm / t - th) / max((th * (1 - th) / t) ** 0.5, 1e-12)
        z2 = (adm / t - th2) / max((th2 * (1 - th2) / t) ** 0.5, 1e-12)
        out.append({"arm": arm, "field_bits": m, "q": 2 ** m, "gen_size": g, "hd": hd, "policy": pol, "width": w,
                    "knowledge": k, "u": int(rs[0]["u"]), "trials": t, "admitted": adm, "silent": sil,
                    "admit_rate": adm / t, "admit_lo": lo, "admit_hi": hi, "silent_rate": sil / t,
                    "theory_admit": th, "z_vs_theory": z, "theory_admit_reeval": th2, "z_vs_reeval": z2,
                    "forge_failed": sum(int(r["forge_failed"]) for r in rs),
                    "receiver_mul_mean": sum(int(r["receiver_mul"]) for r in rs) / t})
    return out


def format_summary(summary: list[dict]) -> str:
    head = (f"{'arm':<8} {'m':>2} {'pol':<6} {'wid':>3} {'know':>4} {'trials':>6} | {'admit':>7} "
            f"[{'95% CI':^15}] {'theory':>7} {'z':>6} | {'silent':>7} {'rcvMul':>7}")
    lines = [head, "-" * len(head)]
    for s in summary:
        w = "all" if s["width"] < 0 else str(s["width"])
        lines.append(f"{s['arm']:<8} {s['field_bits']:>2} {s['policy']:<6} {w:>3} {s['knowledge']:>4} {s['trials']:>6} | "
                     f"{s['admit_rate']:>7.4f} [{s['admit_lo']:.4f},{s['admit_hi']:.4f}] {s['theory_admit']:>7.4f} "
                     f"{s['z_vs_theory']:>6.2f} | {s['silent_rate']:>7.4f} {s['receiver_mul_mean']:>7.0f}")
    return "\n".join(lines)


def run_sweep(trials=4000, ms=(2, 4), g=GEN_SIZE, hd=0, seed_start=0, workers=1, out_dir=None, chunk=250) -> Path:
    if out_dir is None:
        from utils.log_helpers import get_run_log_dir
        out_dir = get_run_log_dir("verify_width_attack", trials=trials, gen=g, m="".join(map(str, ms)))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = list(range(seed_start, seed_start + trials))
    jobs = [(cell, seeds[i:i + chunk]) for cell in sweep_cells(ms, g, hd=hd) for i in range(0, len(seeds), chunk)]
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


def run_smoke(trials=60, ms=(2,), seed_start=0) -> str:
    rows = []
    for cell in sweep_cells(ms):
        rows.extend(run_trial(cell, s) for s in range(seed_start, seed_start + trials))
    return format_summary(summarize(rows))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="S2: verification width vs forgery success.")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--trials", type=int, default=4000)
    p.add_argument("--seed-start", type=int, default=0)
    p.add_argument("--ms", default="2,4")
    p.add_argument("--gen-size", type=int, default=GEN_SIZE)
    p.add_argument("--hd", type=int, default=0, help="receiver repair Hamming distance (0 = off)")
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)
    ms = tuple(int(x) for x in a.ms.split(","))
    if a.smoke:
        print(run_smoke(ms=ms))
    if a.sweep:
        run_sweep(trials=a.trials, ms=ms, g=a.gen_size, hd=a.hd, seed_start=a.seed_start, workers=a.workers,
                  out_dir=a.out)
    if not (a.smoke or a.sweep):
        p.print_help()


if __name__ == "__main__":
    main()
