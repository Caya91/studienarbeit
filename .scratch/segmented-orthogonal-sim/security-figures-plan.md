# Plan: security comparison figures (keyless vs keyed)

Draft 2026-09-24, for review. Draft figures: `logs/security_figs_draft/` (D1–D4 + the script that makes them). Existing ticket-17 data only, no new sims yet.

## The story (one line per act)

**Thesis claim:** per unknown constraint both tags are equally strong (q^-u). They differ in HOW an attacker removes unknowns: keyless falls to *listening*, keyed only to *key theft*. Two things weaken both: the receiver's own repair, and segmentation (splice).

| act | message (= figure title) | figure | series |
|---|---|---|---|
| 1 | "Same tag strength, different doors" | **D1** two panels: x = packets observed / keys leaked | keyless, keyed (+ gray theory) |
| 2 | "The receiver helps the forger" | **D3** bars: admit rate ÷ q^-u per u | keyed repair, keyless tie-break (+ keyless repair-bait, E1) |
| 3 | "Segmenting unbinds coeffs from data: both fall" | **D2** bars: silent % per attack variant | keyless-seg, keyed-seg, N=1 |
| 4 | "What each attacker gets" (summary) | **D4** bars: bits of security per attacker type, GF(2^8) | keyless, keyed |

Talk: D1 → D2 → D4 (3 slides); D3 as backup slide. Thesis: D1, D3, D2, D4 + one appendix validation plot.

## Figures

**D1 "two doors"** (replaces `silent_vs_u` + `oracle_vs_u`)
- Left: x = r packets observed. Keyless climbs q^-(g-1-r) → 1. Keyed flat at q^-g (listening gives nothing).
- Right: x = k keys leaked. Keyed climbs → 1. Keyless flat (no key to steal).
- Same slope in both panels = the "equal strength" result, with no need for the abstract u axis.
- y = strict tag check (clean). Production effects go to D3, not here.
- Field: GF(2^2) = every point measurable (keyed flat 13/4000). GF(2^4) = more realistic, but keyed flat is 0/4000 (bound only). **Recommend GF(2^4) main, GF(2^2) appendix.**
- Caveat that has to be on the figure: "keyed flat" holds only for a forger that does NOT splice (act 3).

**D3 "receiver amplification"** (replaces `repair_effect_keyed`)
- Linear y axis: amplification factor = production admit rate ÷ q^-u. Line at 1× = ideal tag. Theory tick on each bar.
- Keyed repair ≈ 1+u·m, so it GROWS with u and with field size (GF(2^8): 9× … 33× = 3–5 bits lost). Keyless tie-break ≈ 1+u(1−1/q)² (≤ 2 bits).
- Weak spot: at GF(2^4) u=3 only 16 and 6 events, so the CIs are wide. Fix = E3, or show GF(2^2).
- **Unfair until E1 runs** (keyless repair-bait not measured). Without E1 don't title it "keyed weaker in production".

**D2 "splice"** (new; Part A had no figure)
- Grouped bars, 4 variants: random change (control), splice, scale, zero. Result 100/100/0 in every case except the control.
- Talk version: add a packet diagram (coeff segment of packet A + data segments of packet B, each tag ✓, decode ✗).

**D4 "security budget"** (new summary; replaces the "security matrix" heatmap idea)
- GF(2^8), g=4, analytic from the validated formulas. y = −log2 P(silent) in bits, linear, 0–32.
- Solid bar = production receiver (worst strike). Dashed cap = tag alone.
- Attacker types: outsider / listener (2 packets) / on-path (all) / 2 keys leaked / all keys leaked / splice.
- Readout: keyless 22 bits vs keyed 26 bits against an outsider (the keyless self-check is public, so it has one symbol less); keyless drops to 0 under listening; keyed only under a key leak; both 0 under splice.
- Key-leak columns: keyless keeps its r=0 value, because that attacker has not listened. Caption must say so.

**Drop:** `attacker_work_vs_u` → one sentence (≤ 123 multiplies, work is no barrier). `silent_vs_u` and `oracle_vs_u` are replaced by D1. Appendix: one validation plot, y = −log_q(P) vs u, both fields fall on the diagonal y=u (justifies the GF(2^8) extrapolation in D4).

## New work needed (ranked)

- **E1: keyless repair-bait forger (A11). Recommend: DO. Effort M.**
  - Reading the code: an unpaired broken coeff segment is first linear-solved (g unknown columns vs g−1 trusted packets = underdetermined → None). Then the receiver bit-flips at distance 1 over the whole segment (payload+salt+tags) and takes the first candidate that passes self+cross (`_search_single_by_bitflip` returns the first match, no uniqueness check).
  - So a forger with a 1-bit self-check error (deliberately failing) offers about L = 2g+1 = 9 self-passing neighbours per packet, each a fresh q^-u lottery ticket.
  - **Prediction:** amplification ≈ up to L at r=0, shrinking as r grows (a neighbour must also meet the known cross constraints). The opposite trend to keyed (1+u·m grows with u).
  - Changes D3 (3rd bar) and D4 (keyless production bars).
- **E2: keyed "listening" measured, not assumed. Effort S, optional.** Keyed k=0 with the strike at index r. Theory and the existing test say it is independent of r, and GF(2^2) k=0 already measures it (13/4000). Likely skip.
- **E3: more seeds for D3 u=3 at GF(2^4). Effort S, background.** `--seed-start 4000 --trials 20000`, u=3 cells only, pooled by the replot script.
- **E4: only if you pick the splice fix.** Bound variant of both schemes; D2 gets a "bound" series (expect 0%); D1/D4 lose their caveat.

## Decisions for you

1. **Splice: fix or limitation?**
   - Recommendation: limitation + N=1 as evidence that binding works; the fix goes to future work.
   - Reason: binding changes the tag input, which hits recovery, and all recovery sims would need re-running. Convergence first.
   - Consequence: D1/D4 carry the "non-splicing forger" caveat.
2. **Run E1?** Recommend yes: without it the production comparison is one-sided.
3. **D4 in bits at GF(2^8), analytic.** OK, or do you want only measured small-field numbers in the thesis?
4. **D1 field:** GF(2^4) main + GF(2^2) appendix?
5. **Output:** matplotlib PNG for the thesis. For the talk, native pptxgenjs charts (D2/D4 bars are easy; D1 needs a log axis) or PNG?

## Style notes

- Thesis colours: keyless `#588157`, keyed `#3d405b`.
  - Validator: CVD separation fine (ΔE 20), but both FAIL the chroma floor (the navy reads almost gray).
  - Keep them for consistency, but never colour alone: shapes (●/■) + direct labels on every figure. Theory lines/ticks in neutral gray/black, never an arm colour.
- One message per figure, stated in the title. No legend box when direct labels do the job.
- Style guide red = attack: use it only in the D2 packet diagram (✗ decode), not in data plots.
