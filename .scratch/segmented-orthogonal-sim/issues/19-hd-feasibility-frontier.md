# 19 — Hamming-distance feasibility frontier: how far can repair be pushed?

**In one line:** sweep the bit-flip search depth (`max_combined_hd`) and find where extra recovery
stops being worth its cost — in ops/time and in silent decodes — for both arms.
[ADR-0013](../../../docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md).

**Why:** at HD=2, every target with ≥3 flipped bits in one segment fails (ACR-only (a), BER 1e-2:
72/126 failures), and pair search fails some ≤2-flip targets when many broken packets share a
segment. Raising HD recovers these, but the candidate count grows combinatorially (≈ C(cols·8, HD))
and every extra candidate is another chance for a wrong accept (~q⁻ᵂ keyed, ~q⁻⁽ᵂ⁺¹⁾ keyless).
The thesis needs the tradeoff curve, not a single HD.

## Questions
1. Recovery gain per HD step (2→3→4…), per BER — where does it saturate?
2. Cost per HD step: ops and wall-clock per recovery call (mean + tail, e.g. p95/max).
3. Silent decodes per HD step and W — where does a deeper search make keyed W=1/2 unsafe?
   Does keyless' free self-check keep it safe deeper?
4. Budget: how often does `candidates_budget` truncate the search (i.e. HD is nominal only)?
5. Feasibility limit: largest HD whose p95 cost stays under a stated bound (e.g. ≤10× HD=2 ops,
   or a per-packet time budget) — per arm, per BER.

## Build to these
1. Sweep dimension `max_combined_hd` ∈ {1,2,3,4} (5 if affordable) in `run_sweep`
   (`simulation/isolated_recovery_sim.py`); add a `max_combined_hd` CLI list flag. The column
   already exists in the frozen CSV schema.
2. Record budget exhaustion: a per-arm count of searches that hit `candidates_budget` (new CSV
   column → schema v3) — check whether the repair outcome already exposes it before adding.
3. Configs ACR-only (a) + (b) first (coefficient_first later: its whole-segment coeff search
   explodes fastest). W ∈ {1,2,3}, BER {1e-3…1e-2}, gen6; gen10 spot-check at the frontier HD.
4. Run budget both capped (20000) and uncapped at small seed count to separate "HD too deep"
   from "budget too small".
5. Plots: recovery / silent / ops (log) / time vs HD, line per (arm, W), panel per BER; plus a
   recovery-vs-ops Pareto plot (one point per HD) — the "how far to push" figure.
6. Depends on ticket 18 (early-exit keyed verify) for fair ops/time — run after 18, or report
   ops caveated.

## Done when
- [ ] HD sweep implemented + CSV (schema bump documented) + replot functions.
- [ ] Budget-exhaustion rate reported per cell.
- [ ] Frontier stated per arm/BER with the bound used; silent-decode behaviour vs HD reported
      (measured, not bounded).
- [ ] Short write-up in ADR-0013 Results (or a new ADR if it changes the recommended HD).

**Blocked by:** 18 (for fair cost numbers). **Status:** first full sweep DONE 2026-09-24 (results below); write-up in ADR-0013 TODO.

## Spot check HD=2 vs HD=3 (2026-09-24, 400 seeds, gen6, ACR-only, BER 6e-3/1e-2, W 1–3)
Script: scratchpad `hd3.py` (not committed). 2400 targets/cell. Machine shared with another sweep → times noisy.
- ACR (a) recovery: 98.6→99.96 % (6e-3), 93.0→99.3 % (1e-2) at W≥2, both arms equal. HD=3 removes nearly all failures.
- Cost: mean ops ×1.5–3.1, p95 ×2.5–5, max ×5–8 (worst: keyed W=3 1e-2, 88k→746k); time ×1.4–2.4.
- Budget 20000 never binds at HD=3 (capped == uncapped outcomes, 100 % of rows).
- Silent: keyed W=1 rises (ACR a 1e-2: 10.8→12.0 %; ACR b 6.1→9.1 %); keyed W=2 goes 0→0.17 % (4/2400) at 1e-2;
  W=3 still 0. Keyless ≤0.08 % at W=1, 0 at W≥2 — deeper search hurts keyed low-W, not keyless.
- ACR (b): HD=3 barely helps (keyless unchanged — its failures are salt/tag hits the payload span can't touch).
→ Next: HD=4 (+5?) to find where cost/silent turn infeasible.

## Full sweep (2026-09-24, branch feat/keyed-early-exit-hd-frontier @ a9ac6ef, keyed early exit on)
Runs `logs/isolated_recovery_v3/t19a_*` (payload span, HD 1–5, budget 20000 + none, 800 seeds, 4800
targets/cell) and `t19b_*` (segment span, HD 1–5, budget 20000, 300 seeds). Plots
`logs/isolated_recovery_plots/v3_t19a_hd_payload/`, `v3_t19b_hd_segment/` (vs_hd_*, pareto_*, budget_effect.csv).

**Payload span, ACR-only (a), recovery % (W≥2, uncapped):**
| BER | HD1 | HD2 | HD3 | HD4 | HD5 |
|---|---|---|---|---|---|
| 4e-3 | 92.6 | 99.5 | 100.0 | 100.0 | 100.0 |
| 1e-2 | 64.7 | 92.8 | 98.9 | 99.9 | 100.0 |

**Cost at BER 1e-2, uncapped (mean / max GF ops per recovery call):** keyless 31k/72k (HD2) →
70k/0.5M (HD3) → 163k/3.8M (HD4) → 335k/25M (HD5); keyed W=2 12k/39k → 31k/0.3M → 75k/2.4M →
142k/10M. Mean ×2–2.5 per HD step; the TAIL explodes (×5–8 per step from HD3). Mean time keyless
61 → 116 → 245 → 475 ms.

**Frontier (this setup):** HD3 = sweet spot — takes recovery to ≥98.9 % at BER ≤1e-2 for ~2–2.5× HD2
mean cost, max ≲0.5M ops. HD4 buys +1 pp only at BER 1e-2 for another ×2.3 mean and multi-M-op
tails. HD5 buys nothing measurable; tails reach 10–25M ops → infeasible.

**Budget (20000):** never binds at HD≤3. At HD4/5 it changes the outcome in ≤1.3 % of seeds on
average (up to ~10 % of seeds, −3.3 pp recovery in the worst keyed cell); keyless ≤0.5 % of seeds.
Capped HD4/5 is *worse* than HD3 for keyed at 1e-2 (97.4 vs 98.9 %).

**Silent decodes vs HD:** keyed W=1 grows with depth (ACR a 1e-2: 2.5 → 10.6 → 11.9 → 12.0 %); keyed
W=2 rises 0.02 → 0.31 % (ACR a) / 0 → 0.81 % (ACR b) at HD5 uncapped; W=3 stays 0. Keyless: ACR (a)
≤0.13 % at W=1 and 0 at W≥2 for every HD; ACR (b) keyless 0.04–0.17 % but flat in HD (the separate
undiagnosed mechanism, not depth-driven). → deeper search erodes keyed low-W safety, not keyless.

**ACR-only (b):** HD barely matters (keyless ~26 % / 3 % at 4e-3 / 1e-2 at every HD) — limited by
salt/tag corruption the payload span can't touch, not by depth.

**Segment span (T19b, capped):** outcomes at HD3 = HD4 = HD5 exactly → the 20000 budget fully binds
from HD3; deeper HD is nominal only. Keyless gains (1e-2 ACR a W=3: 93.0 → 98.8 %), but keyed LOSES
recovery going HD2 → HD3 (93.0 → 89.6 %) — budget-truncated wider search (mechanism not yet traced).
Keyless segment span is expensive (HD3 mean 0.49M ops, max 3.1M at 1e-2).

**Cost numbers above include the post-repair pool check (v3).** Repair-only (v4, ticket 20), ACR a,
1e-2, W=2, uncapped, mean ops keyless/keyed: HD2 15.8k/8.7k → HD3 54.9k/27.9k → HD4 148k/71k →
HD5 320k/139k; max HD5 25.1M/10.3M. Frontier conclusion unchanged. Plots: `v4_t19a_hd_payload/`, `v4_t19b_hd_segment/`.

**Open:** (1) why capped segment-span HD3 hurts keyed; (2) state the frontier bound formally (e.g.
p95 ≤ 10× HD2) in ADR-0013; (3) gen10 spot check at HD3/4.
