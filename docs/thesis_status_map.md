# Thesis status map — finish-line checklist

Purpose: converge, don't explore. Machinery is built; remaining work is runs + writing.
Generated 2026-09-16. Updated 2026-09-29.

## Coverage vs. thesis task requirements (the 6 focus points)

| # | Task requires | Status | Notes |
|---|---|---|---|
| 1 | Lit review: pollution, recovery, HMAC verify | 🟡 research done, write-up not | sources in `docs/research/`, glossary in `CONTEXT.md` |
| 2 | Implement combined recovery + HMAC verify | ✅ done | orthogonal scheme, ACR+linear-solve, segmented+pairing, IC-refinement both arms (tkt 07) |
| 3 | Detection speed & recovery vs conventional ARQ | ✅ framing closed | `docs/arq_baseline_framing.md` — CRC/MAC detect-drop-resend = ARQ; overhead axis. Writing-only left |
| 4 | Latency, throughput, computational overhead | 🟡 infra done, headline figure pending | tick/goodput sim (ADR-5/6) + op-count methodology note |
| 5 | Trade-offs: overhead vs reliability | 🟡 pending same figure | 4-metric comparison (tkt 03/09) |
| 6 | Intermediate presentation + final report | 🟡 deck done, report not | TUD deck built; report unwritten |

## ✅ DONE (banked)
- Orthogonal-tag RLNC over GF(2^m) + field ops
- Zero-tag failure analysis + salt-byte fix (ADR-0010) — novel contribution
- Sniffing/trust (ADR-4), acceptance oracle (ADR-1), ACR + linear-solve recovery (ADR-2)
- Segmented tagging + segment-scoped trust + pairing (ADR-12), IC-refinement both arms
- Baselines built: CRC HD-search (ADR-11), keyed homomorphic Combined-Recovery MAC (tkt 04)
- Attacker sim keyless-vs-keyed (tkt 06)
- Isolated recovery comparison, ADR-0013 (tkt 10-16), keyed early-exit verify (18), HD feasibility frontier (19), repair-only cost (20)
- Pareto sweep keyless N x df x BER (scripts/pareto_sweep.py)
- Security sims (tkt 17): splice attack CONFIRMED on both segmented arms (needs no key; N=1 immune); q^-u equal tag strength; keyed repair amplification; ADR-0008 addendum
- Unit-tag-column guard + verifiable exact-solve rule (silent-decode fix 2026-09-25), merged to main 2026-09-29
- Computation-axis methodology note (op-counts vs wall-clock)
- Intermediate presentation deck

## 🎯 NEEDED TO SUBMIT (the finish line)
1. ~~Run tkt 03 — full N-sweep, pick best N/strategy~~ ✅ done → `docs/segmented_n_sweep_findings.md` (winner: keyless N=5 coefficient_first)
2. Run tkt 09 — headline keyless-vs-keyed figure (recovery rate, silent pollutions, completion time, overhead) — data already in the tkt 03 run; just redraw N=5 panels + label ARQ
3. ~~Label the ARQ baseline~~ ✅ framed in `docs/arq_baseline_framing.md`; just wire the label into the headline figure when it runs
4. Write the lit review (§1) — assemble from existing sources
5. Write the report — assemble from ADRs 1–12 + methodology note + CONTEXT.md

## 🔶 OPEN DECISIONS / SMALL ITEMS (2026-09-29)
- Splice: bind coeffs into every segment's tag (fix) vs report as limitation (plan recommends limitation + N=1 as evidence)
- Security figures D1-D4 (`.scratch/segmented-orthogonal-sim/security-figures-plan.md`): run E1 keyless repair-bait forger? E3 more seeds? D4 analytic at GF(2^8)? D1 field?
- Re-check ticket-17 numbers (q^-u, amplification) after the unit-tag-column guard
- Tidy: 3 mis-collected helper "tests" (fixture errors) in generate_symbols_test / othrogonal_tag_creator_test

## ✂️ CUT TO FUTURE WORK (explicitly, guilt-free)
- Tkt 08 (segmented-CRC PRAC arm) — extra baseline, not required
- BER-floor study — already optional/later
- Wall-clock leveling / Cython field ops — op-counts are the primary metric
- Benchmark pairing optimization — changes cost not outcome
- gen>30 scaling, incremental-trust perf (idea_list.md)

## Reframe
~80% done. Remaining = headline figure (tkt 09) + security decisions/figures + 3 writing pushes. Every deferred/optional item is a
future-work bullet, not a debt.
