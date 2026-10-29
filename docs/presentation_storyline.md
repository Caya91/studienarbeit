# Presentation storyline — answers to the supervisors' 12 questions

Generated 2026-10-22. Sources: ADR-0013/14/15, memory notes, 9 papers in
`C:\Users\marti\OneDrive\studienarbeit_docs\` (+ `paper/`). Numbers quoted from ADR Results sections —
re-check against final plots before putting on slides.

---

## 0. One-sentence story (say this in the first minute and the last minute)

> Partial-packet recovery in RLNC needs a check that (a) survives recoding and (b) needs no key distribution.
> CRC fails (a), keyed homomorphic MACs fail (b). A **keyless homomorphic tag** gives the same recovery,
> 0 silent decodes and recoding-safe detection as both baselines — paid for with tag bytes that grow with
> generation size, more compute per check, and work-based (not key-based) security.

---

## 1. RQ — what are you solving?

Current deck slide 5 RQs are fine, but RQ2 says "reduce communication overhead" — results show per-packet
overhead is **equal or slightly worse** (salt byte, −1..3 pp goodput vs keyed). Saving is in **key
distribution**, not per-packet bytes. Suggested reframe:

- **RQ1** Can RLNC packets be verified **without keys** (intelligent redundancy = orthogonal self/cross tags),
  such that verification survives recoding?
- **RQ2** Does it support **partial-packet recovery** as well as SOTA (CRC+ACR = S-PRAC/QPPR line; keyed HMAC =
  Combined Recovery 2025) — recovery rate, silent decodes, transmissions, compute?
- **RQ3** What does it cost and where does it break: tag overhead, compute, security vs an adversary;
  do closed forms and simulation agree?

## 2. Why should I care? (applications)

Three needs, each backed by a paper:

| Need | Evidence | Paper |
|---|---|---|
| Noisy links waste mostly-good packets | PRAC: +35 % avg throughput vs ARQ, +148 % on high-PER links; −16 % energy (up to −50 %); only 65 % (ARQ) / 77 % (iHARQ) of testbed links meet throughput target vs **100 % with PRAC** | Harnessing PP (Angelopoulos, TWC'17) |
| Real channels are that noisy | V2V BER > 1e-5 | QPPR (Gholamian, **Nazari**, Fitzek '23) |
| Relays must recode → need homomorphic check | CRC "prevents recoding" (task text); FHPRAC: HMAC enables relay recoding, receiver O(n²)→O(n) | FHPRAC; Fly-PRAC (recovery at intermediate node: −16 % transmissions, 2-hop, BER 1e-4) |
| Keys don't scale | Agrawal–Boneh: "tag per network node … unacceptable", tag size ∝ c² (collusion); MacSig key pool ∝ (c+1)² ln N; Esfahani: source holds c× keys of each node | hommac, Esfahani, `docs/research/key_distribution_scaling.md` |

Application targets to name: **Tactile Internet / CeTI** (funds QPPR + Fly-PRAC, supervisors' cluster —
low latency, no time for retransmits), **V2V**, **WSN/IoT** (energy, constrained, no PKI), **ad-hoc/mesh
multi-hop** (dynamic topology, no KDC).

## 3. How did you solve it?

Reuse existing deck slides 9–22 (ACR, keyless HMAC, tags, homomorphic property, zero-tag). Pipeline in 1 slide:

1. Source: segment packet, per segment append salt + g tag bytes so every pair of packets is orthogonal
   (self-tag = √⟨d,d⟩, cross-tags solved).
2. Relay/receiver: verify = inner products (self + W cross) — survives recoding for free.
3. Recovery: ACR localizes inconsistent columns → bit-flip search up to HD (pairing as in Combined Recovery)
   → accept candidate when orthogonality holds.
4. Novel bits: zero-self-tag degeneracy (char-2 XOR checksum) + salt-byte fix (ADR-0010); segmented trust.

## 4. Did you reach the goals?

Define goals from §2, then tick:

| Goal (from application) | Result | Met? |
|---|---|---|
| G1 No key distribution | by construction | ✅ |
| G2 Detection ≈ CRC-32 | miss/corrupted segment @1e-3: keyless W4 3e-14 vs CRC-32 4e-14; self-only 2 % (misses 2-bit same-lane) | ✅ at W≥3–4 |
| G3 Fewer transmissions than ARQ | df300 @1e-3: 8.4 pkts vs ARQ 39.1 (87.5 % decoded); df1000 @1e-3: 10.2 vs **ARQ 0 % decoded**; goodput df1000 @1e-4 0.69 vs 0.40 | ✅ |
| G4 Recovery = SOTA | keyless == CRC+ACR in **all 16 800** paired rows (W≥2, HD3/4); == keyed within CI e2e | ✅ (equal, not better) |
| G5 0 silent decodes | 0 in 48 248 e2e generations; isolated: only W=1 has silent (54/16 800 @HD4) | ✅ for W≥2 |
| G6 Safe at recoding relays | 2-hop blind relay: CRC → **38–81 % silent wrong decodes** (→100 % @1e-3); keyless → 0 silent (detects, stalls); keyless verify relay mixed 0/4200 corrupted | ✅ key differentiator |
| G7 Tag errors repairable | tag-only errors: ~100 % decoded all BER (S-PRAC states corrupted inner CRC = unrecoverable) | ✅ |
| G8 Compute acceptable for real-time | verify 50 B: keyless 3.5–18 µs (Python) vs CRC 0.84 µs (C); compiled vs compiled: 2.3 vs 1.2 µs, repair CRC only 1.1–1.4× faster | 🟡 |
| G9 Security vs adversary | tag pollution: keyless admits ~0 (50/264k) vs keyed ~1−W/g; but white-box forger sub-ms, splice attack works on both segmented arms | 🟡/❌ (honest) |

## 5./6. If not — how close, how much is left?

- **BER floor**: df1000 fails at 3e-3 with HD2; HD4 moves floor 1e-3 → 3e-3 but 10–60× compute. Explain with
  QPPR's H_c = (1−ε)^{q(G+1)} (P[column clean]) — inconsistent columns explode with BER·G·packet length.
  V2V (1e-5) fully covered (overhead ≈ 1.0), 1e-3 covered up to ~1000 B, 1e-2 not.
- **Overhead**: tag bytes = g per segment + salt → grows with gen size (CRC-32 flat 4 B). Fair at g=4 only.
- **Security**: splice (per-segment verify, no coefficient binding) → fix = bind coeffs into every segment tag;
  work-based security only.
- **Compute**: Python implementation; C/numba kernel estimates ~2× CRC per check.
- **Relays**: verify-relays drop, don't repair → starve at high BER (df1000 3e-4: 75 % stall).
- Not done: burst errors (Gilbert–Elliott, used by FHPRAC), multicast, real testbed, keyed arm in three-model run.

## 7. Experimental setup (1 slide, table)

GF(2^8), poly 0x11D · gen size g=4 (CRC-fair: 4 tag B = CRC-32) / 6 / 10 · data 100/300/1000 B in 50 B segments
(2/6/20) · iid BER 1e-5…1e-2 · error scopes payload / tag / both, coeffs clean · max HD 1–4, budget 20 000
candidates/step · 200 paired seeds per cell (isolated), 100–200 gens/cell (e2e) · single hop + two hop
(blind vs verify relay) · arms: keyless W1–4, keyed HMAC (Combined Recovery), CRC-32+ACR (S-PRAC/QPPR-like),
CRC-32 ARQ · metrics: recovery %, silent decodes, transmissions/gen, goodput, ops + wall-clock.
Two harnesses: **isolated** (injected trust, only the oracle differs) and **end-to-end** (ARQ, relays).

## 8. Results — 4 headline slides max

1. **Transmissions vs BER** (e2e): 3 repair arms overlap, ARQ explodes/fails → "recovery works, tag doesn't matter for it".
2. **Two-hop silent vs stall**: CRC blind relay silent 38–100 %, keyless 0 → "why homomorphic".
3. **Detection**: P(miss) vs W, CRC-32 line → "W=4 ≈ CRC-32".
4. **Cost**: wall-clock ratio + tag bytes vs g → "the price".
Back-up: tag-pollution admit (keyless vs keyed), recovery vs HD, zero-tag probability.

## 9. Baselines + SOTA — why fair?

- Baselines = the paper lineage: ARQ (PRAC's baseline), CRC+ACR (S-PRAC/QPPR), keyed HMAC Combined Recovery
  (Fathi & Pahlevani, Comm. Lett. 2025 — current SOTA).
- **Same code path**: ACR + search shared, only the acceptance oracle swapped → proof: crc_acr == keyless in
  every one of 16 800 paired rows.
- **Matched width**: g=4 → 4 tag bytes = CRC-32; keyed/keyless verify same W.
- **Paired seeds**: identical packets + bit flips per arm.
- **Baseline-favouring choices**: CRC in C (zlib), keyless in Python; salt byte counted against keyless.
- Contrast with SOTA papers: Combined Recovery assumes keys "pre-generated and securely shared" and its delay
  comparison "disregarded false positives and retransmissions" — we count both.

## 10. Why trust the results — CI + statistics

- Rates: Wilson 95 % CIs; zero counts → rule of 3 (0 silent / 48 248 gens → < 6.2e-5 at 95 %).
- **Sim vs closed form** (strongest argument): ARQ sim = exact expectation wherever cap doesn't bind; tag
  pollution theory fit, max |z| 2.7; zero-tag A = 1/q inside 99 % Wilson; detection = exact enumeration k≤4,
  brute-force-tested.
- Reproducibility: deterministic seeds, CRC rerun (pure-Python → zlib) gave identical outcomes row-for-row,
  regression tests byte-identical.
- Field practice: QPPR/FHPRAC 1000 reps, "95 % CI < 5 % of mean, omitted"; S-PRAC 10 000 reps + std; Combined
  Recovery 1000 reps, no CI. We match/exceed and show CIs.
- Caveat to state: budget-capped floor cells have 5–59 trials → hollow markers / "indicative".

## 11. Lessons learned

1. Recovery power comes from **ACR localization + search**, not from the check → the check's job is
   recoding-safety + no key.
2. **Localization makes deep search safe**: blind CRC with more HD → more collisions → silent corruption.
3. Math pitfalls are real: zero self-tag (char-2 XOR) broke tag generation; per-segment verify enabled splice.
4. **Isolate the mechanism before comparing** — a keyed budget bug once flipped a conclusion; paired reruns caught it.
5. Wall-clock measures the implementation (C vs Python; libraries slower at 55 B) → report op counts + both.
6. Where you verify (relay vs sink) matters more than which check you use.

## 12. Conclusion

Keyless homomorphic tag = **same recovery and silent-safety as keyed HMAC and CRC+ACR, no keys, safe under
recoding**. Price: tag bytes ∝ g, ~2× compute per check, work-based security. Good fit: noisy, multi-hop,
keyless/dynamic networks (IoT, V2V, mesh) with non-adversarial or weak adversaries. Future: coefficient
binding vs splice, burst channels, multicast, compiled kernel, testbed.

---

## Paper → slide usage map

| Paper | Use for | Best item |
|---|---|---|
| Harnessing PP / PRAC (TWC'17) | Q2 why care, Q9 ARQ baseline | +35 %/+148 % throughput, −16..50 % energy, 100 % links meet target; real 7-node testbed (our limitation) |
| S-PRAC (Wireless Days'19) | Q3 segmentation origin, Q4 G7 | "cannot correct errors when inner CRC codes are corrupted" → we repair tags ~100 % |
| QPPR (Comm. Lett.'23, Nazari) | Q2 V2V BER, Q5 floor formula, Q10 stats template | H_c = H_s^{G+1}; 1000 reps, CI < 5 % omitted |
| Fly-PRAC | Q2 relay recovery, Q6 two-hop comparison | −16 % transmissions 2-hop @1e-4; CeTI |
| FHPRAC (IEEE Access) | Q2 relay recoding, Q5 future (burst) | HMAC → relay recoding, O(n²)→O(n); Gilbert–Elliott model |
| Combined Recovery (Comm. Lett.'25) | Q9 SOTA baseline, Q1 gap | keys assumed pre-shared; Fig 3: CRC-8/HMAC-8 collide, CRC-32/HMAC-16 zero → matches our detection; future work = multi-hop (we did 2-hop) |
| Agrawal–Boneh HomMAC | Q1/Q2 key-scaling | tag per node unacceptable; tag ∝ c² |
| Esfahani et al. (IJIS'17) | Q2 pollution threat, Q4 G9 | data + tag pollution definitions; only adversarial paper; prob-bound security style |
| Jepsen CRC paper | Q9 CRC-32 strength | CRC HD / burst detection → justifies CRC-32 HD ≥ 5 at 50 B |

## Suggested deck order (~18 slides, reuses live deck slides)

1 Title · 2 RQ (Q1) · 3–4 Why care: noisy links + recoding + keys (Q2; deck 3, 4, 6 + PRAC numbers) ·
5 Goals table G1–G9 (sets up Q4) · 6–9 How (deck 9–19 condensed) · 10 Zero-tag (deck 20–22, 1 slide) ·
11 Setup (Q7) · 12 Baselines + fairness (Q9) · 13–16 Results (Q8, 4 headline plots) ·
17 Goals table again, ticked (Q4–6) + trust box (Q10) · 18 Lessons (Q11) · 19 Conclusion (Q12).
Back-up: stats details, security sims, HD sweep, compute backends.
