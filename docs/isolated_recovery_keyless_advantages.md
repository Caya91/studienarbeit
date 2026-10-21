# Where keyless beats keyed — isolated recovery comparison (ADR-0013)

Selling points for the keyless orthogonal scheme vs the keyed homomorphic MAC, from the isolated
recovery harness (`simulation/isolated_recovery_sim.py`). Same algorithm in both arms (ACR-localize →
bit-flip, max HD 2), injected trust, identical corruption on `[coeff | payload]`, matched acceptance
width **W** (keyless: orthogonal to W helper packets + free self-check; keyed: W of its MAC tags verify).
Both arms carry gen_size tag symbols per segment (keyless +1 salt byte).

Data: gen6 = G=T=6, 18 B data, 800 seeds (4800 targets/cell); gen10 = G=T=10, 30 B data, 200 seeds
(2000 targets/cell); GF(2^8). Rates are per scored target; ± = Wilson 95 % CI.
Runs: `logs/isolated_recovery/*_gen6_*`, `*_gen10_*`, `*info_only*` (2026-09-23).

---

## 1. Near-zero silent decodes at the weakest oracle (W=1) — the headline

When both schemes check just **one** thing, keyed accepts wrong repairs often; keyless almost never does.

Silent-decode %, W=1, pooled over BER 1e-3…1e-2:

| config | keyless | keyed | factor |
|---|---|---|---|
| ACR-only (a), data-only BER, gen6 | **0.01** | 3.51 | ~350× |
| ACR-only (a), data-only BER, gen10 | **0.03** | 9.48 | ~300× |
| ACR-only (b), whole-packet BER, gen6 | **0.09** | 2.50 | ~28× |
| ACR-only (b), whole-packet BER, gen10 | **0.06** | 4.31 | ~70× |
| ACR-only (b), payload-only BER, gen6 | **0.03** | 2.65 | ~90× |

**Why (the mechanism, not luck):** the keyless self-check (`<x,x> = 0`, an XOR over the whole segment) is
structure that comes for free and is always on. So keyless at W=1 is really *two* independent checks
(≈ q⁻², 1/65 536) against keyed's one (q⁻¹, 1/256). Confirmed by oracle Monte Carlo: keyless random-error
wrong-accept ≈ q⁻⁽ᵂ⁺¹⁾, keyed ≈ q⁻ᵂ (`isolated_recovery_verification_test.py`).

**Phrasing for the thesis:** *"At equal acceptance width, the orthogonal tag's built-in self-check acts as
one free additional check: keyless at W=1 matches keyed at W=2 in data-segment repair (0.01 % vs 0.01 %
silent decodes, gen6)."*

## 2. Keyless stays flat as the channel gets worse; keyed does not

Silent-decode % at W=1, data-only BER (ACR-only (a)):

| BER | 1e-3 | 2e-3 | 4e-3 | 6e-3 | 1e-2 |
|---|---|---|---|---|---|
| keyless gen6 | 0.00 | 0.00 | 0.00 | 0.00 | 0.04 ± 0.07 |
| keyed gen6 | 0.10 | 0.56 | 2.17 | 4.10 | **10.62 ± 0.87** |
| keyless gen10 | 0.00 | 0.00 | 0.00 | 0.10 | 0.05 ± 0.14 |
| keyed gen10 | 0.45 | 1.35 | 6.60 | 11.95 | **27.05 ± 1.95** |

More bit errors → larger bit-flip search → more candidates tried → more chances for a 1/q collision.
Keyed's silent rate grows with every candidate; keyless' q⁻² floor absorbs it.

ACR-only (b) whole-packet shows the same shape: keyed W=1 0.25 → 5.92 % (gen6) and 0.25 → 8.85 % (gen10);
keyless ≤ 0.17 % throughout.

## 3. Keyless stays flat as the generation grows; keyed does not

Going gen6 → gen10 (W=1, pooled over BER):

| config | keyless | keyed |
|---|---|---|
| ACR-only (a) | 0.01 → 0.03 % | 3.51 → **9.48 %** (×2.7) |
| ACR-only (b) | 0.09 → 0.06 % | 2.50 → **4.31 %** (×1.7) |

Larger generations mean larger segments and searches, so keyed at a fixed W degrades. Keyless doesn't.

## 4. Higher recovery rate at W=1 on data corruption

Because keyed's wrong-accepts become silent decodes instead of correct repairs, keyless recovers more
targets at W=1 (ACR-only (a), recovery %):

| BER | 1e-3 | 4e-3 | 6e-3 | 1e-2 |
|---|---|---|---|---|
| keyless gen6 | 100.0 | 99.5 | 98.1 | **92.7** |
| keyed gen6 | 99.9 | 97.6 | 95.1 | 87.1 |
| keyless gen10 | 99.8 | 98.0 | 93.5 | **75.4** |
| keyed gen10 | 99.4 | 92.9 | 87.0 | 68.5 |

Up to +5.6 pp (gen6) and +6.9 pp (gen10) at BER 1e-2. At W≥2 the two are identical (same corruption, same
method, both oracles strong) — keyless is never worse on data corruption.

## 5. Keyless never accepts a packet with any damaged byte

The self-check covers every byte of the segment (payload, salt, all tags). A keyless-accepted packet is
consistent end to end; keyed at W<gen_size never looks at tags W…gen_size−1. In the whole-packet runs
≈ 20 % of targets are damaged only in salt/tag bytes: keyed passes those as "recovered" (correct, since
their data is fine), keyless rejects them. **Use with care** — see caveat C: this costs keyless recovery
rate on a real channel. It's an integrity property ("nothing unverified gets through"), not a recovery win.

---

## Caveats — state these alongside the claims (reviewers will find them)

- **A. The advantage is a low-W effect.** At W≥2 keyed silent decodes are ≈ 0 in the ACR-only configs as
  well (≤ 0.06 %), so both arms are equally safe there. The honest claim is "keyless reaches the safety of
  keyed-W+1 for free", not "keyed is unsafe".
- **B. coefficient_first is not a keyless win at W≥2.** Keyless has a structural floor of 2–5 % silent
  decodes when repairing the *coefficient* segment (the identity-coefficient helpers are sparse there, so
  W checks leave coefficient column W unconstrained; closes only at W=gen_size). Keyed there: 0.18 % (W=2),
  0 % (W=3). At W=1 keyless is better *overall* (4.07 vs 14.25 % gen6), but **at low BER keyed W=1 is better**
  (1e-3: keyless 4.44 % vs keyed 0.90 %; 2e-3: 5.77 vs 3.25 %). Only from BER ≥ 4e-3 does keyless win.
  Don't include coefficient_first in the headline plot.
- **C. Whole-packet recovery rate favours keyed** (e.g. ACR-only (b) W=2: 34 % vs 59 %), because keyless
  rejects packets with harmless salt/tag damage (point 5). With payload-only corruption the two are equal
  (79.6 % vs 79.6 %).
- **D. Keyless is NOT cheaper — repair costs ≈2× keyed at every W and BER.** Fair accounting (ticket 18:
  keyed stops at the first bad tag; ticket 20: the post-repair pool check is costed separately):
  ACR-only (a) repair-only keyless 5.5–6.1k vs keyed 2.7–3.3k ops (W 1–6, 500 seeds), 14 vs 10–11 ms. The
  2× is the price of the whole-segment self-check (13 B incl. tags vs 6-B payload per MAC tag) — the same
  check that gives keyless its free extra safety. Earlier "keyless cheaper at W≥4" and "keyed 3× cheaper"
  were both accounting artifacts — use neither. The keyless post-repair pool check (all packet pairs,
  ~15k ops at gen6 vs keyed ~3k) is a separate, O(M²) cost if a receiver runs it.
- **E. Scope.** Isolated repair sub-mechanism only: trust is injected (no sniffing), bit-flip only (the
  ADR-0002 exact solve is off in both arms). Not an end-to-end or adversarial result; keyless-vs-keyed
  *security against an attacker* is a separate argument (keyless has no key to distribute but is
  white-box forgeable; see intelligent-attacker ADR-0008).
- **F.** Tiny keyless ACR-only silent rates (≤ 0.1 %) appeared at 800 seeds; not yet diagnosed.

## Plots

| figure | file | use |
|---|---|---|
| **Headline:** silent @ W=1 vs BER, ACR-only (a)+(b), gen6 solid / gen10 dashed | `logs/isolated_recovery_plots/combined/silent_w1_vs_ber_payload.{png,pdf}` | points 1–3 |
| Same, per setup | `logs/isolated_recovery_plots/{gen6,gen10}/silent_w1_vs_ber_payload.*` | |
| Silent vs BER, all W, all configs (shows caveats A/B honestly) | `.../{gen6,gen10}/silent_vs_ber_payload.*` | appendix / backup |
| Recovery vs BER, all W | `.../{gen6,gen10}/recovery_vs_ber_payload.*` (ACR-only (a) panel) | point 4 |
| Payload-only fairness check | `.../gen6_info_only/recovery_vs_ber_payload.*` | caveat C |

Regenerate the headline figure (PowerShell, from repo root):
```powershell
$env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; .\.venv\Scripts\python.exe -c "from scripts.isolated_recovery_plots_from_csv import load, plot_silent_w1; g6=load('logs/isolated_recovery/*_gen6_T6_seeds[26]00'); g10=load('logs/isolated_recovery/*_gen10_*'); plot_silent_w1(g6, 'logs/isolated_recovery_plots/combined', setups=[('gen_size 6', g6), ('gen_size 10', g10)])"
```
