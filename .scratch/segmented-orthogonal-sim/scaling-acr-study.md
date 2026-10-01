# Scaling + security re-check under ACR-only (2026-09-29)

Branch `feat/scaling-acr` (worktree `.claude/worktrees/scaling-acr`), from main c60c64b. Redoes the
tasks of `HANDOFF-scaling-and-security.md` independently (its results were NOT reused) and compares
at the end with branch `feat/scaling-and-op-audit` (not merged, per user).
ACR = algebraic consistency check (the step the code calls "ARC"; code names unchanged, see CONTEXT.md).

## User decisions (2026-09-29)
- Recovery sims: ACR-only only. No coefficient repair, no bit flips over the whole packet.
- "Wait for enough packets, then ACR; don't drop packets before" (end-to-end logic).
- gen_size 6. Error models: data payload only, AND data payload + data salt/tags (compare).
- S2: small fields measured; GF(2^8) = smoke + estimate only. Random-witness option added.
- Estimate + smoke before every long run.

## Code (all defaults unchanged = old behaviour)
| what | where |
|---|---|
| production strategy `acr_only`: no coeff repair; data segs repaired only where ACR localizes; unlocalizable packet left IN the pool (retried next arrival); bit-flip over ACR columns (both arms, like the harness); `repair_span` payload/segment | `segmented_recovery.recover_acr_only`, `segmented_mac_recovery.recover_acr_only_mac`, `integrity_schemes` (AdmitConfig.repair_span) |
| channel-error scopes `whole_packet` (default) / `data_payload` / `data_segment` (+salt/tags), coeff never hit | `scheme_comparison_sim.run_recovery_trial(error_scope=)`, `*Scheme.error_positions` |
| isolated config `acr_only_data_tags` (error model `data_segment`), CLI `--num-data-segments --bers` | `isolated_recovery_sim.py` |
| pareto sweep knobs `--gen-size --strategy --error-scope --repair-span --min-pool-size`, schema v2 (+error_scope, repair_span) | `scripts/pareto_sweep.py`, `pareto_from_csv.py` |
| inner-product fast path: table lookup, SAME values and op counts (test compares whole sweeps with/without), ~12x | `operations.inner_product_bytes`, `custom_field.TableField/CountingField.inner_product` |
| S2 witness policy `first` (default) / `random` (receiver-secret per-packet subset), keyed `mac_verify_count` | `binary_ext_fields/witness_policy.py`, `classify_segment_trust(witness_rank=)`, `classify_segment_trust_mac(verify_count=, key_rank=)`, AdmitConfig |
| S2 driver + plots | `simulation/verify_width_attack_sim.py`, `scripts/verify_width_plots_from_csv.py` |
| R2/R3 run chain + plots | `scripts/scaling_acr_runs.sh`, `scripts/scaling_plots_from_csv.py` |
Tests (new): `inner_product_fast_path_test`, `acr_only_production_test`, `verify_width_attack_test`. Regression: 20 suites green.

## Findings

### F1 — "wait, then ACR" was NOT implemented before
`coefficient_first`/`uniform_hd` admit: when ACR cannot localize (fewer than g trusted rows in the
segment, e.g. the first admit at pool = g) the data segment got a BLIND whole-segment HD-2 search
(payload+salt+tags), cubic in segment length. That was the old R1 compute wall. `acr_only` now waits.

### F2 — N = 2 never repairs end-to-end under ACR-only (structural)
ACR for a segment needs g packets trusted in that segment. With ONE data segment that already means
g decodable packets, so the admit decodes before ACR could ever run. Repair only helps when N >= 3:
a packet broken in segment A but clean in B serves as a basis row for B. Pinned by a test.
-> Segmentation is what makes ACR-only recovery useful at all (R2 "role of segmentation").

### F3 — R1 re-check: df = 1000 is compute-feasible at every N and BER (ACR-only + fast path)
End-to-end probe, g=6, HD 2, budget 20000, cap 8g=48 packets, data_payload errors; worst of 4 trials
(2 keyless + 2 keyed), wall s (6 parallel procs) and decoded/4:

| df | N | L | 1e-05 | 1e-04 | 1e-03 | 3e-03 | 1e-02 |
|---|---|---|---|---|---|---|---|
| 100 | 2 | 100 | 0s 4/4 | 0s 4/4 | 0s 4/4 | 1s 4/4 | 2s 0/4 |
| 100 | 3 | 50 | 0s 4/4 | 0s 4/4 | 0s 4/4 | 1s 4/4 | 2s 0/4 |
| 100 | 5 | 25 | 0s 4/4 | 0s 4/4 | 0s 4/4 | 1s 4/4 | 8s 0/4 |
| 100 | 11 | 10 | 1s 4/4 | 1s 4/4 | 1s 4/4 | 1s 4/4 | 4s 4/4 |
| 300 | 2 | 300 | 0s 4/4 | 0s 4/4 | 3s 0/4 | 3s 0/4 | 2s 0/4 |
| 300 | 4 | 100 | 0s 4/4 | 0s 4/4 | 1s 4/4 | 7s 0/4 | 2s 0/4 |
| 300 | 7 | 50 | 0s 4/4 | 0s 4/4 | 1s 4/4 | 26s 3/4 | 3s 0/4 |
| 300 | 13 | 25 | 0s 4/4 | 0s 4/4 | 1s 4/4 | 2s 4/4 | 25s 0/4 |
| 300 | 31 | 10 | 1s 4/4 | 1s 4/4 | 1s 4/4 | 2s 4/4 | 76s 0/4 |
| 1000 | 2 | 1000 | 0s 4/4 | 1s 4/4 | 7s 0/4 | 5s 0/4 | 7s 0/4 |
| 1000 | 5 | 250 | 0s 4/4 | 1s 4/4 | 36s 0/4 | 10s 0/4 | 10s 0/4 |
| 1000 | 11 | 100 | 1s 4/4 | 1s 4/4 | 12s 4/4 | 29s 0/4 | 11s 0/4 |
| 1000 | 21 | 50 | 1s 4/4 | 1s 4/4 | 7s 4/4 | 128s 0/4 | 12s 0/4 |
| 1000 | 41 | 25 | 2s 4/4 | 2s 4/4 | 7s 4/4 | 122s 2/4 | 88s 0/4 |

Limit is decodability, set by errors per data segment (HD 2): at 1e-3 need L <= ~100, at 3e-3 L <= ~25-50,
at 1e-2 only L = 10. Isolated harness: <= ~20 s per config (budget-capped) everywhere.
Cost drivers now: keyless detection O(M^2 L) per admit (pool M up to 48) and budget-capped searches in
hopeless cells. Possible (NOT done) cheap early-exit: ACR returns K corrupted bytes; K > HD cannot be
repaired correctly -> skip the search (changes only wrong-accept chances).

### F4 — S1 re-audit: op counting correct (independent re-derivation)
Per forged packet only the COEFF segment is computed (data segments copied, 0 ops, both arms), so
`attacker_mul` is flat in df. Measured = closed form (40 seeds/cell, df 12/96/1000, g 4/6, GF(2^2/8)):
keyed = k*g exactly; keyless = r*g + (r+1)(g+1) + (r+1)^2(g+2), reached exactly at GF(2^8); at
GF(2^2) the mean is lower (zero pivots skip elimination rows: g=4,r=3 -> ~108-110 vs 128).
The "keyless ~120 vs keyed ~20" gap = null-space solve (O(g^3)) vs k dot products (O(g^2)), not a bug.
Data-segment forger (analytic): ratio keyless/keyed = 3.17 / 1.05 / 0.78 at L = 12 / 96 / 1000 (g=4, u=0)
-> "gap grows with packet size" refuted.

### F5 — ticket-17 numbers after the unit-tag-column guard: unchanged
Re-ran `main_g4_n2_t4000` (GF(2^2/4), hd 0/1, early/late) and `spot_g4_n5_t2000` on current code
(`logs/ticket17_recheck/`). Per-trial outcomes differ (the guard re-draws salts/data), aggregates do not:
old-vs-new |z| <= 1.4 in every cell; oracle still = q^-u (|z| <= 2.0). Pre-existing, unchanged: the
first-order keyless late-strike tie-break formula over-predicts at q=4 (new 3.2/11.6/35.7 % vs 4.2/13.3/39.1 %,
old run 3.7/12.4/36.6 %); fine at q=16. D4's GF(2^8) bits (22 keyless vs 26 keyed) rest on formulas
that still match -> stand.

### F6 — S2: verification width x witness policy (GF(2^2), GF(2^4); g=4, N=2, 4000 trials/cell, repair off)
Run: `logs/verify_width_attack/g4_m24_t4000_hd0/`, plots `logs/verify_width_attack/plots/`.
- Deterministic witnesses/keys ("first", today's code): admit = q^-max(0, W-k) (keyed) and
  q^-max(0, vc-r) (keyless) -> 100 % as soon as the attacker knows the checked ones. Measured = theory.
- Receiver-secret random subset: keyed = sum_j Hyp(j; g, g-k, W) q^-j; W=1 -> k/g + (1-k/g)/q
  (supervisor formula confirmed, e.g. GF(4): 24.6/43.8/61.2/80.6 % vs 25.0/43.8/62.5/81.3 %).
- Keyless random is ABOVE its first-admit analogue r/(g-1) + (1-r/(g-1))/q (up to 8 sigma): the receiver
  is stateless and re-classifies at the next arrival; the new honest packet enters the forger's random
  witness set with prob n/g -> one extra lottery ticket. With that term (verify_width_attack_sim
  .theory_admit_reeval) all 110 cells fit (max |z| 2.7). Hardening idea (not built): freeze a packet's
  witness subset / verdict at its first evaluation.
- GF(2^8) (run 2026-10-01, `logs/verify_width_attack/g4_m8_t4000_hd0/`, 4000 trials/cell): all 55 cells
  fit the theory incl. re-evaluation (max |z| 2.58). With q = 256 the 1/q term vanishes, so a random
  single check is just k/g (keyed 25.4 / 49.3 / 75.3 % for k = 1/2/3) and r/(g-1) (keyless 33.8 / 65.4 %),
  while the deterministic check is 100 % from k >= W / r >= vc. Checking everything (width all) = q^-u.

## R2 / R3 — size x segmentation x BER (DONE 2026-09-30, `scripts/scaling_acr_runs.sh`, 7 h 51 min)
Sizes df {100, 300, 1000}, N for matched L: 100: N 2,3,5,11 | 300: N 2,4,7,13,31 | 1000: N 2,5,11,21,41.
BER 1e-5,3e-5,1e-4,3e-4,1e-3,3e-3,1e-2 at every size. g=6, GF(2^8), ACR-only, HD 2, budget 20000.
Runs `logs/scaling_acr/{iso_w,iso_hd,prod}/`; plots `logs/scaling_acr/plots/` (cross-size set) and
`logs/scaling_acr/plots/standard/df*_N*/` (the usual isolated overview set per layout: vs_w, vs_hd,
pareto, silent_w1, *_vs_ber). All cells complete, no wall-limit hits, 0 silent decodes end-to-end.

### Isolated harness (recovery of 6 corrupted targets, injected trust)
Keyless recovery, payload errors, W=6 (keyed identical to 0.0 at W=6):

| df | N | L | 1e-4 | 3e-4 | 1e-3 | 3e-3 | 1e-2 |
|---|---|---|---|---|---|---|---|
| 100 | 2 / 3 / 5 / 11 | 100 / 50 / 25 / 10 | 100 all | 100 all | 91 / 97 / 99 / 99 | 38 / 59 / 81 / 96 | 0 / 0 / 5 / 35 |
| 300 | 2 / 4 / 7 / 13 / 31 | 300 / 100 / 50 / 25 / 10 | 100 all | 92 / 100 ... | 32 / 75 / 90 / 99 / 99 | 1 / 5 / 22 / 55 / 90 | 0 ... 6 |
| 1000 | 2 / 5 / 11 / 21 / 41 | 1000 / 250 / 100 / 50 / 25 | 95 / 99 / 100 ... | 29 / 83 / 97 / 100 / 100 | 0 / 8 / 38 / 71 / 97 | 0 ... 14 | 0 |

- Segmentation is what carries recovery to higher BER: shorter L -> fewer flips per segment -> within HD.
- Same L, bigger df = WORSE (L=50 @1e-3: 97 / 90 / 71 %): a packet needs EVERY segment repaired,
  more segments -> more chances one fails (~p_seg^(N-1)).
- HD sweep (W=3): HD3 is the big step over HD2 for long segments (df1000 L=50 @1e-3: 71 -> 95 %;
  @3e-3 L=25: 14 -> 86 %); HD4 = HD5 everywhere (budget 20000 binds). Cost x3-10 per HD step at long L.
- Silent (wrong accept): keyed W=1 large (e.g. 1e-3: 1-99 %, grows with L), W=2 <= 2 %, W=3 = 0;
  keyless <= 0.7 % at W=1 (4 cells, 1-2 of 300 targets), 0 at W>=2. W=1 keyed is non-monotone at the
  floor BERs (budget-capped search) -- floor region, not interpreted.
- Tag errors (data salt/tags also hit): payload-only repair loses a lot as N grows (e.g. 1000 B N=41
  @3e-4: 42 % keyless / 53 % keyed vs 100 %); keyless a bit worse (1 extra salt byte per segment). Repairing
  over payload+salt/tags restores the payload-only curve. -> `iso_error_models_W6.png`.

### End-to-end (send until decodable, cap 48 packets)
Best bit-efficiency N per (df, BER), keyless (keyed same N almost everywhere):

| df | 1e-5 | 3e-5 | 1e-4 | 3e-4 | 1e-3 | 3e-3 | 1e-2 |
|---|---|---|---|---|---|---|---|
| 100 | N2 .82 | N2 .83 | N2 .79 | N3 .66 | N5 .49 | N11 .32 | N11 .16 |
| 300 | N2 .91 | N2 .87 | N2 .78 | N7 .64 | N13 .45 | N31 .30 | none |
| 1000 | N2 .90 | N5 .82 | N11 .72 | N41 .56 | N41 .41 | .02 | none |

- The optimal segment count grows with BER AND with payload size; at low BER N=2 wins (least tag
  overhead), at high BER short segments win despite 7 extra bytes per segment.
- Decodability floor (48-packet cap): df1000 ends at 1e-3 (3e-3: only N=41 23 %); df300 at 3e-3 (N>=13);
  df100 reaches 1e-2 only at N=11 (L=10).
- Keyed ~1 pp more efficient on average (6 tag bytes per segment vs 7 = salt + 6).
- N=2 never repairs (F2): its curve is pure "wait for g clean packets"; still the best at <= 1e-4.
- Tag errors end-to-end: payload-only repair costs little at 100 B but kills df1000 L=50 at 1e-3
  (eff .37 -> .02); segment-span repair recovers most of it (.32).

### F7 — BUG (fixed 2026-10-01): keyed pair fallback had less search than keyless
Seen as "keyless recovers more at HD 4, even at W=3" (df1000 N11 1e-3: keyed 22 vs keyless 42 of 48,
0 silent both; IC-refinement off in both arms: 22 vs 22). Three differences in the keyed pair path
(`segmented_mac_recovery._search_pair_mac`) vs keyless (`repair_segment` -> `_ic_refine_pair`):
1. one budget SHARED by combined search + both fallback halves (keyless: fresh budget per step);
2. combined search hitting the budget RETURNED, skipping the fallback (keyless: fallback still runs);
3. fallback halves searched the UNION of both halves' ACR columns (keyless: each half its own).
Fix (user: fresh budget per search step for keyed too): all three aligned to the keyless rule. Same
cell after fix: HD3 40/40, HD4 42/42, 0 per-target differences. Test `simulation/pair_budget_parity_test.py`
(3 cases, each red on the old code). Keyless code unchanged.
Stale (keyed arm only, rerun pending by user choice): `logs/scaling_acr/iso_hd` (HD >= 3) and its
vs_hd / pareto / hd3-5 plots; the ticket-19 HD runs `logs/isolated_recovery_v4/t19*`. HD 2 headline
results stand (W >= 3: 0 per-target differences between arms already before the fix); keyed W <= 2
numbers at HD 2 may shift slightly (fallback path also hit by wrong-accept candidates).

## vs branch feat/scaling-and-op-audit
| item | old branch | this branch |
|---|---|---|
| S1 | closed forms, no bug | same closed forms, independently measured -> agree |
| R1 | df=1000 only with L <= 50 and BER <= 5e-4; long segments = hours/days per admit | cause was the blind pre-ACR search (F1); under ACR-only every N works, compute <= ~2 min/trial; limit = decodability |
| R1 isolated | df=1000 1e-3 = 0 % (N 2/5) | same at N 2/5; N >= 21 recovers at 1e-3 |
| speedups | proposed (table lookup ~13x), not built | table lookup built, identical outputs/counts (test), ~12x |
| S2 | planned | done at GF(2^2/4); supervisor formula holds for keyed; keyless has the re-evaluation term |
| ticket-17 re-check | TODO | done, unchanged |

## Open (user)
1. Merge `feat/scaling-acr`? (touches recovery + admit code; all new behaviour behind non-default knobs,
   plus the behaviour-identical fast path.)
2. Keyless random witnesses: accept the re-evaluation effect or add "freeze on first evaluation"?
3. ~~GF(2^8) S2 full run~~ done 2026-10-01.
4. Production `acr_only` uses bit-flip over ACR columns in BOTH arms (like the harness), not the keyless
   ADR-0002 exact solve. OK, or should keyless keep the exact solve end-to-end?
