# Security analysis plan: forged packets → silent decodes, keyless vs keyed

Draft 2026-09-23. **Plan only. Nothing implemented.** For review.

**Decisions 2026-09-23:**
- Keys are always per generation, so A2 (replay) and A8 (blast radius) are dropped.
- Selected: A3 (splice test) + A5 (partial knowledge) → ticket `.scratch/segmented-orthogonal-sim/issues/17-splice-test-and-partial-knowledge-forgery.md`.
- The rest is parked.

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

## 0. Scope

- **Success** = silent decode: the forged packet is admitted, the generation decodes, and the result ≠ ground truth (ADR-0008). Passing the oracle alone does not count.
- **Arms**: keyless = `SegmentedScheme`, keyed = `SegmentedMacScheme` (naming convention). **Controls**: N=1 (`OrthogonalScheme`, and a whole-packet MAC), used to separate what segmentation causes from what the tag causes.
- **Attack the production admit rules**: `classify_segment_trust` (greedy-peel core + `verify_count` witnesses) and `SegmentedMacScheme.admit`.
  - `segmented_attack_sim.py` (ticket 06) instead uses its own absolute-count stand-in (`_orth_segment_trusted`).
  - Greedy-peel changes the picture. ADR-0008's "honest majority gives zero protection" held for the absolute-count rule only.

## 1. What already exists

| piece | state |
|---|---|
| ADR-0008 + `intelligent_attack_sim.py` | N=1 targeted forgery, absolute-count rule |
| `segmented_attack_sim.py` (ticket 06) | coeff-segment forgery. keyless silent 1.0, MAC key secret 0.0, MAC key compromised 1.0. The "cliff vs flat floor" result. |
| gaps | only two key states (all or nothing). Old trust rule. The keyed-secret forger is naive (random coeff row + bogus tag). |

## 2. Attack catalogue (silent-decode attacks)

u = number of verification constraints the attacker cannot compute. q = 2^m.

| # | attack | attacker needs | keyless (predicted) | keyed (predicted) | sim effort |
|---|---|---|---|---|---|
| A1 | **Blind injection / guessing**: random packets or random tags, A attempts | nothing | ≈ 1-(1-q^-u)^A | same | S |
| A2 | **Cross-generation replay**: valid packet(s) from an old generation | old traffic | rejected (not orthogonal to the current generation) | **accepted if the key is reused across generations** (session key); rejected if rekeyed per generation | S |
| A3 | **Segment splice / scale** (NEW, analytic, unverified): mix segments from different linear combinations, scale one segment by α≠1, or zero the data segments | 1 observed packet, ~0 ops | predicted **vulnerable** | predicted **vulnerable, no key needed** (homomorphism) | S |
| A4 | **Targeted forgery, on-path full view** (existing) | forwarded packets | 1.0 (linear solve) | needs the key | done (port to production rule) |
| A5 | **Partial-knowledge forgery**: keyless attacker observed r packets or fraction f; keyed attacker holds k of W keys | partial view / leaked keys | ≈ q^-u | ≈ q^-u | M |
| A6 | **Sybil flood / fake-generation majority**: b mutually-orthogonal fake packets (`tag_generation_segmented` on fake data). Replaying a whole old generation is the zero-compute variant. | nothing (zero knowledge) | **peel core flips once b > honest self-passers** | rejected (secret key) / 1.0 (leaked key) | S–M |
| A7 | **Structural blind spot**: flip coeff[j] plus the matching tag byte. Passes the self-check and the first W sparse witnesses (ADR-0013 finding). | knows the witnesses are systematic | zero-work forgery *if* the witnesses are sparse | no analog | S (check first whether it is exploitable end-to-end with dense recoded witnesses) |
| A8 | **Compromise blast radius**: one compromise at generation g0; how many later generations can be forged | temporary access | only the observed generations | every generation until rekey | M |
| A9 | Collusion (pooled views or keys) | several nodes | same axis as A5 | same axis as A5 | none (reuses A5) |
| A10 | Pollution through recoding relays: in-network verification | relay position | relays verify key-free | relays need keys (more exposure) or skip verification | L (`network_sim`) |
| A11 | Recovery-oracle abuse: crafted corruption so the HD search "repairs" to a wrong valid packet | error-pattern knowledge | above channel false-repair | same | M |

**Out of scope** (not silent decodes, DoS only): tag pollution (valid packets dropped), CPU exhaustion via repair search, drop/jam, same-generation duplicate replay. At most a list plus one sentence in the thesis.

### A3 reasoning (verify first)

- Both segmented arms verify each segment **independently**. The coeff segment and the data segments are never bound together.
- Segment tags are linear per segment in both arms (homomorphic). So these forged packets pass **every** segment check:
  - `[coeff seg of combination A | data segs of combination B]`
  - `[p with one data seg × α]`
  - `[coeff seg | all-zero data segs + zero tags]`. The zero vector is self- and cross-orthogonal, and its MAC is 0.
- Their coefficients are inconsistent with the data, so the decode is wrong.
- **Innovative requirement**: the on-path relay swaps a fresh packet's data segments before forwarding it. Its coeff row is new to the receiver, so it pivots.
- **N=1 is immune**: one tag covers `[coeff|data]`, so the same combination is forced across all columns.
- **Consequence if confirmed**: ticket 06's "MAC key secret → 0" holds only against the naive forger. The fix is to **bind the coefficients into every segment's tagged input** in both arms (no extra bytes on the wire, some extra compute). Otherwise report it as a shared limitation.

## 3. Fairness rules (quantifiable, like-for-like)

1. Same success definition and ground-truth grading (re-decode vs source).
2. Same layout: gen_size, data_fields, N, m. Overhead parity (tags/segment = gen_size; keyless +1 salt).
3. Same acceptance width W where it applies (ADR-0013). Keyed verifies a W-subset.
4. **Only knowledge differs.** Same attacker position, injection budget A, strike time S, and op counter (`CountingField`).
5. **Normalize knowledge to u**:
   - keyless: u = rank of the receiver's checking span − rank of its overlap with the attacker's view. At decode time ≈ gen_size−1−r.
   - keyed: u = W − (leaked keys among the verified ones).
   - Theory ≈ q^-u per forgery. Draw the theory line on every plot.
6. Paired seeds (common random numbers), as in ADR-0013.
7. **Rare events**: q^-u at m=8 cannot be measured (u=2 → 1.5e-5).
   - Measure at m=2/4 to validate the theory, then extrapolate m=8 analytically.
   - Wilson CIs. Report zero counts as an upper bound (rule of 3: <3/n).
8. Report four numbers per attack: silent-decode rate, attacker ops per success, forged packets injected, and knowledge required plus how it is acquired (passive / insider).

## 4. Your idea: keyless forged packets vs keyed leaked keys

- **Good core, one fix.** "Keyless attacker forges packets" vs "keyed keys leaked" compares an action with a knowledge state.
  - Matched pair: keyless **observed packets** (r, or fraction f) ↔ keyed **leaked keys** (k). Both are knowledge.
  - Forging (A, ops) is the same action axis for both arms.
- **Prediction**: plotted against u, the two curves coincide (both ≈ q^-u).
  - That is honest and fine: equal knowledge gives equal security.
  - The real difference is the **price of one knowledge unit**. Keyless: passive observation (free for an on-path node). Keyed: node compromise. Show it as an annotation or second axis.
- **The keyless advantage lives elsewhere**, and A2/A6/A8/A10 measure it: no key to leak, generation binding for free (replay), a blast radius limited to observed generations, key-free relay verification. The keyless *weakness* is also measured: A6 (majority), A4 (on-path = free forgery).
- **Caveat 1**: keyless u depends on time. The receiver's pool grows beyond the attacker's view, and the peel catches the forger later. Keyed u is static. So for keyless, fix the strike time and sweep the view fraction f.
- **Caveat 2**: settle A3 first. If splicing works, the A5 forger must be non-splicing (and say so), or run A5 on binding-fixed or N=1 variants.

## 5. Order (easy → hard, all paper-worthy)

| step | what | output |
|---|---|---|
| 0 | A3 splice/scale: small test on both arms + N=1 control | yes/no. Decide: fix or limitation |
| 0b | Infra: `segmented_attack_sim` → production admit rules (or a `trust_rule` switch) | re-run ticket-06 cells |
| 1 | A1 blind + A2 replay | F3 + F1 rows |
| 2 | A5 knowledge axis (**main figure**) | F2 |
| 3 | A6 Sybil / replay-flood | F4 |
| 4 | A8 blast radius (multi-generation) | F5 |
| later / future work | A7, A10, A11, DoS | text only |

Tier 1 (minimum for the paper) = steps 0–2. Convergence first (thesis status map).

## 6. Target figures

- **F1** security matrix: attacks × arms (keyless / keyed-secret / keyed-leaked) → silent rate. Headline table/heatmap.
- **F2** silent rate vs knowledge u (keyless observed / keyed leaked). m=4 measured + theory, m=8 theory.
- **F3** silent rate vs forged injections A (blind), m ∈ {2,4,8}.
- **F4** silent rate vs attacker share b/(b+h) (Sybil). Predicted step for keyless near 0.5; keyed flat.
- **F5** compromised generations after one compromise event (blast radius).
- (opt) **F6** attacker ops per success vs gen_size.

## 7. Open points (for the joint review, not blocking)

- A3: fix by binding, or report as a limitation?
- Keyed key lifetime: per generation or per session (drives A2, A8)?
- Keyless witness choice is the first `verify_count` core members: deterministic, so the attacker knows the witnesses. Random witness selection is a cheap hardening.
- Greedy-peel tie-break (`max` over a set) with a forger that disagrees with exactly 1 honest packet: check whether the forger survives.
- Off-path observation model: each packet seen i.i.d. with probability f?
- Budget: Tier 1 only?
