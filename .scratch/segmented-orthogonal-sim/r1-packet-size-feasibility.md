# R1 — feasibility of large data fields (goal df = 1000 B)

2026-09-29, branch `feat/scaling-and-op-audit`. GF(2^8), smoke probes only (1–4 seeds/cell),
6–7 parallel workers → wall times contended (~1.5–2x a quiet machine). Memory ~70 MB/process, not an issue.
N = total segments (1 coeff + N-1 data). N=1 impossible for segmented schemes → used N=2 (one data seg).
λ = expected bit errors per packet = BER · 8 · wire_symbols.

## Verdict
- **df=1000 is feasible**, with two conditions:
  1. **short segments** in the end-to-end (pareto) sim: data-segment length L ≤ ~50 (df=1000 → N ≥ 22).
     With L = 250 (N=5) or 1000 (N=2) a *single* admit costs 10 min … ~1 day → compute-infeasible.
  2. **BER ≤ 5e-4** (λ ≤ 5). At 1e-3 (λ ≈ 10–12) both sims fail: pareto hits 1500 s wall limit
     (compute + high overhead), isolated harness recovers 0 % (HD-2 frontier, a finding not a failure).
- Isolated keyless-vs-keyed harness: df=1000 cheap at every BER (budget-capped search, ≤ 25 s/seed/config
  up to 3e-4). Limit there is decodability (HD frontier), not compute.

## Why long segments break the pareto sim (profile, df=500 N=5 BER 1e-4, 498 s profiled)
- First admit happens at pool = g = 10 packets → no (g+1)-th packet → **ARC cannot localize** → any broken
  data segment gets the **blind whole-segment HD-2 search** (payload+salt+tags, `pair_budget=None`).
- Candidates ≈ (8·L_seg)²/2, each needs a self-check inner product of length L_seg
  → **~32·L_seg³ muls per blind search** (cubic in segment length). L_seg = L + 1 + g.
- Profile: 100 % in `repair_segment` → pair search 333 s + unpaired bit-flip 163 s (693k candidates);
  91 % in `check_orth_packet` → `inner_product_bytes`; ~0.37 M mul/s unprofiled.
- Predicted time per blind search (quiet machine): L=48 → ~20 s; L=125 → ~4 min; L=250 → ~25 min;
  L=500 → ~3 h; L=1000 → ~1 day. Matches probes (below). P(blind search needed) is high even at BER 1e-5
  for df=1000 (λ≈0.08/packet → ~55 % that one of the first 10 packets is hit): df=1000 N=5 took 649 s at 1e-5.

## Probe table — keyless pareto sweep (end-to-end, `scripts/pareto_sweep.py`, g=10, HD 2, pair_budget none)
| df | N | L | λ | BER | sec/trial | outcome |
|---|---|---|---|---|---|---|
| 192 | 2 | 192 | 1.8 | 1e-3 | >1826 | wall_limit after 1st admit (compute) |
| 192 | 5 | 48 | 2.1 | 1e-3 | 382 | decoded ov 1.7 (existing full run: mean 275 s) |
| 500 | 2 | 500 | 0.4/4.3 | 1e-4/1e-3 | – | killed: 1st admit unfinished >20 min (compute) |
| 500 | 5 | 125 | 0.45 | 1e-4 | 276 | decoded ov 1.0 (one blind search) |
| 500 | 5 | 125 | 4.5 | 1e-3 | >1290 | wall_limit ov 1.0 (compute) |
| 500 | 11 | 50 | 0.5 | 1e-4 | 0.4 / 5 | decoded |
| 500 | 11 | 50 | 1.5 | 3e-4 | 41 / 108 | decoded ov 1.0/1.5 |
| 500 | 11 | 50 | 2.5 | 5e-4 | 203 / 340 | decoded ov 2.7/1.7 |
| 500 | 11 | 50 | 5.0 | 1e-3 | 1202 / 1401 | decoded ov 4.1/3.6 |
| 1000 | 2 | 1000 | 0.08 | 1e-5 | 0.3 | decoded (no error landed) |
| 1000 | 2 | 1000 | 0.8/8 | 1e-4/1e-3 | – | killed: 1st admit unfinished >20 min (est. ~1 day) |
| 1000 | 5 | 250 | 0.09 | 1e-5 | 649 | decoded (one blind search) |
| 1000 | 5 | 250 | 0.85 | 1e-4 | >1462 | wall_limit after 1st admit (compute) |
| 1000 | 22 | 48 | 0.1 | 1e-5 | 0.3 / 1 | decoded |
| 1000 | 22 | 48 | 1.0 | 1e-4 | 3 / 10 | decoded ov 1.0 |
| 1000 | 22 | 48 | 3.0 | 3e-4 | 35 / 183 | decoded ov 1.0/1.7 |
| 1000 | 22 | 48 | 5.0 | 5e-4 | 390 / 897 | decoded ov 2.0/5.1 |
| 1000 | 22 | 48 | 10 | 1e-3 | >1552 / >1598 | wall_limit ov 1.7 (compute) |
| 1000 | 43 | 24 | 1.2 | 1e-4 | 5 / 6 | decoded |
| 1000 | 43 | 24 | 3.6 | 3e-4 | 11 / 104 | decoded ov 1.0/2.5 |
| 1000 | 43 | 24 | 5.9 | 5e-4 | >1504 / 1502 | wall_limit ov 6.6 / **timeout** (80-pkt cap, decodability) |
| 1000 | 43 | 24 | 12 | 1e-3 | >1508 / >1514 | wall_limit ov 7.2/5.3 (both) |
No silent decodes in any probe. Raw: `logs/r1_pareto/*/raw_trials.csv` (worktree, not committed).
Many segments hurt at high BER (N=43 worse than N=22 at 5e-4; same trend as df=192 N=17/22 timeouts at 1e-3
in the existing full run): more tag/salt bytes on the wire and every segment must be trusted.

## Probe table — isolated harness (`simulation/isolated_recovery_sim.py`, g=6, T=8, W=2, HD 2, budget 20000, payload span)
sec = one `run_config` (both arms) per seed; rec = recovered/T (keyless | keyed); coefficient_first unless noted.
| df | N | BER | seeds | sec/config | rec kl / kd | note |
|---|---|---|---|---|---|---|
| 192 | 2 | 3e-4 | 3 | 5.8 | 0.92 / 0.92 | |
| 192 | 5 | 1e-3 | 1 | 4.5 | 0.38 / 1.00 | keyless coeff-seg blind spot (known) |
| 500 | 2 | 3e-4 | 3 | 3.1 | 0.71 / 0.79 | |
| 500 | 2 | 1e-3 | 1 | 85 | 0 / 0 | HD floor (≈4.6 flips/target) |
| 500 | 5 | 3e-4 | 3 | 0.6 | 0.88 / 1.00 | |
| 500 | 5 | 1e-3 | 1 | 37 | 0.25 / 0.25 | |
| 1000 | 2 | 1e-4 | 4 | 2.1 | 1.00 / 1.00 | |
| 1000 | 2 | 3e-4 | 3 | 24 | 0.33 / 0.33 | HD floor starts |
| 1000 | 2 | 1e-3 | 1 | 337 | 0 / 0 | HD floor, budget-bound cost |
| 1000 | 5 | 1e-4 | 4 | 0.8 | 1.00 / 1.00 | |
| 1000 | 5 | 3e-4 | 3 | 3.1 | 0.67 / 0.83 | |
| 1000 | 5 | 1e-3 | 1 | 248 | 0 / 0 | HD floor (≈9.5 flips/target) |
arc_only_a same picture, cheaper. Pool build (tagging) ≤ 1 s at df=1000. Raw: `logs/_r1_isolated*.jsonl`.
No wall cap exists in this harness; `candidates_budget` bounds each search so cost stays finite.

## Largest feasible df per BER
| BER | pareto (end-to-end) | isolated harness |
|---|---|---|
| 1e-5 | 1000 (any N if L ≤ 50; long L risky even here) | 1000 |
| 1e-4 | 1000 at L ≤ 50 (N ≥ 22) | 1000 |
| 3e-4 | 1000 at L ≤ 50 | 1000 (N=5: 67–83 % rec; N=2: 33 %) |
| 5e-4 | 1000 at N=22 (390–900 s/trial); N=43 fails (decodability) | ~500 (untested at 1000, expect < 50 %) |
| 1e-3 | 500 at N=11 (~20 min/trial); 1000 = wall limit | ~192 (500+ → 0–25 % rec) |

## Hotspots + suggested optimizations (NOT implemented — known perf costs, reported explicitly)
Both sims: ~100 % of time in `operations.inner_product_bytes` via `CountingField.mul/add`.
Micro-benchmark, L=1000 inner product (loaded machine): current 856 µs; direct field.mul/add 613 µs;
table lookup + bulk count (`mul_count += L`) 64 µs (**13x**, identical result + counts); numpy gather+xor 15 µs (55x).
1. **Count-preserving constant factor (~10x)**: `inner_product_bytes` wraps each product in a 1-element
   `vector_multiply_into`, and `CountingField` does a phase-stack check + 2 dict ops per op. A fast path that
   looks up the mul table and adds `L` to the counters (and phase bucket) once per call keeps every
   result and op count identical. Caveat: `inner_product_bytes` also takes pyerasure fields → keep fallback.
2. **Pareto only, behaviour-changing**: blind pre-ARC whole-segment HD-2 search is cubic in L_seg. Options:
   (a) defer data-segment repair until ARC can localize (≥ g trusted + the broken packet — ADR-0003 "wait");
   (b) finite `pair_budget` for *blind* searches only (the L=48 truncation confound in the pareto docstring
   applies to localized searches). Or simply keep L ≤ 50 (recommended grid below).
3. **Algorithmic, changes the ops metric**: incremental candidate evaluation. Self-check ⟨c,c⟩ = (XOR-sum)²
   in char 2, cross ⟨c+e,w⟩ = ⟨c,w⟩ + ⟨e,w⟩ → O(hd·W) per candidate instead of O(L·W) → L-fold speedup.
   Needs a methodology decision on how to count ops (reported receiver compute would drop ~L-fold).
4. Persist `pair_cache` across admits (already-known deferred item, ADR-0012 sim status).

## Recommended packet sizes + BER grids (next step)
Pick BER per size by λ (errors/packet), not by absolute BER — same λ ≈ same repair difficulty.
| size | df | N (L) | pareto BER grid | isolated BER grid |
|---|---|---|---|---|
| small | 192 (existing) | 5, 9, 13 (48, 24, 16) | 1e-4, 5e-4, 1e-3 (have data) | 1e-4, 3e-4, 1e-3 |
| medium | 500 | 11, 21 (50, 25; N=21 untested) | 1e-4, 3e-4, 5e-4, 1e-3 (1e-3 capped) | 3e-5, 1e-4, 3e-4 |
| largest | **1000** | 22, 43 (48, 24) | 3e-5, 1e-4, 3e-4, 5e-4 (1e-3 = 1–2 capped trials as "floor" point) | 2e-5, 5e-5, 1e-4, 3e-4 |
Isolated harness at df=1000: N=2 and N=5 both fine (budget-capped); N=5 preferred (recovers more at 3e-4).

## Runtime estimates (30 trials/seeds, 6 workers, current code)
- Pareto df=1000: N=22 {3e-5,1e-4,3e-4,5e-4} ≈ 30·(1+7+110+640) s ≈ 23k CPU-s; N=43 {3e-5,1e-4,3e-4}
  ≈ 2k CPU-s. df=500: N=11 {1e-4,3e-4,5e-4} ≈ 10k, + 1e-3 capped at 1800 s cell budget; N=21 untested, assumed similar.
  Total ≈ 40–50k CPU-s → **~2–3 h wall** (6 workers), +~30 min per capped 1e-3 cell.
- Isolated df=1000 (3 configs × 2 spans × 3 W × 4 BERs = 72 run_configs/seed):
  N=5 ≈ 90 s/seed → ~8 min for 30 seeds; N=2 ≈ 500 s/seed → ~45 min. df=500 less.
- With optimization 1 (count-preserving) all of the above ÷ ~5–10.
