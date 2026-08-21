# 06 — Smart-attacker spectrum: keyless orthogonal vs keyed homomorphic MAC

**What to build:** The security-axis comparison (recovery axis is tickets 03–05; this is the other half of the thesis). Put the keyless orthogonal self-tag against the matched homomorphic Combined-Recovery MAC (ticket 04) under a *smart attacker*, measured across a **key-trust spectrum**, not a single assumption. Reuses `simulation/intelligent_attack_sim.py` + `forge_hmac` (ADR-0008 malicious-relay model).

**Why a spectrum (the honest framing):** a homomorphic MAC is cryptographically unforgeable without the key (≈ q^-V, and relays recode WITHOUT holding the key), so with a secret key it simply beats the keyless scheme on forgery resistance. The orthogonal scheme is keyless → forgeable by construction; its value is *work-based* security + needing no key at all. So the comparison must show:
- **Key-secret:** MAC silent-accept ≈ 0 (unforgeable); orthogonal forgeable at measured field-op work W. MAC wins this column — state it plainly.
- **Key-compromised** (node capture / key leak): MAC → 0 security (silent-accept = 1); orthogonal → still costs W. Orthogonal wins here.
- The result is the **shape**: MAC security is a *cliff* contingent on secrecy; orthogonal is a *flat, key-independent* work floor. Thesis point = "keyless: no key to distribute, security doesn't evaporate on key compromise" — NOT "harder to forge."

**Blocked by:** 04 (need the matched homomorphic MAC arm to attack; `forge_hmac` today only models the plain flat-HMAC key-secret case).

**Status:** blocked

- [ ] Both key assumptions (secret / compromised) implemented as attacker configs against the homomorphic MAC arm; orthogonal attacked white-box (Kerckhoffs) in both.
- [ ] Metrics per scheme × key-assumption: silently-accepted pollution rate + attacker forging work (field-ops / time to a targeted accepted forgery).
- [ ] A figure/table showing the MAC secrecy-cliff vs orthogonal flat work floor.
- [ ] The key-secret column honestly reports the MAC winning forgery resistance; the argument for orthogonal is stated as key-freedom + compromise-resilience, not raw forge-hardness.
- [ ] Decision recorded (ADR update): what the security comparison concludes for the keyless-alternative claim.
