# Integrity/Authentication Schemes for Network Coding and the Degenerate / All-Zero Packet Problem

Research note for the RLNC-over-GF(2^m) thesis. Focus: how the main families of
pollution-defense schemes handle **degenerate packets** (all-zero payload,
self-orthogonal payload, zero coefficient vector) and whether any of them exhibit
the same **zero-self-tag** failure mode this thesis hits, plus the mitigations they use.

All claims are cited to a **primary source** (original paper / author PDF / IACR ePrint).
Each entry: core construction (1-3 sentences) -> degenerate-case handling -> citation.

---

## 0. Shared background: augmentation is the universal anti-degeneracy device

Every cryptographic network-coding integrity scheme below assumes packets are first
**augmented**: the source appends (or prepends) to each message vector `w_i` the unit
coordinate vector `e_i`, forming `v_i = (w_i , 0..0,1,0..0)`. This "global encoding
vector" travels with the packet so any node can recover the coefficients of the
linear combination it holds.

Two consequences matter for the degeneracy question, and both are stated explicitly in
the primary sources:

- The augmentation block makes each basis vector **non-zero and linearly independent
  by construction**, regardless of payload content. Charles-Jain-Lauter state the source
  "creates the augmented vectors `v_1,...,v_k` by setting `v_i = (0,...,0,1,0,...,0, w_i1,...,w_id)`"
  and that "one can assume without loss of generality that the vectors `v_i` are linearly
  independent." (Charles, Jain, Lauter, MSR-TR-2005-159, Sec. 3.1.)
- A combination whose **coefficient/augmentation block is all-zero** is treated as a
  degenerate, meaningless object and is *excluded by definition* from what a scheme must
  protect (see Agrawal-Boneh below).

This is the single most important prior-art fact for the thesis: the standard fix for a
degenerate construct is **an appended controlled block (coefficients / a unit vector / a
padding symbol), not a change to the payload**.

Primary source for augmentation as an RLNC building block:
- T. Ho, M. Medard, R. Koetter, D. Karger, M. Effros, J. Shi, B. Leong, "A Random Linear
  Network Coding Approach to Multicast," IEEE Trans. Inf. Theory 52(10), 2006.
  https://www.mit.edu/~medard/mpapersnew/HoMedardKoetterKargerEffrosShiLeong.pdf
- R. Koetter, F. Kschischang, "Coding for Errors and Erasures in Random Network Coding,"
  IEEE Trans. Inf. Theory 54(8), 2008 (subspace/"transmit a subspace" view).
  https://arxiv.org/abs/cs/0703061

---

## 1. Homomorphic MACs for network coding

### 1.1 Agrawal & Boneh — Homomorphic MACs (ACNS 2009)

**Construction.** A symmetric-key homomorphic MAC: `Sign(k, id, v, i)` tags each augmented
basis vector `v ∈ F_q^{n+m}` of a space identified by `id`; a `Combine` step lets any node
compute the correct tag of any linear combination without the key, and `Verify` checks it.
Implemented over `F_{2^8}` (q=256) — the **same GF(2^m) family as this thesis**.

**Degenerate-case handling — direct hit for the thesis.** The security game *defines away*
the degenerate combination: a forgery `y = (y_1,...,y_{n+m})` only counts if
"the augmentation `(y_{n+1},...,y_{n+m})` in `y` is **not the all zero vector** (which
corresponds to a trivial forgery)." I.e. a packet whose coefficient block is zero is a
degenerate object the MAC is not required to authenticate — it carries no information and
is discarded rather than mitigated. The payload itself is never constrained; the *appended
coefficient block* is what is required to be non-zero. This is exactly the shape of the
thesis's zero-self-tag problem, and the resolution is at the appended-block level.

**Citation.** S. Agrawal, D. Boneh, "Homomorphic MACs: MAC-based Integrity for Network
Coding," ACNS 2009, LNCS 5536. Author PDF: http://crypto.stanford.edu/~dabo/papers/hommac.pdf ;
Springer: https://link.springer.com/chapter/10.1007/978-3-642-01957-9_18
(quotes from the "trivial forgery" clause of the security definition and Sec. on augmentation).

### 1.2 Homomorphic subspace / tag-pollution MAC variants

Later homomorphic-MAC work targets **tag pollution** (attacker forges the tags, not just
the data) and small keys, but inherits the same augmentation and non-zero-coefficient
assumption. Representative primary sources:
- Cheng, Jiang, et al., "An Efficient Homomorphic MAC with Small Key Size...," and
  the ETRI "Homomorphic Subspace MAC" scheme:
  https://koreascience.kr/article/JAKO201373959965099.page
- Boo, et al., "An efficient homomorphic MAC-based scheme against data and tag pollution
  attacks," Int. J. Inf. Sec. 2017: https://link.springer.com/article/10.1007/s10207-016-0351-z

These do not introduce a *new* degeneracy mitigation beyond augmentation + non-zero
coefficient block.

---

## 2. Homomorphic signatures for network coding

### 2.1 Charles, Jain & Lauter — Signatures for Network Coding (CISS 2006)

**Construction.** First homomorphic signature scheme; uses a bilinear (Weil-pairing) map on
an elliptic curve. The server signs each augmented vector `v_i` so that any linear
combination's signature can be derived homomorphically by intermediate nodes without the
secret key; verification uses the pairing.

**Degenerate-case handling.** Handled *structurally* by augmentation (Sec. 3.1, quoted in §0):
every signed vector carries a unit-vector block, so signed basis vectors are non-zero and
independent. The zero vector maps to the group identity `O` (the paper notes the point set
"can be given the structure of an abelian group with `O` as the identity"), i.e. the zero
input signs to the identity element — degenerate but well-defined; a *forgery* is a non-zero
vector outside the span. No payload constraint is imposed.

**Citation.** D. Charles, K. Jain, K. Lauter, "Signatures for Network Coding," CISS 2006 /
Microsoft Research TR-2005-159.
https://www.microsoft.com/en-us/research/wp-content/uploads/2005/11/tr-2005-159.pdf

### 2.2 Boneh, Freeman, Katz & Waters — Signing a Linear Subspace (PKC 2009)

**Construction.** Two pairing-based schemes that "sign a linear subspace": a signature on a
subspace `V` verifies **exactly** the vectors in `V`. First scheme is homomorphic with
constant public-key and per-packet overhead; second avoids random oracles. They also prove a
lower bound showing the signature length is essentially optimal.

**Degenerate-case handling.** Same subspace framing: the signed basis is the augmented
(properly-augmented) basis, so vectors are non-zero/independent; the zero vector lies in
every subspace and signs trivially, so a valid forgery is defined as a **non-zero** vector
outside `V`. Requires large coefficients — coefficients must live in a field `F_q` with
`q ≈ 2^160` (discrete-log-hard group), which is why augmentation overhead is large (this
limitation is the explicit motivation for §2.3 and §1.1).

**Citation.** D. Boneh, D. Freeman, J. Katz, B. Waters, "Signing a Linear Subspace:
Signature Schemes for Network Coding," PKC 2009. IACR ePrint 2008/316:
https://eprint.iacr.org/2008/316 . (Large-field requirement also documented in
Agrawal-Boneh §"Previous solutions", hommac.pdf.)

### 2.3 Boneh & Freeman — Linearly Homomorphic Signatures over Binary Fields (PKC 2011)

**Construction.** First homomorphic signature that authenticates vectors defined over
**binary fields** `F_2` (prior schemes needed large or growing coefficients); lattice-based,
introducing the k-SIS problem. **Most relevant to a GF(2^m) thesis** because it directly
tackles the small-field regime.

**Degenerate-case handling.** Authenticates a subspace `V`; zero vector is in every subspace
and is the trivial/degenerate case (valid forgery = non-zero vector outside `V`). The
small-field-specific hazard it must contend with is that over `F_2` random combinations
collide far more often than over huge prime fields — the security reduction is engineered
around exactly this, rather than by constraining payloads.

**Citation.** D. Boneh, D. Freeman, "Linearly Homomorphic Signatures over Binary Fields and
New Tools for Lattice-Based Signatures," PKC 2011. IACR ePrint 2010/453:
https://eprint.iacr.org/2010/453 ; Springer:
https://link.springer.com/chapter/10.1007/978-3-642-19379-8_1

### 2.4 Gennaro, Katz, Krawczyk & Rabin; Zhao et al. — related homomorphic signatures

- Gennaro, Katz, Krawczyk, Rabin, "Secure Network Coding over the Integers," PKC 2010 —
  RSA-based homomorphic signature over the integers; same subspace/augmentation framing,
  zero vector trivial. IACR ePrint 2010/183: https://eprint.iacr.org/2010/183
- Zhao, Kalker, Medard, Han, "Signatures for Content Distribution with Network Coding,"
  ISIT 2007 — a signature/hash on the *source subspace* (orthogonality-flavored: the source
  publishes a vector; valid packets are orthogonal to it). This is a homomorphic-signature
  cousin of the Null-Keys idea.
  https://www.mit.edu/~medard/mpapersnew/ZhaoKalkerMedardHan.pdf

Neither adds a payload-level anti-degeneracy trick beyond augmentation.

---

## 3. Null-space / subspace / orthogonality-based integrity (closest relatives to this thesis)

### 3.1 Kehdi & Li — Null Keys (INFOCOM 2009)  ← nearest relative

**Construction.** The source's `r` augmented blocks `{x_1,...,x_r}` (each of size `r+d`,
block `i` augmented with a `1` in position `i` and zeros elsewhere) span a subspace `X`.
Its **null space** `X^⊥` has a basis `{z_1,...,z_d}` (found by Gaussian elimination via the
rank-nullity theorem). A **null key** is a *random linear combination* of `{z_1,...,z_d}`,
distributed by the source (and itself protected by homomorphic hashing so it can't be forged).
A node forms its null-key matrix `K_i` and **verifies a received block `w` by checking
`w · K_i = 0`** (inner product / orthogonality) — no shared secret, exactly the "keyless
orthogonality check" this thesis uses.

**Degenerate-case handling — this is the key finding for the thesis.**
- The paper does **not** explicitly treat the all-zero / self-orthogonal degenerate case.
  Non-triviality of the *data* vectors is guaranteed only by augmentation (each `x_i` has a
  `1` in a distinct position, so no source block is zero and payload content is irrelevant).
- The null keys are *random* combinations of a basis, so a zero null key occurs only with
  negligible probability `~1/q^{...}` over a large field — the paper relies on this
  probabilistic non-degeneracy rather than an explicit non-zero check.
- The paper explicitly acknowledges the orthogonality test is a **necessary but not
  sufficient** check: "if the condition is satisfied, it does not imply that the received
  vector belongs to X." The all-zero vector `w = 0` trivially satisfies `w·K_i = 0` — the
  same false-accept degeneracy the thesis's zero-self-tag creates — but Null Keys leaves
  this to the augmentation invariant and the attacker's inability to learn a node's specific
  random null keys, not to an explicit guard.

So: Null Keys is the direct ancestor of the orthogonal-tag idea, uses the *same*
`<v,key>=0` verification, and its protection against degeneracy is **augmentation +
randomization of the orthogonal vectors**, i.e. resampling the *key/tag side*, never the
payload.

**Citation.** E. Kehdi, B. Li, "Null Keys: Limiting Malicious Attacks Via Null Space
Properties of Network Coding," IEEE INFOCOM 2009, pp. 1224-1232. Author PDF:
https://iqua.ece.toronto.edu/papers/ekehdi-infocom09.pdf
(construction in Secs. III-IV; "does not imply that the received vector belongs to X" in Sec. IV.)

### 3.2 Zhang et al. — "Padding for Orthogonality" / MacSig (INFOCOM 2011)  ← direct source for Q4

**Construction.** The source **pads each packet with one extra symbol**, choosing the padding
value so that the subspace spanned by the padded packets is **orthogonal to a specific
vector** `w`; forwarders check integrity by verifying that a received packet maps `w` to zero
(`<packet, w> = 0`). The padding symbol is *solved for* to force the orthogonality constraint
to hold. From this they build a public-key signature and a symmetric-key MAC, unified as
**MacSig** (first hybrid-key scheme; also defeats tag pollution).

**Degenerate-case handling / relevance.** This is the primary source that most directly
matches Q4: **append a controlled padding symbol to guarantee a valid orthogonality relation
while leaving the original payload intact.** The padding value is chosen deterministically to
satisfy the constraint — the same maneuver the thesis needs when a payload would otherwise
yield a zero self-tag. Because the padding degree of freedom absorbs the constraint, no
payload is ever a "bad" payload.

**Citation.** P. Zhang, Y. Jiang, C. Lin, H. Yao, A. Wasef, X. Shen, "Padding for
Orthogonality: Efficient Subspace Authentication for Network Coding," IEEE INFOCOM 2011,
pp. 1026-1034. https://ieeexplore.ieee.org/document/5934876/

### 3.3 Jaggi et al. — Resilient Network Coding vs. Byzantine Adversaries (INFOCOM 2007 / IT 2008)

**Construction.** Information-theoretic (not cryptographic): rate-optimal distributed codes
that tolerate `z` Byzantine (jamming) links, achieving rate `C - 2z_0` (or `C - z_0` with
limited adversary snooping) by adding redundancy/hashes in the code itself so corrupted
subspaces can be filtered at the sink.

**Degenerate-case handling.** No self-tag notion; correctness is by minimum-distance /
rank arguments over the code, so the all-zero-payload issue does not arise in the same form.
Included for completeness as the canonical *coding-theoretic* alternative to tag-based
integrity.

**Citation.** S. Jaggi, M. Langberg, S. Katti, T. Ho, D. Katabi, M. Medard, M. Effros,
"Resilient Network Coding in the Presence of Byzantine Adversaries," IEEE Trans. Inf. Theory
54(6), 2008 (conf. INFOCOM 2007). https://arxiv.org/abs/0803.3452
(overhead-analysis companion: https://arxiv.org/pdf/0806.4451 )

### 3.4 Krohn, Freedman & Mazières — homomorphic hashing (S&P 2004)

**Construction.** Homomorphic collision-resistant hash surviving linear combinations; the
`[7]` baseline Null Keys and CJL compare against. Verification is a homomorphic hash check,
not an orthogonality inner product.

**Degenerate-case handling.** Zero vector hashes to the identity element; no payload-level
special case. Cited as the origin of "on-the-fly" RLNC verification.

**Citation.** M. Krohn, M. Freedman, D. Mazieres, "On-the-Fly Verification of Rateless
Erasure Codes for Efficient Content Distribution," IEEE S&P 2004.
https://pdos.csail.mit.edu/papers/otfvec/paper.pdf

---

## 4. Summary table: does each scheme have a zero-tag/key degeneracy, and how is it handled?

| Scheme (primary source) | Verify primitive | Degenerate object | Explicit mitigation |
|---|---|---|---|
| Agrawal-Boneh Hom-MAC (ACNS'09) | keyed tag + combine | all-zero **coefficient block** | defined as "trivial forgery", excluded; augmentation forces non-zero coeff block |
| Charles-Jain-Lauter sig (CISS'06) | Weil pairing | zero vector -> group identity `O` | augmentation (unit-vector block) makes signed vectors non-zero/independent |
| BFKW subspace sig (PKC'09) | pairing, per-subspace | zero vector in every `V` | forgery := non-zero vector outside `V`; proper augmentation |
| Boneh-Freeman binary-field sig (PKC'11) | lattice / k-SIS | zero vector; small-field collisions | security reduction handles `F_2` collisions; augmentation |
| **Null Keys (INFOCOM'09)** | **`<v, key>=0`** | **zero packet / zero null key** | **implicit only: augmentation + randomized null keys; test is necessary-not-sufficient** |
| **Padding for Orthogonality / MacSig (INFOCOM'11)** | **`<v, w>=0`** | payload that breaks orthogonality | **append one padding symbol solved to force the relation** |
| Jaggi et al. Byzantine (IT'08) | code min-distance | n/a (no tag) | redundancy in code |
| Krohn et al. hashing (S&P'04) | hom. hash | zero -> identity | none needed |

---

## 5. Relevance to the zero-self-tag problem in this thesis

The thesis builds self- and pairwise-orthogonal tags (`<v_i,v_j>=0`, keyless) — this is
structurally the **Null Keys** family (§3.1) with the **Padding-for-Orthogonality** trick
(§3.2) as its natural fix. The prior art points to one clear conclusion:

1. **The right fix is on the appended block, never the payload.** Across *every* scheme,
   the degeneracy guard is a controlled appended structure — the coefficient/unit-vector
   augmentation (§0, CJL §2.1, Agrawal-Boneh §1.1) or a solved padding symbol
   (Padding-for-Orthogonality §3.2). None of them ever alters the payload to dodge a
   degenerate tag. This directly justifies adding a **per-packet salt/padding byte** (a
   free coordinate solved to force a non-zero, valid tag) over touching payload bits.

2. **The strongest single precedent is "Padding for Orthogonality" (Zhang et al., INFOCOM
   2011).** It literally appends one extra symbol, *chosen so the orthogonality relation
   holds*, keeping the payload intact — the exact operation needed when a payload would
   otherwise self-orthogonalize to a zero tag. Cite this for the padding-byte design.

3. **Agrawal-Boneh's "trivial forgery" clause** justifies the *complementary* stance: a
   packet whose constructed tag/coefficient block is all-zero is a **degenerate, discardable
   object**, not a security failure to be patched at the payload — supporting rejecting or
   resampling rather than accepting a zero tag.

4. **Null Keys justifies resampling the tag/key side rather than the payload:** its null
   keys are *random* combinations of the null-space basis, and non-degeneracy is obtained by
   re-randomizing those vectors — i.e. **rejection-sampling the coefficients/keys** until the
   orthogonal object is non-zero, again leaving payload untouched. This is the precedent for
   "resample coefficients, not payload."

**Recommendation to cite in the thesis:** for the *padding-byte* mechanism ->
Zhang et al. 2011 (§3.2), reinforced by the augmentation invariant in Charles-Jain-Lauter
1.1/§0. For treating a zero self-tag as a degenerate case to reject/resample rather than a
payload to rewrite -> Agrawal-Boneh 2009 "trivial forgery" (§1.1) and Kehdi-Li Null Keys
2009 (§3.1).

---

### Primary sources (consolidated)

- Agrawal & Boneh, Homomorphic MACs, ACNS 2009 — http://crypto.stanford.edu/~dabo/papers/hommac.pdf
- Charles, Jain & Lauter, Signatures for Network Coding, MSR-TR-2005-159 / CISS 2006 — https://www.microsoft.com/en-us/research/wp-content/uploads/2005/11/tr-2005-159.pdf
- Boneh, Freeman, Katz & Waters, Signing a Linear Subspace, PKC 2009 — https://eprint.iacr.org/2008/316
- Boneh & Freeman, Linearly Homomorphic Signatures over Binary Fields, PKC 2011 — https://eprint.iacr.org/2010/453
- Gennaro, Katz, Krawczyk & Rabin, Secure Network Coding over the Integers, PKC 2010 — https://eprint.iacr.org/2010/183
- Zhao, Kalker, Medard & Han, Signatures for Content Distribution with Network Coding, ISIT 2007 — https://www.mit.edu/~medard/mpapersnew/ZhaoKalkerMedardHan.pdf
- Kehdi & Li, Null Keys, INFOCOM 2009 — https://iqua.ece.toronto.edu/papers/ekehdi-infocom09.pdf
- Zhang, Jiang, Lin, Yao, Wasef & Shen, Padding for Orthogonality (MacSig), INFOCOM 2011 — https://ieeexplore.ieee.org/document/5934876/
- Jaggi et al., Resilient Network Coding vs. Byzantine Adversaries, IEEE Trans. IT 2008 — https://arxiv.org/abs/0803.3452
- Krohn, Freedman & Mazieres, On-the-Fly Verification (homomorphic hashing), IEEE S&P 2004 — https://pdos.csail.mit.edu/papers/otfvec/paper.pdf
- Ho et al., A Random Linear Network Coding Approach to Multicast, IEEE Trans. IT 2006 — https://www.mit.edu/~medard/mpapersnew/HoMedardKoetterKargerEffrosShiLeong.pdf
- Koetter & Kschischang, Coding for Errors and Erasures in Random Network Coding, IEEE Trans. IT 2008 — https://arxiv.org/abs/cs/0703061
