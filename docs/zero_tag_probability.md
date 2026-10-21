# The zero self-tag: probability, cost, and the fixed-data fix

*Companion code: `simulation/zero_tag_probability.py` (Monte Carlo validation). Decision record: [ADR-0010](adr/0010-zero-self-tag-resample-appended-block.md). Literature notes: [`research/char2-symmetric-factorization.md`](research/char2-symmetric-factorization.md), [`research/network-coding-mac-degenerate-packets.md`](research/network-coding-mac-degenerate-packets.md).*

## 1. The problem

In the orthogonal-tag scheme, each packet in a generation carries appended tags so that every pair of packets — and every packet with itself — has inner product `0` over GF(2^m). The tag on the diagonal, the **self-tag**, is the one that makes a packet self-orthogonal.

Sometimes the self-tag comes out **zero**. This is not a harmless value: when a later packet builds its cross-tag against an earlier packet it solves `t1 · t2 = d` for `t2`, where `t1` is that earlier packet's self-tag. If `t1 = 0` the equation is unsolvable and the generator falls back to a random tag, so the generation can no longer be made orthogonal and fails verification. The current code (`generate_symbols_until_nonzero`) reacts by throwing away the **whole generation** and drawing fresh random data until every self-tag is nonzero.

This document answers three questions precisely and checks each with Monte Carlo:

- **A** — how likely is *one* packet to get a zero self-tag?
- **B** — how likely is a *whole generation* to need regeneration?
- **C** — how many regenerations does the current strategy cost on average?

It then reframes the failure as a linear-algebra degeneracy, compares the two fix strategies, and derives a fix that works **even when the payload is fixed and cannot be regenerated**.

## 2. Setup and notation

- Field `GF(2^m)`, with `q = 2^m` elements. Addition is bitwise XOR (characteristic 2).
- A generation has `g = gen_size` packets. Packet layout: `[ g coefficient symbols | data symbols | g tag symbols ]`.
- At the source the coefficient block is the **identity matrix**: packet `i` has a single `1` in coefficient column `i`.
- Inner product `⟨x, y⟩ = Σ_c x[c]·y[c]` over the field.
- The self-tag of packet `i` is the value `t` placed in tag column `i` so that `⟨v_i, v_i⟩ = 0`.

## 3. Assumptions (the i.i.d. model)

1. **Uniform data.** Every data symbol is uniformly random over the `q` field elements.
2. **Independent packets.** Each packet's data is drawn independently of the others.
3. **Fixed coefficients.** The identity coefficient block is a constant pattern; it does not add randomness.

These hold exactly for the source generation as coded today. §7 states precisely where the resulting formulas are exact and where they are a (small) approximation.

## 4. Key lemma: the self-tag is the XOR-checksum of the packet

> **Lemma.** In characteristic 2, `⟨p, p⟩ = (⊕_c p[c])²`, where `⊕` is XOR. Hence the self-tag equals `⊕_c p[c]` (the XOR of all the packet's other bytes), and it is **zero iff the packet's bytes XOR to zero**.

*Proof.* `⟨p, p⟩ = Σ_c p[c]²`. In characteristic 2 the Frobenius map `x ↦ x²` is additive: `(a+b)² = a² + 2ab + b² = a² + b²` because `2ab = 0`. Applying this across the sum, `Σ_c p[c]² = (Σ_c p[c])² = (⊕_c p[c])²`. The scheme sets the self-tag to the square root of the residual so that the total is `0`; since squaring is a bijection on GF(2^m), that square root is unique and equals `⊕_c p[c]`. It is zero exactly when the XOR of the bytes is zero. ∎

So the "keyless HMAC" self-tag is, at heart, an XOR checksum — and the failure event "self-tag = 0" is exactly "the payload already XORs to zero."

## 5. The three probabilities

Write `q = 2^m`.

### A — one packet

The first packet's self-tag is `1 ⊕ (⊕ data bytes)` (the `1` from its identity coefficient). The XOR of one or more independent uniform symbols is itself uniform over GF(2^m), so:

> **A = P(self-tag = 0) = 1/q.**

### B — a whole generation needs a redo

A generation is regenerated iff **at least one** of its `g` self-tags is zero. Treating the `g` self-tags as independent (see §7):

> **B = 1 − (1 − 1/q)^g.**

### C — expected number of regenerations

Each fresh generation succeeds (all self-tags nonzero) with probability `s = (1 − 1/q)^g`. The number of attempts until the first success is geometric, so:

> **C = 1 / (1 − 1/q)^g = (q/(q−1))^g.**

### Numeric values

| Quantity | Formula | GF(2⁴), g=3 | GF(2⁴), g=8 | GF(2⁸), g=3 |
|---|---|---:|---:|---:|
| A | `1/q` | 6.25% | 6.25% | 0.391% |
| B | `1−(1−1/q)^g` | 17.6% | 40.3% | 1.17% |
| C | `(q/(q−1))^g` | 1.214× | 1.676× | 1.012× |

Reading: over GF(2⁴) at `g = 8`, two of every five generations are thrown away. Over GF(2⁸) the effect is negligible. Small fields are where this matters.

## 6. The two fix strategies and their cost

Counting **packet-generations** (one tag+draw of a single packet's data):

| Strategy | Cost (packet-generations) | Growth in g |
|---|---|---|
| Regenerate the whole generation (current) | `g · (q/(q−1))^g` | **exponential** |
| Regenerate only the offending packet | `g · q/(q−1)` | **linear** |

The two agree at `g = 1` and diverge fast. Over GF(2⁴): at `g = 8` regenerate-all costs ≈ 13.4 packet-generations vs ≈ 8.5 for single-packet (≈1.6×); over GF(2²) the same `g = 8` gap is ≈ 80 vs ≈ 11 (≈7.5×). Single-packet resampling produces the identical output distribution — it just stops throwing away good packets.

## 7. Where the formulas are exact, and the small-field correction

The clean i.i.d. derivation is **not exact for every packet**. Its status:

- **Packet 0 is exactly `1/q`.** Its self-tag is `1 ⊕ (⊕ data₀)`, a uniform element — no approximation.
- **Later packets are slightly below `1/q`.** Packet `i>0`'s cross-tags are computed from `⟨p_i, p_k⟩`, which *contains* packet `i`'s own data. So the packet's XOR-checksum and its cross-tags are **correlated**, not independent, which biases `P(self-tag = 0)` a little below uniform. The bias shrinks like ~`1/q` and vanishes into sampling noise by GF(2⁴).

**Monte Carlo, per-tag-position `P(self-tag = 0)` (40 000 generations, `g = 8`, `1/q` in the header):**

| Field | 1/q | pos 0 | pos 1 | pos 2 | … | pos 7 |
|---|---:|---:|---:|---:|---|---:|
| GF(2²) | 0.2500 | 0.2522 | 0.2296 | 0.2361 | … | 0.2447 |
| GF(2³) | 0.1250 | 0.1240 | 0.1233 | 0.1237 | … | 0.1245 |
| GF(2⁴) | 0.0625 | 0.0608 | 0.0612 | 0.0613 | … | 0.0616 |

Position 0 sits on `1/q`; the sub-`1/q` dip is visible only for GF(2²) and, faintly, GF(2³). Consequently:

> **A/B/C are exact for packet 0 and asymptotically exact in `q`; for the fields actually used (GF(2⁴), GF(2⁸)) they match Monte Carlo to sampling precision. The deviation is a small-field artifact, quantified above.**

The harness (`simulation/zero_tag_probability.py`) therefore *asserts* `A = 1/q` exactly on **packet 0** (via a 99% Wilson interval, all fields), asserts the generation-wide A/B/C for `q ≥ 16` within a small tolerance (the §7 bias), and *displays* (does not assert) the GF(2²)/GF(2³) deviation. A separate experiment confirms **A is invariant to the number of data symbols** (1, 2, 5, 10 all give `1/q` over GF(2⁴)), as the lemma predicts. An exact position-dependent closed form is left as future work.

## 8. Why this is a linear-algebra degeneracy (and what that buys us)

Stack the tag columns into a `g × g` matrix `T` (row `i` = packet `i`'s tags). Full orthogonality — `⟨v_i, v_j⟩ = 0` for all `i, j` — is exactly:

```
T · Tᵀ = G ,   where  G[i][j] = ⟨payload_i, payload_j⟩   (the payload Gram matrix)
```

The greedy generator builds `T` **lower-triangular** — this is Cholesky / LDLᵀ factorization over GF(2^m), and the diagonal entries `T[i][i]` are the self-tags. **A zero self-tag is a zero pivot.**

Characteristic 2 makes the pivot theory sharp (Conrad, *Bilinear Forms*, Ex. 5.4; corroborated by Grove; Milnor–Husemoller):

- A nondegenerate symmetric form over a char-2 field admits a **nonzero-diagonal** factorization `G = T·Tᵀ` **iff it is not *alternating*** (alternating = symmetric with an all-zero diagonal, i.e. every payload XOR-checksum is 0).
- **Reordering packets is a congruence `PᵀGP`, which preserves the alternating property.** So permuting/swapping packets (the `generate_all_tags_with_swap` idea) can rescue a *positional* zero pivot but **provably cannot** fix a Gram matrix that is fully alternating — and for `g = 1` nothing in the tag space helps at all.
- The minimal general escape is one extra degree of freedom: Lempel–Seroussi (SIAM J. Comput. 1980) show every symmetric matrix factors with `rank` or `rank+1` columns, the "+1" being exactly the alternating case.

That "+1 column" is the salt byte of §9. (An even-sized cluster of degeneracies can instead be paired into a 2×2 hyperbolic block — the char-2 analog of Bunch–Kaufman pivoting, and the same structure as the thesis's "XOR two packets" combined-recovery idea — but an odd leftover still needs one free coordinate, so the salt byte remains the general fix.)

## 9. The fixed-data fix: a salt byte

The strategies of §6 assume we may resample the data. When the payload is **fixed** (a real application message we must transmit verbatim), we cannot — yet the packet may still XOR to zero.

**Fix: append one per-packet *salt* symbol to the tagged input and resample the salt vector until every self-tag is nonzero.** The salt enters the Gram matrix like any payload symbol, so cross-orthogonality is enforced exactly as before; the real payload is transmitted untouched.

**Important — one salt byte is not a hard guarantee.** Monte Carlo (Experiment 5) shows the salt fix leaves a small fraction of frozen payloads *unsolvable*: `0/5000` in GF(2⁸), `0.02%` in GF(2⁴), but `4.0%` in GF(2²). The reason is structural: packet `i`'s self-tag depends on the salt as `salt_i · (1 ⊕ Σ_{k<i} salt_k / t_k)`, and when that multiplier is zero, `salt_i` cannot move the self-tag off zero at all. One extra column guarantees a nonzero-diagonal factorization *exists* (§8, Lempel–Seroussi rank+1), but the greedy triangular generator plus random salt sampling does not always *find* it. Two practical consequences:

- **Resample the whole salt vector, not one position.** Resampling a single position can loop forever (multiplier-zero); redrawing all `g` salts escapes it. Mean cost is ~1 draw in GF(2⁸), ~1.3 in GF(2⁴), ~3.1 in GF(2²).
- **In GF(2⁸) — the working field — the salt byte is a guarantee for all practical purposes** (`0/5000` failures); the residual small-field failures need a fallback (a second salt byte drives the rate down further, or regenerate the packet if its data is ever mutable). A construction that is guaranteed even in small fields (proper symmetric pivoting / rank+1 completion via a hyperbolic pair) is noted as future work in [ADR-0010](adr/0010-zero-self-tag-resample-appended-block.md).

Special cases fall out for free:
- **Recoded packets** already carry *random* coefficients — resample the coefficient row; no extra byte needed.
- **Source packets with a mutable payload** — resample that packet's data (§6, solution 2).
- **Source packets with a fixed payload** — the salt byte, with the caveat above.

This is the established move in the network-coding integrity literature, not an ad-hoc patch (see [`research/network-coding-mac-degenerate-packets.md`](research/network-coding-mac-degenerate-packets.md)):
- Every scheme appends a unit-vector coefficient block so non-degeneracy lives on appended structure, never the message (Charles–Jain–Lauter §3.1; Agrawal–Boneh).
- Agrawal–Boneh's homomorphic MAC calls an all-zero coefficient block a **"trivial forgery"** — a degenerate object excluded by definition, the exact analog of the zero self-tag.
- Kehdi–Li "Null Keys" (INFOCOM'09), the ancestor of the orthogonal-tag idea, handles its degenerate case by **resampling null-space vectors, not payload**.
- Zhang et al. "Padding for Orthogonality" / MacSig (INFOCOM'11) is the direct precedent: the source **appends one extra symbol solved so the orthogonality relation holds, payload untouched** — precisely the salt byte.

The Monte Carlo harness verifies the salt path: in GF(2⁸) it reaches all-nonzero self-tags in ~1 salt-vector draw, keeps the payload byte-for-byte intact, and every solved generation passes full `check_orth`.

## 10. Recommendation

- Keep the field at **GF(2⁸)** where possible — it makes the zero-tag event (`≈0.4%` per packet) practically irrelevant.
- Replace "regenerate the whole generation" with **resample the smallest free thing**: coefficients for recoded packets, one packet's data for mutable source data, a **salt byte** for fixed payloads. Linear rather than exponential cost, and the only option that supports fixed data.
- The salt byte is effectively a guarantee in GF(2⁸); in small fields keep a fallback (extra salt byte, or regenerate a mutable packet). See [ADR-0010](adr/0010-zero-self-tag-resample-appended-block.md).

## 11. References

- K. Conrad, *Bilinear Forms* (expository notes), Ex. 5.4, Thms 1.6/1.7/2.7/5.4 — symmetric vs alternating forms and orthogonal bases in characteristic 2.
- A. Lempel, G. Seroussi, "Factorization of symmetric matrices …," *SIAM J. Comput.* (1980) — `rank`/`rank+1` factorization.
- L. M. Grove, *Classical Groups and Geometric Algebra*; J. Milnor, D. Husemoller, *Symmetric Bilinear Forms*.
- S. Agrawal, D. Boneh, "Homomorphic MACs: MAC-Based Integrity for Network Coding," ACNS 2009.
- D. Charles, K. Jain, K. Lauter, "Signatures for Network Coding," 2006.
- E. Kehdi, B. Li, "Null Keys: Limiting Malicious Attacks Via Null Space Properties of Network Coding," INFOCOM 2009.
- P. Zhang et al., "Padding for Orthogonality: Efficient Subspace Authentication for Network Coding" / MacSig, INFOCOM 2011.
