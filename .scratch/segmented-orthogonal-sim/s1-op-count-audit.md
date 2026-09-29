# S1 — op-count audit, security (attack) sims

2026-09-29, branch `feat/scaling-and-op-audit`. Question (supervisor): "is mul per packet counted
correctly? keyless ~120 vs keyed ~20 — expected closer."

## TL;DR
- Counting correct, no bug. Like-for-like on shared work. Numbers unchanged.
- `attacker_mul` is **not per packet**: it is the cost of forging the **coeff segment only**
  (g coeffs + salt + g tags). Data segments are copied from the victim, 0 ops, both arms.
  → independent of data_fields / packet length (measured flat df 12..1000).
- Gap = structure, not bookkeeping: keyed = k dot products of length g (O(g²));
  keyless = same r dot products **plus** a null-space solve (O(g³)). Ratio at u=0 = g+4 (8x at g=4).
- Scaling hypothesis "keyed linear, keyless superlinear in packet size → gap widens": **refuted**.
  In g: yes (g² vs g³). In forged length L: both linear, **same slope**; keyless extra is an
  L-independent constant → ratio → (g-1-u)/(g-u) < 1 for long forged segments.
- Ticket-17 data note: `main_g4_n2_t4000` is GF(2^2)/GF(2^4) (ms=2,4), not GF(2^8).

## What is charged (knowledge_attack_sim, ticket 17 Part B)
Per trial one `CountingField cnt` = attacker. Receiver work = separate `receiver_mul` (instrument field).

| step | keyless | keyed | charged? |
|---|---|---|---|
| choose c' (outside honest span), victim, recode honest traffic | harness RNG + base field | same | no, both (shared, equal) |
| copy victim, splice coeff slice (data segs untouched) | byte copy | byte copy | 0 ops, both |
| knowledge_dot: dot(c', known thing) over g coeff symbols | r × g muls (vs r observed coeff slices) + g adds XOR row | k × g muls (vs k leaked keys) | yes, both — identical per constraint (g muls) |
| unknown constraints | nothing (free vars) | random guess, 0 ops | — |
| randomise free vars: b + A·x0, x0 + y | (r+1)(g+1) muls (incl. g+1 muls-by-1 of the XOR row) | n/a | yes, keyless only |
| solve: Gauss-Jordan on (r+1)×(g+2) augmented | ≤ (r+1)²(g+2) muls (= unless an entry is 0 → skipped) | n/a | yes, keyless only |
| field inverse (`get_mul_inverse`, table scan) | r+1 per solve | n/a | **not** charged (negligible) |
| receiver admit/verify/repair | `receiver_mul` | `receiver_mul` | separate metric |

Closed forms (g = gen_size, r = observed, k = leaked):
- keyed = **k·g**
- keyless = **r·g + (r+1)(g+1) + (r+1)²(g+2)** (upper bound; exact in generic case) ; r=0 → 2g+3 exact.

Per-phase counts, g=4, GF(2^8), 200 seeds (probe; closed form in brackets):

| u | keyed k | keyed mul | keyless r | knowledge_dot | randomise | solve | keyless total | ticket-17 mean m=4 |
|---|---|---|---|---|---|---|---|---|
| 0 | 4 | 16 | 3 | 12 | 20 | 95.6 [96] | 127.6 [128] | 122.95 |
| 1 | 3 | 12 | 2 | 8 | 15 | 53.8 [54] | 76.8 [77] | 74.45 |
| 2 | 2 | 8 | 1 | 4 | 10 | 23.9 [24] | 37.9 [38] | 37.31 |
| 3 | 1 | 4 | 0 | 0 | 5 | 6 [6] | 11 [11] | 11.0 |
| 4 | 0 | 0 | – | – | – | – | – | – |

Ticket-17 means sit slightly below the bound because zero entries (prob 1/q) skip
elimination rows; more often at q=4/16 than q=256. Max in CSV = bound exactly (128/77/38/11).
forge_attempts = 1 in all 128k keyless trials (no retry cost hidden).

## Verdict
- Like-for-like: yes. Shared work (c', victim, splice) uncounted in both; knowledge use
  (dot products) charged identically: g muls per known constraint. Keyed silently omits nothing:
  its only real work is k dot products; guessing unknown tags is free.
- Keyless extra = arm-specific and legitimate: it has no key, so it must solve for tags that
  satisfy r+1 linear constraints. Now reported separately (phases `knowledge_dot` / `randomise` / `solve`).
- Caveats, all conservative for keyless (inflate it, never keyed):
  - `randomise` (20 of 128 at u=0) is a modelling choice (forgery uniform over solution space,
    tested in `test_keyless_forgery_satisfies_constraints_and_is_random`); a lean forger could set
    free vars to 0. Includes g+1 muls-by-1.
  - naive dense Gauss-Jordan (normalises full row incl. zeros); a lean solver ~(r+1)³/3 — still cubic.
  - Lean lower bound at g=4, u=0 (no randomise, 4×4 elimination on chosen pivots) ≈ 12 dot +
    ~37 solve ≈ 50 muls → still ~3x keyed. Gap is real, just smaller than 8x.
- For the thesis: report per-phase, say "per forged coeff segment", and state that the
  *knowledge-proportional* part is equal (g muls per constraint); the keyless premium is a one-off
  O(g³) solve, independent of payload size.

## Scaling
### vs data_fields (actual sim, g=4, N=2, u=0, GF(2^8), 20 seeds) — flat
| df | 12 | 18 | 48 | 96 | 192 | 1000 |
|---|---|---|---|---|---|---|
| keyed | 16 | 16 | 16 | 16 | 16 | 16 |
| keyless | 127.1 | 127.4 | 127.7 | 128 | 127.4 | 128 |

### vs gen_size g (u=0, df=24, 10 seeds) — keyed g², keyless g³+4g², ratio g+4
| g | 2 | 4 | 6 | 8 | 12 | 16 |
|---|---|---|---|---|---|---|
| keyed | 4 | 16 | 36 | 64 | 144 | 256 |
| keyless | 24 | 128 | 356.8 | 766 | 2301 | 5091 (bound 5120) |

### vs forged segment length L (hypothetical: forge a DATA segment of L symbols; same algebra, scratch probe, g=4, u=0)
keyed = k·L (k=g=4); keyless = r·L + (r+1)(g+1) + (r+1)²(g+2) (r=g-1=3).
| L | 12 | 48 | 96 | 192 | 500 | 1000 |
|---|---|---|---|---|---|---|
| keyed | 48 | 192 | 384 | 768 | 2000 | 4000 |
| keyless | 152 | 259 | 403 | 692 | 1615 | 3116 |
| ratio kl/kd | 3.17 | 1.35 | 1.05 | 0.90 | 0.81 | 0.78 |

→ gap does NOT widen with length; crosses over at L≈116 (keyless needs one fewer dot product per u:
its self-check is free, char 2). Same holds for an N=1 whole-packet forger (L = g + df).

### Ticket 06 (`segmented_attack_sim.py`, g=6, threshold 2, GF(2^8), 8 trials, df 24 and 96 — identical)
| arm | coeff-row select | dots | solve | total |
|---|---|---|---|---|
| orthogonal | 0 | 14 (= 2 targets × (g+1), salt col incl.) | 63 (3 pivots × 3 rows × 7) | 77 |
| MAC compromised | 0 | 36 (= g × g) | – | 36 |
| MAC secret | 0 | 0 (random tags) | – | 0 |
`_independent_coeff_row` is charged in both arms (equal) but costs 0 at the strike (receiver
still in warm-up → nothing accepted to avoid). No randomisation there. Also like-for-like.

## Changes
- `simulation/knowledge_attack_sim.py`: `cnt.phase(...)` around the three keyless steps and the
  keyed dot products. Pure attribution, totals/CSV/RNG unchanged (frozen schema untouched).
- `simulation/knowledge_attack_test.py`: `test_attacker_work_closed_form` — keyed = k·g exact;
  keyless phases exact (knowledge_dot r·g, randomise (r+1)(g+1)), solve ≤ (r+1)²(g+2) and = on
  seed 0; r=0 → 2g+3; g ∈ {4,6}, df ∈ {12,96} (df-independence).
- No fix needed → no effect on reported numbers.
