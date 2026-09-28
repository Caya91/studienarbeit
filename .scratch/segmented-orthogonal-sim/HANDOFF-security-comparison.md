# HANDOFF: security comparison, keyless vs keyed (after ticket 17)

Written 2026-09-24.

**Next goal:**
1. Dig deeper into the keyless-vs-keyed security comparison.
2. Find figures that show the difference CLEARLY for the thesis and the talk.

## Where things are
- **Code:** worktree `E:\projects\studienarbeit\.claude\worktrees\security-sim`, branch `feat/security-sim`.
  - NOT committed. Commit only when the user asks.
- **Run** (the user uses PowerShell only; there is no venv in the worktree):
  ```
  $env:LOG_FOLDER="./logs"; $env:PYTHONPATH="."; $py="E:/projects/studienarbeit/.venv/Scripts/python.exe"
  ```
- **Scheme names:**
  - keyless = `SegmentedScheme` (per-segment orthogonal self+cross tags + 1 salt per segment);
  - keyed = `SegmentedMacScheme` (per-segment homomorphic MAC, gen_size keys per segment);
  - both do combined recovery.
  - N = segments per packet (1 coefficient segment + N-1 data segments).
- **Keys are per generation** (user decision), so replay and multi-generation attacks are out of scope.
- **`docs/` is gitignored** and lives in the main checkout only. An agent inside the worktree cannot write there. The ADR-0008 addendum and the plan results are staged in `ticket17-docs-addenda.md` for the user to paste.
- **Read first:**
  - `issues/17-splice-test-and-partial-knowledge-forgery.md`: results, files, deviations;
  - `ticket17-tests-and-plots.md`: what each test and plot proves, plus the replot commands;
  - main checkout `docs/plans/security-analysis-plan.md`: the full attack catalogue A1–A11.

## Findings that matter
1. **Splice attack breaks BOTH segmented schemes** (Part A, deterministic).
   - Each segment is verified independently and each tag is linear per segment. So combining segments from different honest packets, scaling one segment, or zeroing the data segments passes every check.
   - Result: 100% silent decodes, 0 field multiplies, no key needed, every N, every field.
   - N=1 (one tag over the whole packet) is immune.
   - This overturns ticket 06's "keyed with secret key → 0 silent decodes" (that forger was naive).
   - **Open user decision:** fix it (bind the coefficients into every segment's tagged input, in both schemes) or report it as a limitation.
   - Side result: in char 2 the keyless self-check is orthogonality to the all-ones vector, so β·1 is a zero-knowledge valid segment whenever the segment length is even.
2. **Pure tag strength is equal** (Part B).
   - The strict tag-check pass rate is q^-u in both schemes.
   - u = constraints the attacker cannot compute: keyless u = g−1−r (r observed packets), keyed u = g−k (k leaked keys).
   - 4000 paired seeds per point, GF(2^2) and GF(2^4). Examples: u=1 GF(4) 0.256 vs 0.247 (theory 0.25); u=2 GF(16) 0.0050 vs 0.0040 (theory 0.0039).
3. **Keyed repair helps the forger** (production receiver, found unexpectedly).
   - A forged packet whose guessed MAC tag is wrong counts as "broken".
   - The coefficient-segment repair bit-flips over payload AND tags (HD=1) and turns a tag guess that is one bit off into a valid-but-wrong packet.
   - Admit rate ≈ q^-u(1+u·m) + payload term. Examples at u=1: 0.76 vs 0.25 (GF4); 0.31 vs 0.065 (GF16).
   - With repair off (hd=0), admit = tag check.
   - **So in production, keyed is WEAKER than keyless at equal knowledge.**
4. **Keyless late-strike tie-break.**
   - The greedy-peel trust rule removes the LOWER pool index on a tie.
   - So a forger injected late that disagrees with exactly one honest packet can survive.
   - ≈ q^-u(1+u(1−1/q)²). Example: 0.116 vs 0.068 (GF16, u=1).
   - A strike right after the observed packets gives exactly q^-u (production admit = tag check, trial by trial).
5. **Framing for the thesis:**
   - equal tag strength per unknown constraint;
   - the keyless weakness is the PRICE of knowledge: observing packets is free for an on-path node, while a keyed attacker needs a key compromise;
   - the keyed production path gets amplified by its own repair;
   - the splice attack breaks both segmented schemes until they are bound.
   - Attacker work is tiny in both (≤ ~120 multiplies), so work is not the barrier; knowledge is.

## Method conventions (keep them when extending)
- **Success = silent decode:** forged packet admitted AND the decode is wrong, graded against ground truth. Always attack the PRODUCTION `scheme.admit`, not ticket 06's stand-in trust rule.
- **Paired seeds:** the seed fixes data, honest coefficient rows, victim and c' in both schemes. Honest packets are recoded from EXPLICIT coefficient rows; `recode_rlnc_without_coeffs` uses the global RNG, so don't use it.
- **c' is forced innovative** (outside the receiver's honest span), so silent = admitted. This is the attacker's best case; a real attacker loses about 1/q of attempts.
- **Report two numbers:** the strict tag-check rate (tag strength, theory q^-u) and the production admit/silent rate (tag + receiver side effects).
- **Rare events:** measure at GF(2^2) and GF(2^4) and extrapolate GF(2^8) analytically. Wilson 95% intervals; 0 events → plot at the 3/n bound (hollow ▽). Pool runs by summing counts, never by averaging rates.
- **Receiver config:** `AdmitConfig(min_pool_size=gen_size)`, everything else production default (verify_count 4, min_trust_count 4, hamming_distance 1); hd is sweepable via `--hds`.

## Code and data (all in the worktree)
**Code**
- `simulation/attack_harness.py`: paired source (`paired_setup`), `recode`, production `admit_codes`, `run_receiver`, strict `passes_oracle`, `injected_status`.
- `simulation/splice_attack_sim.py`: Part A table (`--smoke`, `--trials N --csv`).
- `simulation/knowledge_attack_sim.py`: Part B.
  - Forgers: `forge_coeff_keyless` (salt + tags solved, free values random), `forge_coeff_keyed`.
  - Theory: `theory_pass`, `theory_keyed_repair`, `theory_keyless_late`.
  - `summarize`; frozen CSV schema v1 in the file header.
  - Command line: `--sweep --trials --ms --ns --hds --strikes --seed-start --workers --out`.
- `scripts/knowledge_attack_plots_from_csv.py`: `load()` → summary rows; `plot_silent`, `plot_oracle`, `plot_repair_effect`, `plot_attacker_work`, `plot_all`. The command line pools `--runs` globs.
- **Tests** (36, all green; run each file with `& $py <file>`, exit 0 = pass): `attack_harness_test.py`, `splice_attack_test.py`, `knowledge_attack_test.py` (~5 min).
  - They pin: pairing, the forger constraints, the u=0 and maximum-u end points, tag check vs q^-u, both production effects BY MECHANISM, invariants, schema.

**Data** (gitignored `logs/`)
- `knowledge_attack/main_g4_n2_t4000/`: GF(2^2) and GF(2^4), hd {0,1}, early/late, 4000 seeds per point.
- `knowledge_attack/spot_g4_n5_t2000/`: N=5 spot check.
- `knowledge_attack_plots/`: pooled `summary.csv` plus 4 PNGs.
- `splice_attack/table_m8_g4_t50.csv`.
- Setup: gen_size g=4, data_fields=12, N=2 unless stated, no channel noise.

## Current figures and their weaknesses (the presentation task)
- `silent_vs_u.png` (main figure): the content is right but it is too busy.
  - It carries 4 measured series, 4 theory lines and a GF(2^8) line in one panel.
  - The early/late strike distinction competes with the keyless/keyed message.
- `oracle_vs_u.png`: the clean "equal strength" message, but it looks almost identical to the main figure.
- `repair_effect_keyed.png`: clear; a good standalone figure.
- `attacker_work_vs_u.png`: low value; probably a table or a single sentence instead.
- Part A has NO figure yet, only a table. It is the most striking result (100% vs 0%) and deserves a visual: for example keyless/keyed × N=1/segmented × variant as a heatmap or bars, or a packet diagram of the splice.
- Ideas to evaluate:
  - one message per figure;
  - a "security matrix" summary (attacks × schemes → silent rate);
  - put GF(2^8) consequences into a small analytic table instead of a line;
  - "cost of one unit of knowledge" framing (observe a packet vs compromise a key) as a text or table next to the curve.
- **Style:**
  - arm colours used across the thesis plots: keyless `#588157`, keyed `#3d405b`;
  - use secondary encoding (marker fill, line style), keep theory lines gray;
  - thesis slide deck: `C:\Users\marti\OneDrive\studienarbeit_docs\presentation\STYLEGUIDE.md` (TUD palette, fixed colour meanings: red = attack/mismatch, green = tag ok).

## Open questions / worthwhile next steps
1. **Keyless "repair-bait" forger (plan A11).** It deliberately fails the self-check so that the keyless repair runs. Untested. It is the FAIR counterpart to finding 3; without it, "keyed weaker in production" is one-sided.
2. **Keyed repair at hd ≥ 2.** Older sweeps used HD=2; not modelled yet (`theory_keyed_repair` returns nan).
3. **Robustness:** larger gen_size (6–10), channel noise combined with forgery, keyless witness choice (currently the FIRST `verify_count` core members, so an attacker knows them in advance; random witnesses would be a cheap hardening).
4. **If the user picks the splice fix:** re-run Part A (expect 0%) and Part B on the bound schemes.

## User preferences
- Very concise reports; PowerShell only; ask questions in plain prose (no multiple-choice tools).
- Correctness before optimisation: defer known performance costs explicitly, never silently.
- Local tickets in `.scratch/…/issues/NN-slug.md`.
- Don't commit or push unless asked.
