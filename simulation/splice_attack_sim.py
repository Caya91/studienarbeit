r"""Ticket 17 Part A -- segment splice / scale test (plan attack A3).

Hypothesis (analytic): both segmented arms verify every segment INDEPENDENTLY, and both
tags are linear per segment (homomorphic). So a packet whose segments come from DIFFERENT
honest linear combinations -- or whose data segment is scaled by a constant, or zeroed --
passes every check, needs no key and (almost) no field work, and poisons the decode
because its coefficients no longer match its data. N=1 (one tag over [coeff|data]) should
be immune: a single tag forces the same combination across all columns.

Setup per trial (no channel noise):
  - receiver pool = gen_size-1 honest recoded packets (rank gen_size-1) + the forged one;
  - victim V = a fresh honest packet the relay intercepts (never delivered), coefficient
    row chosen OUTSIDE the pool's span so V's row is innovative (pivots at the receiver);
  - O = honest pool packet #0 (the relay forwarded it and kept a copy);
  - after the forged packet, fresh honest packets keep arriving until decode (cap 4*gen_size).
Grading = the production admit path + _try_decode vs ground truth (attack_harness).

Variants (region = segment full slice incl. salt/tags for N>=2; data columns for N=1):
  none    V unmodified (sanity: must decode correctly)
  random  V with data region 0 replaced by random bytes (negative control: must be rejected)
  splice  V's coeff region + O's data regions
  scale   V with data region 0 multiplied by alpha (alpha not in {0,1})
  zero    V with every data region set to 0
  ones    V with every data region set to beta*(1,...,1). In char 2 the self-check <v,v> =
          (sum v)^2 is the linear check "v orthogonal to the all-ones vector", so every
          honest keyless segment is orthogonal to 1 and beta*1 is self-orthogonal iff the
          segment length is even: keyless admits it iff ALL data slices have even length.
          A MAC tag of beta*1 is not beta*1 -> keyed rejects.

Readable table (PowerShell, main .venv; run from the repo/worktree root):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" simulation/splice_attack_sim.py --smoke
  ... simulation/splice_attack_sim.py --trials 50 --csv logs/splice_attack/table.csv
"""

import argparse
import csv
import random
from dataclasses import dataclass, asdict
from pathlib import Path

from binary_ext_fields.custom_field import CountingField
from simulation.attack_harness import (
    SEGMENTED_ARMS, N1_ARMS, default_cfg, field_for, independent_rows, row_outside_span,
    paired_setup, recode, run_receiver, passes_oracle, injected_status, arrivals_with_injection,
)


VARIANTS = ("none", "random", "splice", "scale", "zero", "ones")
SEGMENTED_NS = (2, 3, 5)
FIELD_M = 8
GEN_SIZE = 4
DATA_FIELDS = 12          # N=5 -> 4 data segments of 3 = gen_size-1 (rank floor), all N feasible
MAX_PACKETS_FACTOR = 4


def cells(segmented_ns=SEGMENTED_NS):
    """(arm, n) pairs of the table: segmented arms x N, then the two N=1 controls."""
    return [(arm, n) for arm in SEGMENTED_ARMS for n in segmented_ns] + [(arm, 1) for arm in N1_ARMS]


def expected(setup, variant) -> tuple[bool, bool]:
    """(forged_admitted, silent) the hypothesis predicts -- deterministic at m=8 up to
    q^-u chance events. N=1 controls reject every modification."""
    if variant == "none":
        return True, False
    if setup.n == 1 or variant == "random":
        return False, False
    if variant == "ones":
        ok = setup.arm == "keyless" and all(length % 2 == 0 for _, length in setup.data_regions())
        return ok, ok
    return True, True     # splice / scale / zero on a segmented arm


def forge(setup, variant, victim, other, atk_rng, atk_field) -> bytearray:
    """The injected packet. Field work goes through atk_field (a CountingField) so the
    attacker's cost is measurable; splice / zero / ones / none are pure byte copies."""
    out = bytearray(victim)
    regions = setup.data_regions()
    if variant == "none":
        pass
    elif variant == "random":
        start, length = regions[0]
        while True:
            fresh = bytearray(atk_rng.randint(0, atk_field.max_value) for _ in range(length))
            if fresh != out[start:start + length]:
                break
        out[start:start + length] = fresh
    elif variant == "splice":
        for start, length in regions:
            out[start:start + length] = other[start:start + length]
    elif variant == "scale":
        start, length = regions[0]
        alpha = atk_rng.randint(2, atk_field.max_value)
        out[start:start + length] = bytearray(atk_field.mul(b, alpha) for b in out[start:start + length])
    elif variant == "zero":
        for start, length in regions:
            out[start:start + length] = bytes(length)
    elif variant == "ones":
        beta = atk_rng.randint(1, atk_field.max_value)
        for start, length in regions:
            out[start:start + length] = bytes([beta]) * length
    else:
        raise ValueError(f"unknown variant {variant!r}")
    assert len(out) == len(victim)
    return out


@dataclass
class SpliceTrial:
    arm: str
    n: int
    variant: str
    seed: int
    field_bits: int
    gen_size: int
    data_fields: int
    oracle_pass: bool           # forged passes every check vs the honest pool (strict, no repair)
    forged_admitted: bool       # forged packet in the admitted set when the receiver stopped
    forged_modified: bool       # ...admitted only after the repair machinery changed it
    decoded: bool
    correct: bool
    silent: bool                # decoded AND wrong -- the safety number
    packets_received: int
    attacker_mul: int
    attacker_add: int
    expected_admitted: bool
    expected_silent: bool

    @property
    def matches(self) -> bool:
        return self.forged_admitted == self.expected_admitted and self.silent == self.expected_silent


def run_splice_trial(arm, n, variant, seed, field_bits=FIELD_M, gen_size=GEN_SIZE,
                     data_fields=DATA_FIELDS, cfg=None, max_packets_factor=MAX_PACKETS_FACTOR) -> SpliceTrial:
    base = field_for(field_bits)
    cfg = cfg or default_cfg(gen_size)
    shared, setup = paired_setup(seed, base, gen_size, data_fields, n, arm)
    head = independent_rows(shared, base, gen_size, gen_size - 1)
    victim_row = row_outside_span(shared, base, gen_size, head)
    tail_rng = random.Random(shared.getrandbits(64))
    atk_rng = random.Random(f"{seed}/{arm}/{n}/{variant}/attacker")

    victim = recode(setup, victim_row)
    honest_head = [recode(setup, r) for r in head]
    atk_field = CountingField(base)
    forged = forge(setup, variant, victim, honest_head[0], atk_rng, atk_field)

    honest_log: list = []
    arrivals = arrivals_with_injection(setup, head, forged, gen_size - 1, tail_rng, honest_log)
    outcome = run_receiver(setup, arrivals, cfg, max_packets_factor * gen_size)
    admitted, modified = injected_status(setup, outcome, forged, honest_log)
    exp_admitted, exp_silent = expected(setup, variant)
    return SpliceTrial(
        arm=arm, n=n, variant=variant, seed=seed, field_bits=field_bits, gen_size=gen_size,
        data_fields=data_fields, oracle_pass=passes_oracle(setup, forged, honest_head),
        forged_admitted=admitted, forged_modified=modified,
        decoded=outcome.decoded, correct=outcome.correct, silent=outcome.decoded and not outcome.correct,
        packets_received=outcome.packets_received,
        attacker_mul=atk_field.mul_count, attacker_add=atk_field.add_count,
        expected_admitted=exp_admitted, expected_silent=exp_silent,
    )


def run_table(seeds, field_bits=FIELD_M, gen_size=GEN_SIZE, data_fields=DATA_FIELDS,
              segmented_ns=SEGMENTED_NS, variants=VARIANTS) -> list[SpliceTrial]:
    return [run_splice_trial(arm, n, v, s, field_bits, gen_size, data_fields)
            for arm, n in cells(segmented_ns) for v in variants for s in seeds]


def summarize(trials: list[SpliceTrial]) -> list[dict]:
    """One row per (arm, n, variant): counts + the prediction + whether every trial matched."""
    groups: dict = {}
    for t in trials:
        groups.setdefault((t.arm, t.n, t.variant), []).append(t)
    rows = []
    for (arm, n, variant), ts in groups.items():
        rows.append({
            "arm": arm, "n": n, "variant": variant, "trials": len(ts),
            "oracle_pass": sum(t.oracle_pass for t in ts),
            "admitted": sum(t.forged_admitted for t in ts),
            "modified": sum(t.forged_modified for t in ts),
            "silent": sum(t.silent for t in ts),
            "clean": sum(t.decoded and t.correct for t in ts),
            "no_decode": sum(not t.decoded for t in ts),
            "atk_mul": max(t.attacker_mul for t in ts),
            "expected": "silent" if ts[0].expected_silent else ("admit" if ts[0].expected_admitted else "reject"),
            "mismatches": sum(not t.matches for t in ts),
        })
    return rows


def format_table(rows: list[dict]) -> str:
    head = (f"{'arm':<11} {'N':>2} {'variant':<7} | {'oracle':>7} {'admit':>7} {'silent':>7} "
            f"{'clean':>7} {'noDec':>6} {'atkMul':>6} | {'expected':<8} verdict")
    lines = [head, "-" * len(head)]
    for r in rows:
        k = r["trials"]
        verdict = "OK" if r["mismatches"] == 0 else f"MISMATCH x{r['mismatches']}"
        lines.append(
            f"{r['arm']:<11} {r['n']:>2} {r['variant']:<7} | {r['oracle_pass']:>3}/{k:<3} {r['admitted']:>3}/{k:<3} "
            f"{r['silent']:>3}/{k:<3} {r['clean']:>3}/{k:<3} {r['no_decode']:>6} {r['atk_mul']:>6} | "
            f"{r['expected']:<8} {verdict}")
    return "\n".join(lines)


def run_smoke(seeds=range(5), **kw) -> str:
    rows = summarize(run_table(seeds, **kw))
    m = kw.get("field_bits", FIELD_M)
    g = kw.get("gen_size", GEN_SIZE)
    d = kw.get("data_fields", DATA_FIELDS)
    text = (f"Splice/scale test (ticket 17 A)  GF(2^{m}) gen_size={g} data_fields={d} seeds={len(list(seeds))}\n"
            f"pool = gen_size-1 honest + 1 forged (victim row innovative); no channel noise\n"
            f"columns: oracle = passes every check vs honest pool (no repair); admit = in the decode basis;\n"
            f"         silent = decoded AND wrong; clean = decoded AND right; atkMul = attacker field muls\n\n"
            + format_table(rows))
    bad = sum(r["mismatches"] for r in rows)
    text += "\n\n" + ("ALL CELLS MATCH THE PREDICTION" if bad == 0 else f"{bad} TRIAL(S) DEVIATE FROM THE PREDICTION")
    return text


def write_csv(trials: list[SpliceTrial], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{**asdict(t), "matches": t.matches} for t in trials]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Ticket 17 Part A: segment splice / scale test.")
    p.add_argument("--smoke", action="store_true", help="5 seeds, readable table")
    p.add_argument("--trials", type=int, default=50, help="seeds per cell (non-smoke)")
    p.add_argument("--m", type=int, default=FIELD_M)
    p.add_argument("--gen-size", type=int, default=GEN_SIZE)
    p.add_argument("--data-fields", type=int, default=DATA_FIELDS)
    p.add_argument("--csv", default=None, help="write per-trial rows here")
    a = p.parse_args(argv)
    kw = dict(field_bits=a.m, gen_size=a.gen_size, data_fields=a.data_fields)
    if a.smoke:
        print(run_smoke(**kw))
        return
    trials = run_table(range(a.trials), **kw)
    print(format_table(summarize(trials)))
    if a.csv:
        write_csv(trials, Path(a.csv))
        print(f"\nwrote {a.csv}")


if __name__ == "__main__":
    main()
