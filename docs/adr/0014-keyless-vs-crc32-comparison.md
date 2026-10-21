Status: ACCEPTED (2026-10-13) — implementation on branch `feat/crc32-vs-keyless`.

# Keyless vs CRC-32: recovery, detection, repair cost

Decisions (user, 2026-10-13):

1. **Harness** — CRC-32 added as extra arms to the isolated recovery harness (ADR-0013): injected trust, paired ground truth, same pool (G = gen_size clean helpers + T targets).
2. **Tag parity** — gen_size = 4, GF(2^8) → keyless carries 4 tag bytes per segment, CRC carries one CRC-32 (4 B) per segment. Multiple segments (coeff segment too). Keyless salt byte (1 B/seg) ignored in the count → same payload, same tag bytes.
3. **CRC repair — two variants**:
   - `crc_acr`: ACR-localized columns (same injected helper basis as keyless).
   - `crc_blind`: no localization, whole segment payload searched.
   Both use the same algorithm as the keyless/keyed arms (pairing + combined search + per-half fallback + unpaired bit-flip), oracle = per-segment CRC-32 check. Combined filter is sound because CRC-32 is affine over GF(2): crc(a⊕b) = crc(a)⊕crc(b)⊕crc(0^L). Same max HD + budget as keyless; budget-out = failure.
4. **Errors** — data payload only (config `arc_only_a`), identical bit flips in every arm.
5. **Detection** — miss rate per corrupted segment, vs BER and vs exact k flips. Keyless: self-check only, and self + W = 1..4 helpers. CRC-32. Measured (MC) + exact undetected-pattern count for small k (syndrome enumeration) + analytic curve.
6. **Cost** — measured wall-clock primary. Op counts secondary (field ops; CRC bytes processed).
   **CRC implementation (2026-10-14, supersedes ADR-0011's pure-Python CRC for this comparison):** library `zlib.crc32` — standard IEEE CRC-32 in C, what a real system calls. Keyless inner products stay pure Python, so the wall-clock compares C (CRC) with Python (keyless); stated with the results. Library-vs-library keyless (galois / pyerasure) = future work, ticket 21.
7. **Scope** — single hop only (CRC does not survive recoding; source CRCs each coded packet).
8. **Grid** — df ∈ {100, 300, 1000} B, BER 1e-5..1e-2, 200 seeds. Runtime estimate + smoke test before long runs.
9. **Cleanup** — old CRC-16 comparison (`CrcScheme`, its arms in `scheme_comparison_sim.py`) removed. CRC primitive `simulation/crc_recovery.py` kept and reused.
10. **Branch** — `feat/crc32-vs-keyless` off `main`.

## Results (2026-10-14, CRC = zlib.crc32)

Runs: `logs/crc32_vs_keyless/` (recovery 200 seeds/df, detection 50 seeds; 17 min total), plots
`logs/crc32_vs_keyless/plots/`. Layout: 50 B data segments (df100 → 2, df300 → 6, df1000 → 20), T = 4, budget 20000.

- **Recovery + silent decodes**: identical to the first run, row for row (CRC implementation only changes time).
  `crc_acr` == keyless everywhere; `crc_blind` equal at HD1, worse at HD2 (df1000 1e-3: 19.8 % vs 76 %).
  1 silent decode total (keyless W=1); 0 for W ≥ 2 and both CRC arms.
- **Repair wall-clock (HD2, CRC in C, keyless in Python)**: `crc_acr`/keyless ≈ 0.75–0.9 at BER ≤ 3e-4,
  0.5–0.6 at 1e-3, ~0.37 at 1e-2 (e.g. df1000 1e-2: 533 vs 1397 ms). Not more than ~2.7× faster although
  one CRC check is ~20× cheaper: ACR localization + the Python search loop are shared by both arms.
  `crc_blind`/keyless 4.6–23×.
- **Verify cost per 50 B segment**: zlib CRC-32 0.84 µs; keyless self 3.5 µs, +1 helper ~7, +2 ~10.5,
  +3 ~14, +4 ~18 µs (Python). Library keyless = ticket 21.
- **Detection**: unchanged statement (same polynomial; exact counts recomputed for zlib, CRC-32 still 0 for k ≤ 4).

### HD3/HD4 run (2026-10-16)

Run: `scripts/crc32_vs_keyless_hd34_runs.sh` — same grid, code and seeds 0..199 as the HD1/2 run (paired: same
pools + bit flips per seed/BER), only `--hds 3,4`, 4 workers. Dirs `logs/crc32_vs_keyless/recovery/df{100,300}_N*_hd34_seeds200`,
df1000 split into `df1000_N20_hd34_seeds0-9` + `..._seeds10-199` (first attempt died after seed 9, machine fork failure;
missing seeds rerun with identical args). Smoke check: HD2 rows rerun with this code reproduce the HD1/2 CSV exactly
(target_outcomes + ops + CRC bytes, 252 rows). Runtime 9 / 34 / ~100 min (df100/300/1000), shared machine; no grid reduction.
Plots `plots/recovery_rate_hd{3,4}`, `repair_time(_all)_hd{3,4}`, new `recovery_vs_hd` (x = HD 1..4), table `silent_decodes_by_hd.csv`.

- **Recovery (% targets, HD1/2/3/4)** — keyless W ≥ 2 == `crc_acr`:
  BER 1e-3: df100 85/97/99.9/100, df300 57/91/98.9/99.6, df1000 13/76/97.1/98.9; blind 85/88/88/88, 57/64/64/64, 13/20/20/20.
  BER 3e-3: df100 27/66/90/95, df300 1.4/23/67/78, df1000 0/0.4/29/44; blind 27/33/33/33, 1.4/2.5/2.5/2.5, 0/0/0/0.
  BER 1e-2: ≤ 9 % (df100 HD4), 0 for df300/1000. Keyless W1 below at HD3/4 (e.g. df1000 3e-3: 23/30 %).
- **`crc_acr` == keyless W2/W3/W4**: identical target_outcomes in all 16800 (seed, cell) rows per W at HD3 and HD4.
  W1 differs in 116 (HD3) / 261 (HD4) targets: mostly F where CRC recovers (a false W1 candidate in an IC half is
  caught by the halves' mutual-orthogonality check → pair fails), plus its silent decodes.
- **Silent decodes (HD1/2/3/4, all df + BER, 16800 targets each)**: keyless W1 0/1/29/54 (df100 0/0/2/6,
  df300 0/1/14/20, df1000 0/0/13/28; at BER 1e-3..1e-2); W2, W3, W4, `crc_acr`, `crc_blind`: 0 at every HD.
- **Budget effect**: `crc_blind` (400 bits/segment; HD1+2 = 80 200 candidates > 20 000) exhausts the budget inside
  HD2 → HD3/HD4 outcomes identical to HD2 in all 4200 (seed, cell) pairs, same CRC bytes; the gap to ACR widens with HD.
  ACR search space fits the budget only up to 6 localized columns (HD3) / 3 columns (HD4) per step. Diagnostic
  (crc_acr, 20 seeds; transfers to keyless, same search): share of search steps ended by the budget at
  HD2/3/4 = 0/0/1–5 % at 1e-3, 0/1/17–20 % at 3e-3, 0/28–32/67–69 % at 1e-2 (combined pair steps 95 % at HD4 1e-2).
  So HD3→HD4 still pays at 1e-3..3e-3; at 1e-2 the budget caps it.
- **Repair wall-clock (ratio of means, measured back to back per seed)**: `crc_acr`/keyless W4 at HD3 and HD4
  0.66–0.73 at 3e-4, 0.40–0.46 at 1e-3, 0.37–0.39 at ≥ 3e-3 (df1000 1e-2 HD4: 4.3 vs 11.4 s). `crc_blind`/keyless:
  HD3 11–14× at 3e-4, ~8.6–9.2× at 1e-3, 2.4–2.7× at 3e-3, 0.5× at 1e-2; HD4 10–13×, 4.5–4.8×, 1.2–1.3×, 0.37× —
  blind stops growing (budget-bound) while keyless keeps growing, so at high BER blind is faster but recovers ~nothing.
  Absolute ms not comparable to the HD1/2 run (10 vs 4 workers, different machine load).

## Results, first run (2026-10-13) — SUPERSEDED: pure-Python CRC

Archived in `logs/crc32_vs_keyless/_superseded_pure_python_crc/`. Recovery/detection outcomes stay valid (the zlib rerun gives identical target outcomes); the CRC timings below do not.

Runs: `logs/crc32_vs_keyless/` (recovery 200 seeds/df, detection 50 seeds), plots `logs/crc32_vs_keyless/plots/`.
Layout: 50 B data segments (df100 → 2, df300 → 6, df1000 → 20), T = 4 targets, budget 20000.

- **Recovery**: `crc_acr` == keyless at every cell (same ACR columns + search, only the oracle differs).
  `crc_blind` equal at HD1, worse at HD2 (budget): df1000 BER 1e-3 19.8 % vs 76 %; df300 64 % vs 91 %.
- **Silent decodes**: 1 in total (keyless W=1, df300, BER 3e-3, seed 85); 0 at W ≥ 2; CRC 0.
- **Repair wall-clock (HD2)**: `crc_acr`/keyless ≈ 1× up to 3e-4, ~1.8× at 1e-3, ~2.3–2.5× at ≥ 3e-3
  (pure-Python CRC per candidate vs table inner products). Blind CRC 10–200× (df1000 1e-3: 9.1 s vs 52 ms).
- **Detection, P(miss | k bits)**: CRC-32 0 for k ≤ 4. Keyless self-only 0.12 (k=2) / 0.042 (k=4), odd k
  never; +1 helper 5e-4; +2 1.7e-6; +3 0 at k=2, 2.6e-9 at k=4; +4 1.6e-11 at k=4.
  Per corrupted segment at BER 1e-3: self-only 2 %, W1 8e-5, W2 3e-7, W3 6e-12, W4 3e-14, CRC-32 4e-14.
  Keyless W=4 ≈ CRC-32 (crossover near BER 1e-3).
- **Verify cost per 50 B segment**: CRC-32 ≈ 11–12 µs; keyless self 4 µs, +1 7, +2 10.5, +3 15, +4 18 µs.

## Library keyless backend (2026-10-16)

Ticket 21, branch `feat/galois-keyless`. Harness switch `--field-backend table|galois|pyerasure|numba`
(`binary_ext_fields/field_backends.py`) replaces ONLY the GF inner product (the keyless oracle); op counts
and outcomes identical (asserted; rerun = main run's target_outcomes, seeds 0..49, all backends). ACR row
ops stay on the tables in every backend and are shared by keyless and `crc_acr`. Output
`logs/crc32_vs_keyless_galois/` (bench/, recovery/, plots_{galois,table,numba}/, ratio_by_backend.csv).

- **Per check of a 50 B segment (+salt+4 tags), µs, W=0 / W=4** (min of 15, loaded machine): table
  6.5 / 31; galois public API 98 / 613; galois compiled ufunc (harness `galois`) 13 / 56, batched 13 / 14;
  pyerasure 54 / 217; numba own kernel (not a library) 2.3 / 10; zlib CRC-32 1.2 (raw crc32 0.13).
- **galois does not help** at 55 B: per-call overhead (FieldArray views, Python-level dispatch, numba
  parallel launch for `@`) exceeds the whole Python loop; batching helps only when all W+1 products are
  needed, but the search rejects >= 99 % of candidates at the self-check. **pyerasure 1.3.0 is pure Python.**
- **Repair wall-clock `crc_acr`/keyless (W=4), same session**: table 0.67–0.99 (BER <= 3e-4), 0.55–0.62
  (1e-3), 0.38 (1e-2); galois 0.57–1.18 / 0.39–0.42 / 0.20–0.22; numba 0.81–0.93 / 0.80–0.85 / 0.70–0.74.
- **Statement for the thesis**: library-vs-library makes keyless slower, not faster; the Python table loop
  stays the reported implementation. Compiled vs compiled (numba, labelled own kernel): one check ~2× CRC at
  W=0, repair `crc_acr` only 1.1–1.4× faster than keyless — the C-vs-Python gap was mostly call overhead.

## Three error models x HD 1..4 (2026-10-17)

User 2026-10-17: payload only / tag only / payload + tag, real BER, max HD 1..4, blind CRC dropped. New harness
config `acr_only_tags` (model `data_tags_only`: only data-segment salt+tags / CRC bytes; same RNG streams, so
payload+tag = payload-only ∪ tag-only flips per seed). Repair span `segment`, budget 20000, keyless W1..4 vs crc_acr,
200 seeds, 6 workers, 5.4 h. Runs `logs/crc32_vs_keyless/recovery_three_models/`, plots + `summary.csv`,
`silent_events.csv`, `outcome_identity.csv` in its `plots/`. Script `scripts/crc32_vs_keyless_three_models_runs.sh`.

- Payload only: keyless W≥2 == crc_acr outcome for outcome (W2 differs in 4 targets at HD3/4).
- Tag only: both repair ~all (≥ 99 % up to 3e-3 at HD ≥ 2); not paired (5 B salt+tags vs 4 B CRC bytes).
- Payload + tag: keyless ≈ crc_acr ±2 pp (e.g. df300 3e-3 HD3: 58 vs 61 %).
- HD3 == HD4 everywhere with segment span: the extra tag columns make the budget bind inside HD3.
- Rare events: at BER ≤ 3e-4, HD ≥ 3 never fails (0 of 9600 targets per arm/model); failures only at HD1/HD2.
- Silent: keyless W1 only (payload 0/6/65/65, payload+tag 0/5/55/55 at HD1..4); W ≥ 2 and crc_acr 0.
- Time crc_acr/keyless W4 at BER ≥ 1e-3: 0.30–0.38 (HD ≥ 2), tag-only 0.14–1.36.
