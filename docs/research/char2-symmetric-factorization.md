# Symmetric / alternating factorization over GF(2^m) and the zero self-tag problem

Research note for the RLNC orthogonal-tagging scheme. Field: `F = GF(2^m)`,
characteristic 2, so `+ = XOR` and the Frobenius map `x -> x^2` is a field
automorphism (hence every element has a *unique* square root).

The question behind everything below: the tag construction builds a
lower-triangular `T` with `T·Tᵀ = G` (a Cholesky/LDLᵀ factorization of the
payload Gram matrix `G`, `G[i][j] = <p_i, p_j>`). The diagonal `T[i][i]` is
packet `i`'s self-tag and equals `√(residual pivot)`. It becomes **zero** when a
Cholesky pivot vanishes, which breaks the scheme. We want to know, rigorously and
citably: *when can a zero self-tag be avoided by reordering packets, and when is
an extra degree of freedom (a free byte) provably required?*

---

## 0. Dictionary: the scheme in bilinear-form language

Everything reduces to the theory of **symmetric bilinear forms in characteristic
2**. Fix that translation first, because it makes every later claim a direct
quotation of a theorem.

- `G` is the matrix of a **symmetric bilinear form** `B(x,y) = xᵀ G y` on `Fᵍ`
  (`Bᵀ = B` because `<p_i,p_j> = <p_j,p_i>`).
- `<p,p> = Σ_k p_k²`. In characteristic 2 Frobenius is additive, so
  `Σ_k p_k² = (Σ_k p_k)²`. Hence **`<p,p> = (XOR of all symbols of p)²`**, and
  `√<p,p> = XOR-checksum of the payload`. The self-tag "square root of the
  residual" is literally an XOR checksum of a residual vector.
- A Cholesky factor `G = T·Tᵀ`, `T` lower-triangular, is equivalent to an
  **LDLᵀ factorization** `G = L·D·Lᵀ` (`L` unit lower-triangular, `D` diagonal)
  with `T = L·D^{1/2}`; the square root `D^{1/2}` exists uniquely because
  Frobenius is a bijection. Then `T[i][i] = √(D[i][i])`, so
  **`T[i][i] = 0` iff `D[i][i] = 0` iff the i-th pivot vanishes.**
- `G = T·Tᵀ` with `T` **invertible** ⟺ `Cᵀ G C = I` for `C = (Tᵀ)⁻¹`, i.e. `G`
  is **congruent to the identity** ⟺ the form `B` has an **orthonormal basis**.
  Because every element of `GF(2^m)` is a square, "orthogonal basis with nonzero
  diagonal" and "orthonormal basis" are the same thing here (rescale each vector
  by the square root of its self-value).

So: *"nonzero self-tags for all packets in the given order"* = *"unpivoted LDLᵀ
of `G` with all pivots nonzero"*, and *"nonzero self-tags after reordering"* =
*"symmetrically-pivoted LDLᵀ of `G` with all 1×1 pivots nonzero"*.

Primary reference for this entire dictionary (matrix ↔ form, congruence
`C ᵀ M C`, alternating = zero diagonal, the char-2 phenomena): K. Conrad,
*Bilinear Forms*, Thms 2.7, 2.8, 2.11, §4 and §7.
<https://kconrad.math.uconn.edu/blurbs/linmultialg/bilinearform.pdf>

---

## 1. Symmetric vs. alternating forms in characteristic 2

**Definitions (Conrad, §1).** A bilinear form `B` is *symmetric* if
`B(v,w)=B(w,v)`, *skew-symmetric* if `B(v,w)=-B(w,v)`, and **alternating** if
`B(v,v)=0` for all `v`. In matrix terms (Conrad, **Theorem 2.7**): `B` is
symmetric iff `Mᵀ=M`; `B` is alternating iff `Mᵀ=-M` **and the diagonal entries
of `M` are zero**.

**Why characteristic 2 is exceptional.**

> **Theorem 1.6 (Conrad).** In all characteristics, an alternating bilinear form
> is skew-symmetric. In characteristic ≠ 2, a form is skew-symmetric iff it is
> alternating. **In characteristic 2, a form is skew-symmetric iff it is
> symmetric.**

Since `1 = -1` in characteristic 2, "skew-symmetric" collapses into
"symmetric" — the off-diagonal antisymmetry condition is vacuous. What remains as
a *genuine* extra condition is the diagonal:

> **Theorem 1.7 (Conrad).** In characteristic ≠ 2 every bilinear form is uniquely
> `B₁ + B₂` with `B₁` symmetric and `B₂` alternating. **In characteristic 2 the
> alternating bilinear forms are a (proper) subset of the symmetric bilinear
> forms.**

Concretely: the symmetric matrices over `GF(2^m)` form a space of dimension
`g(g+1)/2`; the **alternating** ones (symmetric *with zero diagonal*) form the
codimension-`g` subspace where all `g` diagonal entries vanish. The diagonal is
the *only* thing distinguishing "symmetric" from "alternating" in characteristic
2. This is precisely the diagonal that carries the self-tags.

**The classification consequence (the load-bearing fact).** In characteristic 2
a nondegenerate symmetric form is of exactly one of two kinds — *diagonalizable*
or *alternating* — and these are mutually exclusive:

> **Conrad, Exercise 5.4 (stated as a theorem).** Let `(V,B)` be nondegenerate
> and symmetric over a field of characteristic 2. Then `(V,B)` **has an
> orthogonal basis if and only if `B` is not alternating.**

(Proof sketch given by Conrad: pick `v₀` with `a := B(v₀,v₀) ≠ 0` — possible iff
`B` is non-alternating; then `v₀⊥` is nondegenerate by Lemma 4.6 and one inducts,
splicing in the hyperbolic-pair trick `B(v₀+e+f, v₀+e+f) ≠ 0` when the complement
happens to be alternating.)

This is the char-2 analogue of the fact that in characteristic ≠ 2 *every*
symmetric form diagonalizes (Conrad, **Theorem 4.7**: an orthogonal basis always
exists when char ≠ 2, equivalently every symmetric `M` satisfies `CᵀMC =
diagonal`). The counterexample that fails in char 2 is the hyperbolic plane
`[[0,1],[1,0]]`: it is symmetric, nondegenerate, alternating, and provably has
**no** orthogonal basis (Conrad, **Example 4.10** — any congruence keeps the
diagonal zero in char 2).

Corroborating primary sources for the classification of symmetric bilinear /
quadratic forms in characteristic 2 (where "alternating vs. non-alternating" is
*the* invariant of a nondegenerate form, refined by the Arf invariant in even
dimension):

- L. C. Grove, *Classical Groups and Geometric Algebra*, AMS GSM 39, 2002 —
  Ch. on bilinear forms in char 2 (Conrad's ref [6]).
- J. Milnor & D. Husemoller, *Symmetric Bilinear Forms*, Springer Ergebnisse 73,
  1973 (Milnor, "Symmetric inner products in characteristic 2", *Prospects in
  Mathematics*, 1970). <https://link.springer.com/book/10.1007/978-3-642-88330-9>
- K. Kato, "Symmetric bilinear forms, quadratic forms and Milnor K-theory in
  characteristic two", *Invent. Math.* 66 (1982).
  <https://link.springer.com/article/10.1007/BF01389226>
- Conrad, *Bilinear Forms*, §7 (quadratic forms in char 2; Arf invariant),
  Theorem 7.20.

---

## 2. When does `G = T·Tᵀ` exist, and when with a nonzero diagonal?

Two different questions; keep them separate.

### 2a. Existence of *some* factorization `G = B·Bᵀ` (any `B`)

**Every** symmetric matrix over a finite field is factorable — the only question
is how many columns `B` needs:

> **Lempel–Seroussi (1980).** Every symmetric matrix `A` over a finite field `F`
> can be written `A = B·Bᵀ` over `F`, where the number of columns of `B` is
> either `rank(A)` or `rank(A) + 1`, the value depending on `A` and on the
> characteristic of `F`.

The "`+1`" is exactly the alternating obstruction: a nondegenerate symmetric
`A` of size `g` factors with `g` columns iff it is *not* the exceptional
(alternating / totally-isotropic) type; otherwise one extra column is provably
needed. This is the matrix-theoretic form of Exercise 5.4.

Source: G. Seroussi & A. Lempel, "Factorization of Symmetric Matrices and
Trace-Orthogonal Bases in Finite Fields", *SIAM J. Comput.* 9(4):758–767, 1980.
<https://epubs.siam.org/doi/10.1137/0209059> (and the GF(2) companion,
*SIAM J. Comput.* 2(4), 1980, <https://epubs.siam.org/doi/10.1137/0204014>).

**Practical reading:** if the tag width equals `g` (one tag column per packet, a
square `T`), a factorization exists *unless* `G` is of the alternating type, in
which case you fundamentally need one more column — i.e. one extra tag
coordinate. This already answers the headline question at the "does a
factorization exist at all" level; §2b and §3 refine it to the *triangular,
nonzero-diagonal* form the scheme actually uses.

### 2b. Existence of a *square, invertible* `T` (equiv. nonzero diagonal)

A square invertible `T` with `G = T·Tᵀ` exists ⟺ `G` is congruent to `I` ⟺ `B`
has an orthonormal basis ⟺ (over `GF(2^m)`, by §0) `B` has an orthogonal basis
with nonzero diagonal. By **Exercise 5.4** this holds (for nondegenerate `G`)
**iff `G` is not alternating**, i.e. iff **not all** `<p_i,p_i>` vanish *and* no
principal piece of `G` is forced alternating (see §3 for the "principal piece"
refinement).

The obstruction, stated as a pivot condition: the standard result is that an
unpivoted LDLᵀ / Cholesky runs to completion with nonzero pivots iff every
**leading principal minor** that must be inverted is nonzero; a **vanishing
leading principal minor produces a zero pivot** (`D[i][i]=0`, hence
`T[i][i]=0`). In characteristic 2 the specific way a pivot dies is that the
current **Schur complement becomes alternating** (its diagonal is all zero) — see
§3. The recent treatment specialized to finite fields, including the
characteristic-2 case and the role of the Frobenius square root, is:

> J. (arXiv:2508.04657) "Cholesky decomposition for symmetric matrices over
> finite fields." Its existence/uniqueness result (Theorem A) states that a
> unique Cholesky factor with nonzero-square ("positive") diagonal exists when
> the field is *definite* **or of characteristic 2**, keyed to the quadratic
> characters of the leading principal minors; the positive square-root map used
> in the diagonal is well defined precisely because Frobenius is a bijection in
> char 2. <https://arxiv.org/abs/2508.04657>

---

## 3. Symmetric pivoting: can reordering packets remove a zero self-tag?

Reordering packets = simultaneous row+column permutation `G ↦ PᵀGP`
(a *congruence*, Conrad Thm 2.8/2.11). Two invariants of `PᵀGP` decide the answer.

**Invariant 1 — the diagonal multiset is preserved.** `PᵀGP` just permutes the
diagonal entries `{<p_i,p_i>}`. So the *set* of candidate self-values is fixed by
reordering; you can only choose which packet is eliminated first, not change the
available pivots.

**Invariant 2 — "alternating" is permutation-invariant.** If `G` is alternating
(zero diagonal), so is `PᵀGP`. Therefore:

> **Hard obstruction.** If **every** payload is self-orthogonal, i.e.
> `<p_i,p_i> = 0` for all `i` (equivalently, in char 2, every payload has
> XOR-checksum 0, since `<p,p> = (⊕ symbols)²`), then `G` is alternating and
> **no reordering can produce a nonzero first pivot** — every diagonal entry is 0
> for every permutation. A 1×1-pivot Cholesky with nonzero diagonal is
> impossible for this `G` in *any* order. This is exactly the "the whole matrix
> is alternating" case where symmetric pivoting provably cannot help.

**When reordering *does* help.** Symmetric (diagonal) pivoting with 1×1 pivots
carries the elimination to completion with all-nonzero pivots iff, at every
stage, the current **Schur complement** `S` (which stays symmetric) has **some
nonzero diagonal entry**; you then pivot on that entry. The process gets stuck
exactly when a Schur complement is **alternating but nonzero** — its diagonal is
entirely zero although the block itself isn't. Crucially, in characteristic 2 a
Schur complement can *become* alternating even if `G` started non-alternating, so
a "good" starting order does not guarantee success further down. The clean
statements:

- Reordering can avoid a zero self-tag **iff** at each elimination step the
  remaining Schur complement is non-alternating. Equivalently (nondegenerate
  case, Exercise 5.4 applied to each residual subspace): the form must be
  diagonalizable, and the greedy "always pivot on a nonzero diagonal entry"
  strategy realizes a diagonalization whenever one exists — this is the finite-
  field analogue of symmetric/rook pivoting.
- Reordering **cannot** help when a principal residual subspace is forced
  alternating (all its `<·,·>` self-values, and those reachable after
  elimination, are 0). The extreme case is `G` itself alternating (above).

The permutation-existence question — "does a `P` exist with `PᵀGP` admitting a
nonzero-diagonal triangular factor?" — therefore has answer: **yes iff `G` is
diagonalizable (non-alternating on every residual piece); no iff the form is
alternating on the whole space or on a residual invariant piece that the
elimination is forced into.** For the fully-alternating `G` the answer is a flat
no, independent of `P`.

Primary support: Conrad, Thm 2.8/2.11 (congruence under `PᵀGP`), Example 4.10
and Exercise 5.4 (alternating = no orthogonal basis, permutation-invariantly);
symmetric-pivoting / Schur-complement mechanics: Golub & Van Loan, *Matrix
Computations* (LDLᵀ and symmetric pivoting), and Bunch–Parlett/Bunch–Kaufman
below.

---

## 4. 2×2 block pivots (Bunch–Kaufman / Aasen) — the "combine two packets" fix

When a symmetric elimination cannot proceed with 1×1 pivots because the Schur
complement is alternating (all diagonal zero), the classical numerical-linear-
algebra fix is a **2×2 block pivot**: the Bunch–Kaufman and Aasen factorizations
compute `G = PᵀL·D·LᵀP` where `D` is **block-diagonal with 1×1 and 2×2 blocks**,
using a 2×2 block precisely when no acceptable 1×1 pivot is available. Inclusion
of 2×2 pivots is what makes a *symmetric indefinite* decomposition possible at
all; over `R` this is a stability device, but **over characteristic 2 it is a
structural necessity**, not an option.

- J. R. Bunch & L. Kaufman, "Some stable methods for calculating inertia and
  solving symmetric linear systems", *Math. Comp.* 31 (1977), 163–179.
- J. R. Bunch & B. N. Parlett, "Direct methods for solving symmetric indefinite
  systems of linear equations", *SIAM J. Numer. Anal.* 8 (1971).
- J. O. Aasen, "On the reduction of a symmetric matrix to tridiagonal form",
  *BIT* 11 (1971), 233–242.

**The exact finite-field analogue exists and is classical — it is the symplectic
decomposition.** In characteristic 2, a nondegenerate **alternating** form is not
just "hard to pivot"; it has a canonical decomposition into 2×2 hyperbolic
blocks:

> **Theorem 5.4 (Conrad).** Any nondegenerate alternating bilinear space has a
> *symplectic basis* `e₁,f₁,…,eₘ,fₘ`, in which the matrix is block-diagonal with
> `m` blocks `[[0,1],[1,0]]` (char 2) along the diagonal. In particular
> `dim = 2m` is even (**Theorem 5.1**).

So a 2×2 "block pivot" over `GF(2^m)` that couples packets `i, j` with
`<p_i,p_j> = 1` and `<p_i,p_i> = <p_j,p_j> = 0` is exactly a **hyperbolic pair**.
This is the precise mathematical content of the thesis's "combined recovery"
idea (XOR two packets): pairing two self-orthogonal packets into one hyperbolic
2×2 block resolves the degenerate (alternating) self-tag that no 1×1 pivot could.
The general structure theorem (mixing 1×1 non-isotropic pieces with 2×2
hyperbolic pieces) is Conrad §5 combined with Exercise 5.4 / §7: every symmetric
form in char 2 splits as (diagonalizable part) ⊥ (alternating part), and the
alternating part is a sum of hyperbolic planes — this **is** the Bunch–Kaufman
1×1/2×2 block structure, with the 2×2 blocks forced by isotropy rather than
chosen for stability.

Caveat for even/odd `g`: a nondegenerate alternating block must be
even-dimensional (Thm 5.1). An **odd** number of mutually self-orthogonal packets
cannot be tiled purely by hyperbolic pairs — one packet is left over, sitting in
the radical `V⊥`. In char 2 that leftover coordinate must be handled by a genuine
quadratic-form degree of freedom (Conrad §7, Thm 7.3/7.20: a nondegenerate
quadratic form exists in odd dimension even though its bilinear form is
degenerate). Practically: pairing fixes even clusters of degenerate packets; an
odd one still needs an extra free coordinate.

---

## 5. Rank of a random symmetric matrix and the probability of a zero pivot

**Exact enumeration exists (classical).** The number of symmetric `n×n` matrices
of each rank `r` over `GF(q)` has closed-form formulas, and **characteristic 2
splits the count into the alternating and non-alternating families** (they obey
different formulas and different rank parities — alternating matrices always have
even rank). Primary sources:

- L. Carlitz, "Representations by quadratic forms in a finite field", *Duke Math.
  J.* 21 (1954); and Carlitz's papers on symmetric matrices over `GF(q)`.
- J. MacWilliams, "Orthogonal matrices over finite fields", *Amer. Math. Monthly*
  76 (1969), 152–164.
- "Symmetric bilinear forms over finite fields with applications to coding
  theory", *J. Algebraic Combin.* 42 (2015), 635–670 (association-scheme counts
  of symmetric / alternating matrices by rank, both parities of `q`).
  <https://link.springer.com/article/10.1007/s10801-015-0595-0>
- For the alternating (skew, zero-diagonal) family specifically, the rank-`2r`
  count over `GF(q)` is
  `∏_{i=0}^{2r-1}(q^{n-i}-1) / ∏_{i=1}^{r}(q^{2i}-1) · q^{r(r-1)}`
  (skew-symmetric / alternating enumeration; see also the *skew rank metric*
  literature, e.g. arXiv:2210.16153).

**Probabilities relevant to the zero self-tag.**

- **First pivot.** `G[0][0] = <p_0,p_0> = (⊕ symbols of p_0)²`. As Frobenius is a
  bijection, this is 0 iff the payload's XOR-checksum is 0, which for a uniformly
  random payload happens with probability `1/q = 2^{-m}`. So a naive
  "eliminate packet 0 first" order fails with probability exactly `1/q`.
- **Fully alternating `G` (no reordering can help, §3).** For a uniform random
  symmetric matrix, all `n` diagonal entries vanish with probability `q^{-n}`.
  For the Gram matrix of random payloads the diagonal entries `<p_i,p_i>` are
  each 0 with probability `1/q`, so `P(G fully alternating) ≈ q^{-n} = 2^{-mn}` —
  astronomically small for realistic `m` (e.g. `m=8`) and generation size `n`.
- **Zero pivot somewhere under a *fixed* order.** Bounded above by roughly `n/q`
  (union bound over the `n` pivots, each a residual self-value that is 0 with
  probability about `1/q`). With **symmetric pivoting** (§3), a failure requires
  an entire residual Schur complement to be alternating, whose probability is of
  order `q^{-(n-k)}` at step `k` — i.e. pivoting drives the practical failure
  probability from `~n/q` down toward `~q^{-n}`.
- **General rank / singularity.** A uniform random symmetric matrix over `GF(q)`
  is singular with probability `~1/q` to leading order; the full rank
  distribution is given by the Carlitz/MacWilliams counts above. (Note: the
  scheme's `G` is a Gram matrix `PPᵀ` of the payload matrix `P`, not a uniform
  symmetric matrix, so use these as guides, not exact laws — but the diagonal
  statistics used above are exact.)

Related general reference for rank distributions of random matrices over `GF(q)`
(non-symmetric baseline): Cooper, and Blake–Studholme,
<http://www.cs.toronto.edu/~cvs/coding/random_report.pdf>.

---

## Implications for the tag scheme

1. **The zero self-tag is the "alternating" phenomenon, exactly.** `T[i][i] = 0`
   iff a Cholesky pivot vanishes iff the residual form is alternating at that
   step. In characteristic 2, "symmetric" and "alternating" differ *only* on the
   diagonal (Conrad Thm 1.6/1.7/2.7), and the diagonal *is* the self-tags. The
   scheme lives or dies on whether `G` (and its Schur complements) avoid the
   alternating subspace.

2. **`√<p,p>` is an XOR checksum.** Because `<p,p> = (⊕ symbols)²`, the ideal
   self-tag is the XOR-checksum of the (residual) payload, and it is zero iff that
   checksum is zero. This gives a cheap, exact test and a cheap fix (see 5).

3. **Reordering helps sometimes, but is not a guarantee.** Symmetric pivoting can
   dodge a zero self-tag *iff* some residual self-value is nonzero at each step
   (form non-alternating on every residual piece — §3, Exercise 5.4). It
   **provably cannot** help when `G` is alternating on the whole space or on a
   residual invariant piece; the cleanest such case is *every payload having zero
   XOR-checksum*, where every diagonal entry is 0 in every order.

4. **When reordering can't help you need either a 2×2 block or a free byte.**
   - *2×2 hyperbolic (block) pivot* = the thesis's "combine two packets" idea,
     and it is the correct fix for an **even** cluster of mutually self-orthogonal
     packets (Conrad Thm 5.4: alternating ⇒ symplectic ⇒ sum of `[[0,1],[1,0]]`
     blocks; the finite-field analogue of Bunch–Kaufman/Aasen 2×2 pivots). An
     **odd** leftover cannot be paired (Thm 5.1, even dimension) and still needs
     an extra coordinate.
   - *One free tag byte per packet* is the universal fix: it lets you set
     `<p_i,p_i>` to any nonzero square, which (over `GF(2^m)` is any nonzero
     value) makes `G` non-alternating and restores a nonzero-diagonal
     factorization. By Lempel–Seroussi this "+1 column" is *exactly* the extra
     degree of freedom the alternating case provably requires — so a single free
     byte is both **sufficient** and, against adversarial (fully alternating)
     data, **necessary**.

5. **In practice you almost never hit the hard case, but an adversary can force
   it.** For random payloads `P(zero first self-tag) = 1/q = 2^{-m}` and
   `P(fully alternating G) ≈ 2^{-mn}` (§5). So with even mild pivoting the scheme
   succeeds with overwhelming probability. But the fully-alternating case is a
   real, reachable configuration (all payloads with zero XOR-checksum), so a
   robust design should carry the one-byte free coordinate (or the 2×2 combine
   path) as a fallback rather than relying on reordering alone.

**Bottom line.** With payload data *fixed*, reordering removes a zero self-tag
**iff** the payload Gram form is non-alternating on every residual subspace
(diagonalizable — Conrad Exercise 5.4); when the data is (or is forced to be)
alternating, no permutation works and you *provably* need one extra degree of
freedom — realized either as a 2×2 hyperbolic pairing of two self-orthogonal
packets (even clusters) or as one free tag byte per packet (universal, and
minimal by Lempel–Seroussi's rank+1).

---

### Sources (primary)

- K. Conrad, *Bilinear Forms* (authoritative lecture notes; full theory in char 2
  incl. Thms 1.6, 1.7, 2.7, 2.8, 2.11, 4.7, 5.1, 5.4, 7.3, 7.20, Examples 4.10,
  7.27, Exercise 5.4).
  <https://kconrad.math.uconn.edu/blurbs/linmultialg/bilinearform.pdf>
- L. C. Grove, *Classical Groups and Geometric Algebra*, AMS GSM 39, 2002.
- J. Milnor & D. Husemoller, *Symmetric Bilinear Forms*, Springer, 1973.
  <https://link.springer.com/book/10.1007/978-3-642-88330-9>
- K. Kato, "Symmetric bilinear forms, quadratic forms and Milnor K-theory in
  characteristic two", *Invent. Math.* 66 (1982).
  <https://link.springer.com/article/10.1007/BF01389226>
- G. Seroussi & A. Lempel, "Factorization of Symmetric Matrices and
  Trace-Orthogonal Bases in Finite Fields", *SIAM J. Comput.* 9(4) (1980).
  <https://epubs.siam.org/doi/10.1137/0209059>
- "Cholesky decomposition for symmetric matrices over finite fields",
  arXiv:2508.04657. <https://arxiv.org/abs/2508.04657>
- J. R. Bunch & L. Kaufman, *Math. Comp.* 31 (1977); J. R. Bunch & B. N.
  Parlett, *SIAM J. Numer. Anal.* 8 (1971); J. O. Aasen, *BIT* 11 (1971).
- L. Carlitz, *Duke Math. J.* 21 (1954); J. MacWilliams, *Amer. Math. Monthly*
  76 (1969); "Symmetric bilinear forms over finite fields...", *J. Algebraic
  Combin.* 42 (2015). <https://link.springer.com/article/10.1007/s10801-015-0595-0>
