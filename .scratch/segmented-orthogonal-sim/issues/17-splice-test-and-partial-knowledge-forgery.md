# 17 — Security: segment-splice test + partial-knowledge forgery (keyless vs keyed)

**In one line:** two attack experiments on the segmented arms, measured as silent-decode rate.
- **Part A** is a yes/no check: can an attacker splice or scale segments to get a packet past both schemes with no key and almost no work?
- **Part B** is the main security figure: silent-decode rate vs attacker knowledge. Keyless: the attacker has *observed* r packets. Keyed: *k keys have leaked*. Both are put on one axis, u (see Part B).

Plan and background: [docs/plans/security-analysis-plan.md](../../../docs/plans/security-analysis-plan.md) (attacks A3 + A5).

## Decisions (2026-09-23)
- **Keys are per generation.** A fresh keyset for every generation (what `generate_keyset` already does per trial).
  - So cross-generation replay (A2) and multi-generation blast radius (A8) are **out of scope**. A leaked key only ever affects its own generation.
- **Arms:** keyless = `SegmentedScheme`, keyed = `SegmentedMacScheme` (both `coefficient_first`; the strategy doesn't matter with no noise).
- **Attack the production admit path.** Call `scheme.admit(instrument, pool, gen_size, cfg)`, not `segmented_attack_sim.py`'s absolute-count stand-in `_orth_segment_trusted`.
  - Keyless then runs greedy-peel + `verify_count` (`classify_segment_trust`).
  - Keyed runs `classify_segment_trust_mac` (all `num_keys = gen_size` tags).
- **No channel noise (BER = 0).** Isolates forgery. Interplay with noise is future work.
- **Success = silent decode**: forged packet admitted AND decode ≠ ground truth (ADR-0008), graded with `_try_decode`. Also record `forged_admitted` on its own.
- **`AdmitConfig(min_pool_size=gen_size)`**, everything else default. Log the cfg in the CSV. The receiver tries to decode as soon as it holds gen_size packets; without this the `min_pool_size=10` artifact shifts u.

## Part A — segment-splice / scale test (do first)

**Hypothesis (analytic, unverified):**
- Both arms verify each segment **independently**, and both tags are linear per segment (homomorphic).
- So a packet whose segments each come from a *different* honest linear combination passes every check.
- Its coefficients don't match its data, so the decode is wrong.
- No key and no solve are needed. The attacker only needs 1–2 intercepted honest packets.
- N=1 (one tag over `[coeff|data]`) should be immune.

**Forged variants.** The victim V is a fresh honest packet the relay intercepts. The receiver never sees the original, so V's coeff row is innovative for the receiver.
1. **splice:** V's coeff segment + data segments of another honest packet O. Take each segment's full slice (payload + salt + tags, or payload + tags).
2. **scale:** V with one data segment's full slice multiplied by α ∉ {0,1}.
3. **zero:** V with every data segment's full slice set to 0. The zero vector is self/cross-orthogonal, and its MAC is 0.

**Cells:**
- both arms × N ∈ {2,3,5} × 3 variants, m=8, gen_size=4, data_fields=12, ~50 seeds each.
- Receiver pool = gen_size−1 honest recoded packets + the forged packet.
- **N=1 controls:**
  - keyless `OrthogonalScheme`: splice/scale only the data columns of a whole-packet-tagged packet.
  - keyed: a whole-packet homomorphic MAC built in the test with `mac_tag_vector` over `[coeff|data]`, same variants.
  - Expect rejection, except with probability ≈ q^-u.

**Build:** `simulation/splice_attack_test.py`. It runs itself via `__main__` (no pytest). It asserts, and prints a readable table: `arm | N | variant | admitted k/n | silent k/n`.
- Reuse `_splice_segment` from `segmented_attack_sim.py`.
- Reuse the generation build via `scheme.make_source` / `new_instrument`.
- Honest arrivals via `recode_rlnc_without_coeffs`.

**Gate after Part A.** Record the result and STOP for a user decision. Don't implement a fix here.
- If confirmed: note in ADR-0008 (addendum) that ticket 06's "MAC key secret → 0" holds only against the naive forger. Candidate fix, both arms: bind the coefficients into every segment's tagged input. The user decides: fix vs report as a limitation.
- If refuted: write down *which* check catches it. That is a finding too.

## Part B — partial-knowledge forgery (main figure)

**Forger: one forged packet, splice-free by construction.** This measures the tag's strength, not the splice.
- Copy the victim V (its data segments stay genuine and verify for free).
- Replace only the coeff segment with a coefficient row c' **outside the attacker's observed coefficient span** (`_independent_coeff_row`, avoid = observed rows).
- Same c' in both arms per seed (paired seeds).

**Knowledge, the one axis that differs:**
- **Keyless:** the attacker observed the first r honest packets the receiver got. Arrival schedule:
  - honest #0..r−1 (observed)
  - forged packet at index r (replaces the intercepted V)
  - unobserved honest packets after that
  - The coeff-segment tags come from `pollute_intelligent` over the r observed coeff slices (`data_length=1` = salt, threshold=r). Randomize free tag variables, don't zero them.
  - r ∈ {0 … gen_size−1}.
- **Keyed:** the attacker holds k of the coeff segment's gen_size key vectors (read from `instrument.keyset[0]`). Tags for known keys are exact; unknown tags are uniform random.
  - k ∈ {0 … gen_size}.
  - Same arrival schedule. For keyed the strike index should not matter; check this in one extra cell.

**Normalized axis: u = verification constraints the attacker cannot compute.**
- keyed: u = gen_size − k (all tags are verified).
- keyless: u = gen_size − 1 − r. At the first decode attempt the pool = gen_size, so the receiver holds gen_size−1 honest witnesses, and the self-check is free.
- Theory (**write before running**): P(admitted) ≈ q^-u for both. P(silent) ≈ q^-u · P(c' innovative for the receiver) ≈ q^-u·(1−1/q). The innovation factor matters at small q; same seeds → same factor in both arms.
- **Expected deviation to watch (a finding, not a bug to silently fix):** the keyless greedy-peel tie-break. `max` over the alive set peels the first maximal index, so a forger that disagrees with exactly 1 honest packet may survive depending on arrival order. Report measured vs theory per u.

**Cells:**
- gen_size=4, data_fields=12, N=2 (plus one N=5 spot check; ticket 06: forgery is flat in N).
- m ∈ {2, 4} measured, ~4000 trials/cell; m=8 theory only.
  - GF(2^8) rates are unmeasurable (u=2 → 1.5e-5).
  - If GF(2^2) segmented tagging gives up too often (salt, ADR-0010), use m=3.

**Build:**
- `simulation/knowledge_attack_sim.py` with `--smoke` (1 seed, readable per-trial lines) and `--sweep`. Frozen CSV schema in the module header, one row per trial: `arm, m, N, gen_size, r_or_k, u, forged_admitted, decoded, correct, silent, attacker_mul, seed, cfg…`.
- Replot script `scripts/knowledge_attack_plots_from_csv.py` (pools CSVs, same pattern as `recovery_plots_from_csv.py`).

**Figures:**
- **F2 (main):** silent-decode rate (and forged-admitted rate) vs u.
  - One line per arm.
  - Markers = measured with Wilson 95% CI; zero counts drawn as the rule-of-3 upper bound.
  - Dashed = theory q^-u per m; m=8 theory line only.
  - Secondary tick labels: keyless r / keyed k.
- **F6 (secondary):** attacker field-muls per forgery vs u (keyless solve cost; keyed ≈ k·payload muls).

**Interpretation to state (don't overclaim):**
- At equal u, both arms should give ≈ equal security.
- The difference is the *price* of a knowledge unit:
  - keyless: passive observation, free for an on-path node;
  - keyed: node compromise / key leak.
- Say this in the text; the figure can't show it.

## Blocked by
— (ticket 06 done; production arms exist). Part B does not depend on Part A's outcome (its forger is splice-free), but finish A first because it changes how B is framed.

## Status
DONE 2026-09-23 (branch `feat/security-sim`, worktree `.claude/worktrees/security-sim`). **Part A gate open:** the splice hypothesis is CONFIRMED. Fix vs limitation is the user's call. Nothing fixed.

## Done when
- [x] **A:** `splice_attack_test.py` runs all variants × arms × N plus the N=1 controls through production `admit`, prints the table, and asserts the observed outcome.
- [x] **A:** result recorded (ADR-0008 addendum staged in `../ticket17-docs-addenda.md`; docs/ is gitignored, paste from the main checkout). Confirmed, so the fix-vs-limitation decision goes to the user. No fix implemented.
- [x] **B:** theory lines written down before the sweep (q^-u, in the `knowledge_attack_sim.py` docstring).
- [x] **B:** `knowledge_attack_sim.py` `--smoke` readable. `--sweep` writes the frozen-schema CSV. Paired seeds across arms (same data, same honest coeffs, same c').
- [x] **B:** sweep at m ∈ {2,4} done. F2 + F6 plotted from CSV. Measured vs theory checked per u. The tie-break deviation is explained; so is the keyed repair deviation (new, see results). The innovation factor is removed by forcing c' innovative.
- [x] Sanity: u=0 → silent = 1.0 in both arms (innovation forced, so P(innov) = 1). Keyed k=0 at m=4 → 0/4000.
- [x] Short results note in the plan doc (§ results) + memory update.

## Deviations from the build notes above
- Generations are built from a shared, seeded source, and honest packets are recoded with EXPLICIT coefficient rows, instead of `make_source` / `recode_rlnc_without_coeffs` (both draw from the global RNG). This is what makes the seeds truly paired across arms.
- The keyless forger is its own solve, not `pollute_intelligent`: that one zeroes the free variables and fixes the salt. Here the salt + tags are the unknowns, and the free variables are randomised.
- c' is forced innovative against the receiver's honest head (the attacker's best case), so silent == admitted and the (1−1/q) innovation factor drops out.
- Added a repair-Hamming-distance knob (`--hds`, 0 = repair off) once the keyed repair effect showed up.

## Files
- `simulation/attack_harness.py`: shared plumbing (paired source, recode by explicit rows, production admit, receiver, strict oracle). Tests: `attack_harness_test.py` (9).
- `simulation/splice_attack_sim.py` (`--smoke`, `--trials N --csv`). Tests: `splice_attack_test.py` (10).
- `simulation/knowledge_attack_sim.py` (`--smoke`, `--sweep`, `--hds 0,1`, `--ns`). Frozen CSV schema v1 in its header. Tests: `knowledge_attack_test.py` (17, ~5 min).
- `scripts/knowledge_attack_plots_from_csv.py`: pools run dirs → `summary.csv` plus 4 PNGs.
- Runs (worktree `logs/`, gitignored):
  - `splice_attack/table_m8_g4_t50.csv`
  - `knowledge_attack/main_g4_n2_t4000/` (m ∈ {2,4}, hd ∈ {0,1}, early/late, 4000 paired seeds/cell)
  - `knowledge_attack/spot_g4_n5_t2000/`
  - pooled plots: `knowledge_attack_plots/`

## Results (gen_size 4, data 12, no channel noise)

**Part A: hypothesis CONFIRMED.** 50 seeds × 48 cells, GF(2^8). Every cell matches the prediction; also holds at GF(2^2) and GF(2^4).
- Both segmented arms (keyless AND keyed, N ∈ {2,3,5}):
  - splice, scale and zero → admitted + silent decode **50/50**.
  - 0 field muls (scale: 1 mul per byte). No key or source needed (the test proves it with the keys removed).
- N=1 controls (whole-packet tag, both arms) reject every variant, and the generation still decodes correctly from honest packets.
- Sanity: an unmodified victim decodes correctly; a random modification is rejected (the oracles work).
- Bonus, keyless only:
  - In char 2 the self-check is linear: it is orthogonality to the all-ones vector.
  - So β·1 is a zero-knowledge valid segment iff the segment length is even.
  - It passes on N=5 (slice length 8) and fails on N=2/3 (odd lengths). Parity rule tested.
- **Consequence:** ticket 06's "MAC key secret → silent 0" holds only against its naive forger. Segmentation removes the binding between coefficients and data in BOTH arms.
- Candidate fix: bind the coefficients into every segment's tagged input. User decision pending.

**Part B: strict oracle = q^-u in both arms, as predicted.** Examples (4000 seeds):
- GF(2^2), u=1: keyless 0.256, keyed 0.247 (q^-u = 0.25).
- GF(2^4), u=2: keyless 0.0050, keyed 0.0040 (q^-u = 0.0039).
- u=0 → 1.0.
- Keyless early strike: production admit == strict oracle, per trial.

The production receiver adds two effects nobody predicted. Both are measured, explained and pinned by tests:
1. **Keyed repair amplification (new finding).**
   - A forgery with a wrong guessed tag is "broken".
   - The coeff-segment repair then bit-flips over payload AND tags (HD=1) and corrects a guessed tag that is 1 bit off.
   - Admit rate ≈ q^-u·(1+u·m) + payload-flip term:

     | field | u | admit hd=1 | theory | admit hd=0 (repair off) |
     |---|---|---|---|---|
     | GF(2^2) | 1 | 0.759 | 0.758 | 0.247 |
     | GF(2^4) | 1 | 0.314 | 0.313 | 0.065 |
     | GF(2^4) | 3 | 0.0040 | 0.0034 | 0.0005 |

   - hd=0 control: admit == oracle.
   - The keyless forger always self-passes, so it never enters repair. A keyless "repair-bait" forger is untested (plan A11).
2. **Keyless late-strike tie-break (greedy peel).**
   - The peel breaks a disagreement tie by peeling the LOWER index.
   - A late forger that disagrees with exactly 1 honest packet survives when the next arrival agrees with it.
   - First-order theory: q^-u·(1+u(1−1/q)²).

     | field | u | late | theory | early |
     |---|---|---|---|---|
     | GF(2^2) | 1 | 0.366 | 0.391 | 0.256 |
     | GF(2^4) | 1 | 0.116 | 0.117 | 0.068 |

   - Per trial, late ⊇ early. The keyed arm is order-independent (early == late).

**Other results**
- Attacker work (mean muls):
  - keyless solve 11 → 123 as r grows 0 → 3 (GF(2^4));
  - keyed exactly k·g.
- N=5 spot check: same curves (forgery flat in N).
- Interpretation: at equal u, the two tags are equally strong (both q^-u).
  - In production the keyed arm is WEAKER at equal u, because of its repair.
  - The keyless weakness is the price of knowledge: observation is free for an on-path node, while a keyed attacker must compromise a key.
- Engineering fixes found in the first sweep:
  - keyless forger: the salt is now an unknown (fixed salt caused 26/4000 forge failures at u=0);
  - plot: Wilson error bars clamped at rate 1.
