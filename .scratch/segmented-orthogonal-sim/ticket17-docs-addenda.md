# Ticket 17: text to paste into the gitignored docs

`docs/` is gitignored and lives only in the main checkout. The worktree session could not
write there, so both addenda are staged here.

---

## → append to `docs/adr/0008-intelligent-pollution-attacker-model.md`

## Addendum 2026-09-23 (ticket 17): segment splice + partial knowledge

Branch `feat/security-sim`. Code: `simulation/{attack_harness,splice_attack_sim,knowledge_attack_sim}.py`
plus tests. Keys are per generation (user decision), so replay and blast-radius attacks are out
of scope. Both attacks run through the PRODUCTION admit path (`SegmentedScheme.admit` /
`SegmentedMacScheme.admit`), not ticket 06's absolute-count stand-in.

**1. Segment splice: the "MAC key secret → silent 0" result above holds only against ticket
06's naive forger.**
- Both segmented arms verify each segment independently, and both tags are linear per
  segment. So a packet built from segments of DIFFERENT honest combinations passes every
  check: coeff segment of V + data segments of O, one data segment scaled by α, or all data
  segments zeroed.
- Its coefficients no longer match its data, so the decode is wrong.
- Measured: 50/50 silent decodes in both arms for N ∈ {2,3,5} and m ∈ {2,4,8}. Zero field
  muls, and no key or source needed.
- The N=1 whole-packet tag rejects all of them (both arms).
- So segmentation removes the coefficient↔data binding in BOTH schemes. Candidate fix: bind
  the coefficients into every segment's tagged input.
- Fix vs report-as-limitation: **open, user decision.**

Keyless bonus: in char 2, <v,v> = (Σv)², so the self-check is orthogonality to the all-ones
vector. β·1 is therefore a zero-knowledge valid segment whenever the segment length is even.

**2. Partial knowledge (splice-free forger, one packet, c' forced innovative).**
- Axis u = constraints the attacker cannot compute:
  - keyless: r observed packets, u = g−1−r;
  - keyed: k leaked keys, u = g−k.
- The strict oracle gives q^-u in BOTH arms (4000 paired seeds/cell, GF(2^2) and GF(2^4)):
  **at equal knowledge the two tags are equally strong.**
- The production receiver adds two effects:
  - **Keyed repair amplification.** The coeff-segment repair bit-flips over payload + tags
    and "fixes" a guessed tag that is one bit off. Admit rate ≈ q^-u(1+u·m) + payload term.
    Examples: 0.76 vs 0.25 at GF(2^2), u=1; 0.31 vs 0.065 at GF(2^4), u=1. With hd=0 it
    equals the oracle.
  - **Keyless greedy-peel tie-break.** A LATE forger that disagrees with exactly one honest
    packet survives, because the peel removes the lower index. Admit ≈ q^-u(1+u(1−1/q)²),
    e.g. 0.12 vs 0.068 at GF(2^4), u=1.
- Headline for the thesis:
  - equal tag strength per unknown constraint;
  - the keyed production path is weaker at equal u (its repair);
  - the keyless weakness is the price of knowledge: observation is free on-path, while a
    keyed attacker needs a key compromise;
  - the splice attack breaks both segmented arms until they are bound.

---

## → insert under "Decisions 2026-09-23" in `docs/plans/security-analysis-plan.md`

**Results 2026-09-23 (ticket 17 done, branch `feat/security-sim`; details in the ticket and the ADR-0008 addendum):**
- **A3 splice: CONFIRMED.** Both segmented arms (keyless AND keyed): splice/scale/zero give 100% silent decodes, 0 field muls, no key needed. N=1 is immune.
  - Ticket 06's "keyed-secret = 0" holds only against the naive forger.
  - Fix (bind the coefficients into every segment) vs limitation: **decision open.**
- **A5 partial knowledge:** strict oracle = q^-u in both arms. Equal tag strength at equal u.
- The production receiver adds two effects:
  - keyed repair amplification: the HD-1 repair corrects guessed tags, ≈ q^-u(1+u·m);
  - keyless late-strike peel tie-break: ≈ q^-u(1+u(1−1/q)²).
- Plots: worktree `logs/knowledge_attack_plots/` (`silent_vs_u`, `oracle_vs_u`, `repair_effect_keyed`, `attacker_work_vs_u`).
- New follow-up candidate: **A11 "repair-bait" keyless forger**. It deliberately fails the self-check so that the keyless repair runs; untested. It is the fair counterpart to the keyed repair effect.
