Status: DONE (2026-09-23) — tickets 10–16 implemented + verified; results below.

# Isolate the recovery mechanism for the keyless↔keyed comparison: inject trust, match the acceptance-oracle width, and pair on identical ground truth

The keyless↔keyed comparison ([[Keyless HMAC]] vs [[Homomorphic MAC]]) is supposed to isolate the *tag/oracle*, but two confounds leak in through recovery. First, the keyless arm's unpaired + IC-refinement paths use the ADR-0002 **exact linear solve** (`recover_packet_linear`), which the keyed arm has no closed form for and falls back to bit-flip search — so any cost/latency/recovery-rate gap is partly the *solver*, not the tag. Second, end-to-end recovery bundles [[Sniffing]] (trust classification) with repair, so a gap can come from detection quality (e.g. the N=5 poisoning starvation) rather than from repair.

We want a comparison whose only surviving difference is the acceptance oracle: keyless orthogonality-to-helpers vs keyed MAC-tag verification.

## Decision

Add an **isolated recovery comparison** harness (additive — the end-to-end sim, `classify_segment_trust(_mac)`, `verify_count`, and the ADR-0002 solve are all left in place for every other use). Within this harness only:

**Same algorithm, both arms.** ACR-localize (coefficient_first) → bit-flip up to Hamming distance. The keyless arm runs **bit-flip only** here (its exact linear solve is bypassed), so both arms execute the identical search and the only difference is the oracle.

**Injected trust, no sniffing.** The destination is *given* known-good verification material — clean [[helper packet]]s (keyless) and keys (keyed) — from ground truth (the harness knows what it corrupted). Trust classification is not measured here. `verify_count` and [[Sniffing]] (ADR-0004) are untouched and still used elsewhere.

**Matched acceptance-oracle width `W`** (the silent-decode dial, recovery-acceptance only):
- keyless: accept a fix iff self-orthogonal **and** orthogonal to **W** helper packets;
- keyed: accept iff **W** of its tags verify (first-W of the carried tags).
- The keyless **self-check is free structure and is not counted** toward `W` — the resulting lower keyless silent-decode is a *reported result of the scheme*, not a confound to equalize. Nominal collision ≈ `q⁻ᵂ` on both sides. Caveat: keyless "checks" are orthogonality to *helper packets* (data-dependent), so if the chosen `W` are linearly dependent the real floor is worse than `q⁻ᵂ`; keyed keys are i.i.d. so `q⁻ᵂ` is exact. Measured, not engineered away.

**Overhead parity.** Keyed carries `num_keys = gen_size` tags (matching the keyless arm's `gen_size` tag columns; keyless additionally carries one salt byte per segment — a negligible, separate overhead detail) but verifies only the `W`-subset.

**Pool.** `G = gen_size` clean helper packets — fixed, never corrupted — are the ACR basis (both arms) and the keyless acceptance witnesses. `T` additional (recoded) **target packets** (knob, default `gen_size`) are corrupted and are what recovery is scored on. This keeps the ACR basis always available, so BER drives target corruption, not basis availability.

**Three configs, each run in both arms:**

| config | error model | coeff repair | measures |
|---|---|---|---|
| coefficient_first | whole-packet BER | yes | full recovery incl. coeff repair |
| ACR-only (a) | data-payload BER only | no (coeffs clean) | pure data-segment recovery, coeffs given |
| ACR-only (b) | whole-packet BER | no (coeff-broken targets drop **symmetrically**) | data recovery when coeffs can be hit |

coefficient_first vs ACR-only-(b), both at whole-packet BER, isolate the coeff-**repair** stage's effect on any arm gap; (a) is the clean pure-data baseline.

**Paired on identical ground truth (common random numbers).** A shared seed fixes the same source payload, the same coefficient vectors, and the same helper/target split for both arms. The **error pattern on the information columns `[coeff | payload]` is applied identically** to both arms — this is the corruption recovery actually fixes, so "who recovers the same errors better" is exact and paired. The **tag/redundancy region cannot be byte-identical** (keyless = salt + orthogonal tags; keyed = MAC tags, no salt — different layouts), so tag/salt corruption is **seed-matched per-arm** (same BER, same RNG stream), not the same bytes. For the ACR-only data-only config (a), errors live only in the payload, so both arms face exactly the same corruption end to end.

**Metrics over the `T` targets:** recovery rate, silent-decode rate, recovery field-ops — plus a **per-target head-to-head** (win/loss/tie on identical corruption), which the paired design makes possible.

**Sweeps:** `W ∈ {1, 2, 3}`; `G = gen_size`; `T = gen_size` default.

## Consequences

- New harness alongside the existing comparison sim; end-to-end recovery, sniffing, `verify_count`, and the ADR-0002 solve are unchanged and still used everywhere else. A `W`-cap parameter is threaded into the acceptance oracles with defaults that leave existing callers untouched.
- This comparison is deliberately **not end-to-end** — it measures the repair sub-mechanism only. Detection/sniffing effects (e.g. N=5 poisoning starvation) are idealized out by construction.
- Keyed `num_keys = gen_size` in this harness changes its wire overhead relative to other keyed configs — scoped to this comparison.
- The keyless silent-decode floor may sit structurally below the nominal `q⁻ᵂ` (helper-independence), and — separately — above the keyed floor is not guaranteed either; the measured rates report the truth rather than an assumed bound.
- Priority item at time of writing (2026-09-20).

## Results (2026-09-23)

Sweep: `logs/isolated_recovery/20260923_005218_gen6_T6_seeds200/raw_trials.csv` (frozen schema v1),
plots `logs/isolated_recovery_plots/`. G=T=gen_size=6, 3 data segs × 6 B, GF(2^8), bit-flip only, max_hd=2,
BER ∈ {1e-3…1e-2}, W ∈ {1,2,3}, 200 seeds (1200 targets / cell, 6000 / (config,arm,W,span) pooled over BER).

**Silent-decode rate, pooled over BER, repair_span=payload** (segment span within ±0.1 pp, except where noted):

| config | keyless W=1/2/3 | keyed W=1/2/3 |
|---|---|---|
| coefficient_first | 4.15 / 3.03 / 2.07 % | 14.68 / 0.22 / 0 % |
| ACR-only (a) data-only | 0 / 0 / 0 % | 3.28 / 0 / 0 % |
| ACR-only (b) whole-packet | 0 / 0 / 0 % | 2.65 / 0 / 0 % |

(`segment` span: keyless ACR-only 1/6000 at W=1; keyed ACR-only W=2 1–3/6000.) Keyed peaks at 39.8 %
(coefficient_first, W=1, BER 1e-2). At W=gen_size both arms give 0 silent in every config (test-asserted).

- **Keyed tracks q⁻ᵂ**: silent collapses from W=1 to W=2 to 0 at W=3; oracle Monte Carlo matches q⁻ᵂ
  (GF(2^4) W=1..3, GF(2^8) W=1).
- **Keyless on random errors sits at ≈q⁻⁽ᵂ⁺¹⁾** (the free self-check), and in the data segments it is 0 at every W.
- **Keyless coefficient_first silent decodes are structural, not wiring** — the caveat above, concretely: the
  identity-coeff helpers are *sparse* in the coefficient segment (helpers 0..W−1 are zero at coeff column W and at
  some tag columns), so a whole-segment coeff repair that turns a tag-byte flip into "flip coeff[W] + that tag byte"
  passes self-check + W witnesses. Hence W barely moves it (4.2→3.0→2.1 %); it closes only at W=gen_size.
  Keyed rejects the same candidate. Pinned in `simulation/isolated_recovery_verification_test.py`.
- **Recovery rate**: data-only (a) arms are equal (≈92–100 %); whole-packet configs keyless ≪ keyed at payload span
  (keyless self-check rejects harmless salt/tag hits; keyed only checks W tags). `repair_span=segment` narrows it
  (coefficient_first BER 4e-3 W=2: keyless 41→65 %, keyed 88→99 %).
- **Coeff-repair stage** (coefficient_first vs ACR-only (b)): buys recovery in both arms at a large ops cost
  (W=2, BER 1e-3→1e-2: keyless 4·10⁴→9·10⁵ vs 1.6→2.5·10⁴ ops/call; keyed 1·10⁴→4.5·10⁵ vs 4·10³→1.3·10⁴)
  and is where every keyless silent decode comes from.

Regression: full suite green (bar pre-existing rref_test / procedural_rref_test); fixed-seed
`scheme_comparison_sim` spot-run (8 segmented/MAC schemes, 24 trials) byte-identical to pre-ticket-10 (`d72fa08`).

**Payload-only follow-up (2026-09-23):** configs `coefficient_first_info` / `arc_only_b_info` (error model `info_only`:
identical [coeff|payload] flips, no salt/tag hits; 200 seeds). ACR-only: keyless = keyed recovery (79.6 % at W≥2) → the
whole-packet gap is entirely redundancy-byte corruption seen by keyless' full self-check vs keyed's W-subset. coefficient_first:
keyed 97.3 % vs keyless 90.4 % (W=2); the residual is the keyless coeff-segment blind spot, which fires without tag
corruption (keyless silent 5.3 / 4.2 / 2.5 % at W=1/2/3).

**Cost accounting correction (2026-09-25, tickets 18 + 20):** the ops figures above were measured with (a) a
keyed verify that computed all W tags per candidate and (b) the post-repair whole-pool check (keyless
all-pairs O(M²) ~15k ops) counted inside recovery. Fair repair-only cost (keyed early exit, pool check
reported separately as `final_check_ops`): **keyless = 2.0× keyed** at every W and BER (per-candidate
13-B whole-segment self-check vs 6-B payload tag); ~2–2.3× across HD 1–5. Outcomes unchanged.
HD frontier (ticket 19): HD3 = sweet spot; HD5 infeasible (max 10–25M ops/recovery).

