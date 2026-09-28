# Ticket 17: what the tests check, what the plots show

Branch `feat/security-sim`, written 2026-09-24. Companion to
`issues/17-splice-test-and-partial-knowledge-forgery.md` (results) and `ticket17-docs-addenda.md`
(ADR text).

The tests are layered:
1. the plumbing is correct;
2. the attacks do what they claim;
3. the measured rates match theory.

The plots show rates against theory.

## Tests

Run any file on its own (exit 0 = pass), PowerShell, main .venv, from the repo/worktree root:
```
$env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" simulation/attack_harness_test.py
```
Same for `simulation/splice_attack_test.py` and `simulation/knowledge_attack_test.py` (~5 min).

### 1. `attack_harness_test.py`: plumbing (9 tests)
If this layer were wrong, every attack number built on it would be meaningless.

| Test | Checks | Why it matters |
|---|---|---|
| pairing | Same seed gives the same data rows and the same random stream in keyless and keyed (96 combinations of field, N and seed) | "Paired" comparison is real: differences between the schemes come from the scheme, not from luck |
| honest recodes | Each recoded packet's coefficients are exactly the requested row; its data is exactly that combination of the source (computed independently); it passes the tag check in all 4 schemes and 3 fields | No bad packet appears by accident, so any bad packet in the results came from the attacker |
| honest-only receiver | 144 runs with no attacker: all decode correctly, 0 silent decodes, 0 timeouts | The false-alarm baseline is 0, so any silent decode later is caused by the attack |
| oracle rejects corruption | Changing a single byte in any region is rejected by every scheme (GF(2^8)) | The strict tag check is not trivially passing |
| bookkeeping | The injected packet lands at the right position; "admitted" and "modified by repair" are told apart correctly | The admitted/modified columns in the CSV are trustworthy |
| config | Only `min_pool_size` differs from the production defaults | We attack the real receiver, not a softened one |

### 2. `splice_attack_test.py`: Part A (10 tests)

| Test | Checks | Significance |
|---|---|---|
| full table | 48 cells (scheme × N × variant) match the prediction exactly | The headline: splice, scale and zero always give silent decodes on segmented schemes and never on N=1 |
| sanity / negative control | An unmodified victim decodes correctly; a random change is rejected and the decode still succeeds | Rules out "the receiver accepts anything": the checks work, and only the splice structure gets through |
| mechanism | Every forged segment passes its check on its own, the coefficients are the victim's, and the data is inconsistent with them | Shows WHY it works: each segment is valid, but they don't belong together |
| no key, no work | The forgery comes out byte-identical with the keys and source removed; multiply count is 0 (scale: 1 per byte) | Proves the attack needs no secret; this overturns ticket 06's secret-key result |
| field-size independence | Still 100% at GF(2^2) and GF(2^4) | Not a lucky collision: it holds with probability 1, not q^-u |
| all-ones parity rule | 7 layouts: keyless accepts β·1 exactly when every data slice has even length; keyed always rejects | Confirms the theory claim that the keyless self-check equals orthogonality to the all-ones vector |
| N=1 recovery | Controls reject the forgery and still decode correctly from honest packets | The fix direction (binding coefficients and data) is sound |
| determinism / smoke / CSV | Reproducible, readable output, correct columns | Results can be re-run and audited |

### 3. `knowledge_attack_test.py`: Part B (17 tests)

**a. Setup validity**
- **Paired and innovative plan:** both schemes get the same forged coefficient row c'. It always adds new rank at the receiver and differs from the victim's row. This removes the innovation factor, so silent equals admitted.
- **Keyless forger constraints:** the forged coefficient segment passes the self-check and is orthogonal to every observed packet. The free tag values are random, not zero (a zero bias would distort q^-u).
- **Keyed forger:** tags for leaked keys are exact. Guessed tags hit the true MAC at 0.233, against the expected 1/q = 0.25. This confirms the guessing model.

**b. End points, where the answer is known exactly**
- u=0 (full knowledge) gives a silent decode 100% of the time in both schemes, all fields, both strike times.
- Maximum u at GF(2^8) gives 0 of 40 silent decodes.
- Regression test for u=0: 1500 of 1500 forgeries succeed. This catches the old fixed-salt bug, which failed 26 of 4000.

**c. Theory agreement (the core scientific claim)**
- Tag-check pass rate is within 4.5 standard errors of q^-u for both schemes at GF(2^2) and GF(2^4), over all u.
  - Significance: equal tag strength per unknown constraint, now MEASURED and not just asserted.
- Keyless early strike: the real receiver's decision equals the strict tag check for all 1000 trials, one by one.
  - Significance: the production trust rule adds nothing beyond the tag here, and silent decodes are exactly the tag-check passes.

**d. The two unexpected effects, pinned**
- **Keyed repair:**
  - With repair off (hd=0), admitted equals the tag check in every trial.
  - With repair on, admitted is always at least the tag check, and the rate matches the formula.
  - Every extra admit with unchanged coefficients came from a guessed tag exactly one bit off.
  - This proves the MECHANISM (the receiver corrects the forger's guess), not just a correlation.
- **Late strike:**
  - Same forged packet in both strikes; late admits everything early admits.
  - Every late-only admit failed the tag check, so it got in through the tie-break.
  - The rate matches the first-order formula, and the keyed scheme is identical per trial for early and late.

**e. Consistency and format**
- **Attacker work:** keyed uses exactly k·g multiplies; keyless work grows with r.
- **Batch invariants:** 900 trials with no timeouts, a silent decode never without an admitted forgery, and every decode without a forgery is correct.
- **N=5 spot check:** same curves (forgery difficulty does not depend on N).
- **Theory functions:** return known values and never exceed 1.
- **Output:** the CSV matches the frozen schema; summary, plots, replot and `load()` all work.

## Plots (`logs/knowledge_attack_plots/`)

| Plot | Shows | How to read it | Significance |
|---|---|---|---|
| `silent_vs_u.png` (main figure) | Silent-decode rate vs u, one panel per field; solid = early strike, dashed/hollow = late; keyless green, keyed dark | Log y-axis. Dashed gray = q^-u, dotted = the two corrected formulas, faint gray = GF(2^8) extrapolation. Hollow ▽ = 0 events drawn at the 3/n upper bound | The thesis figure. Keyless early follows q^-u; keyed sits well above it because of repair; keyless late sits slightly above because of the tie-break |
| `oracle_vs_u.png` | Tag-check pass rate only (no receiver) | Both schemes fall on q^-u | The clean equal-strength result, free of production side effects |
| `repair_effect_keyed.png` | Keyed admit rate, repair off (hd=0) vs on (hd=1) | The gap between the two lines is the receiver helping the attacker | Isolates the keyed weakness; hd=0 matches theory, so the effect is caused by the repair |
| `attacker_work_vs_u.png` | Attacker multiplies per forgery | Keyless grows with knowledge (a larger system to solve), keyed = k·g | Both costs are tiny (≤ ~120 multiplies), so work is not a security barrier; knowledge is |

Part A has no figure. Its result is a yes/no table (`simulation/splice_attack_sim.py --smoke` or
`--trials 50 --csv <path>`); the 50-seed run is in `logs/splice_attack/table_m8_g4_t50.csv`.

## Regenerating the plots from CSV (no re-simulation)

`scripts/knowledge_attack_plots_from_csv.py` pools any number of sweep run dirs (each holds a
`raw_trials.csv`). It recomputes counts, rates and Wilson CIs on the union and writes
`summary.csv` + the 4 PNGs.

**Everything at once (CLI):**
```
$env:LOG_FOLDER="./logs"; $env:PYTHONPATH="."; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" scripts/knowledge_attack_plots_from_csv.py --runs "logs/knowledge_attack/*" --out logs/knowledge_attack_plots
```

**One plot at a time (Python):**
```python
from scripts.knowledge_attack_plots_from_csv import load, plot_silent, plot_oracle, plot_repair_effect, plot_attacker_work
s = load()                                                    # all runs under logs/knowledge_attack/*, N=2
s = load(["logs/knowledge_attack/main_g4_n2_t4000"], n=2)     # or specific run dir(s) / N
plot_silent(s, "logs/knowledge_attack_plots")                 # -> silent_vs_u.png
plot_oracle(s, "logs/knowledge_attack_plots")                 # -> oracle_vs_u.png
plot_repair_effect(s, "logs/knowledge_attack_plots")          # -> repair_effect_keyed.png (None if no hd=0 cells)
plot_attacker_work(s, "logs/knowledge_attack_plots")          # -> attacker_work_vs_u.png
```

**Functions:**
- `discover(globs)` → paths of `raw_trials.csv`.
- `load_rows(paths)` → trial rows. Skips files whose header ≠ the frozen schema.
- `summarize(rows)` (in the sim) → per-cell summary.
- `load(runs, n)` = discover + load_rows + summarize + pick one N.
- `plot_all(paths, out_dir)` = summary.csv + all plots.

**Pooling rule:** adding more runs (new seeds via `--seed-start`) just adds trials to the same
cells. Rates are recomputed from summed counts, never averaged.

**New data:**
```
simulation/knowledge_attack_sim.py --sweep --trials 4000 --ms 2,4 --hds 0,1 --workers 6 --out logs/knowledge_attack/<name>
```
Add `--ns 5` for other N (the plots show N=2; `summary.csv` keeps every N).

## Not covered (limits)
- **No channel noise.** Forgery and repair together with real bit errors is untested.
- **Small generations.** Only gen_size 4 was run. The formulas should carry over, but that is not measured.
- **GF(2^8) is extrapolated.** Its rates are too small to measure, so GF(2^8) is theory only; the formulas are checked at small fields.
- **Late and repair formulas are first-order.** Deviations of about 2–3 standard errors are accepted, not modelled exactly.
- **Repair distance.** Only hd ∈ {0,1} was run; hd ≥ 2 (used in the older sweeps) is not modelled.
- **Keyless repair-bait attacker.** A forger that deliberately fails the keyless self-check to trigger repair is untested, so the keyed repair effect has no keyless counterpart measured yet.
- **Coefficient row always innovative.** A realistic attacker loses about 1/q of attempts to rank; this sets the attacker to its best case.
