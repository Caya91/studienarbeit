# Literature review — skeleton (thesis requirement #1)

Requirement #1: "literature review on **packet pollution in network coding, recovery
strategies, and HMAC-based verification**." Structure below = those three pillars +
RLNC background + a synthesis/gap section that positions this thesis.

Every citation is already gathered in `docs/research/`. This is an outline to write prose
into, not the prose. `[key]` markers point at the source note holding the full reference.
Sources: `network-coding-mac-degenerate-packets.md` (=NC-MAC), `char2-symmetric-factorization.md`
(=CHAR2), `hmac-partial-packet-recovery-implementations.md` (=PPR).

---

## 2.1 Background: RLNC and the pollution threat model
*Goal: set up why integrity is hard in coded networks — recoding mixes packets, so one
bad packet contaminates every combination downstream.*

- RLNC fundamentals + augmentation (global encoding vector travels with packet). [Ho et al.
  2006; Koetter–Kschischang 2008 — NC-MAC §0]
- Why pollution is amplified by recoding: a single corrupted packet propagates through every
  recoded combination — the core motivation for in-network verification.
- Define the two corruption sources the thesis treats together: **channel noise** (BER) and
  **intentional pollution** (adversary). Tie to ADR-0008 attacker model.

## 2.2 Pillar 1 — Packet pollution defenses in network coding
*Goal: survey the families that detect/reject polluted packets; end by narrowing to the
orthogonality family this thesis belongs to.*

Organize as a taxonomy (also captured in NC-MAC §4 summary table):

1. **Homomorphic MACs (keyed).** Agrawal–Boneh ACNS'09 — keyed tag surviving recoding;
   `Combine`/`Verify`; over GF(2^8), same field family as this thesis. [NC-MAC §1.1]
   - Tag-pollution / small-key variants. [Cheng et al.; Boo et al. — NC-MAC §1.2]
2. **Homomorphic signatures (public-key).** Charles–Jain–Lauter CISS'06 (first, pairing-based);
   BFKW PKC'09 (sign a subspace, large field); Boneh–Freeman PKC'11 (**binary fields** — most
   relevant to GF(2^m)); Gennaro et al. PKC'10; Zhao et al. ISIT'07. [NC-MAC §2]
3. **Null-space / orthogonality checks (keyless — the direct ancestors).**
   - **Null Keys (Kehdi–Li INFOCOM'09)** ← nearest relative: verify `⟨v,key⟩=0`, no shared
     secret; explicitly "necessary but not sufficient." [NC-MAC §3.1]
   - **Padding for Orthogonality / MacSig (Zhang et al. INFOCOM'11)**: append one symbol
     *solved* to force orthogonality — direct precedent for this thesis's salt byte. [NC-MAC §3.2]
4. **Coding-theoretic (no tags).** Jaggi et al. Byzantine-resilient NC. [NC-MAC §3.3]
5. **Homomorphic hashing.** Krohn et al. S&P'04 (origin of on-the-fly RLNC verification). [NC-MAC §3.4]

*Write the "gap" beat here:* keyless orthogonality (Null Keys family) avoids key
distribution but the orthogonality test is not sufficient — motivates this thesis's
self+cross tagging and the recovery layer.

## 2.3 Pillar 2 — Recovery strategies (partial packet recovery + ARQ)
*Goal: contrast throw-away-and-resend (ARQ) with repair-in-place (PPR); establish the
lineage the thesis's recovery + benchmark come from.*

- **Conventional ARQ**: detect → drop → retransmit. The baseline this thesis measures
  against (see `docs/arq_baseline_framing.md`). Cost = extra transmissions.
- **Partial Packet Recovery lineage (all CRC-based, all from the Fitzek/TU-Dresden line):**
  PRAC (Angelopoulos et al. TWC'17) → S-PRAC (Irianto et al. Wireless Days'19, segmentation +
  inner CRCs) → QPPR (Gholamian et al. Comm. Lett.'23). [PPR §"Predecessor code"]
- **The benchmark: Combined Recovery (Fathi–Pahlevani, IEEE Comm. Lett. 2025).** Replaces
  CRC with a linear (homomorphic) tag to kill checksum-collision false positives; XOR-pairs
  two broken segments to correct jointly. [PPR §"Scheme summary"] Note the key subtlety: its
  Eq. 2 is a keyed linear inner-product checksum, *not* the Agrawal–Boneh polynomial MAC —
  which is exactly why it maps onto this thesis's orthogonal-tag work. [PPR §"Scheme summary" note]
- CRC's core weakness to name here: **checksum collision → silent false-repair** (the hazard
  the homomorphic benchmark and this thesis's tag both drive to ~0).

## 2.4 Pillar 3 — HMAC-based (homomorphic) verification, and the degeneracy problem
*Goal: go deep on the keyed-vs-keyless homomorphic integrity axis that is the thesis's
headline comparison, and surface the zero-tag/degeneracy issue as a genuine research gap.*

- Clarify terminology up front (avoids the thesis's biggest naming trap): **"HMAC" in this
  literature = Homomorphic MAC, not hash-based HMAC-SHA-256.** [CONTEXT.md glossary]
- Keyed homomorphic MAC vs **keyless homomorphic tag** (this thesis) — same family, only the
  key differs. Position via Null Keys (keyless) + Agrawal–Boneh (keyed).
- **The degeneracy / zero-self-tag gap** (this thesis's novel contribution area):
  - How prior schemes handle degenerate (all-zero / self-orthogonal) objects: universally by
    **augmentation + non-zero coefficient block**, never by touching payload. Agrawal–Boneh
    "trivial forgery" clause; CJL group identity; Null Keys' implicit reliance. [NC-MAC §4, §5]
  - The math of why it happens: zero self-tag = **alternating symmetric bilinear form in
    char 2**; `√⟨p,p⟩` is an XOR checksum; reordering can't fix a fully-alternating Gram
    matrix. [CHAR2 §1–3]
  - The two provably-minimal fixes: **2×2 hyperbolic pairing** (= "combine two packets") for
    even clusters, or **one free tag/salt byte** (universal, minimal by Lempel–Seroussi
    rank+1). [CHAR2 §4, §"Implications" 4] — precedent: Padding-for-Orthogonality. [NC-MAC §3.2]

## 2.5 Synthesis and gap → this thesis
*Goal: one page that makes the contribution obvious.*

- Prior art = keyed homomorphic integrity (needs key distribution) **or** keyless
  orthogonality (Null Keys — detects but doesn't *recover*, and test insufficient).
- PPR lineage = recovery, but CRC-based → silent false-repairs; the 2025 benchmark fixes that
  with a *keyed* tag.
- **Gap this thesis fills:** a *keyless* homomorphic tag that both verifies **and** recovers
  (self/cross orthogonal tags + ACR + linear-solve + segmented pairing), with the zero-tag
  degeneracy characterized and fixed (salt byte, ADR-0010) — and evaluated head-to-head
  against the keyed benchmark and conventional ARQ on recovery rate, silent-pollution rate,
  overhead, and completion time.

---

## Writing notes
- Target length: ~4–6 pages (letters/thesis proportion). Pillars 1–3 carry it; §2.1 and §2.5
  stay short.
- Every `[key]` already has a primary-source URL/DOI in the named research note — copy into
  the bibliography as you go; don't re-search.
- Two terminology guards to state once and hold (both in CONTEXT.md): "homomorphic MAC" not
  bare "HMAC"; "keyless HMAC" = the orthogonal tag, not a 4th scheme.
