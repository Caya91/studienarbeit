# Key distribution cost in keyed HMAC schemes — how it scales

Source set: thesis papers in `C:\Users\marti\OneDrive\studienarbeit_docs\` (`paper/`, `proof_paper/`, `hommac.pdf`).
Purpose: back the claim on deck slide 6 ("more nodes → more key material, scales badly")
with numbers and formulas. Notation unified below; papers' own symbols noted where they differ.

## Notation

| Symbol | Meaning |
|---|---|
| N | number of non-source nodes that must verify (relays + sinks) |
| c | collusion bound: max. number of compromised nodes that may pool keys |
| ε | allowed failure probability of the key assignment (security parameter) |
| q | field size (GF(q), e.g. 2⁸) |
| m+n | coded packet length in symbols (m coeffs + n payload) |
| \|K\| | size of the key pool held by the source |
| l | number of MAC tags carried per packet |

**Key size fact (all MAC schemes below):** one MAC key is a vector `k ∈ F_q^{m+n+1}`, i.e.
**one key ≈ one packet** of material (Agrawal–Boneh §3; MacSig §III-C; Esfahani Eq. 9/18;
Combined Recovery §III: "each key consists of n symbols … n = size of the data chunk").

## 1. What the papers say (with location)

### Agrawal & Boneh — *Homomorphic MACs* (hommac.pdf)
- Intro: basic HomMac needs a shared secret key between source and recipient. If relays also
  verify, "the sender would need to have a shared secret key with each network node. Every
  packet would need to include a tag per network node, which is unacceptable."
  → naive cost: **N keys at the source, N tags per packet, N secure transfers**.
- §5: fix via **cover-free families** (Canetti et al.): source holds all keys X, node i gets
  block A_i ⊂ X. Security error (1/q)^d, d = keys of a node not covered by c colluders.
- Only **c-collusion resistant**: "when more than c … collude, the MAC becomes insecure."
- §8: "The tag size grows **quadratically with c**."
- §6: multi-sender needs a cover-free family per sender, or a PRF-derived second key set per node.
- §7 numbers: (2,1)-CFF: 49 keys, 7 per node, 2401 verifiers, security (1/2)⁸;
  (2,5)-CFF: 121 keys, 11 per node, 14641 verifiers, security (1/2)⁴⁰.

### Zhang et al. — *Padding for Orthogonality / MacSig* (INFOCOM 2011)
- §III-A: null-key style approach would have to "pre-distribute v's **per generation using a
  secure channel**" — they avoid it by padding.
- §III-C Thm 4: a packet polluted by A passes verifier B with prob ≤ **1/q^d**, d = keys B
  holds that A does not → security depends entirely on how keys are distributed.
- §III-D (Canetti probabilistic assignment, each key given to a node with P_a = 1/(c+1)):
  - one random (node, coalition) pair safe w.p. ≥ 1−ε with `|K| = e(c+1) ln(1/ε)`
  - **all** nodes / all coalitions safe ⇒ `|K| ≥ e(c+1)² ln N`, and every packet carries
    that many MACs — "clearly does not scale when the network size N is large."
- Their fix, **double-random key distribution** (Thm 5):
  `|K| = e(c+1)·m`, `m = (2/δ²)(γ+1)(c+1) ln N`, MACs per packet `l = e(c+1) ln(1/ε)/(1−δ)`.
  → tags per packet no longer depend on N, **but the key pool still grows ∝ (c+1)² ln N**,
  and l key *indices* are added to every packet.
- §V-A: "We **neglect the bandwidth consumed by the key distribution** in the Setup stage, since
  it can be done offline." → distribution cost is excluded from their evaluation, not zero.

### Esfahani et al. — *An efficient homomorphic MAC-based scheme* (the adversarial HMAC paper)
- §4.3: KDC gives the source `L = l + l' = e(c+1) ln(1/ε)/(1−δ)` key vectors (paper writes
  ln(q) with q as security parameter, Eq. 10 taken from MacSig); each non-source node gets
  **one** MAC key vector + **one** D-MAC key vector + the public signature key.
- "the number of keys at the source should be **c times more** than the number of keys assigned
  to each intermediate or sink node."
- §6.3 key storage, Eq. 18/19:
  - `T_source = [ l(m+n+1) + l'(l+1) + l'+1 ] · ⌈log₂ p⌉` bits
  - `T_non-source = [ (m+n+1) + (l+1) + l'+1 ] · ⌈log₂ p⌉` bits
  - Fig. 7: source 117k–235k bits for 27–54 tags; non-source nearly flat.
- Adversary model §3.2: data pollution uses "**the pre-shared key** of compromised nodes".

### Dual-HMAC (Mantas et al., IJDSN 2015)
- §2.2: key distribution "is a challenging issue". Trusted-server and public-key schemes are
  **infeasible in WSNs** (energy, compute) → key predistribution is used.
- §4.4: keys "distributed to all participant nodes **in a secure and authenticated manner**".
  Source pool `L = e(c+1) ln(1/q_s)` with security parameter `q_s = (N·C(N,c))⁻¹`
  ⇒ `ln(1/q_s) = ln N + ln C(N,c) ≈ (c+1) ln N` ⇒ **L ≈ e(c+1)² ln N** (same as MacSig).
  Per node `R = e ln(1/√q_s)`. Source ≥ (c+1)× node key count (cites [25]).

### Combined Recovery — *Enhancing PPR in RLNC using HMACs* (our keyed benchmark)
- §III: sender generates m random keys of n symbols each (n = chunk size).
- §V: keys "**pre-generated and securely shared with the receiver, using a key exchange
  protocol**." Only point-to-point; scaling to many receivers not addressed.

### Others
- FHPRAC: tag via "shared secret key"; future work lists scalability to large multi-node networks.
- E-HMAC (Hayouni): optimises key *storage* (~50 % less at source than Esfahani) — still KDC-based.
- Own draft `keyless_sysmodel_only`: generic HMAC model = KDC → key pool to source, random key
  set to every non-source node.

## 2. The scaling, put together

Three cost drivers, all paid **before the first packet**, over a secure channel:

1. **Network size N** — every verifying node needs its own keys delivered.
   Total setup traffic = N × (keys per node) × (key size).
2. **Collusion tolerance c** — to survive c colluders the pool grows ∝ (c+1)², each node
   holds ∝ (c+1) keys, and the source ≈ (c+1)× a node's keys.
3. **Key size ≈ packet size** — each key vector is m+n+1 field symbols.

With probabilistic (Canetti/MacSig/Dual-HMAC) assignment:

```
pool  |K|          ≈ e (c+1)² ln N
keys per node      ≈ |K|/(c+1) = e (c+1) ln N
total secure-channel setup traffic
                   ≈ N · e (c+1) ln N · (m+n+1)·log₂q  bits     =  O(c · N log N · packet)
```

Esfahani's 1-key-per-node model brings the per-node part down to ~1 packet, but total setup
traffic is still **linear in N**, and the source still holds ∝ (c+1) keys.

Additional costs not captured in the formulas:
- **c is a hard cliff**: more than c compromised nodes ⇒ insecure ⇒ re-key over secure channels.
- **Multi-sender**: a separate key family per sender (Agrawal–Boneh §6) ⇒ another factor ~N.
- **Per-generation keys** (null-key style): redistribution every generation (MacSig §III-A).

### Illustrative numbers (key ≈ 1 KB, as in Agrawal–Boneh §7: 1024 symbols over GF(2⁸))

| N | keys/node (c=2) | MACs/packet, Canetti (c=2) | total setup traffic c=1 | c=2 | c=3 |
|---:|---:|---:|---:|---:|---:|
| 10 | 19 | 56 | 0.12 MB | 0.18 MB | 0.24 MB |
| 100 | 38 | 113 | 2.4 MB | 3.7 MB | 4.9 MB |
| 1 000 | 56 | 169 | 37 MB | 55 MB | 73 MB |
| 10 000 | 75 | 225 | 489 MB | 733 MB | 978 MB |

Rule of thumb: **10× more nodes → ~15× more key traffic** (N log N), all over secure channels.

## 3. Keyless contrast (this thesis)

- 0 keys, no KDC, no secure channel, no re-keying, no collusion bound c.
- Per-packet overhead = k = gen_size tag symbols → depends on **generation size**, not on N.
- Honest caveat: security is work-based (attacker must solve the orthogonality system),
  not key secrecy — see `intelligent_pollution_attacker` / ADR-0008.
